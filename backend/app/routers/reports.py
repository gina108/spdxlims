from __future__ import annotations

import base64
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import and_, case, delete, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.core.audit import log_audit
from app.db.session import get_db
from app.models.models import (
    LabOrder,
    LabProfile,
    OrderItem,
    OutsourcedPanelRow,
    OutsourcedPanelTable,
    Patient,
    Provider,
    ReportItemImageSnapshot,
    ReportItemSnapshot,
    ReportOutsourcedRowSnapshot,
    ReportSnapshot,
    Result,
    ResultImage,
    TestCatalog,
)
from app.routers.common import actor_from_header

router = APIRouter()


class ReportOrderChoiceOut(BaseModel):
    id: str
    label: str


class ResultsWorkflowOrderOut(BaseModel):
    id: str
    order_number: str
    order_date: str | None = None
    patient_name: str
    patient_phone: str | None = None
    doctor_name: str | None = None
    client_name: str | None = None
    client_phone: str | None = None
    report_version: int | None = None
    report_finalized_at: str | None = None
    result_count: int = 0
    completed_result_count: int = 0
    report_outdated: int = 0


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
    result_kind: str | None = None
    images: list[dict[str, Any]] = []


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
    patient_age_value: int | None = None
    patient_age_unit: str | None = None
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
    outsourced_panels: list[dict[str, Any]] = []
    report_settings: dict[str, Any] = {}


@router.get('/order-choices', response_model=list[ReportOrderChoiceOut])
def list_report_order_choices(
    client_id: str | None = None,
    test_id: str | None = None,
    date_from: str = "",
    date_to: str = "",
    db: Session = Depends(get_db),
    _actor: UUID | None = Depends(actor_from_header),
):
    stmt = (
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
    )
    if client_id:
        stmt = stmt.where(LabOrder.client_id == _parse_uuid(client_id, field_name='client_id'))
    if test_id:
        match_item = aliased(OrderItem)
        parsed_test = _parse_uuid(test_id, field_name='test_id')
        stmt = stmt.where(
            exists().where(match_item.order_id == LabOrder.id, match_item.test_id == parsed_test)
        )
    if date_from:
        stmt = stmt.where(func.date(LabOrder.ordered_at) >= _parse_date_filter(date_from, field_name='date_from'))
    if date_to:
        stmt = stmt.where(func.date(LabOrder.ordered_at) <= _parse_date_filter(date_to, field_name='date_to'))
    rows = db.execute(stmt).all()
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


# Panel heading/comment rows carry these sentinel test codes on the desktop; they
# are layout, not billable/result-bearing tests, so they never count toward the
# results-workflow progress totals.
_PANEL_META_CODES = ('__PANEL_HEADING__', '__PANEL_COMMENT__')


