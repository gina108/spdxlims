from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.core.audit import log_audit
from app.db.session import get_db
from app.models.models import PanelCatalog, PanelCatalogItem, TestCatalog
from app.routers.common import actor_from_header

router = APIRouter()


class PanelSummaryOut(BaseModel):
    id: str
    code: str
    name: str
    is_active: bool
    test_names: str | None = None


class PanelItemIn(BaseModel):
    item_type: str = 'test'
    test_id: str | None = None
    heading_text: str | None = None
    sort_order: int = 0
    label: str | None = None


class PanelIn(BaseModel):
    code: str
    name: str
    items: list[PanelItemIn]
    # The desktop has always sent these; until panel_catalog had the columns
    # they were accepted and silently dropped, so a report rendered in server
    # mode lost its "Metodologia ... | Tipo de Muestra ..." line.
    specimen_type: str | None = None
    method: str | None = None


class PanelDetailOut(BaseModel):
    id: str
    code: str
    name: str
    is_active: bool
    items: list[dict]
    specimen_type: str | None = None
    method: str | None = None


@router.get('', response_model=list[PanelSummaryOut])
def list_panels(status_filter: str = Query('active'), db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    normalized = status_filter.strip().lower() or 'active'
    stmt = (
        select(
            PanelCatalog.id,
            PanelCatalog.code,
            PanelCatalog.name,
            PanelCatalog.active,
            func.string_agg(
                func.coalesce(TestCatalog.name, PanelCatalogItem.heading_text),
                ', ',
            ).label('test_names'),
        )
        .outerjoin(PanelCatalogItem, PanelCatalogItem.panel_id == PanelCatalog.id)
        .outerjoin(TestCatalog, TestCatalog.id == PanelCatalogItem.test_id)
        .group_by(PanelCatalog.id, PanelCatalog.code, PanelCatalog.name, PanelCatalog.active)
        .order_by(PanelCatalog.active.desc(), PanelCatalog.name.asc())
    )
    if normalized == 'active':
        stmt = stmt.where(PanelCatalog.active.is_(True))
    elif normalized == 'archived':
        stmt = stmt.where(PanelCatalog.active.is_(False))
    rows = db.execute(stmt).all()
    return [
        PanelSummaryOut(
            id=str(row.id),
            code=row.code,
            name=row.name,
            is_active=bool(row.active),
            test_names=row.test_names,
        )
        for row in rows
    ]


@router.get('/{panel_id}', response_model=PanelDetailOut)
def get_panel(panel_id: str, include_inactive: bool = Query(False), db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    parsed_panel_id = _parse_uuid(panel_id, field_name='panel_id')
    panel = db.get(PanelCatalog, parsed_panel_id)
    if panel is None or (not include_inactive and not panel.active):
        raise HTTPException(status_code=404, detail='panel not found')
    items = _load_panel_items(parsed_panel_id, db)
    return PanelDetailOut(
        id=str(panel.id),
        code=panel.code,
        name=panel.name,
        is_active=bool(panel.active),
        items=items,
        specimen_type=panel.specimen_type,
        method=panel.method,
    )


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


@router.post('')
def create_panel(payload: PanelIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    panel = PanelCatalog(
        code=payload.code.strip(),
        name=payload.name.strip(),
        active=True,
        specimen_type=_clean(payload.specimen_type),
        method=_clean(payload.method),
    )
    db.add(panel)
    db.flush()
    _replace_panel_items(panel.id, payload.items, db)
    db.flush()
    log_audit(db, actor_user_id=actor, entity='panel', entity_id=str(panel.id), action='create', after_json=_panel_audit_payload(panel, db))
    db.commit()
    return {'id': str(panel.id)}


@router.put('/{panel_id}')
def update_panel(panel_id: str, payload: PanelIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    parsed_panel_id = _parse_uuid(panel_id, field_name='panel_id')
    panel = db.get(PanelCatalog, parsed_panel_id)
    if panel is None:
        raise HTTPException(status_code=404, detail='panel not found')
    before = _panel_audit_payload(panel, db)
    panel.code = payload.code.strip()
    panel.name = payload.name.strip()
    panel.specimen_type = _clean(payload.specimen_type)
    panel.method = _clean(payload.method)
    db.query(PanelCatalogItem).filter(PanelCatalogItem.panel_id == parsed_panel_id).delete()
    db.flush()
    _replace_panel_items(parsed_panel_id, payload.items, db)
    db.flush()
    log_audit(db, actor_user_id=actor, entity='panel', entity_id=str(panel.id), action='update', before_json=before, after_json=_panel_audit_payload(panel, db))
    db.commit()
    return {'id': str(panel.id)}


@router.post('/{panel_id}/archive')
def archive_panel(panel_id: str, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    parsed_panel_id = _parse_uuid(panel_id, field_name='panel_id')
    panel = db.get(PanelCatalog, parsed_panel_id)
    if panel is None:
        raise HTTPException(status_code=404, detail='panel not found')
    before = _panel_audit_payload(panel, db)
    panel.active = False
    log_audit(db, actor_user_id=actor, entity='panel', entity_id=str(panel.id), action='archive', before_json=before, after_json=_panel_audit_payload(panel, db))
    db.commit()
    return {'id': str(panel.id), 'active': False}


@router.post('/{panel_id}/unarchive')
def unarchive_panel(panel_id: str, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    parsed_panel_id = _parse_uuid(panel_id, field_name='panel_id')
    panel = db.get(PanelCatalog, parsed_panel_id)
    if panel is None:
        raise HTTPException(status_code=404, detail='panel not found')
    before = _panel_audit_payload(panel, db)
    panel.active = True
    log_audit(db, actor_user_id=actor, entity='panel', entity_id=str(panel.id), action='unarchive', before_json=before, after_json=_panel_audit_payload(panel, db))
    db.commit()
    return {'id': str(panel.id), 'active': True}


def _replace_panel_items(panel_id: UUID, items: list[PanelItemIn], db: Session) -> None:
    if not items:
        raise HTTPException(status_code=400, detail='panel must contain at least one item')
    seen_tests: set[UUID] = set()
    for index, item in enumerate(items):
        item_type = item.item_type.strip().lower() or 'test'
        if item_type not in {'test', 'heading', 'comment'}:
            raise HTTPException(status_code=400, detail='invalid panel item type')
        if item_type == 'test':
            if not item.test_id:
                raise HTTPException(status_code=400, detail='test item requires test_id')
            test_id = _parse_uuid(item.test_id, field_name='test_id')
            test = db.get(TestCatalog, test_id)
            if test is None:
                raise HTTPException(status_code=404, detail='test not found')
            if test_id in seen_tests:
                continue
            seen_tests.add(test_id)
            db.add(PanelCatalogItem(panel_id=panel_id, test_id=test_id, item_type='test', sort_order=index))
            continue
        heading_text = (item.heading_text or item.label or '').strip()
        if not heading_text:
            raise HTTPException(status_code=400, detail='heading/comment item requires text')
        db.add(PanelCatalogItem(panel_id=panel_id, item_type=item_type, heading_text=heading_text, sort_order=index))


def _load_panel_items(panel_id: UUID, db: Session) -> list[dict]:
    rows = db.execute(
        select(
            PanelCatalogItem.item_type,
            PanelCatalogItem.test_id,
            PanelCatalogItem.heading_text,
            PanelCatalogItem.sort_order,
            TestCatalog.code.label('test_code'),
            TestCatalog.name.label('test_name'),
        )
        .outerjoin(TestCatalog, TestCatalog.id == PanelCatalogItem.test_id)
        .where(PanelCatalogItem.panel_id == panel_id)
        .order_by(PanelCatalogItem.sort_order.asc(), PanelCatalogItem.id.asc())
    ).all()
    result: list[dict] = []
    for row in rows:
        label = f"{row.test_name} ({row.test_code})" if row.item_type == 'test' and row.test_name else str(row.heading_text or '')
        result.append({
            'item_type': row.item_type,
            'test_id': str(row.test_id) if row.test_id else None,
            'test_code': row.test_code,
            'heading_text': row.heading_text,
            'sort_order': int(row.sort_order or 0),
            'label': label,
        })
    return result


def _parse_uuid(raw_value: str, *, field_name: str) -> UUID:
    try:
        return UUID(str(raw_value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f'invalid {field_name}') from exc


def _panel_audit_payload(panel: PanelCatalog, db: Session) -> dict:
    return {
        'id': str(panel.id),
        'code': panel.code,
        'name': panel.name,
        'is_active': bool(panel.active),
        'items': _load_panel_items(panel.id, db),
    }
