from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.deps import require_roles
from app.db.session import get_db
from app.models.models import InventoryItem, InventoryLot, InventoryTxn
from app.routers.common import actor_from_header

router = APIRouter(dependencies=[Depends(require_roles("admin", "lab_manager", "tech"))])


class InventoryItemIn(BaseModel):
    sku: str
    name: str
    category: str
    unit: str
    min_stock: Decimal = Decimal("0")
    max_stock: Decimal | None = None


class InventoryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku: str
    name: str
    category: str
    unit: str
    min_stock: Decimal
    max_stock: Decimal | None
    active: bool


class InventoryLotIn(BaseModel):
    item_id: UUID
    supplier_id: UUID | None = None
    lot_number: str
    expiration_date: date | None = None
    received_date: date
    unit_cost: Decimal | None = None
    initial_qty: Decimal
    current_qty: Decimal
    status: str = "active"


class InventoryTxnIn(BaseModel):
    item_id: UUID
    lot_id: UUID | None = None
    txn_type: str
    qty: Decimal
    unit_cost: Decimal | None = None
    reference_type: str | None = None
    reference_id: str | None = None
    note: str | None = None


@router.post("/items", response_model=InventoryItemOut)
def create_item(payload: InventoryItemIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    item = InventoryItem(**payload.model_dump())
    db.add(item)
    db.flush()
    log_audit(db, actor_user_id=actor, entity="inventory_item", entity_id=str(item.id), action="create", after_json=payload.model_dump(mode="json"))
    db.commit()
    db.refresh(item)
    return item


@router.get("/items", response_model=list[InventoryItemOut])
def list_items(db: Session = Depends(get_db)):
    return db.scalars(select(InventoryItem).order_by(InventoryItem.name.asc())).all()


@router.post("/lots")
def create_lot(payload: InventoryLotIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    lot = InventoryLot(**payload.model_dump())
    db.add(lot)
    db.flush()
    log_audit(db, actor_user_id=actor, entity="inventory_lot", entity_id=str(lot.id), action="create", after_json=payload.model_dump(mode="json"))
    db.commit()
    return {"id": str(lot.id)}


@router.get("/lots")
def list_lots(item_id: UUID | None = None, expiring_before: date | None = None, db: Session = Depends(get_db)):
    q = select(InventoryLot)
    if item_id:
        q = q.where(InventoryLot.item_id == item_id)
    if expiring_before:
        q = q.where(InventoryLot.expiration_date.is_not(None), InventoryLot.expiration_date <= expiring_before)
    lots = db.scalars(q.order_by(InventoryLot.expiration_date.asc().nulls_last())).all()
    return [
        {
            "id": str(x.id),
            "item_id": str(x.item_id),
            "lot_number": x.lot_number,
            "expiration_date": x.expiration_date,
            "current_qty": str(x.current_qty),
            "status": x.status,
        }
        for x in lots
    ]


@router.post("/txns")
def create_txn(payload: InventoryTxnIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    if payload.qty <= 0:
        raise HTTPException(status_code=400, detail="qty must be > 0")
    if actor is None:
        raise HTTPException(status_code=400, detail="x-user-id header required for inventory transactions")

    txn = InventoryTxn(created_by=actor, **payload.model_dump())
    db.add(txn)
    db.flush()

    if payload.lot_id:
        lot = db.get(InventoryLot, payload.lot_id)
        if not lot:
            raise HTTPException(status_code=404, detail="lot not found")
        if payload.txn_type in {"purchase_in", "adjustment_plus"}:
            lot.current_qty = Decimal(lot.current_qty) + payload.qty
        else:
            lot.current_qty = Decimal(lot.current_qty) - payload.qty

    log_audit(db, actor_user_id=actor, entity="inventory_txn", entity_id=str(txn.id), action="create", after_json=payload.model_dump(mode="json"))
    db.commit()
    return {"id": str(txn.id)}


@router.get("/stock-summary")
def stock_summary(db: Session = Depends(get_db)):
    rows = db.execute(
        select(
            InventoryItem.id,
            InventoryItem.sku,
            InventoryItem.name,
            InventoryItem.min_stock,
            func.coalesce(func.sum(InventoryLot.current_qty), 0).label("stock"),
        )
        .outerjoin(InventoryLot, InventoryLot.item_id == InventoryItem.id)
        .group_by(InventoryItem.id)
        .order_by(InventoryItem.name.asc())
    ).all()
    return [
        {
            "item_id": str(r.id),
            "sku": r.sku,
            "name": r.name,
            "min_stock": str(r.min_stock),
            "stock": str(r.stock),
        }
        for r in rows
    ]


@router.get("/alerts/low-stock")
def low_stock(db: Session = Depends(get_db)):
    rows = db.execute(
        select(
            InventoryItem.id,
            InventoryItem.sku,
            InventoryItem.name,
            InventoryItem.min_stock,
            func.coalesce(func.sum(InventoryLot.current_qty), 0).label("stock"),
        )
        .outerjoin(InventoryLot, InventoryLot.item_id == InventoryItem.id)
        .group_by(InventoryItem.id)
        .having(func.coalesce(func.sum(InventoryLot.current_qty), 0) < InventoryItem.min_stock)
        .order_by(InventoryItem.name.asc())
    ).all()
    return [{"item_id": str(r.id), "sku": r.sku, "name": r.name, "stock": str(r.stock), "min_stock": str(r.min_stock)} for r in rows]


@router.get("/alerts/expiring")
def expiring(days: int = 30, db: Session = Depends(get_db)):
    limit_date = date.today().fromordinal(date.today().toordinal() + days)
    lots = db.scalars(
        select(InventoryLot)
        .where(InventoryLot.expiration_date.is_not(None), InventoryLot.expiration_date <= limit_date, InventoryLot.current_qty > 0)
        .order_by(InventoryLot.expiration_date.asc())
    ).all()
    return [
        {
            "lot_id": str(x.id),
            "item_id": str(x.item_id),
            "lot_number": x.lot_number,
            "expiration_date": x.expiration_date,
            "current_qty": str(x.current_qty),
        }
        for x in lots
    ]


