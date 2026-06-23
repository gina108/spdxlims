from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, aliased

from app.core.audit import log_audit
from app.db.session import get_db
from app.models.models import LabOrder, LabProfile, OrderItem, Patient, Provider, ReportItemImageSnapshot, ReportItemSnapshot, ReportSnapshot, Result, ResultImage, TestCatalog
from app.routers.common import actor_from_header

router = APIRouter()


class ReportOrderChoiceOut(BaseModel):
    id: str
    label: str


class ReportPreviewItemOut(BaseModel):
    order_test_id: str | None = None
    item_type: str = "test"
    test_name: str
    result_value: str | None = None
    unit: str | None = None
    reference_text: str | None = None
    lower_value: str | None = None
    upper_value: str | None = None
    flag: str | None = None
    comments: str | None = None
    sort_order: int


class FinalizeReportIn(BaseModel):
    header_image_path: str | None = None
    footer_signature_image_path: str | None = None
    preview_override: dict[str, Any] | None = None

class ReportPreviewOut(BaseModel):
    source: str
    report_status: str
    report_version: int | None = None
    finalized_at: str | None = None
    order_id: str
    order_number: str
    accession_id: str | None = None
    sample_id: str | None = None
    ordered_at: str | None = None
    reported_at: str | None = None
    order_status: str
    patient_name: str
    patient_sex: str | None = None
    patient_dob: str | None = None
    doctor_name: str | None = None
    client_name: str | None = None
    lab_name: str = ""
    lab_address: str = ""
    lab_phone: str = ""
    lab_email: str = ""
    director_name: str = ""
    director_license: str = ""
    footer_text: str = ""
    header_image_path: str = ""
    footer_signature_image_path: str = ""
    general_comments: str = ""
    items: list[ReportPreviewItemOut]


