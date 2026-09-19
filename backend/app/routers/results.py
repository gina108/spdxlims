from __future__ import annotations

import ast as _ast
import base64
import operator as _operator
import re as _re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.audit import log_audit
from app.db.session import get_db
from app.models.models import LabOrder, OrderItem, Patient, Provider, Result, ResultImage, TestCatalog
from app.routers.common import (
    actor_from_header,
    age_to_days,
    inject_panel_title_rows,
    panel_catalog_structures,
    resolve_reference_range,
    restore_panel_catalog_structure,
)

router = APIRouter()


class ResultEntryOut(BaseModel):
    order_test_id: str
    order_id: str
    order_number: str
    patient_name: str
    doctor_name: str | None = None
    patient_sex: str | None = None
    patient_age_days: int | None = None
    test_id: str
    test_name: str
    specimen_type: str | None = None
    item_type: str = "test"
    result_kind: str = "text"
    select_options: str | None = None
    default_result_value: str | None = None
    formula: str | None = None
    result_value: str | None = None
    unit: str | None = None
    lower_value: str | None = None
    upper_value: str | None = None
    flag: str | None = None
    reference_text: str | None = None
    comments: str | None = None
    test_status: str
    is_outsourced: bool = False
    source_label: str | None = None


class ResultEntryIn(BaseModel):
    result_value: str = ""
    unit: str = ""
    lower_value: str | None = None
    upper_value: str | None = None
    reference_text: str = ""
    comments: str = ""
    result_kind: str = "text"


class ResultImageIn(BaseModel):
    image_data_b64: str
    mime_type: str = "image/png"
    caption: str = ""


class ResultImageOut(BaseModel):
    id: str
    order_item_id: str
    mime_type: str
    caption: str | None = None
    sort_order: int
    image_data_b64: str


class InstrumentObservationIn(BaseModel):
    observation_id: str | None = None
    instrument_test_code: str = ""
    instrument_test_name: str | None = None
    mapped_lis_test_id: str | None = None
    value_raw: str = ""
    value_numeric: float | None = None
    value_text: str | None = None
    units_raw: str | None = None
    units_normalized: str | None = None
    abnormal_flag: str | None = None
    result_status: str | None = None


class InstrumentMessageIn(BaseModel):
    source_device_id: str = ""
    source_profile_id: str = ""
    protocol_type: str = ""
    transport_type: str = ""
    received_at: datetime | None = None
    patient_id: str | None = None
    accession_id: str | None = None
    sample_id: str | None = None
    analyzer_run_id: str | None = None
    observations: list[InstrumentObservationIn] = []


class InstrumentResultIn(BaseModel):
    capture_id: str | None = None
    message: InstrumentMessageIn
    mapping_trace: list[str] = []


class InstrumentImportIn(BaseModel):
    order_id: str | None = None
    result: InstrumentResultIn
    # The patient_id fallback matches a loose identifier against the sample /
    # accession / order-number columns and takes the most recent hit. That is
    # acceptable when a human picked the capture, but an unattended importer
    # must not attach results to an order on a guess, so auto-import sends False.
    allow_patient_fallback: bool = True


class InstrumentImportOut(BaseModel):
    order_id: str
    order_number: str
    matched_by: str
    imported_count: int
    unmatched_codes: list[str] = []


