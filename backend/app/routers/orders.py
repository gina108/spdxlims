from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Integer, delete, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.audit import log_audit
from app.db.session import get_db
from app.models.models import LabOrder, OrderItem, PanelCatalog, PanelCatalogItem, Patient, Provider, TestCatalog
from app.routers.common import actor_from_header

router = APIRouter()


class RecentOrderOut(BaseModel):
    id: str
    order_number: str
    patient_name: str
    doctor_name: str | None = None
    client_name: str | None = None
    status: str
    created_at: str
    item_count: int


class OrderBrowserOut(BaseModel):
    id: str
    order_number: str
    order_date: str
    patient_name: str
    client_name: str | None = None
    doctor_name: str | None = None
    status: str
    item_count: int


class TestChoiceOut(BaseModel):
    id: str
    label: str


class PanelChoiceOut(BaseModel):
    id: str
    label: str


class PanelOrderItemOut(BaseModel):
    item_type: str
    test_id: str | None = None
    heading_text: str | None = None
    sort_order: int
    label: str


class ProviderChoiceOut(BaseModel):
    id: str
    label: str


class OrderItemIn(BaseModel):
    test_id: str
    source: str | None = None


class OrderCreateIn(BaseModel):
    patient_id: str
    test_ids: list[str] = []
    items: list[OrderItemIn] = []
    accession_id: str | None = None
    sample_id: str | None = None
    status: str = "registered"
    notes: str | None = None
    doctor_id: str | None = None
    client_id: str | None = None


class OrderItemOut(BaseModel):
    item_type: str
    test_id: str | None = None
    label: str
    source: str = ""


class OrderDetailOut(BaseModel):
    id: str
    order_number: str
    accession_id: str | None = None
    sample_id: str | None = None
    patient_id: str | None = None
    doctor_id: str | None = None
    client_id: str | None = None
    status: str
    notes: str | None = None
    is_preallocated: int = 0
    items: list[OrderItemOut]


@router.get("/recent", response_model=list[RecentOrderOut])
def recent_orders(db: Session = Depends(get_db)):
    doctor_provider = aliased(Provider)
    client_provider = aliased(Provider)
    rows = db.execute(
        select(
            LabOrder.id,
            LabOrder.order_number,
            Patient.first_name,
            Patient.last_name,
            Patient.middle_name,
            doctor_provider.legal_name.label("doctor_name"),
            client_provider.legal_name.label("client_name"),
            LabOrder.status,
            LabOrder.ordered_at,
            func.count(OrderItem.id).label("item_count"),
        )
        .join(Patient, Patient.id == LabOrder.patient_id)
        .outerjoin(doctor_provider, doctor_provider.id == LabOrder.doctor_id)
        .outerjoin(client_provider, client_provider.id == LabOrder.client_id)
        .outerjoin(OrderItem, OrderItem.order_id == LabOrder.id)
        .group_by(
            LabOrder.id,
            LabOrder.order_number,
            Patient.first_name,
            Patient.last_name,
            Patient.middle_name,
            doctor_provider.legal_name,
            client_provider.legal_name,
            LabOrder.status,
            LabOrder.ordered_at,
        )
        .order_by(LabOrder.ordered_at.desc(), LabOrder.order_number.desc())
        .limit(25)
    ).all()
    result: list[RecentOrderOut] = []
    for row in rows:
        parts = [row.first_name or "", row.last_name or "", row.middle_name or ""]
        patient_name = " ".join(part for part in parts if part).strip()
        result.append(
            RecentOrderOut(
                id=str(row.id),
                order_number=row.order_number,
                patient_name=patient_name,
                doctor_name=row.doctor_name,
                client_name=row.client_name,
                status=row.status,
                created_at=row.ordered_at.isoformat() if row.ordered_at else "",
                item_count=int(row.item_count or 0),
            )
        )
    return result


