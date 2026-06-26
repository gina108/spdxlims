from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.db.session import get_db
from app.models.models import TestCatalog, TestReferenceRange
from app.routers.common import actor_from_header

router = APIRouter()


class ReferenceRangeIn(BaseModel):
    sex: str | None = None
    age_min_days: int | None = None
    age_max_days: int | None = None
    lower_value: str | None = None
    upper_value: str | None = None
    unit: str = ''
    reference_text: str = ''


class TestIn(BaseModel):
    code: str
    name: str
    category_name: str = ''
    specimen_type: str = ''
    method: str = ''
    result_kind: str = 'text'
    select_options: list[str] = []
    default_result_value: str = ''
    formula: str = ''
    price: float = 0
    reference_ranges: list[ReferenceRangeIn] = []


class TestSummaryOut(BaseModel):
    id: str
    code: str
    name: str
    category_name: str | None = None
    specimen_type: str | None = None
    method: str | None = None
    result_kind: str
    select_options: str | None = None
    default_result_value: str | None = None
    is_active: bool
    range_count: int


class TestDetailOut(BaseModel):
    id: str
    code: str
    name: str
    category_name: str | None = None
    specimen_type: str | None = None
    method: str | None = None
    result_kind: str
    select_options: str | None = None
    default_result_value: str | None = None
    formula: str | None = None
    price: float = 0
    is_active: bool
    reference_ranges: list[dict]