@router.get('/orders/{order_id}/entries', response_model=list[ResultEntryOut])
def get_order_entries(order_id: str, db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    parsed_order_id = _parse_uuid(order_id, field_name='order_id')
    doctor_provider = aliased(Provider)
    rows = db.execute(
        select(
            OrderItem.id.label('order_item_id'),
            OrderItem.item_type,
            OrderItem.display_name,
            LabOrder.id.label('order_id'),
            LabOrder.order_number,
            Patient.first_name,
            Patient.last_name,
            Patient.middle_name,
            Patient.sex,
            Patient.dob,
            Patient.age_value,
            Patient.age_unit,
            doctor_provider.legal_name.label('doctor_name'),
            TestCatalog.id.label('test_id'),
            TestCatalog.name.label('test_name'),
            TestCatalog.code.label('test_code'),
            TestCatalog.unit.label('test_unit'),
            TestCatalog.specimen_type,
            TestCatalog.result_kind,
            TestCatalog.select_options,
            TestCatalog.default_result_value,
            TestCatalog.formula.label('test_formula'),
            OrderItem.group_label,
            OrderItem.is_outsourced,
            OrderItem.source_label,
            Result.value_text,
            Result.unit,
            Result.lower_value_text,
            Result.upper_value_text,
            Result.flag,
            Result.reference_text,
            Result.comments,
            Result.status.label('result_status'),
        )
        .join(LabOrder, LabOrder.id == OrderItem.order_id)
        .join(Patient, Patient.id == LabOrder.patient_id)
        .outerjoin(doctor_provider, doctor_provider.id == LabOrder.doctor_id)
        .outerjoin(TestCatalog, TestCatalog.id == OrderItem.test_id)
        .outerjoin(Result, Result.order_item_id == OrderItem.id)
        .where(OrderItem.order_id == parsed_order_id)
        .order_by(OrderItem.sort_order.asc(), OrderItem.id.asc())
    ).all()
    if not rows:
        return []

    first = rows[0]
    patient_name = ' '.join(part for part in [first.first_name or '', first.last_name or '', first.middle_name or ''] if part).strip()
    patient_age_days = age_to_days(first.age_value, first.age_unit, first.dob)

    raw_items: list[dict[str, Any]] = []
    for row in rows:
        item_type = row.item_type
        if row.test_code in ('__PANEL_HEADING__', '__PANEL_COMMENT__'):
            # Legacy import bug: __PANEL_COMMENT__ rows were imported as fake
            # test items pointing at an inactive sentinel TestCatalog row.
            item_type = 'heading' if row.test_code == '__PANEL_HEADING__' else 'comment'
        raw_items.append(
            {
                'order_item_id': row.order_item_id,
                'test_id': row.test_id if item_type == 'test' else None,
                'item_type': item_type,
                'display_name': row.display_name,
                'test_name': row.test_name,
                'test_code': row.test_code,
                'test_unit': row.test_unit,
                'specimen_type': row.specimen_type,
                'result_kind': row.result_kind,
                'select_options': row.select_options,
                'default_result_value': row.default_result_value,
                'test_formula': row.test_formula,
                'is_outsourced': row.is_outsourced,
                'value_text': row.value_text,
                'unit': row.unit,
                'lower_value_text': row.lower_value_text,
                'upper_value_text': row.upper_value_text,
                'flag': row.flag,
                'reference_text': row.reference_text,
                'comments': row.comments,
                'result_status': row.result_status,
                'source_label': row.group_label,
            }
        )

    structures = panel_catalog_structures(db)
    restored = restore_panel_catalog_structure(raw_items, structures)
    final_items = inject_panel_title_rows(restored)

    entries: list[ResultEntryOut] = []
    for entry in final_items:
        item_type = str(entry.get('item_type') or 'test')
        source_label = entry.get('source_label') or None
        order_item_id = entry.get('order_item_id')
        if item_type in ('heading', 'comment'):
            entries.append(
                ResultEntryOut(
                    order_test_id=str(order_item_id) if order_item_id else f'heading:{source_label or len(entries)}',
                    order_id=str(first.order_id),
                    order_number=first.order_number,
                    patient_name=patient_name,
                    doctor_name=first.doctor_name,
                    patient_sex=first.sex,
                    patient_age_days=patient_age_days,
                    test_id='',
                    test_name=entry.get('display_name') or '',
                    specimen_type=None,
                    item_type=item_type,
                    result_kind='text',
                    select_options=None,
                    default_result_value=None,
                    result_value=None,
                    unit=None,
                    lower_value=None,
                    upper_value=None,
                    flag=None,
                    reference_text=None,
                    comments=None,
                    test_status='pending',
                    source_label=source_label,
                )
            )
            continue
        test_id = entry.get('test_id')
        reference = resolve_reference_range(db, test_id, first.sex, patient_age_days) if test_id is not None else None
        result_kind = entry.get('result_kind') or 'text'
        default_result_value = entry.get('default_result_value')
        result_value = entry.get('value_text') or default_result_value
        unit = entry.get('unit') or (reference.unit if reference is not None and reference.unit else None) or entry.get('test_unit')
        lower_value = entry.get('lower_value_text') or (reference.lower_value_text if reference is not None else None)
        upper_value = entry.get('upper_value_text') or (reference.upper_value_text if reference is not None else None)
        reference_text = entry.get('reference_text') or (reference.reference_text if reference is not None else None)
        flag = entry.get('flag') or _calculate_flag(result_kind, result_value or '', lower_value, upper_value)
        entries.append(
            ResultEntryOut(
                order_test_id=str(order_item_id),
                order_id=str(first.order_id),
                order_number=first.order_number,
                patient_name=patient_name,
                doctor_name=first.doctor_name,
                patient_sex=first.sex,
                patient_age_days=patient_age_days,
                test_id=str(test_id),
                test_name=f"{entry.get('test_name')} ({entry.get('test_code')})",
                specimen_type=entry.get('specimen_type'),
                item_type='test',
                result_kind=result_kind,
                select_options=entry.get('select_options'),
                default_result_value=default_result_value,
                formula=entry.get('test_formula'),
                result_value=result_value,
                unit=unit,
                lower_value=lower_value,
                upper_value=upper_value,
                flag=flag,
                reference_text=reference_text,
                comments=entry.get('comments'),
                test_status=entry.get('result_status') or 'pending',
                is_outsourced=bool(entry.get('is_outsourced')),
                source_label=source_label,
            )
        )
    return entries


@router.post('/order-items/{order_item_id}')
def save_order_item_result(order_item_id: str, payload: ResultEntryIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    parsed_order_item_id = _parse_uuid(order_item_id, field_name='order_item_id')
    order_item = db.get(OrderItem, parsed_order_item_id)
    if order_item is None:
        raise HTTPException(status_code=404, detail='order item not found')

    test = db.get(TestCatalog, order_item.test_id)
    if test is None:
        raise HTTPException(status_code=404, detail='test not found')

    normalized_value = payload.result_value.strip()
    normalized_unit = payload.unit.strip()
    lower_value = (payload.lower_value or '').strip() or None
    upper_value = (payload.upper_value or '').strip() or None
    reference_text = payload.reference_text.strip() or None
    comments = payload.comments.strip() or None
    result_kind = test.result_kind or payload.result_kind or 'text'
    if result_kind == 'select':
        valid_options = _deserialize_select_options(test.select_options)
        if normalized_value and valid_options and normalized_value not in valid_options:
            raise HTTPException(status_code=400, detail='result value must match a configured selectable option')
    flag = _calculate_flag(result_kind, normalized_value, lower_value, upper_value)
    numeric_value = _decimal_to_float(normalized_value) if result_kind == 'numeric' else None

    result = db.scalars(select(Result).where(Result.order_item_id == parsed_order_item_id)).first()
    before = _result_audit_payload(result)
    if result is None:
        result = Result(
            order_item_id=parsed_order_item_id,
            value_text=normalized_value or None,
            value_num=numeric_value,
            unit=normalized_unit or None,
            lower_value_text=lower_value,
            upper_value_text=upper_value,
            reference_text=reference_text,
            comments=comments,
            flag=flag,
            entered_by=actor,
            status='draft',
        )
        db.add(result)
    else:
        result.value_text = normalized_value or None
        result.value_num = numeric_value
        result.unit = normalized_unit or None
        result.lower_value_text = lower_value
        result.upper_value_text = upper_value
        result.reference_text = reference_text
        result.comments = comments
        result.flag = flag
        result.entered_by = actor
        result.status = 'draft'

    order = db.get(LabOrder, order_item.order_id)
    if order is not None and order.status == 'registered':
        order.status = 'in_lab'

    db.flush()
    log_audit(
        db,
        actor_user_id=actor,
        entity='result',
        entity_id=str(result.id),
        action='save',
        before_json=before,
        after_json=_result_audit_payload(result),
    )
    _recalculate_formula_order_items(db, order_item.order_id, actor)
    db.commit()
    return {'id': str(result.id), 'flag': flag, 'status': result.status}


@router.get('/order-items/{order_item_id}/images', response_model=list[ResultImageOut])
def list_order_item_images(order_item_id: str, db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    parsed_order_item_id = _parse_uuid(order_item_id, field_name='order_item_id')
    images = db.scalars(
        select(ResultImage)
        .where(ResultImage.order_item_id == parsed_order_item_id)
        .order_by(ResultImage.sort_order.asc(), ResultImage.created_at.asc())
    ).all()
    return [
        ResultImageOut(
            id=str(image.id),
            order_item_id=str(image.order_item_id),
            mime_type=image.mime_type,
            caption=image.caption,
            sort_order=image.sort_order,
            image_data_b64=base64.b64encode(image.image_data).decode('ascii'),
        )
        for image in images
    ]


@router.post('/order-items/{order_item_id}/images')
def add_order_item_image(order_item_id: str, payload: ResultImageIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    parsed_order_item_id = _parse_uuid(order_item_id, field_name='order_item_id')
    order_item = db.get(OrderItem, parsed_order_item_id)
    if order_item is None:
        raise HTTPException(status_code=404, detail='order item not found')
    # Images are expected to be downscaled by the caller before upload (the desktop
    # app caps the long edge at ~2000px); the backend has no image library and
    # stores the received bytes as-is.
    try:
        image_bytes = base64.b64decode(payload.image_data_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail='image_data_b64 must be valid base64') from exc
    if not image_bytes:
        raise HTTPException(status_code=400, detail='image data is empty')
    next_sort = db.scalar(
        select(func.coalesce(func.max(ResultImage.sort_order), -1) + 1).where(ResultImage.order_item_id == parsed_order_item_id)
    ) or 0
    image = ResultImage(
        order_item_id=parsed_order_item_id,
        image_data=image_bytes,
        mime_type=payload.mime_type or 'image/png',
        caption=(payload.caption or '').strip() or None,
        sort_order=int(next_sort),
    )
    db.add(image)
    db.flush()
    _refresh_image_result_summary(db, order_item, actor)
    order = db.get(LabOrder, order_item.order_id)
    if order is not None and order.status == 'registered':
        order.status = 'in_lab'
    db.commit()
    return {'id': str(image.id), 'sort_order': image.sort_order}


@router.delete('/images/{image_id}')
def delete_order_item_image(image_id: str, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    parsed_image_id = _parse_uuid(image_id, field_name='image_id')
    image = db.get(ResultImage, parsed_image_id)
    if image is None:
        raise HTTPException(status_code=404, detail='image not found')
    order_item = db.get(OrderItem, image.order_item_id)
    db.delete(image)
    db.flush()
    if order_item is not None:
        _refresh_image_result_summary(db, order_item, actor)
    db.commit()
    return {'deleted': True}


def _refresh_image_result_summary(db: Session, order_item: OrderItem, actor: UUID | None) -> None:
    count = db.scalar(
        select(func.count()).select_from(ResultImage).where(ResultImage.order_item_id == order_item.id)
    ) or 0
    summary = f'{count} image(s)' if count else None
    result = db.scalars(select(Result).where(Result.order_item_id == order_item.id)).first()
    if result is None:
        result = Result(
            order_item_id=order_item.id,
            value_text=summary,
            flag='none',
            entered_by=actor,
            status='draft',
        )
        db.add(result)
    else:
        result.value_text = summary
        result.flag = 'none'
        result.status = 'draft'


@router.post('/import-instrument', response_model=InstrumentImportOut)
def import_instrument_results(payload: InstrumentImportIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    order, matched_by = _resolve_instrument_order(payload, db)
    if order is None:
        raise HTTPException(status_code=400, detail='instrument result must be linked to an order manually')

    order_items = db.execute(
        select(OrderItem, TestCatalog)
        .join(TestCatalog, TestCatalog.id == OrderItem.test_id)
        .where(OrderItem.order_id == order.id)
    ).all()
    order_item_by_code = {test.code.strip().upper(): (item, test) for item, test in order_items if (test.code or '').strip()}

    imported_count = 0
    unmatched_codes: list[str] = []
    for obs in payload.result.message.observations:
        candidate_codes = [
            (obs.mapped_lis_test_id or '').strip().upper(),
            (obs.instrument_test_code or '').strip().upper(),
        ]
        matched = None
        for code in candidate_codes:
            if code and code in order_item_by_code:
                matched = order_item_by_code[code]
                break
        if matched is None:
            unmatched_codes.append(obs.instrument_test_code or obs.mapped_lis_test_id or 'unknown')
            continue
        order_item, test = matched
        _upsert_instrument_result(db, order, order_item, test, obs, actor)
        imported_count += 1

    if imported_count == 0:
        raise HTTPException(status_code=409, detail='instrument payload matched an order, but no order items matched the observation codes')

    if order.status == 'registered':
        order.status = 'in_lab'
    log_audit(
        db,
        actor_user_id=actor,
        entity='instrument_result_import',
        entity_id=str(order.id),
        action='import',
        after_json={
            'order_id': str(order.id),
            'order_number': order.order_number,
            'matched_by': matched_by,
            'imported_count': imported_count,
            'unmatched_codes': unmatched_codes,
            'capture_id': payload.result.capture_id,
        },
    )
    db.commit()
    return InstrumentImportOut(
        order_id=str(order.id),
        order_number=order.order_number,
        matched_by=matched_by,
        imported_count=imported_count,
        unmatched_codes=unmatched_codes,
    )


def _parse_uuid(raw_value: str, *, field_name: str) -> UUID:
    try:
        return UUID(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f'invalid {field_name}') from exc


def _decimal_to_float(raw_value: str) -> float | None:
    try:
        return float(Decimal(raw_value))
    except (InvalidOperation, ValueError):
        return None


def _calculate_flag(result_kind: str, result_value: str, lower_value: str | None, upper_value: str | None) -> str:
    if result_kind != 'numeric' or not result_value:
        return 'none'
    try:
        numeric_value = Decimal(result_value)
    except (InvalidOperation, ValueError):
        return 'abnormal'
    lower_decimal = Decimal(lower_value) if lower_value else None
    upper_decimal = Decimal(upper_value) if upper_value else None
    if lower_decimal is not None and numeric_value < lower_decimal:
        return 'low'
    if upper_decimal is not None and numeric_value > upper_decimal:
        return 'high'
    if lower_decimal is not None or upper_decimal is not None:
        return 'normal'
    return 'none'


def _match_order_for_instrument(
    message: InstrumentMessageIn, db: Session, allow_patient_fallback: bool = True
) -> tuple[LabOrder | None, str]:
    candidates = [
        ('sample_id', (message.sample_id or '').strip()),
        ('accession_id', (message.accession_id or '').strip()),
        ('order_number', (message.sample_id or '').strip()),
        ('order_number', (message.accession_id or '').strip()),
    ]
    seen: set[tuple[str, str]] = set()
    for field_name, value in candidates:
        key = (field_name, value)
        if not value or key in seen:
            continue
        seen.add(key)
        column = getattr(LabOrder, field_name)
        order = db.scalars(select(LabOrder).where(column == value).order_by(LabOrder.ordered_at.desc())).first()
        if order is not None:
            return order, field_name
    if allow_patient_fallback and (message.patient_id or '').strip():
        patient_order = db.scalars(
            select(LabOrder).where(
                or_(
                    LabOrder.sample_id == message.patient_id.strip(),
                    LabOrder.accession_id == message.patient_id.strip(),
                    LabOrder.order_number == message.patient_id.strip(),
                )
            ).order_by(LabOrder.ordered_at.desc())
        ).first()
        if patient_order is not None:
            return patient_order, 'patient_fallback'
    return None, ''


def _resolve_instrument_order(payload: InstrumentImportIn, db: Session) -> tuple[LabOrder | None, str]:
    if (payload.order_id or '').strip():
        parsed_order_id = _parse_uuid(payload.order_id.strip(), field_name='order_id')
        order = db.get(LabOrder, parsed_order_id)
        if order is None:
            raise HTTPException(status_code=404, detail='order not found')
        return order, 'manual_order_id'
    return _match_order_for_instrument(
        payload.result.message, db, allow_patient_fallback=payload.allow_patient_fallback
    )


def _upsert_instrument_result(
    db: Session,
    order: LabOrder,
    order_item: OrderItem,
    test: TestCatalog,
    obs: InstrumentObservationIn,
    actor_id: UUID,
) -> None:
    result = db.scalars(select(Result).where(Result.order_item_id == order_item.id)).first()
    result_kind = (test.result_kind or 'text').strip().lower()
    result_value = _instrument_result_value(obs, result_kind)
    unit_value = (obs.units_normalized or obs.units_raw or test.unit or '').strip() or None
    lower_value = None
    upper_value = None
    reference_text = None
    flag = _calculate_flag(result_kind, result_value, lower_value, upper_value)
    numeric_value = obs.value_numeric if result_kind == 'numeric' else None

    if result is None:
        result = Result(
            order_item_id=order_item.id,
            sample_id=None,
            entered_by=actor_id,
            status='draft',
        )
        db.add(result)

    result.value_text = result_value or None
    result.value_num = numeric_value
    result.unit = unit_value
    result.lower_value_text = lower_value
    result.upper_value_text = upper_value
    result.reference_text = reference_text
    # Nothing is written to comments. The capture, profile, device and codes
    # used to be stored here as a JSON trace, but comments print on the report
    # as a line under the result, so every imported result carried that trace
    # onto the patient's report. The same detail is in the audit log below, and
    # a comment a technician typed is left alone.
    result.flag = flag
    result.entered_by = actor_id
    result.status = 'draft'


def _instrument_result_value(obs: InstrumentObservationIn, result_kind: str) -> str:
    if result_kind == 'numeric' and obs.value_numeric is not None:
        return format(obs.value_numeric, 'g')
    if (obs.value_text or '').strip():
        return obs.value_text.strip()
    if (obs.value_raw or '').strip():
        return obs.value_raw.strip()
    if obs.value_numeric is not None:
        return format(obs.value_numeric, 'g')
    return ''


_FORMULA_OPS: dict = {
    _ast.Add: _operator.add,
    _ast.Sub: _operator.sub,
    _ast.Mult: _operator.mul,
    _ast.Div: _operator.truediv,
    _ast.USub: _operator.neg,
}


def _safe_eval_formula_node(node: _ast.AST) -> float:
    if isinstance(node, _ast.BinOp) and type(node.op) in _FORMULA_OPS:
        return _FORMULA_OPS[type(node.op)](_safe_eval_formula_node(node.left), _safe_eval_formula_node(node.right))
    if isinstance(node, _ast.UnaryOp) and type(node.op) in _FORMULA_OPS:
        return _FORMULA_OPS[type(node.op)](_safe_eval_formula_node(node.operand))
    if isinstance(node, _ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    raise ValueError(f"Unsupported node: {type(node).__name__}")


def _evaluate_formula(formula: str, values_by_code: dict[str, float]) -> float | None:
    expr = formula.upper()
    for code, value in values_by_code.items():
        expr = _re.sub(r'\[' + _re.escape(code) + r'\]', str(value), expr)
    if _re.search(r'\[', expr):
        return None
    try:
        tree = _ast.parse(expr, mode='eval')
        return _safe_eval_formula_node(tree.body)
    except (ValueError, ZeroDivisionError, SyntaxError, TypeError):
        return None


def _format_formula_result(value: float) -> str:
    if value == int(value) and abs(value) < 1e10:
        return str(int(value))
    return f"{value:.6g}"


def _recalculate_formula_order_items(db: Session, order_id: UUID, actor: UUID | None) -> None:
    formula_items = db.execute(
        select(OrderItem.id, TestCatalog.formula, TestCatalog.unit)
        .join(TestCatalog, TestCatalog.id == OrderItem.test_id)
        .where(OrderItem.order_id == order_id)
        .where(TestCatalog.formula.is_not(None))
        .where(TestCatalog.formula != '')
    ).all()
    if not formula_items:
        return

    result_rows = db.execute(
        select(TestCatalog.code, Result.value_text)
        .join(OrderItem, OrderItem.test_id == TestCatalog.id)
        .outerjoin(Result, Result.order_item_id == OrderItem.id)
        .where(OrderItem.order_id == order_id)
    ).all()
    values_by_code: dict[str, float] = {}
    for row in result_rows:
        code = (row.code or '').strip().upper()
        raw = (row.value_text or '').strip()
        if code and raw:
            try:
                values_by_code[code] = float(Decimal(raw))
            except (InvalidOperation, ValueError):
                pass

    for item_id, formula, test_unit in formula_items:
        computed = _evaluate_formula(formula, values_by_code)
        if computed is None:
            continue
        result_str = _format_formula_result(computed)
        existing = db.scalars(select(Result).where(Result.order_item_id == item_id)).first()
        if existing is None:
            existing = Result(
                order_item_id=item_id,
                entered_by=actor,
                status='draft',
            )
            db.add(existing)
        existing.value_text = result_str
        existing.value_num = computed
        existing.unit = existing.unit or test_unit
        existing.flag = 'none'
        existing.entered_by = actor
        existing.status = 'draft'
    db.flush()


def _result_audit_payload(result: Result | None) -> dict[str, object] | None:
    if result is None:
        return None
    return {
        'id': str(result.id) if result.id is not None else None,
        'order_item_id': str(result.order_item_id),
        'value_text': result.value_text,
        'value_num': float(result.value_num) if result.value_num is not None else None,
        'unit': result.unit,
        'lower_value_text': result.lower_value_text,
        'upper_value_text': result.upper_value_text,
        'reference_text': result.reference_text,
        'comments': result.comments,
        'flag': result.flag,
        'status': result.status,
    }
