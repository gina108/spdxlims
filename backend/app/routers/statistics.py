from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import distinct, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.db.session import get_db
from app.models.models import LabOrder, OrderItem, PanelCatalog, Provider, TestCatalog
from app.routers.common import actor_from_header

router = APIRouter()

# Orders carry placeholder "tests" for panel headings/comments; never count them.
_PLACEHOLDER_CODES = ("__PANEL_HEADING__", "__PANEL_COMMENT__")


class StatsQuery(BaseModel):
    date_from: str = ""
    date_to: str = ""
    client_id: str | None = None
    # Each subject is [kind, value]; kind in {doctor, client, test, panel}.
    # Panel values may themselves be a list of source-label forms (code/name).
    subjects: list[list[Any]] = []


def _to_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


def _parse_date(raw: str, field: str) -> date:
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid {field}") from exc


def _base_conditions(body: StatsQuery) -> list[Any]:
    conds: list[Any] = [func.coalesce(LabOrder.is_archived, False).is_(False)]
    if body.date_from:
        conds.append(func.date(LabOrder.ordered_at) >= _parse_date(body.date_from, "date_from"))
    if body.date_to:
        conds.append(func.date(LabOrder.ordered_at) <= _parse_date(body.date_to, "date_to"))
    if body.client_id:
        cid = _to_uuid(body.client_id)
        if cid is not None:
            conds.append(LabOrder.client_id == cid)
    return conds


def _subject_conditions(body: StatsQuery, *, test_direct: bool = False, panel_direct: bool = False) -> list[Any]:
    doctors = [_to_uuid(v) for k, v in _kv(body.subjects) if k == "doctor"]
    clients = [_to_uuid(v) for k, v in _kv(body.subjects) if k == "client"]
    tests = [_to_uuid(v) for k, v in _kv(body.subjects) if k == "test"]
    doctors = [u for u in doctors if u is not None]
    clients = [u for u in clients if u is not None]
    tests = [u for u in tests if u is not None]
    panels: list[str] = []
    for kind, value in _kv(body.subjects):
        if kind != "panel" or value in (None, ""):
            continue
        if isinstance(value, (list, tuple)):
            panels.extend(str(form) for form in value if form not in (None, ""))
        else:
            panels.append(str(value))

    conds: list[Any] = []
    if doctors:
        conds.append(LabOrder.doctor_id.in_(doctors))
    if clients:
        conds.append(LabOrder.client_id.in_(clients))
    if tests:
        if test_direct:
            conds.append(OrderItem.test_id.in_(tests))
        else:
            sx = aliased(OrderItem)
            conds.append(exists().where(sx.order_id == LabOrder.id, sx.test_id.in_(tests)))
    if panels:
        if panel_direct:
            conds.append(func.trim(OrderItem.source_label).in_(panels))
        else:
            sp = aliased(OrderItem)
            conds.append(exists().where(sp.order_id == LabOrder.id, func.trim(sp.source_label).in_(panels)))
    return conds


def _kv(subjects: list[list[Any]]):
    for entry in subjects or []:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            yield str(entry[0]), entry[1]


