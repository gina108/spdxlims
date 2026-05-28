from __future__ import annotations

import base64
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.deps import require_roles
from app.db.session import get_db
from app.models.models import AppUser, LabProfile
from app.routers.common import actor_from_header

router = APIRouter()

UPLOAD_DIR = Path(__file__).resolve().parent.parent / 'static' / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class LabProfileAssetIn(BaseModel):
    filename: str | None = None
    content_b64: str | None = None


class LabProfileIn(BaseModel):
    lab_name: str = ''
    address: str = ''
    phone: str = ''
    email: str = ''
    report_footer: str = ''
    director_name: str = ''
    director_license: str = ''
    logo: LabProfileAssetIn | None = None
    header: LabProfileAssetIn | None = None
    footer_signature: LabProfileAssetIn | None = None


class LabProfileOut(BaseModel):
    lab_name: str = ''
    address: str = ''
    phone: str = ''
    email: str = ''
    logo_path: str = ''
    header_image_path: str = ''
    footer_signature_image_path: str = ''
    report_footer: str = ''
    director_name: str = ''
    director_license: str = ''


@router.get('', response_model=LabProfileOut)
def get_lab_profile(request: Request, db: Session = Depends(get_db), _actor=Depends(actor_from_header)):
    profile = _get_or_create_profile(db)
    db.commit()
    return _serialize_profile(profile, request)


@router.put('', response_model=LabProfileOut)
def save_lab_profile(
    payload: LabProfileIn,
    request: Request,
    db: Session = Depends(get_db),
    actor: AppUser = Depends(require_roles('admin', 'lab_manager')),
):
    profile = _get_or_create_profile(db)
    before = _lab_profile_audit_payload(profile)
    profile.lab_name = payload.lab_name.strip()
    profile.address = payload.address.strip()
    profile.phone = payload.phone.strip()
    profile.email = payload.email.strip()
    profile.report_footer = payload.report_footer.strip()
    profile.director_name = payload.director_name.strip()
    profile.director_license = payload.director_license.strip()

    _update_asset(profile, 'logo_path', 'logo', payload.logo)
    _update_asset(profile, 'header_image_path', 'header', payload.header)
    _update_asset(profile, 'footer_signature_image_path', 'footer_signature', payload.footer_signature)

    db.add(profile)
    db.flush()
    log_audit(
        db,
        actor_user_id=actor.id,
        entity='lab_profile',
        entity_id=str(profile.id),
        action='update',
        before_json=before,
        after_json=_lab_profile_audit_payload(profile),
    )
    db.commit()
    db.refresh(profile)
    return _serialize_profile(profile, request)


def _get_or_create_profile(db: Session) -> LabProfile:
    profile = db.get(LabProfile, 1)
    if profile is None:
        profile = LabProfile(id=1)
        db.add(profile)
        db.flush()
    return profile


def _update_asset(profile: LabProfile, field_name: str, stem: str, payload: LabProfileAssetIn | None) -> None:
    if payload is None or not payload.content_b64:
        return
    filename = payload.filename or f'{stem}.bin'
    suffix = Path(filename).suffix.lower() or '.bin'
    target = UPLOAD_DIR / f'lab_profile_{stem}{suffix}'
    raw_bytes = base64.b64decode(payload.content_b64)
    target.write_bytes(raw_bytes)
    setattr(profile, field_name, f'/static/uploads/{target.name}')


def _serialize_profile(profile: LabProfile, request: Request) -> LabProfileOut:
    return LabProfileOut(
        lab_name=profile.lab_name or '',
        address=profile.address or '',
        phone=profile.phone or '',
        email=profile.email or '',
        logo_path=_public_asset_url(profile.logo_path, request),
        header_image_path=_public_asset_url(profile.header_image_path, request),
        footer_signature_image_path=_public_asset_url(profile.footer_signature_image_path, request),
        report_footer=profile.report_footer or '',
        director_name=profile.director_name or '',
        director_license=profile.director_license or '',
    )


def _lab_profile_audit_payload(profile: LabProfile) -> dict[str, object]:
    return {
        'id': profile.id,
        'lab_name': profile.lab_name,
        'address': profile.address,
        'phone': profile.phone,
        'email': profile.email,
        'logo_path': profile.logo_path,
        'header_image_path': profile.header_image_path,
        'footer_signature_image_path': profile.footer_signature_image_path,
        'report_footer': profile.report_footer,
        'director_name': profile.director_name,
        'director_license': profile.director_license,
    }


def _public_asset_url(raw_path: str | None, request: Request) -> str:
    if not raw_path:
        return ''
    if raw_path.startswith('http://') or raw_path.startswith('https://'):
        return raw_path
    return str(request.base_url).rstrip('/') + raw_path
