from datetime import date
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.models.models import AppUser, TestReferenceRange


def actor_from_header(current_user: AppUser = Depends(get_current_user)) -> UUID:
    return current_user.id


def age_to_days(age_value: int | None, age_unit: str | None, dob: date | None = None) -> int | None:
    if dob is not None:
        return max((date.today() - dob).days, 0)
    if age_value is None or not age_unit:
        return None
    unit = age_unit.strip().lower()
    if unit == 'days':
        return age_value
    if unit == 'months':
        return age_value * 30
    if unit == 'years':
        return age_value * 365
    return None


def resolve_reference_range(
    db: Session,
    test_id: UUID,
    patient_sex: str | None,
    patient_age_days: int | None,
) -> TestReferenceRange | None:
    rows = db.scalars(
        select(TestReferenceRange)
        .where(TestReferenceRange.test_id == test_id)
        .order_by(
            TestReferenceRange.sex.is_(None),
            TestReferenceRange.age_min_days.is_(None),
            TestReferenceRange.age_min_days.asc(),
            TestReferenceRange.age_max_days.is_(None),
            TestReferenceRange.age_max_days.asc(),
        )
    ).all()
    for row in rows:
        if row.sex and patient_sex and row.sex != patient_sex:
            continue
        if row.sex and not patient_sex:
            continue
        if patient_age_days is not None:
            if row.age_min_days is not None and patient_age_days < row.age_min_days:
                continue
            if row.age_max_days is not None and patient_age_days > row.age_max_days:
                continue
        return row
    return None