@router.get("/search", response_model=list[OrderBrowserOut])
def search_orders(search: str = "", db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    doctor_provider = aliased(Provider)
    client_provider = aliased(Provider)
    q = (
        select(
            LabOrder.id,
            LabOrder.order_number,
            Patient.first_name,
            Patient.last_name,
            Patient.middle_name,
            doctor_provider.legal_name.label("doctor_name"),
            client_provider.legal_name.label("client_name"),
            LabOrder.status,
            LabOrder.ordered_at,
            func.count(OrderItem.id).label("item_count"),
        )
        .join(Patient, Patient.id == LabOrder.patient_id)
        .outerjoin(doctor_provider, doctor_provider.id == LabOrder.doctor_id)
        .outerjoin(client_provider, client_provider.id == LabOrder.client_id)
        .outerjoin(OrderItem, OrderItem.order_id == LabOrder.id)
        .group_by(
            LabOrder.id,
            LabOrder.order_number,
            Patient.first_name,
            Patient.last_name,
            Patient.middle_name,
            doctor_provider.legal_name,
            client_provider.legal_name,
            LabOrder.status,
            LabOrder.ordered_at,
        )
    )
    normalized = search.strip()
    if normalized:
        like_value = f"%{normalized}%"
        q = q.where(
            or_(
                LabOrder.order_number.ilike(like_value),
                Patient.first_name.ilike(like_value),
                Patient.last_name.ilike(like_value),
                Patient.middle_name.ilike(like_value),
                doctor_provider.legal_name.ilike(like_value),
                client_provider.legal_name.ilike(like_value),
            )
        )
    rows = db.execute(q.order_by(LabOrder.ordered_at.desc(), LabOrder.order_number.desc()).limit(200)).all()
    result: list[OrderBrowserOut] = []
    for row in rows:
        patient_name = " ".join(part for part in [row.first_name or "", row.last_name or "", row.middle_name or ""] if part).strip()
        result.append(
            OrderBrowserOut(
                id=str(row.id),
                order_number=row.order_number,
                order_date=row.ordered_at.isoformat() if row.ordered_at else "",
                patient_name=patient_name,
                client_name=row.client_name,
                doctor_name=row.doctor_name,
                status=row.status,
                item_count=int(row.item_count or 0),
            )
        )
    return result


@router.get("/next-number")
def next_number(db: Session = Depends(get_db)):
    rows = db.scalars(select(LabOrder.order_number).order_by(LabOrder.ordered_at.desc(), LabOrder.order_number.desc()).limit(200)).all()
    highest = 0
    for value in rows:
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits:
            highest = max(highest, int(digits))
    return {"order_number": f"{highest + 1:06d}"}


@router.get("/test-choices", response_model=list[TestChoiceOut])
def test_choices(db: Session = Depends(get_db)):
    rows = db.scalars(select(TestCatalog).where(TestCatalog.active.is_(True)).order_by(TestCatalog.name.asc())).all()
    return [TestChoiceOut(id=str(row.id), label=f"{row.name} ({row.code})") for row in rows]


@router.get("/panel-choices", response_model=list[PanelChoiceOut])
def panel_choices(db: Session = Depends(get_db)):
    rows = db.execute(
        select(
            PanelCatalog.id,
            PanelCatalog.code,
            PanelCatalog.name,
            func.sum(func.cast(PanelCatalogItem.item_type == "test", Integer)).label("item_count"),
        )
        .outerjoin(PanelCatalogItem, PanelCatalogItem.panel_id == PanelCatalog.id)
        .where(PanelCatalog.active.is_(True))
        .group_by(PanelCatalog.id, PanelCatalog.code, PanelCatalog.name)
        .order_by(PanelCatalog.name.asc())
    ).all()
    return [
        PanelChoiceOut(
            id=str(row.id),
            label=f"{row.name} ({row.code}) - {int(row.item_count or 0)} tests",
        )
        for row in rows
    ]


@router.get("/panels/{panel_id}/order-items", response_model=list[PanelOrderItemOut])
def panel_order_items(panel_id: str, db: Session = Depends(get_db)):
    parsed_panel_id = _parse_uuid(panel_id, field_name="panel_id")
    panel = db.get(PanelCatalog, parsed_panel_id)
    if panel is None or not panel.active:
        raise HTTPException(status_code=404, detail="panel not found")
    rows = db.execute(
        select(
            PanelCatalogItem.item_type,
            PanelCatalogItem.test_id,
            PanelCatalogItem.heading_text,
            PanelCatalogItem.sort_order,
            TestCatalog.name.label("test_name"),
            TestCatalog.code.label("test_code"),
        )
        .outerjoin(TestCatalog, TestCatalog.id == PanelCatalogItem.test_id)
        .where(PanelCatalogItem.panel_id == parsed_panel_id)
        .order_by(PanelCatalogItem.sort_order.asc(), PanelCatalogItem.id.asc())
    ).all()
    return [
        PanelOrderItemOut(
            item_type=row.item_type,
            test_id=str(row.test_id) if row.test_id else None,
            heading_text=row.heading_text,
            sort_order=int(row.sort_order or 0),
            label=(f"{row.test_name} ({row.test_code})" if row.item_type == "test" and row.test_name else str(row.heading_text or "")),
        )
        for row in rows
    ]


@router.get("/provider-choices", response_model=list[ProviderChoiceOut])
def provider_choices(provider_type: str = Query(...), db: Session = Depends(get_db)):
    normalized = provider_type.strip().lower()
    if normalized not in {"doctor", "clinic"}:
        raise HTTPException(status_code=400, detail="provider_type must be doctor or clinic")
    rows = db.scalars(
        select(Provider)
        .where(Provider.provider_type == normalized, Provider.active.is_(True))
        .order_by(Provider.legal_name.asc())
    ).all()
    result: list[ProviderChoiceOut] = []
    for row in rows:
        if normalized == "doctor":
            label = row.legal_name if not row.code else f"{row.legal_name} ({row.code})"
        else:
            label = row.legal_name if not row.phone else f"{row.legal_name} ({row.phone})"
        result.append(ProviderChoiceOut(id=str(row.id), label=label))
    return result


def _build_order_detail(order: LabOrder, db: Session) -> OrderDetailOut:
    items = db.execute(
        select(OrderItem, TestCatalog)
        .join(TestCatalog, TestCatalog.id == OrderItem.test_id)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.id.asc())
    ).all()
    return OrderDetailOut(
        id=str(order.id),
        order_number=order.order_number,
        accession_id=order.accession_id,
        sample_id=order.sample_id,
        patient_id=str(order.patient_id) if order.patient_id else None,
        doctor_id=str(order.doctor_id) if order.doctor_id else None,
        client_id=str(order.client_id) if order.client_id else None,
        status=order.status,
        notes=order.notes,
        is_preallocated=0,
        items=[
            OrderItemOut(
                item_type="test",
                test_id=str(test.id),
                label=f"{test.name} ({test.code})",
                source=_item.group_label or "",
            )
            for _item, test in items
        ],
    )


