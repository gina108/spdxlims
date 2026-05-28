from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.db.session import get_db
from app.models.models import Patient
from app.routers.common import actor_from_header

router = APIRouter()


class PatientIn(BaseModel):
    mrn: str | None = None
    first_name: str
    last_name: str
    middle_name: str | None = None
    sex: str | None = None
    dob: date | None = None
    age_value: int | None = None
    age_unit: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    is_active: bool = True


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mrn: str | None
    first_name: str
    last_name: str
    middle_name: str | None
    sex: str | None
    dob: date | None
    age_value: int | None
    age_unit: str | None
    phone: str | None
    email: str | None
    address: str | None
    is_active: bool


def _normalize_status_filter(status_filter: str) -> str:
    normalized = status_filter.strip().lower()
    return normalized if normalized in {"active", "archived", "all"} else "active"


@router.get("", response_model=list[PatientOut])
def list_patients(status_filter: str = "active", db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    q = select(Patient)
    normalized = _normalize_status_filter(status_filter)
    if normalized == "active":
        q = q.where(Patient.is_active.is_(True))
    elif normalized == "archived":
        q = q.where(Patient.is_active.is_(False))
    return db.scalars(q.order_by(Patient.created_at.desc(), Patient.last_name.asc(), Patient.first_name.asc())).all()


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: UUID, db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="patient not found")
    return patient


@router.post("", response_model=PatientOut)
def create_patient(payload: PatientIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    patient = Patient(**payload.model_dump())
    db.add(patient)
    db.flush()
    log_audit(db, actor_user_id=actor, entity="patient", entity_id=str(patient.id), action="create", after_json=payload.model_dump(mode="json"))
    db.commit()
    db.refresh(patient)
    return patient


@router.put("/{patient_id}", response_model=PatientOut)
def update_patient(patient_id: UUID, payload: PatientIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="patient not found")
    before = {
        "mrn": patient.mrn,
        "first_name": patient.first_name,
        "last_name": patient.last_name,
        "middle_name": patient.middle_name,
        "sex": patient.sex,
        "dob": str(patient.dob) if patient.dob else None,
        "age_value": patient.age_value,
        "age_unit": patient.age_unit,
        "phone": patient.phone,
        "email": patient.email,
        "address": patient.address,
        "is_active": patient.is_active,
    }
    for key, value in payload.model_dump().items():
        setattr(patient, key, value)
    log_audit(db, actor_user_id=actor, entity="patient", entity_id=str(patient.id), action="update", before_json=before, after_json=payload.model_dump(mode="json"))
    db.commit()
    db.refresh(patient)
    return patient


@router.post("/{patient_id}/archive")
def archive_patient(patient_id: UUID, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="patient not found")
    patient.is_active = False
    log_audit(db, actor_user_id=actor, entity="patient", entity_id=str(patient.id), action="archive")
    db.commit()
    return {"id": str(patient.id), "is_active": patient.is_active}


@router.post("/{patient_id}/unarchive")
def unarchive_patient(patient_id: UUID, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="patient not found")
    patient.is_active = True
    log_audit(db, actor_user_id=actor, entity="patient", entity_id=str(patient.id), action="unarchive")
    db.commit()
    return {"id": str(patient.id), "is_active": patient.is_active}