@router.get('/results-workflow', response_model=list[ResultsWorkflowOrderOut])
def list_results_workflow_orders(
    db: Session = Depends(get_db),
    _actor: UUID | None = Depends(actor_from_header),
):
    """Server-mode source for the Resultados workflow table. Mirrors the desktop's
    Database.list_results_workflow_orders(): one row per active order with progress
    counts (real, non-outsourced tests) and the latest report version.

    report_outdated is always 0 here: unlike the desktop schema, the server's
    lab_order/patient tables have no updated_at, so post-finalization edits can't
    be detected server-side."""
    doctor = aliased(Provider)
    client = aliased(Provider)
    countable = and_(
        TestCatalog.code.notin_(_PANEL_META_CODES),
        OrderItem.is_outsourced.is_(False),
    )
    completed = and_(
        countable,
        func.coalesce(
            func.nullif(func.trim(Result.value_text), ''),
            func.nullif(func.trim(TestCatalog.default_result_value), ''),
        ).isnot(None),
    )
    stmt = (
        select(
            LabOrder.id,
            LabOrder.order_number,
            LabOrder.ordered_at,
            Patient.first_name,
            Patient.last_name,
            Patient.middle_name,
            Patient.phone.label('patient_phone'),
            doctor.legal_name.label('doctor_name'),
            client.legal_name.label('client_name'),
            client.phone.label('client_phone'),
            ReportSnapshot.report_version,
            ReportSnapshot.finalized_at,
            func.count(case((countable, 1))).label('result_count'),
            func.count(case((completed, 1))).label('completed_result_count'),
        )
        .join(Patient, Patient.id == LabOrder.patient_id)
        .outerjoin(doctor, doctor.id == LabOrder.doctor_id)
        .outerjoin(client, client.id == LabOrder.client_id)
        .outerjoin(ReportSnapshot, ReportSnapshot.order_id == LabOrder.id)
        .outerjoin(OrderItem, OrderItem.order_id == LabOrder.id)
        .outerjoin(TestCatalog, TestCatalog.id == OrderItem.test_id)
        .outerjoin(Result, Result.order_item_id == OrderItem.id)
        .where(func.coalesce(LabOrder.is_archived, False).is_(False))
        .group_by(
            LabOrder.id,
            LabOrder.order_number,
            LabOrder.ordered_at,
            Patient.first_name,
            Patient.last_name,
            Patient.middle_name,
            Patient.phone,
            doctor.legal_name,
            client.legal_name,
            client.phone,
            ReportSnapshot.report_version,
            ReportSnapshot.finalized_at,
        )
        .order_by(LabOrder.ordered_at.desc(), LabOrder.order_number.desc())
        .limit(100)
    )
    rows = db.execute(stmt).all()
    result: list[ResultsWorkflowOrderOut] = []
    for row in rows:
        result.append(
            ResultsWorkflowOrderOut(
                id=str(row.id),
                order_number=row.order_number,
                order_date=_iso_or_none(row.ordered_at),
                patient_name=_patient_name(row.first_name, row.last_name, row.middle_name),
                patient_phone=row.patient_phone,
                doctor_name=row.doctor_name,
                client_name=row.client_name,
                client_phone=row.client_phone,
                report_version=row.report_version,
                report_finalized_at=_iso_or_none(row.finalized_at),
                result_count=int(row.result_count or 0),
                completed_result_count=int(row.completed_result_count or 0),
                report_outdated=0,
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

    # Snapshot outsourced-PDF rows so finalized reports keep an immutable copy,
    # independent of later edits to the live extraction workspace.
    db.execute(delete(ReportOutsourcedRowSnapshot).where(ReportOutsourcedRowSnapshot.report_id == report.id))
    live_outsourced = db.execute(
        select(
            OutsourcedPanelTable.panel_label,
            OutsourcedPanelTable.source_pdf_path,
            OutsourcedPanelRow.row_index,
            OutsourcedPanelRow.col_1,
            OutsourcedPanelRow.col_2,
            OutsourcedPanelRow.col_3,
            OutsourcedPanelRow.col_4,
            OutsourcedPanelRow.col_5,
        )
        .join(OutsourcedPanelTable, OutsourcedPanelTable.id == OutsourcedPanelRow.outsourced_panel_table_id)
        .where(OutsourcedPanelTable.order_id == parsed_order_id)
        .order_by(OutsourcedPanelTable.panel_label.asc(), OutsourcedPanelRow.row_index.asc(), OutsourcedPanelRow.id.asc())
    ).all()
    for outsourced_row in live_outsourced:
        db.add(
            ReportOutsourcedRowSnapshot(
                report_id=report.id,
                panel_label=(outsourced_row.panel_label or '').strip(),
                source_pdf_path=(outsourced_row.source_pdf_path or '').strip(),
                row_index=outsourced_row.row_index or 0,
                col_1=outsourced_row.col_1,
                col_2=outsourced_row.col_2,
                col_3=outsourced_row.col_3,
                col_4=outsourced_row.col_4,
                col_5=outsourced_row.col_5,
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


@router.delete('/orders/{order_id}')
def delete_saved_report(order_id: str, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    parsed_order_id = _parse_uuid(order_id, field_name='order_id')
    report = db.scalars(select(ReportSnapshot).where(ReportSnapshot.order_id == parsed_order_id)).first()
    if report is None:
        return {'status': 'not_found'}
    before = _report_audit_payload(report, db)
    report_id = report.id
    # Children have ON DELETE CASCADE, but delete explicitly to be safe and clear.
    db.execute(delete(ReportItemImageSnapshot).where(ReportItemImageSnapshot.report_id == report_id))
    db.execute(delete(ReportOutsourcedRowSnapshot).where(ReportOutsourcedRowSnapshot.report_id == report_id))
    db.execute(delete(ReportItemSnapshot).where(ReportItemSnapshot.report_id == report_id))
    db.delete(report)
    db.flush()
    log_audit(
        db,
        actor_user_id=actor,
        entity='report',
        entity_id=str(report_id),
        action='delete',
        before_json=before,
        after_json=None,
    )
    db.commit()
    return {'status': 'ok'}


def _build_live_preview(order_id: UUID, request: Request, db: Session) -> ReportPreviewOut | None:
    context = _get_report_context(order_id, db)
    if context is None:
        return None
    item_rows = db.execute(
        select(
            OrderItem.id.label('order_item_id'),
            TestCatalog.name.label('test_name'),
            TestCatalog.code.label('test_code'),
            TestCatalog.result_kind.label('result_kind'),
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
        .order_by(OrderItem.sort_order.asc(), OrderItem.id.asc())
    ).all()
    live_images = _live_images_by_order_item(order_id, db)
    items: list[ReportPreviewItemOut] = []
    current_group_label: str | None = None
    for index, row in enumerate(item_rows):
        group_label = (row.group_label or '').strip()
        if group_label and group_label != current_group_label:
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
        current_group_label = group_label
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
                result_kind=row.result_kind,
                images=_encode_images(live_images.get(row.order_item_id, [])),
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
        patient_age_value=context['patient_age_value'],
        patient_age_unit=context['patient_age_unit'],
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
        outsourced_panels=_build_outsourced_sections(order_id, None, db),
        report_settings=_report_settings(db),
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
    # Prefer live patient age over the (age-less) snapshot so it reflects edits,
    # matching the desktop's saved-preview behaviour.
    patient = db.get(Patient, order.patient_id)
    result_kinds = {
        row.id: row.result_kind
        for row in db.execute(
            select(OrderItem.id, TestCatalog.result_kind)
            .join(TestCatalog, TestCatalog.id == OrderItem.test_id)
            .where(OrderItem.order_id == order_id)
        ).all()
    }
    snapshot_images = _snapshot_images_by_order_item(report.id, db)
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
        patient_age_value=patient.age_value if patient is not None else None,
        patient_age_unit=patient.age_unit if patient is not None else None,
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
                result_kind=result_kinds.get(item.order_item_id),
                images=_encode_images(snapshot_images.get(item.order_item_id, [])),
            )
            for item in items
        ],
        outsourced_panels=_build_outsourced_sections(order.id, report.id, db),
        report_settings=_report_settings(db),
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
            Patient.age_value.label('patient_age_value'),
            Patient.age_unit.label('patient_age_unit'),
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
        'patient_age_value': row.patient_age_value,
        'patient_age_unit': row.patient_age_unit,
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


def _parse_date_filter(raw: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f'invalid {field_name}') from exc


def _get_lab_profile(db: Session) -> LabProfile:
    profile = db.get(LabProfile, 1)
    if profile is None:
        profile = LabProfile(id=1)
        db.add(profile)
        db.flush()
    return profile


def _report_settings(db: Session) -> dict[str, Any]:
    profile = _get_lab_profile(db)
    settings = profile.report_settings
    return dict(settings) if isinstance(settings, dict) else {}


def _build_outsourced_sections(order_id: UUID, report_id: UUID | None, db: Session) -> list[dict[str, Any]]:
    """Group outsourced-PDF rows into report sections, matching the desktop.

    Prefers the live (editable) workspace for the order so edits show immediately;
    falls back to the immutable snapshot captured when the report was finalized.
    """
    live_rows = db.execute(
        select(
            OutsourcedPanelTable.panel_label,
            OutsourcedPanelTable.source_pdf_path,
            OutsourcedPanelRow.col_1,
            OutsourcedPanelRow.col_2,
            OutsourcedPanelRow.col_3,
            OutsourcedPanelRow.col_4,
            OutsourcedPanelRow.col_5,
        )
        .join(OutsourcedPanelTable, OutsourcedPanelTable.id == OutsourcedPanelRow.outsourced_panel_table_id)
        .where(OutsourcedPanelTable.order_id == order_id)
        .order_by(OutsourcedPanelTable.panel_label.asc(), OutsourcedPanelRow.row_index.asc(), OutsourcedPanelRow.id.asc())
    ).all()
    if live_rows:
        return _group_outsourced_rows(live_rows)

    if report_id is None:
        return []
    snapshot_rows = db.execute(
        select(
            ReportOutsourcedRowSnapshot.panel_label,
            ReportOutsourcedRowSnapshot.source_pdf_path,
            ReportOutsourcedRowSnapshot.col_1,
            ReportOutsourcedRowSnapshot.col_2,
            ReportOutsourcedRowSnapshot.col_3,
            ReportOutsourcedRowSnapshot.col_4,
            ReportOutsourcedRowSnapshot.col_5,
        )
        .where(ReportOutsourcedRowSnapshot.report_id == report_id)
        .order_by(ReportOutsourcedRowSnapshot.panel_label.asc(), ReportOutsourcedRowSnapshot.row_index.asc(), ReportOutsourcedRowSnapshot.id.asc())
    ).all()
    return _group_outsourced_rows(snapshot_rows)


def _encode_images(rows) -> list[dict[str, Any]]:
    """Encode result-image bytes as base64 for the report renderer's data URIs."""
    return [
        {
            'data': base64.b64encode(row.image_data).decode('ascii') if row.image_data else '',
            'mime_type': row.mime_type or 'image/png',
            'caption': row.caption or '',
        }
        for row in rows
    ]


def _live_images_by_order_item(order_id: UUID, db: Session) -> dict[Any, list[Any]]:
    rows = db.scalars(
        select(ResultImage)
        .join(OrderItem, OrderItem.id == ResultImage.order_item_id)
        .where(OrderItem.order_id == order_id)
        .order_by(ResultImage.order_item_id.asc(), ResultImage.sort_order.asc(), ResultImage.id.asc())
    ).all()
    grouped: dict[Any, list[Any]] = {}
    for row in rows:
        grouped.setdefault(row.order_item_id, []).append(row)
    return grouped


def _snapshot_images_by_order_item(report_id: UUID, db: Session) -> dict[Any, list[Any]]:
    rows = db.scalars(
        select(ReportItemImageSnapshot)
        .where(ReportItemImageSnapshot.report_id == report_id)
        .order_by(ReportItemImageSnapshot.order_item_id.asc(), ReportItemImageSnapshot.sort_order.asc(), ReportItemImageSnapshot.id.asc())
    ).all()
    grouped: dict[Any, list[Any]] = {}
    for row in rows:
        if row.order_item_id is None:
            continue
        grouped.setdefault(row.order_item_id, []).append(row)
    return grouped


def _group_outsourced_rows(rows) -> list[dict[str, Any]]:
    grouped: list[dict[str, Any]] = []
    current_key: tuple[str, str] | None = None
    current_section: dict[str, Any] | None = None
    for row in rows:
        panel_label = str(row.panel_label or '').strip()
        source_pdf_path = str(row.source_pdf_path or '').strip()
        key = (panel_label, source_pdf_path)
        if current_key != key:
            current_key = key
            current_section = {'panel_label': panel_label, 'source_pdf_path': source_pdf_path, 'rows': []}
            grouped.append(current_section)
        # Renumber sequentially: each extraction restarts row_index at 0, so the
        # stored value collides across pages. Insertion order gives the true sequence.
        current_section['rows'].append(
            {
                'row_index': len(current_section['rows']),
                'col_1': str(row.col_1 or ''),
                'col_2': str(row.col_2 or ''),
                'col_3': str(row.col_3 or ''),
                'col_4': str(row.col_4 or ''),
                'col_5': str(row.col_5 or ''),
            }
        )
    return grouped


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
