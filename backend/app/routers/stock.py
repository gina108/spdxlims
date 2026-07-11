from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.core.deps import require_roles
from app.db.session import get_db
from app.models.models import InventoryMovement, InventoryStockItem, InventorySupplier

router = APIRouter(dependencies=[Depends(require_roles("admin", "lab_manager", "tech"))])


class StockItemIn(BaseModel):
    sku: str
    name: str
    unit: str | None = None
    on_hand: float = 0
    reorder_level: float = 0
    unit_cost: float = 0


class SupplierIn(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    tax_id: str | None = None


class MovementIn(BaseModel):
    inventory_item_id: str
    supplier_id: str | None = None
    movement_type: str = "purchase"
    quantity: float = 0
    unit_cost: float = 0
    movement_date: str = ""
    notes: str | None = None


def _uuid(raw: Any, field: str) -> UUID:
    try:
        return UUID(str(raw))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid {field}") from exc


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, InvalidOperation):
        return 0.0


def _item_out(item: InventoryStockItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "sku": item.sku,
        "name": item.name,
        "unit": item.unit,
        "on_hand": _num(item.on_hand),
        "reorder_level": _num(item.reorder_level),
        "unit_cost": _num(item.unit_cost),
    }


# ---- stock items ----
@router.get("/items")
def list_items(db: Session = Depends(get_db)):
    items = db.scalars(select(InventoryStockItem).order_by(InventoryStockItem.name.asc(), InventoryStockItem.sku.asc())).all()
    return [_item_out(i) for i in items]


@router.get("/item-choices")
def item_choices(db: Session = Depends(get_db)):
    items = db.scalars(select(InventoryStockItem).order_by(InventoryStockItem.name.asc(), InventoryStockItem.sku.asc())).all()
    return [{"id": str(i.id), "label": f"{i.name} ({i.sku})"} for i in items]