def _parse_order_id(order_id: str) -> UUID:
    try:
        return UUID(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid order_id") from exc


@router.get('/{order_id}', response_model=OrderDetailOut)
def get_order(order_id: str, db: Session = Depends(get_db)):
    parsed_id = _parse_order_id(order_id)
    order = db.get(LabOrder, parsed_id)
    if order is None:
        raise HTTPException(status_code=404, detail='order not found')
    return _build_order_detail(order, db)


@router.get('/by-number/{order_number}', response_model=OrderDetailOut)
def get_order_by_number(order_number: str, db: Session = Depends(get_db)):
    normalized = order_number.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail='order_number is required')
    order = db.scalars(select(LabOrder).where(LabOrder.order_number == normalized)).first()
    if order is None:
        raise HTTPException(status_code=404, detail='order not found')
    return _build_order_detail(order, db)


@router.put('/{order_id}', response_model=OrderDetailOut)
def update_order(order_id: str, payload: OrderCreateIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    parsed_id = _parse_order_id(order_id)
    order = db.get(LabOrder, parsed_id)
    if order is None:
        raise HTTPException(status_code=404, detail='order not found')

    try:
        patient_id = UUID(payload.patient_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='invalid patient_id') from exc
    if db.get(Patient, patient_id) is None:
        raise HTTPException(status_code=404, detail='patient not found')
    requested_items = _normalize_order_items(payload, db)
    if not requested_items:
        raise HTTPException(status_code=400, detail='at least one test is required')

    doctor_id = _parse_provider_id(payload.doctor_id, field_name='doctor_id', expected_type='doctor', db=db)
    client_id = _parse_provider_id(payload.client_id, field_name='client_id', expected_type='clinic', db=db)

    before = _order_audit_payload(order, db)
    order.patient_id = patient_id
    order.doctor_id = doctor_id
    order.client_id = client_id
    order.accession_id = (payload.accession_id or '').strip() or None
    order.sample_id = (payload.sample_id or '').strip() or None
    order.notes = (payload.notes or '').strip() or None
    order.status = payload.status

    db.execute(delete(OrderItem).where(OrderItem.order_id == order.id))
    db.flush()
    for requested in requested_items:
        db.add(OrderItem(order_id=order.id, test_id=requested['test_id'], group_label=requested['source'], priority='routine'))

    db.flush()
    log_audit(
        db,
        actor_user_id=actor,
        entity="order",
        entity_id=str(order.id),
        action="update",
        before_json=before,
        after_json=_order_audit_payload(order, db),
    )
    db.commit()
    db.refresh(order)
    return _build_order_detail(order, db)


@router.post("")
def create_order(payload: OrderCreateIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    try:
        patient_id = UUID(payload.patient_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid patient_id") from exc
    requested_items = _normalize_order_items(payload, db)
    if not requested_items:
        raise HTTPException(status_code=400, detail="at least one test is required")

    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="patient not found")

    doctor_id = _parse_provider_id(payload.doctor_id, field_name="doctor_id", expected_type="doctor", db=db)
    client_id = _parse_provider_id(payload.client_id, field_name="client_id", expected_type="clinic", db=db)

    next_payload = next_number(db)
    order = LabOrder(
        order_number=next_payload["order_number"],
        patient_id=patient_id,
        doctor_id=doctor_id,
        client_id=client_id,
        accession_id=(payload.accession_id or "").strip() or None,
        sample_id=(payload.sample_id or "").strip() or None,
        notes=(payload.notes or "").strip() or None,
        status=payload.status,
    )
    db.add(order)
    db.flush()

    for requested in requested_items:
        db.add(OrderItem(order_id=order.id, test_id=requested["test_id"], group_label=requested["source"], priority="routine"))

    db.flush()
    log_audit(
        db,
        actor_user_id=actor,
        entity="order",
        entity_id=str(order.id),
        action="create",
        after_json=_order_audit_payload(order, db),
    )
    db.commit()
    return {"id": str(order.id), "order_number": order.order_number}

def _parse_provider_id(raw_value: str | None, *, field_name: str, expected_type: str, db: Session) -> UUID | None:
    if not raw_value:
        return None
    try:
        provider_id = UUID(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid {field_name}") from exc
    provider = db.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"{field_name} not found")
    if provider.provider_type != expected_type:
        raise HTTPException(status_code=400, detail=f"{field_name} must reference a {expected_type} provider")
    return provider_id


def _parse_uuid(raw_value: str, *, field_name: str) -> UUID:
    try:
        return UUID(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid {field_name}") from exc


def _normalize_order_items(payload: OrderCreateIn, db: Session) -> list[dict[str, UUID | str]]:
    raw_items = payload.items or [OrderItemIn(test_id=test_id, source="") for test_id in payload.test_ids]
    normalized: list[dict[str, UUID | str]] = []
    seen: set[UUID] = set()
    for item in raw_items:
        test_id = _parse_uuid(item.test_id, field_name="test_id")
        if test_id in seen:
            continue
        test = db.get(TestCatalog, test_id)
        if test is None or not test.active:
            raise HTTPException(status_code=404, detail="test not found")
        seen.add(test_id)
        normalized.append({"test_id": test_id, "source": (item.source or "").strip()})
    return normalized


def _order_audit_payload(order: LabOrder, db: Session) -> dict[str, object]:
    item_rows = db.execute(select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id.asc())).scalars().all()
    return {
        "order_number": order.order_number,
        "patient_id": str(order.patient_id) if order.patient_id else None,
        "doctor_id": str(order.doctor_id) if order.doctor_id else None,
        "client_id": str(order.client_id) if order.client_id else None,
        "accession_id": order.accession_id,
        "sample_id": order.sample_id,
        "status": order.status,
        "notes": order.notes,
        "items": [
            {"test_id": str(item.test_id), "source": item.group_label or ""}
            for item in item_rows
        ],
    }

