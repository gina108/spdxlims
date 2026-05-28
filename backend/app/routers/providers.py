from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.deps import require_roles
from app.db.session import get_db
from app.models.models import Provider, ProviderPrice
from app.routers.common import actor_from_header

router = APIRouter(dependencies=[Depends(require_roles("admin", "lab_manager"))])


class ProviderIn(BaseModel):
    provider_type: str
    code: str | None = None
    legal_name: str
    tax_id: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    billing_terms_days: int = 30
    active: bool = True


class ProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_type: str
    code: str | None
    legal_name: str
    tax_id: str | None
    email: str | None
    phone: str | None
    billing_terms_days: int
    active: bool


class ProviderPriceIn(BaseModel):
    test_id: UUID
    price: Decimal
    effective_from: date
    effective_to: date | None = None


@router.post("", response_model=ProviderOut)
def create_provider(payload: ProviderIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    obj = Provider(**payload.model_dump())
    db.add(obj)
    db.flush()
    log_audit(db, actor_user_id=actor, entity="provider", entity_id=str(obj.id), action="create", after_json=payload.model_dump(mode="json"))
    db.commit()
    db.refresh(obj)
    return obj


@router.get("", response_model=list[ProviderOut])
def list_providers(provider_type: str | None = Query(None), status_filter: str = Query("all"), db: Session = Depends(get_db)):
    stmt = select(Provider)
    if provider_type:
        stmt = stmt.where(Provider.provider_type == provider_type.strip().lower())
    normalized = status_filter.strip().lower()
    if normalized == "active":
        stmt = stmt.where(Provider.active.is_(True))
    elif normalized == "archived":
        stmt = stmt.where(Provider.active.is_(False))
    return db.scalars(stmt.order_by(Provider.active.desc(), Provider.legal_name.asc())).all()


@router.get("/{provider_id}", response_model=ProviderOut)
def get_provider(provider_id: UUID, db: Session = Depends(get_db)):
    provider = db.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="provider not found")
    return provider


@router.put("/{provider_id}", response_model=ProviderOut)
def update_provider(provider_id: UUID, payload: ProviderIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    provider = db.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="provider not found")
    before = _provider_audit_payload(provider)
    for key, value in payload.model_dump().items():
        setattr(provider, key, value)
    log_audit(db, actor_user_id=actor, entity="provider", entity_id=str(provider.id), action="update", before_json=before, after_json=payload.model_dump(mode="json"))
    db.commit()
    db.refresh(provider)
    return provider


@router.post("/{provider_id}/archive")
def archive_provider(provider_id: UUID, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    provider = db.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="provider not found")
    before = _provider_audit_payload(provider)
    provider.active = False
    log_audit(db, actor_user_id=actor, entity="provider", entity_id=str(provider.id), action="archive", before_json=before, after_json=_provider_audit_payload(provider))
    db.commit()
    return {"id": str(provider.id), "active": False}


@router.post("/{provider_id}/unarchive")
def unarchive_provider(provider_id: UUID, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    provider = db.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="provider not found")
    before = _provider_audit_payload(provider)
    provider.active = True
    log_audit(db, actor_user_id=actor, entity="provider", entity_id=str(provider.id), action="unarchive", before_json=before, after_json=_provider_audit_payload(provider))
    db.commit()
    return {"id": str(provider.id), "active": True}


@router.post("/{provider_id}/prices")
def add_provider_price(provider_id: UUID, payload: ProviderPriceIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    obj = ProviderPrice(provider_id=provider_id, **payload.model_dump())
    db.add(obj)
    db.flush()
    log_audit(db, actor_user_id=actor, entity="provider_price", entity_id=str(obj.id), action="create", after_json=payload.model_dump(mode="json"))
    db.commit()
    return {"id": str(obj.id)}


@router.get("/{provider_id}/prices")
def list_provider_prices(provider_id: UUID, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(ProviderPrice)
        .where(ProviderPrice.provider_id == provider_id)
        .order_by(ProviderPrice.effective_from.desc())
    ).all()
    return [
        {
            "id": str(x.id),
            "test_id": str(x.test_id),
            "price": str(x.price),
            "effective_from": x.effective_from,
            "effective_to": x.effective_to,
        }
        for x in rows
    ]


def _provider_audit_payload(provider: Provider) -> dict:
    return {
        "id": str(provider.id),
        "provider_type": provider.provider_type,
        "code": provider.code,
        "legal_name": provider.legal_name,
        "tax_id": provider.tax_id,
        "email": provider.email,
        "phone": provider.phone,
        "address": provider.address,
        "billing_terms_days": provider.billing_terms_days,
        "active": provider.active,
    }