@router.post("/items")
def create_item(payload: StockItemIn, db: Session = Depends(get_db)):
    item = InventoryStockItem(
        sku=payload.sku.strip(),
        name=payload.name.strip(),
        unit=(payload.unit or None),
        on_hand=payload.on_hand or 0,
        reorder_level=payload.reorder_level or 0,
        unit_cost=payload.unit_cost or 0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": str(item.id)}


@router.put("/items/{item_id}")
def update_item(item_id: str, payload: StockItemIn, db: Session = Depends(get_db)):
    item = db.get(InventoryStockItem, _uuid(item_id, "item_id"))
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    item.sku = payload.sku.strip()
    item.name = payload.name.strip()
    item.unit = payload.unit or None
    item.on_hand = payload.on_hand or 0
    item.reorder_level = payload.reorder_level or 0
    item.unit_cost = payload.unit_cost or 0
    db.commit()
    return {"status": "ok"}


@router.get("/items/{item_id}/has-movements")
def item_has_movements(item_id: str, db: Session = Depends(get_db)):
    found = db.scalar(select(exists().where(InventoryMovement.inventory_item_id == _uuid(item_id, "item_id"))))
    return {"has_movements": bool(found)}


@router.delete("/items/{item_id}")
def delete_item(item_id: str, db: Session = Depends(get_db)):
    db.execute(delete(InventoryStockItem).where(InventoryStockItem.id == _uuid(item_id, "item_id")))
    db.commit()
    return {"status": "ok"}


# ---- suppliers ----
def _supplier_out(s: InventorySupplier) -> dict[str, Any]:
    return {"id": str(s.id), "name": s.name, "phone": s.phone, "email": s.email, "tax_id": s.tax_id}


@router.get("/suppliers")
def list_suppliers(db: Session = Depends(get_db)):
    rows = db.scalars(select(InventorySupplier).order_by(InventorySupplier.name.asc())).all()
    return [_supplier_out(s) for s in rows]


@router.get("/supplier-choices")
def supplier_choices(db: Session = Depends(get_db)):
    rows = db.scalars(select(InventorySupplier).order_by(InventorySupplier.name.asc())).all()
    return [{"id": str(s.id), "label": s.name if not s.tax_id else f"{s.name} ({s.tax_id})"} for s in rows]


@router.post("/suppliers")
def create_supplier(payload: SupplierIn, db: Session = Depends(get_db)):
    s = InventorySupplier(name=payload.name.strip(), phone=payload.phone or None, email=payload.email or None, tax_id=payload.tax_id or None)
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": str(s.id)}


@router.put("/suppliers/{supplier_id}")
def update_supplier(supplier_id: str, payload: SupplierIn, db: Session = Depends(get_db)):
    s = db.get(InventorySupplier, _uuid(supplier_id, "supplier_id"))
    if s is None:
        raise HTTPException(status_code=404, detail="supplier not found")
    s.name = payload.name.strip()
    s.phone = payload.phone or None
    s.email = payload.email or None
    s.tax_id = payload.tax_id or None
    db.commit()
    return {"status": "ok"}


@router.get("/suppliers/{supplier_id}/has-movements")
def supplier_has_movements(supplier_id: str, db: Session = Depends(get_db)):
    found = db.scalar(select(exists().where(InventoryMovement.supplier_id == _uuid(supplier_id, "supplier_id"))))
    return {"has_movements": bool(found)}


@router.delete("/suppliers/{supplier_id}")
def delete_supplier(supplier_id: str, db: Session = Depends(get_db)):
    db.execute(delete(InventorySupplier).where(InventorySupplier.id == _uuid(supplier_id, "supplier_id")))
    db.commit()
    return {"status": "ok"}


# ---- movements ----
@router.get("/movements")
def list_movements(db: Session = Depends(get_db)):
    supplier = aliased(InventorySupplier)
    rows = db.execute(
        select(
            InventoryMovement.id,
            InventoryMovement.inventory_item_id,
            InventoryStockItem.name.label("inventory_name"),
            supplier.name.label("supplier_name"),
            InventoryMovement.movement_type,
            InventoryMovement.quantity,
            InventoryMovement.unit_cost,
            InventoryMovement.movement_date,
            InventoryMovement.notes,
        )
        .join(InventoryStockItem, InventoryStockItem.id == InventoryMovement.inventory_item_id)
        .outerjoin(supplier, supplier.id == InventoryMovement.supplier_id)
        .order_by(InventoryMovement.movement_date.desc().nulls_last(), InventoryMovement.created_at.desc())
    ).all()
    return [
        {
            "id": str(r.id),
            "inventory_item_id": str(r.inventory_item_id),
            "inventory_name": r.inventory_name,
            "supplier_name": r.supplier_name,
            "movement_type": r.movement_type,
            "quantity": _num(r.quantity),
            "unit_cost": _num(r.unit_cost),
            "movement_date": r.movement_date.isoformat() if r.movement_date else "",
            "notes": r.notes,
        }
        for r in rows
    ]


@router.post("/movements")
def create_movement(payload: MovementIn, db: Session = Depends(get_db)):
    item = db.get(InventoryStockItem, _uuid(payload.inventory_item_id, "inventory_item_id"))
    if item is None:
        raise HTTPException(status_code=404, detail="inventory item not found")
    quantity = _num(payload.quantity)
    movement_type = payload.movement_type or "purchase"
    signed = quantity if movement_type in {"purchase", "adjustment_in"} else -abs(quantity)
    unit_cost = _num(payload.unit_cost)
    parsed_date: date | None = None
    if payload.movement_date.strip():
        try:
            parsed_date = date.fromisoformat(payload.movement_date.strip()[:10])
        except ValueError:
            parsed_date = None
    movement = InventoryMovement(
        inventory_item_id=item.id,
        supplier_id=_uuid(payload.supplier_id, "supplier_id") if payload.supplier_id else None,
        movement_type=movement_type,
        quantity=signed,
        unit_cost=unit_cost,
        movement_date=parsed_date,
        notes=payload.notes or None,
    )
    db.add(movement)
    item.on_hand = Decimal(str(_num(item.on_hand))) + Decimal(str(signed))
    if unit_cost > 0:
        item.unit_cost = unit_cost
    db.flush()
    db.commit()
    return {"id": str(movement.id)}
