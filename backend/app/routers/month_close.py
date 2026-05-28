from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.deps import require_roles
from app.db.session import get_db
from app.models.models import MonthEndChecklist, MonthEndClose, MonthEndSnapshot
from app.routers.common import actor_from_header

router = APIRouter(dependencies=[Depends(require_roles("admin", "lab_manager"))])

DEFAULT_CHECKLIST = ["billing_reviewed", "inventory_reviewed", "reports_generated", "approved"]


class OpenCloseIn(BaseModel):
    period_start: date
    period_end: date
    notes: str | None = None


class ChecklistCompleteIn(BaseModel):
    note: str | None = None


class SnapshotIn(BaseModel):
    payload: dict


@router.post("/open")
def open_month(payload: OpenCloseIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    if actor is None:
        raise HTTPException(status_code=400, detail="x-user-id header required")
    if payload.period_end < payload.period_start:
        raise HTTPException(status_code=400, detail="period_end must be >= period_start")

    existing = db.scalars(select(MonthEndClose).where(MonthEndClose.period_start == payload.period_start, MonthEndClose.period_end == payload.period_end)).first()
    if existing:
        raise HTTPException(status_code=409, detail="month period already exists")

    close = MonthEndClose(
        period_start=payload.period_start,
        period_end=payload.period_end,
        status="open",
        opened_by=actor,
        notes=payload.notes,
    )
    db.add(close)
    db.flush()

    for key in DEFAULT_CHECKLIST:
        db.add(MonthEndChecklist(close_id=close.id, item_key=key, is_done=False))

    log_audit(db, actor_user_id=actor, entity="month_end_close", entity_id=str(close.id), action="open", after_json=payload.model_dump(mode="json"))
    db.commit()
    return {"id": str(close.id), "status": close.status}


@router.get("/{close_id}")
def get_close(close_id: UUID, db: Session = Depends(get_db)):
    close = db.get(MonthEndClose, close_id)
    if not close:
        raise HTTPException(status_code=404, detail="not found")
    checklist = db.scalars(select(MonthEndChecklist).where(MonthEndChecklist.close_id == close_id).order_by(MonthEndChecklist.item_key.asc())).all()
    return {
        "id": str(close.id),
        "period_start": close.period_start,
        "period_end": close.period_end,
        "status": close.status,
        "opened_at": close.opened_at,
        "closed_at": close.closed_at,
        "checklist": [
            {"item_key": x.item_key, "is_done": x.is_done, "done_by": str(x.done_by) if x.done_by else None, "done_at": x.done_at}
            for x in checklist
        ],
    }


@router.post("/{close_id}/checklist/{item_key}/complete")
def complete_item(
    close_id: UUID,
    item_key: str,
    payload: ChecklistCompleteIn,
    db: Session = Depends(get_db),
    actor: UUID | None = Depends(actor_from_header),
):
    if actor is None:
        raise HTTPException(status_code=400, detail="x-user-id header required")
    item = db.scalars(select(MonthEndChecklist).where(MonthEndChecklist.close_id == close_id, MonthEndChecklist.item_key == item_key)).first()
    if not item:
        raise HTTPException(status_code=404, detail="checklist item not found")
    item.is_done = True
    item.done_by = actor
    item.done_at = datetime.now(timezone.utc)
    item.note = payload.note

    close = db.get(MonthEndClose, close_id)
    if close and close.status == "open":
        close.status = "in_review"

    log_audit(db, actor_user_id=actor, entity="month_end_checklist", entity_id=str(item.id), action="complete", after_json={"item_key": item_key})
    db.commit()
    return {"item_key": item_key, "is_done": True}


@router.post("/{close_id}/snapshot/{snapshot_type}")
def add_snapshot(close_id: UUID, snapshot_type: str, payload: SnapshotIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    if snapshot_type not in {"billing", "inventory", "operations"}:
        raise HTTPException(status_code=400, detail="invalid snapshot_type")
    close = db.get(MonthEndClose, close_id)
    if not close:
        raise HTTPException(status_code=404, detail="month close not found")

    snap = MonthEndSnapshot(close_id=close_id, snapshot_type=snapshot_type, payload=payload.payload)
    db.add(snap)
    db.flush()
    log_audit(db, actor_user_id=actor, entity="month_end_snapshot", entity_id=str(snap.id), action="create", after_json={"snapshot_type": snapshot_type})
    db.commit()
    return {"id": str(snap.id)}


@router.post("/{close_id}/close")
def close_month(close_id: UUID, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    if actor is None:
        raise HTTPException(status_code=400, detail="x-user-id header required")

    close = db.get(MonthEndClose, close_id)
    if not close:
        raise HTTPException(status_code=404, detail="month close not found")
    if close.status == "closed":
        raise HTTPException(status_code=409, detail="already closed")

    open_items = db.scalars(
        select(MonthEndChecklist).where(MonthEndChecklist.close_id == close_id, MonthEndChecklist.is_done.is_(False))
    ).all()
    if open_items:
        raise HTTPException(status_code=409, detail="cannot close month: checklist incomplete")

    close.status = "closed"
    close.closed_by = actor
    close.closed_at = datetime.now(timezone.utc)
    log_audit(db, actor_user_id=actor, entity="month_end_close", entity_id=str(close.id), action="close")
    db.commit()
    return {"id": str(close.id), "status": close.status}


@router.get("/history")
def history(db: Session = Depends(get_db)):
    rows = db.scalars(select(MonthEndClose).order_by(MonthEndClose.period_end.desc())).all()
    return [
        {
            "id": str(x.id),
            "period_start": x.period_start,
            "period_end": x.period_end,
            "status": x.status,
            "opened_at": x.opened_at,
            "closed_at": x.closed_at,
        }
        for x in rows
    ]