@router.post("/test-volume")
def report_test_volume(body: StatsQuery, db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    conds = _base_conditions(body) + _subject_conditions(body, test_direct=True)
    rows = db.execute(
        select(
            TestCatalog.code.label("test_code"),
            TestCatalog.name.label("test_name"),
            func.coalesce(TestCatalog.category_name, "").label("category"),
            func.count().label("times_ordered"),
        )
        .select_from(OrderItem)
        .join(LabOrder, LabOrder.id == OrderItem.order_id)
        .join(TestCatalog, TestCatalog.id == OrderItem.test_id)
        .where(TestCatalog.code.notin_(_PLACEHOLDER_CODES), *conds)
        .group_by(TestCatalog.id, TestCatalog.code, TestCatalog.name, TestCatalog.category_name)
        .order_by(func.count().desc(), TestCatalog.name)
    ).all()
    return [
        {"test_code": r.test_code, "test_name": r.test_name, "category": r.category, "times_ordered": int(r.times_ordered)}
        for r in rows
    ]


@router.post("/panel-volume")
def report_panel_volume(body: StatsQuery, db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    conds = _base_conditions(body) + _subject_conditions(body, panel_direct=True)
    label = func.coalesce(PanelCatalog.name, func.trim(OrderItem.source_label))
    rows = db.execute(
        select(
            label.label("panel"),
            func.count(distinct(LabOrder.id)).label("times_ordered"),
            func.count().label("test_instances"),
        )
        .select_from(OrderItem)
        .join(LabOrder, LabOrder.id == OrderItem.order_id)
        .join(TestCatalog, TestCatalog.id == OrderItem.test_id)
        .outerjoin(
            PanelCatalog,
            (PanelCatalog.code == func.trim(OrderItem.source_label)) | (PanelCatalog.name == func.trim(OrderItem.source_label)),
        )
        .where(func.coalesce(OrderItem.source_label, "") != "", TestCatalog.code.notin_(_PLACEHOLDER_CODES), *conds)
        .group_by(label)
        .order_by(func.count(distinct(LabOrder.id)).desc(), label)
    ).all()
    return [
        {"panel": r.panel, "times_ordered": int(r.times_ordered), "test_instances": int(r.test_instances)}
        for r in rows
    ]


@router.post("/client-volume")
def report_client_volume(body: StatsQuery, db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    client = aliased(Provider)
    conds = _base_conditions(body) + _subject_conditions(body)
    rows = db.execute(
        select(
            func.coalesce(client.legal_name, "").label("client_name"),
            func.count(distinct(LabOrder.id)).label("order_count"),
            func.count(OrderItem.id).filter(TestCatalog.code.notin_(_PLACEHOLDER_CODES)).label("test_count"),
        )
        .select_from(LabOrder)
        .outerjoin(client, (client.id == LabOrder.client_id) & (client.provider_type == "clinic"))
        .outerjoin(OrderItem, OrderItem.order_id == LabOrder.id)
        .outerjoin(TestCatalog, TestCatalog.id == OrderItem.test_id)
        .where(*conds)
        .group_by(LabOrder.client_id, client.legal_name)
        .order_by(func.count(distinct(LabOrder.id)).desc(), func.coalesce(client.legal_name, ""))
    ).all()
    return [
        {"client_name": r.client_name, "order_count": int(r.order_count), "test_count": int(r.test_count or 0)}
        for r in rows
    ]


@router.post("/doctor-volume")
def report_doctor_volume(body: StatsQuery, db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    doctor = aliased(Provider)
    conds = _base_conditions(body) + _subject_conditions(body)
    rows = db.execute(
        select(
            func.coalesce(doctor.legal_name, "").label("doctor_name"),
            func.count(distinct(LabOrder.id)).label("order_count"),
            func.count(OrderItem.id).filter(TestCatalog.code.notin_(_PLACEHOLDER_CODES)).label("test_count"),
        )
        .select_from(LabOrder)
        .outerjoin(doctor, (doctor.id == LabOrder.doctor_id) & (doctor.provider_type == "doctor"))
        .outerjoin(OrderItem, OrderItem.order_id == LabOrder.id)
        .outerjoin(TestCatalog, TestCatalog.id == OrderItem.test_id)
        .where(*conds)
        .group_by(LabOrder.doctor_id, doctor.legal_name)
        .order_by(func.count(distinct(LabOrder.id)).desc(), func.coalesce(doctor.legal_name, ""))
    ).all()
    return [
        {"doctor_name": r.doctor_name, "order_count": int(r.order_count), "test_count": int(r.test_count or 0)}
        for r in rows
    ]


@router.get("/panel-filter-options")
def list_panel_filter_options(db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    used = {
        str(row[0]).strip()
        for row in db.execute(
            select(distinct(func.trim(OrderItem.source_label))).where(func.coalesce(OrderItem.source_label, "") != "")
        ).all()
        if row[0] and str(row[0]).strip()
    }
    catalog = db.execute(select(PanelCatalog.code, PanelCatalog.name)).all()
    options: list[dict[str, Any]] = []
    consumed: set[str] = set()
    for code, name in catalog:
        code_s = (code or "").strip()
        name_s = (name or "").strip()
        forms = [f for f in (code_s, name_s) if f]
        if not any(f in used for f in forms):
            continue
        consumed.update(forms)
        options.append({"forms": forms, "label": name_s or code_s})
    for label in sorted(used - consumed, key=str.lower):
        options.append({"forms": [label], "label": label})
    options.sort(key=lambda o: o["label"].lower())
    return options


def _provider_choices(db: Session, provider_type: str, active_only: bool) -> list[dict[str, str]]:
    stmt = select(Provider.id, Provider.legal_name).where(Provider.provider_type == provider_type)
    if active_only:
        stmt = stmt.where(Provider.active.is_(True))
    stmt = stmt.order_by(Provider.legal_name.asc())
    return [{"id": str(pid), "label": name or ""} for pid, name in db.execute(stmt).all()]


@router.get("/clients")
def list_client_choices(active_only: bool = True, db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    return _provider_choices(db, "clinic", active_only)


@router.get("/doctors")
def list_doctor_choices(active_only: bool = True, db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    return _provider_choices(db, "doctor", active_only)


@router.get("/tests")
def list_test_choices(db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    rows = db.execute(
        select(TestCatalog.id, TestCatalog.code, TestCatalog.name)
        .where(TestCatalog.active.is_(True))
        .order_by(TestCatalog.name.asc())
    ).all()
    return [{"id": str(tid), "label": f"{name} ({code})" if code else (name or "")} for tid, code, name in rows]