@router.get('', response_model=list[TestSummaryOut])
def list_tests(status_filter: str = Query('active'), db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    normalized = status_filter.strip().lower() or 'active'
    stmt = (
        select(
            TestCatalog.id,
            TestCatalog.code,
            TestCatalog.name,
            TestCatalog.category_name,
            TestCatalog.specimen_type,
            TestCatalog.method,
            TestCatalog.result_kind,
            TestCatalog.select_options,
            TestCatalog.default_result_value,
            TestCatalog.active,
            func.count(TestReferenceRange.id).label('range_count'),
        )
        .outerjoin(TestReferenceRange, TestReferenceRange.test_id == TestCatalog.id)
        .group_by(
            TestCatalog.id,
            TestCatalog.code,
            TestCatalog.name,
            TestCatalog.category_name,
            TestCatalog.specimen_type,
            TestCatalog.method,
            TestCatalog.result_kind,
            TestCatalog.select_options,
            TestCatalog.default_result_value,
            TestCatalog.active,
        )
        .order_by(TestCatalog.active.desc(), TestCatalog.category_name.asc().nulls_last(), TestCatalog.name.asc())
    )
    if normalized == 'active':
        stmt = stmt.where(TestCatalog.active.is_(True))
    elif normalized == 'archived':
        stmt = stmt.where(TestCatalog.active.is_(False))
    rows = db.execute(stmt).all()
    return [
        TestSummaryOut(
            id=str(row.id),
            code=row.code,
            name=row.name,
            category_name=row.category_name,
            specimen_type=row.specimen_type,
            method=row.method,
            result_kind=row.result_kind,
            select_options=row.select_options,
            default_result_value=row.default_result_value,
            is_active=bool(row.active),
            range_count=int(row.range_count or 0),
        )
        for row in rows
    ]


@router.get('/{test_id}', response_model=TestDetailOut)
def get_test(test_id: str, db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    parsed_test_id = _parse_uuid(test_id, field_name='test_id')
    test = db.get(TestCatalog, parsed_test_id)
    if test is None:
        raise HTTPException(status_code=404, detail='test not found')
    return _serialize_test_detail(test, db)


@router.post('')
def create_test(payload: TestIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    test = TestCatalog(
        code=payload.code.strip(),
        name=payload.name.strip(),
        category_name=payload.category_name.strip() or None,
        specimen_type=payload.specimen_type.strip() or None,
        method=payload.method.strip() or None,
        result_kind=payload.result_kind,
        select_options=_serialize_select_options(payload.select_options),
        default_result_value=payload.default_result_value.strip() or None,
        formula=payload.formula.strip() or None,
        price=float(payload.price or 0),
        active=True,
    )
    db.add(test)
    db.flush()
    _replace_reference_ranges(test.id, payload.reference_ranges, db)
    log_audit(db, actor_user_id=actor, entity='test', entity_id=str(test.id), action='create', after_json=payload.model_dump(mode='json'))
    db.commit()
    return {'id': str(test.id)}


@router.put('/{test_id}')
def update_test(test_id: str, payload: TestIn, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    parsed_test_id = _parse_uuid(test_id, field_name='test_id')
    test = db.get(TestCatalog, parsed_test_id)
    if test is None:
        raise HTTPException(status_code=404, detail='test not found')
    before = _test_audit_payload(test, db)
    test.code = payload.code.strip()
    test.name = payload.name.strip()
    test.category_name = payload.category_name.strip() or None
    test.specimen_type = payload.specimen_type.strip() or None
    test.method = payload.method.strip() or None
    test.result_kind = payload.result_kind
    test.select_options = _serialize_select_options(payload.select_options)
    test.default_result_value = payload.default_result_value.strip() or None
    test.formula = payload.formula.strip() or None
    test.price = float(payload.price or 0)
    db.query(TestReferenceRange).filter(TestReferenceRange.test_id == parsed_test_id).delete()
    db.flush()
    _replace_reference_ranges(parsed_test_id, payload.reference_ranges, db)
    db.flush()
    log_audit(db, actor_user_id=actor, entity='test', entity_id=str(test.id), action='update', before_json=before, after_json=_test_audit_payload(test, db))
    db.commit()
    return {'id': str(test.id)}


@router.post('/{test_id}/archive')
def archive_test(test_id: str, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    parsed_test_id = _parse_uuid(test_id, field_name='test_id')
    test = db.get(TestCatalog, parsed_test_id)
    if test is None:
        raise HTTPException(status_code=404, detail='test not found')
    if test.code.startswith('__PANEL_'):
        raise HTTPException(status_code=400, detail='This system test cannot be archived.')
    before = _test_audit_payload(test, db)
    test.active = False
    log_audit(db, actor_user_id=actor, entity='test', entity_id=str(test.id), action='archive', before_json=before, after_json=_test_audit_payload(test, db))
    db.commit()
    return {'id': str(test.id), 'active': False}


@router.post('/{test_id}/unarchive')
def unarchive_test(test_id: str, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    parsed_test_id = _parse_uuid(test_id, field_name='test_id')
    test = db.get(TestCatalog, parsed_test_id)
    if test is None:
        raise HTTPException(status_code=404, detail='test not found')
    before = _test_audit_payload(test, db)
    test.active = True
    log_audit(db, actor_user_id=actor, entity='test', entity_id=str(test.id), action='unarchive', before_json=before, after_json=_test_audit_payload(test, db))
    db.commit()
    return {'id': str(test.id), 'active': True}


def _replace_reference_ranges(test_id: UUID, reference_ranges: list[ReferenceRangeIn], db: Session) -> None:
    for reference in reference_ranges:
        db.add(
            TestReferenceRange(
                test_id=test_id,
                sex=(reference.sex or '').strip() or None,
                age_min_days=reference.age_min_days,
                age_max_days=reference.age_max_days,
                lower_value_text=(reference.lower_value or '').strip() or None,
                upper_value_text=(reference.upper_value or '').strip() or None,
                unit=reference.unit.strip() or None,
                reference_text=reference.reference_text.strip() or None,
            )
        )


def _serialize_test_detail(test: TestCatalog, db: Session) -> TestDetailOut:
    ranges = db.scalars(
        select(TestReferenceRange)
        .where(TestReferenceRange.test_id == test.id)
        .order_by(TestReferenceRange.id.asc())
    ).all()
    return TestDetailOut(
        id=str(test.id),
        code=test.code,
        name=test.name,
        category_name=test.category_name,
        specimen_type=test.specimen_type,
        method=test.method,
        result_kind=test.result_kind,
        select_options=test.select_options,
        default_result_value=test.default_result_value,
        formula=test.formula,
        price=float(test.price or 0),
        is_active=bool(test.active),
        reference_ranges=[
            {
                'sex': item.sex,
                'age_min_days': item.age_min_days,
                'age_max_days': item.age_max_days,
                'lower_value': item.lower_value_text,
                'upper_value': item.upper_value_text,
                'unit': item.unit,
                'reference_text': item.reference_text,
            }
            for item in ranges
        ],
    )


def _serialize_select_options(options: list[str]) -> str | None:
    normalized = [str(option).strip() for option in options if str(option).strip()]
    return json.dumps(normalized, ensure_ascii=True) if normalized else None


def _parse_uuid(raw_value: str, *, field_name: str) -> UUID:
    try:
        return UUID(str(raw_value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f'invalid {field_name}') from exc


def _test_audit_payload(test: TestCatalog, db: Session) -> dict:
    return _serialize_test_detail(test, db).model_dump(mode='json')