@router.get('/order-choices', response_model=list[ReportOrderChoiceOut])
def list_report_order_choices(db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    rows = db.execute(
        select(
            LabOrder.id,
            LabOrder.order_number,
            LabOrder.status,
            Patient.first_name,
            Patient.last_name,
            Patient.middle_name,
            func.count(OrderItem.id).label('item_count'),
        )
        .join(Patient, Patient.id == LabOrder.patient_id)
        .join(OrderItem, OrderItem.order_id == LabOrder.id)
        .group_by(
            LabOrder.id,
            LabOrder.order_number,
            LabOrder.status,
            Patient.first_name,
            Patient.last_name,
            Patient.middle_name,
        )
        .order_by(LabOrder.ordered_at.desc(), LabOrder.order_number.desc())
    ).all()
    result: list[ReportOrderChoiceOut] = []
    for row in rows:
        patient_name = _patient_name(row.first_name, row.last_name, row.middle_name)
        result.append(
            ReportOrderChoiceOut(
                id=str(row.id),
                label=f"{row.order_number} - {patient_name} ({int(row.item_count or 0)} tests, {row.status})",
            )
        )
    return result


@router.get('/orders/{order_id}/live-preview', response_model=ReportPreviewOut)
def get_live_report_preview(order_id: str, request: Request, db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    parsed_order_id = _parse_uuid(order_id, field_name='order_id')
    preview = _build_live_preview(parsed_order_id, request, db)
    if preview is None:
        raise HTTPException(status_code=404, detail='order not found')
    return preview


@router.get('/orders/{order_id}/saved-preview', response_model=ReportPreviewOut)
def get_saved_report_preview(order_id: str, request: Request, db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    parsed_order_id = _parse_uuid(order_id, field_name='order_id')
    preview = _build_saved_preview(parsed_order_id, request, db)
    if preview is None:
        raise HTTPException(status_code=404, detail='saved report not found')
    return preview


@router.post('/orders/{order_id}/finalize')
def finalize_report(order_id: str, payload: FinalizeReportIn, request: Request, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    parsed_order_id = _parse_uuid(order_id, field_name='order_id')
    if payload.preview_override is not None:
        live_preview = ReportPreviewOut(**payload.preview_override)
    else:
        live_preview = _build_live_preview(parsed_order_id, request, db)
    if live_preview is None:
        raise HTTPException(status_code=404, detail='order not found')
    live_preview.order_id = order_id
    if payload.header_image_path is not None:
        live_preview.header_image_path = payload.header_image_path.strip()
    if payload.footer_signature_image_path is not None:
        live_preview.footer_signature_image_path = payload.footer_signature_image_path.strip()
    for index, item in enumerate(live_preview.items):
        item.sort_order = index
    if not any(item.item_type != 'heading' for item in live_preview.items):
        raise HTTPException(status_code=409, detail='The selected order has no reportable items.')

    existing = db.scalars(select(ReportSnapshot).where(ReportSnapshot.order_id == parsed_order_id)).first()
    before = _report_audit_payload(existing, db)
    next_version = (existing.report_version + 1) if existing is not None else 1

    if existing is None:
        report = ReportSnapshot(
            order_id=parsed_order_id,
            report_version=next_version,
            status='final',
            patient_snapshot_name=live_preview.patient_name,
            patient_snapshot_sex=live_preview.patient_sex,
            patient_snapshot_dob=live_preview.patient_dob,
            doctor_snapshot_name=live_preview.doctor_name,
            client_snapshot_name=live_preview.client_name,
            lab_snapshot_name=live_preview.lab_name.strip() or None,
            lab_snapshot_address=live_preview.lab_address.strip() or None,
            lab_snapshot_phone=live_preview.lab_phone.strip() or None,
            lab_snapshot_email=live_preview.lab_email.strip() or None,
            director_snapshot_name=live_preview.director_name.strip() or None,
            director_snapshot_license=live_preview.director_license.strip() or None,
            footer_snapshot_text=live_preview.footer_text.strip() or None,
            header_image_snapshot_path=live_preview.header_image_path.strip() or None,
            footer_signature_snapshot_path=live_preview.footer_signature_image_path.strip() or None,
            general_comments=(live_preview.general_comments or '').strip() or None,
        )
        db.add(report)
        db.flush()
    else:
        report = existing
        report.report_version = next_version
        report.status = 'final'
        report.patient_snapshot_name = live_preview.patient_name
        report.patient_snapshot_sex = live_preview.patient_sex
        report.patient_snapshot_dob = live_preview.patient_dob
        report.doctor_snapshot_name = live_preview.doctor_name
        report.client_snapshot_name = live_preview.client_name
        report.lab_snapshot_name = live_preview.lab_name.strip() or None
        report.lab_snapshot_address = live_preview.lab_address.strip() or None
        report.lab_snapshot_phone = live_preview.lab_phone.strip() or None
        report.lab_snapshot_email = live_preview.lab_email.strip() or None
        report.director_snapshot_name = live_preview.director_name.strip() or None
        report.director_snapshot_license = live_preview.director_license.strip() or None
        report.footer_snapshot_text = live_preview.footer_text.strip() or None
        report.header_image_snapshot_path = live_preview.header_image_path.strip() or None
        report.footer_signature_snapshot_path = live_preview.footer_signature_image_path.strip() or None
        report.general_comments = (live_preview.general_comments or '').strip() or None
        db.execute(delete(ReportItemSnapshot).where(ReportItemSnapshot.report_id == report.id))
        db.execute(delete(ReportItemImageSnapshot).where(ReportItemImageSnapshot.report_id == report.id))
        db.flush()

    for item in live_preview.items:
        db.add(
            ReportItemSnapshot(
                report_id=report.id,
                order_item_id=_parse_uuid(item.order_test_id, field_name='order_test_id') if item.order_test_id else None,
                test_name_snapshot=item.test_name,
                result_value_snapshot=item.result_value,
                unit_snapshot=item.unit,
                reference_text_snapshot=item.reference_text,
                lower_value_snapshot_text=item.lower_value,
                upper_value_snapshot_text=item.upper_value,
                flag_snapshot=item.flag,
                comments_snapshot=item.comments,
                sort_order=item.sort_order,
                item_type_snapshot=item.item_type,
            )
        )

    # Snapshot result images so finalized reports keep an immutable copy.
    result_images = db.scalars(
        select(ResultImage)
        .join(OrderItem, OrderItem.id == ResultImage.order_item_id)
        .where(OrderItem.order_id == parsed_order_id)
        .order_by(ResultImage.order_item_id.asc(), ResultImage.sort_order.asc())
    ).all()
    for image in result_images:
        db.add(
            ReportItemImageSnapshot(
                report_id=report.id,
                order_item_id=image.order_item_id,
                image_data=image.image_data,
                mime_type=image.mime_type,
                caption=image.caption,
                sort_order=image.sort_order,
            )
        )

    order = db.get(LabOrder, parsed_order_id)
    if order is None:
        raise HTTPException(status_code=404, detail='order not found')
    order.status = 'reported'
    order.reported_at = func.now()
    db.flush()
    log_audit(
        db,
        actor_user_id=actor,
        entity='report',
        entity_id=str(report.id),
        action='finalize',
        before_json=before,
        after_json=_report_audit_payload(report, db),
    )
    db.commit()
    db.refresh(report)
    return {'id': str(report.id), 'report_version': report.report_version, 'status': report.status}


def _build_live_preview(order_id: UUID, request: Request, db: Session) -> ReportPreviewOut | None:
    context = _get_report_context(order_id, db)
    if context is None:
        return None
    item_rows = db.execute(
        select(
            OrderItem.id.label('order_item_id'),
            TestCatalog.name.label('test_name'),
            TestCatalog.code.label('test_code'),
            Result.value_text,
            Result.unit,
            Result.reference_text,
            Result.lower_value_text,
            Result.upper_value_text,
            Result.flag,
            Result.comments,
            OrderItem.group_label,
        )
        .join(TestCatalog, TestCatalog.id == OrderItem.test_id)
        .outerjoin(Result, Result.order_item_id == OrderItem.id)
        .where(OrderItem.order_id == order_id)
        .order_by(OrderItem.id.asc())
    ).all()
    items: list[ReportPreviewItemOut] = []
    for index, row in enumerate(item_rows):
        group_label = (row.group_label or '').strip()
        if group_label and (not items or items[-1].item_type != 'heading' or items[-1].test_name != group_label):
            items.append(
                ReportPreviewItemOut(
                    order_test_id=None,
                    item_type='heading',
                    test_name=group_label,
                    result_value=None,
                    unit=None,
                    reference_text=None,
                    lower_value=None,
                    upper_value=None,
                    flag=None,
                    comments=None,
                    sort_order=len(items),
                )
            )
        items.append(
            ReportPreviewItemOut(
                order_test_id=str(row.order_item_id),
                item_type='test',
                test_name=f"{row.test_name} ({row.test_code})",
                result_value=row.value_text,
                unit=row.unit,
                reference_text=row.reference_text,
                lower_value=row.lower_value_text,
                upper_value=row.upper_value_text,
                flag=row.flag,
                comments=row.comments,
                sort_order=len(items),
            )
        )
    profile = _get_lab_profile(db)
    return ReportPreviewOut(
        source='live',
        report_status='draft',
        report_version=None,
        finalized_at=None,
        order_id=str(context['order_id']),
        order_number=context['order_number'],
        accession_id=context['accession_id'],
        sample_id=context['sample_id'],
        ordered_at=_iso_or_none(context['ordered_at']),
        reported_at=_iso_or_none(context['reported_at']),
        order_status=context['order_status'],
        patient_name=context['patient_name'],
        patient_sex=context['patient_sex'],
        patient_dob=context['patient_dob'],
        doctor_name=context['doctor_name'],
        client_name=context['client_name'],
        lab_name=profile.lab_name or '',
        lab_address=profile.address or '',
        lab_phone=profile.phone or '',
        lab_email=profile.email or '',
        director_name=profile.director_name or '',
        director_license=profile.director_license or '',
        footer_text=profile.report_footer or '',
        header_image_path=_public_asset_url(profile.header_image_path, request),
        footer_signature_image_path=_public_asset_url(profile.footer_signature_image_path, request),
        general_comments=context['notes'] or '',
        items=items,
    )


def _build_saved_preview(order_id: UUID, request: Request, db: Session) -> ReportPreviewOut | None:
    order = db.get(LabOrder, order_id)
    report = db.scalars(select(ReportSnapshot).where(ReportSnapshot.order_id == order_id)).first()
    if order is None or report is None:
        return None
    items = db.scalars(
        select(ReportItemSnapshot)
        .where(ReportItemSnapshot.report_id == report.id)
        .order_by(ReportItemSnapshot.sort_order.asc(), ReportItemSnapshot.id.asc())
    ).all()
    return ReportPreviewOut(
        source='saved',
        report_status=report.status,
        report_version=report.report_version,
        finalized_at=_iso_or_none(report.finalized_at),
        order_id=str(order.id),
        order_number=order.order_number,
        accession_id=order.accession_id,
        sample_id=order.sample_id,
        ordered_at=_iso_or_none(order.ordered_at),
        reported_at=_iso_or_none(order.reported_at),
        order_status=order.status,
        patient_name=report.patient_snapshot_name,
        patient_sex=report.patient_snapshot_sex,
        patient_dob=report.patient_snapshot_dob,
        doctor_name=report.doctor_snapshot_name,
        client_name=report.client_snapshot_name,
        lab_name=report.lab_snapshot_name or '',
        lab_address=report.lab_snapshot_address or '',
        lab_phone=report.lab_snapshot_phone or '',
        lab_email=report.lab_snapshot_email or '',
        director_name=report.director_snapshot_name or '',
        director_license=report.director_snapshot_license or '',
        footer_text=report.footer_snapshot_text or '',
        header_image_path=_public_asset_url(report.header_image_snapshot_path, request),
        footer_signature_image_path=_public_asset_url(report.footer_signature_snapshot_path, request),
        general_comments=report.general_comments or '',
        items=[
            ReportPreviewItemOut(
                order_test_id=str(item.order_item_id) if item.order_item_id else None,
                item_type=item.item_type_snapshot,
                test_name=item.test_name_snapshot,
                result_value=item.result_value_snapshot,
                unit=item.unit_snapshot,
                reference_text=item.reference_text_snapshot,
                lower_value=item.lower_value_snapshot_text,
                upper_value=item.upper_value_snapshot_text,
                flag=item.flag_snapshot,
                comments=item.comments_snapshot,
                sort_order=item.sort_order,
            )
            for item in items
        ],
    )


def _get_report_context(order_id: UUID, db: Session):
    doctor_provider = aliased(Provider)
    client_provider = aliased(Provider)
    row = db.execute(
        select(
            LabOrder.id.label('order_id'),
            LabOrder.order_number,
            LabOrder.accession_id,
            LabOrder.sample_id,
            LabOrder.ordered_at,
            LabOrder.reported_at,
            LabOrder.status.label('order_status'),
            LabOrder.notes,
            Patient.first_name,
            Patient.last_name,
            Patient.middle_name,
            Patient.sex.label('patient_sex'),
            Patient.dob.label('patient_dob'),
            doctor_provider.legal_name.label('doctor_name'),
            client_provider.legal_name.label('client_name'),
        )
        .join(Patient, Patient.id == LabOrder.patient_id)
        .outerjoin(doctor_provider, doctor_provider.id == LabOrder.doctor_id)
        .outerjoin(client_provider, client_provider.id == LabOrder.client_id)
        .where(LabOrder.id == order_id)
    ).first()
    if row is None:
        return None
    return {
        'order_id': row.order_id,
        'order_number': row.order_number,
        'accession_id': row.accession_id,
        'sample_id': row.sample_id,
        'ordered_at': row.ordered_at,
        'reported_at': row.reported_at,
        'order_status': row.order_status,
        'notes': row.notes,
        'patient_name': _patient_name(row.first_name, row.last_name, row.middle_name),
        'patient_sex': row.patient_sex,
        'patient_dob': row.patient_dob.isoformat() if row.patient_dob else None,
        'doctor_name': row.doctor_name,
        'client_name': row.client_name,
    }


def _patient_name(first_name: str | None, last_name: str | None, middle_name: str | None) -> str:
    return ' '.join(part for part in [first_name or '', last_name or '', middle_name or ''] if part).strip()


def _iso_or_none(value) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_uuid(raw_value: str, *, field_name: str) -> UUID:
    try:
        return UUID(str(raw_value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f'invalid {field_name}') from exc


def _get_lab_profile(db: Session) -> LabProfile:
    profile = db.get(LabProfile, 1)
    if profile is None:
        profile = LabProfile(id=1)
        db.add(profile)
        db.flush()
    return profile


def _public_asset_url(raw_path: str | None, request: Request) -> str:
    if not raw_path:
        return ''
    if raw_path.startswith('http://') or raw_path.startswith('https://') or raw_path.startswith('file:///'):
        return raw_path
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate.as_uri()
    return str(request.base_url).rstrip('/') + raw_path


def _report_audit_payload(report: ReportSnapshot | None, db: Session) -> dict[str, Any] | None:
    if report is None:
        return None
    item_rows = db.scalars(
        select(ReportItemSnapshot)
        .where(ReportItemSnapshot.report_id == report.id)
        .order_by(ReportItemSnapshot.sort_order.asc(), ReportItemSnapshot.id.asc())
    ).all()
    return {
        'id': str(report.id),
        'order_id': str(report.order_id),
        'report_version': report.report_version,
        'status': report.status,
        'patient_snapshot_name': report.patient_snapshot_name,
        'patient_snapshot_sex': report.patient_snapshot_sex,
        'patient_snapshot_dob': report.patient_snapshot_dob,
        'doctor_snapshot_name': report.doctor_snapshot_name,
        'client_snapshot_name': report.client_snapshot_name,
        'lab_snapshot_name': report.lab_snapshot_name,
        'header_image_snapshot_path': report.header_image_snapshot_path,
        'footer_signature_snapshot_path': report.footer_signature_snapshot_path,
        'general_comments': report.general_comments,
        'items': [
            {
                'order_item_id': str(item.order_item_id) if item.order_item_id else None,
                'item_type': item.item_type_snapshot,
                'test_name': item.test_name_snapshot,
                'result_value': item.result_value_snapshot,
                'unit': item.unit_snapshot,
                'flag': item.flag_snapshot,
                'sort_order': item.sort_order,
            }
            for item in item_rows
        ],
    }
