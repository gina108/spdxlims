import re
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.models.models import AppUser, PanelCatalog, PanelCatalogItem, TestReferenceRange


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


def normalize_report_panel_label(value: str) -> str:
    label = (value or '').strip()
    if not label:
        return ''
    label = re.sub(r'\s*-\s*\d+\s+tests\s*$', '', label, flags=re.IGNORECASE).strip()
    return re.sub(r'\s+\([A-Z0-9_-]{1,20}\)$', '', label).strip()


def panel_catalog_structures(db: Session) -> dict[str, dict[str, Any]]:
    """Live panel templates (name/code -> ordered heading+test structure), keyed by
    every casefolded alias a stored order_item.group_label might use, so historical
    orders (tagged with a panel's code, name, or a stale "Name (CODE) - N tests"
    combo-box label) all resolve to the same structure."""
    panels = db.scalars(select(PanelCatalog)).all()
    items_by_panel: dict[UUID, list[PanelCatalogItem]] = {}
    for item in db.scalars(select(PanelCatalogItem).order_by(PanelCatalogItem.panel_id, PanelCatalogItem.sort_order, PanelCatalogItem.id)).all():
        items_by_panel.setdefault(item.panel_id, []).append(item)
    structures: dict[str, dict[str, Any]] = {}
    for panel in panels:
        name = (panel.name or '').strip()
        code = (panel.code or '').strip()
        if not name:
            continue
        structure = {'name': name, 'code': code, 'items': items_by_panel.get(panel.id, [])}
        aliases = {name, code, normalize_report_panel_label(f'{name} ({code})'), normalize_report_panel_label(f'{name} ({code}) - 1 tests')}
        for alias in aliases:
            normalized = (alias or '').strip()
            if normalized:
                structures[normalized.casefold()] = structure
    return structures


def restore_panel_catalog_structure(items: list[dict[str, Any]], structures: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Mirrors the desktop's local-mode equivalent (spdxlims/db/results.py). For a
    panel group with no heading/comment rows of its own (true for every order
    migrated before order_item supported them), rebuild its item list from the
    CURRENT live panel template so sub-headings like "Formula Roja" show up
    without needing any change to historical order data."""
    if not structures:
        return items
    grouped: dict[str, list[dict[str, Any]]] = {}
    group_order: list[str] = []
    passthrough: list[dict[str, Any]] = []
    for item in items:
        raw_label = normalize_report_panel_label(str(item.get('source_label') or ''))
        structure = structures.get(raw_label.casefold())
        label = str((structure or {}).get('name') or raw_label).strip()
        if not label:
            passthrough.append(item)
            continue
        if label not in grouped:
            group_order.append(label)
        grouped.setdefault(label, []).append(item)
    if not grouped:
        return items
    restored: list[dict[str, Any]] = list(passthrough)
    for label in group_order:
        group_items = grouped[label]
        structure = structures.get(label.casefold())
        if structure is None or any(str(item.get('item_type') or 'test') in ('heading', 'comment') for item in group_items):
            for item in group_items:
                normalized = dict(item)
                normalized['source_label'] = label
                restored.append(normalized)
            continue
        by_test_id = {item['test_id']: item for item in group_items if item.get('test_id') is not None}
        used_test_ids: set[Any] = set()
        for panel_item in structure['items']:
            if panel_item.item_type in ('heading', 'comment'):
                restored.append(
                    {
                        'order_item_id': None,
                        'test_id': None,
                        'item_type': panel_item.item_type,
                        'display_name': panel_item.heading_text or '',
                        'test_name': None,
                        'test_code': None,
                        'result_kind': None,
                        'value_text': None,
                        'unit': None,
                        'reference_text': None,
                        'lower_value_text': None,
                        'upper_value_text': None,
                        'flag': None,
                        'comments': None,
                        'source_label': structure['name'],
                    }
                )
                continue
            if panel_item.test_id is None:
                continue
            matched = by_test_id.get(panel_item.test_id)
            if matched is None:
                continue
            normalized = dict(matched)
            normalized['source_label'] = structure['name']
            restored.append(normalized)
            used_test_ids.add(panel_item.test_id)
        for item in group_items:
            test_id = item.get('test_id')
            if test_id is None or test_id not in used_test_ids:
                normalized = dict(item)
                normalized['source_label'] = structure['name']
                restored.append(normalized)
    return restored


def inject_panel_title_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mirrors the desktop's local-mode equivalent: inserts one top-level heading
    row whenever the (already-resolved) panel label changes, so e.g. "BIOMETRIA
    HEMATICA" shows as a bold banner above its sub-headings/tests."""
    rendered: list[dict[str, Any]] = []
    active_panel = ''
    for item in items:
        normalized = dict(item)
        item_type = str(normalized.get('item_type') or 'test')
        label = normalize_report_panel_label(str(normalized.get('source_label') or ''))
        normalized['source_label'] = label
        if item_type in ('test', 'heading', 'comment') and label and label != active_panel:
            rendered.append(
                {
                    'order_item_id': None,
                    'test_id': None,
                    'item_type': 'heading',
                    'display_name': label,
                    'test_name': None,
                    'test_code': None,
                    'result_kind': None,
                    'value_text': None,
                    'unit': None,
                    'reference_text': None,
                    'lower_value_text': None,
                    'upper_value_text': None,
                    'flag': None,
                    'comments': None,
                    'source_label': label,
                }
            )
            active_panel = label
        rendered.append(normalized)
        if item_type == 'heading' and not label:
            active_panel = ''
    return rendered
