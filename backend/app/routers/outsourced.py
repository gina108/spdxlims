from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.session import get_db
from app.models.models import (
    LabOrder,
    OrderItem,
    OutsourcedPanelExtraction,
    OutsourcedPanelRow,
    OutsourcedPanelTable,
    Patient,
)
from app.routers.common import actor_from_header

router = APIRouter()


class OutsourcedOrderChoiceOut(BaseModel):
    id: str
    label: str


class ExtractionOut(BaseModel):
    id: str
    source_pdf_path: str
    page_label: str
    row_count: int
    extracted_at: str | None = None


class AppendExtractionIn(BaseModel):
    panel_label: str
    source_pdf_path: str
    page_label: str = ""
    rows: list[list[Any]] = []


class OutsourcedSectionIn(BaseModel):
    panel_label: str
    source_pdf_path: str | None = ""
    rows: list[dict[str, Any]] = []


class ReplaceRowsIn(BaseModel):
    sections: list[OutsourcedSectionIn] = []


def _parse_uuid(raw: str, *, field: str) -> UUID:
    try:
        return UUID(str(raw))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid {field}") from exc


def _patient_name(first: str | None, last: str | None, middle: str | None) -> str:
    return ' '.join(part for part in [first or '', last or '', middle or ''] if part).strip()


def _normalize_rows(rows: list[list[Any]]) -> list[list[str]]:
    """Match the desktop: keep the first five columns as trimmed strings, pad to
    five, and drop rows that are entirely blank."""
    normalized: list[list[str]] = []
    for raw in rows:
        cells = [str(value or '').strip() for value in list(raw)[:5]]
        while len(cells) < 5:
            cells.append('')
        if any(cells):
            normalized.append(cells)
    return normalized


def _get_or_create_table(db: Session, order_id: UUID, panel_label: str, source_pdf_path: str) -> OutsourcedPanelTable:
    table = db.scalars(
        select(OutsourcedPanelTable).where(
            OutsourcedPanelTable.order_id == order_id,
            OutsourcedPanelTable.panel_label == panel_label,
        )
    ).first()
    if table is None:
        table = OutsourcedPanelTable(order_id=order_id, panel_label=panel_label, source_pdf_path=source_pdf_path)
        db.add(table)
        db.flush()
    else:
        table.updated_at = func.now()
    return table


@router.get('/order-choices', response_model=list[OutsourcedOrderChoiceOut])
def list_order_choices(db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    rows = db.execute(
        select(
            LabOrder.id,
            LabOrder.order_number,
            LabOrder.ordered_at,
            Patient.first_name,
            Patient.last_name,
            Patient.middle_name,
        )
        .join(Patient, Patient.id == LabOrder.patient_id)
        .join(OrderItem, OrderItem.order_id == LabOrder.id)
        .where(OrderItem.is_outsourced.is_(True), LabOrder.is_archived.is_(False))
        .group_by(LabOrder.id, LabOrder.order_number, LabOrder.ordered_at, Patient.first_name, Patient.last_name, Patient.middle_name)
        .order_by(LabOrder.ordered_at.desc())
    ).all()
    return [
        OutsourcedOrderChoiceOut(id=str(row.id), label=f"{row.order_number} - {_patient_name(row.first_name, row.last_name, row.middle_name)}")
        for row in rows
    ]


@router.get('/orders/{order_id}/panels', response_model=list[str])
def list_panels(order_id: str, db: Session = Depends(get_db), _actor: UUID | None = Depends(actor_from_header)):
    parsed = _parse_uuid(order_id, field='order_id')
    rows = db.execute(
        select(distinct(OrderItem.source_label))
        .where(
            OrderItem.order_id == parsed,
            OrderItem.is_outsourced.is_(True),
            OrderItem.source_label.isnot(None),
            func.trim(OrderItem.source_label) != '',
        )
    ).all()
    return sorted(str(row[0]).strip() for row in rows if row[0] and str(row[0]).strip())


@router.get('/orders/{order_id}/extractions', response_model=list[ExtractionOut])
def list_extractions(
    order_id: str,
    panel_label: str = Query(...),
    db: Session = Depends(get_db),
    _actor: UUID | None = Depends(actor_from_header),
):
    parsed = _parse_uuid(order_id, field='order_id')
    table = db.scalars(
        select(OutsourcedPanelTable).where(
            OutsourcedPanelTable.order_id == parsed,
            OutsourcedPanelTable.panel_label == panel_label.strip(),
        )
    ).first()
    if table is None:
        return []
    extractions = db.scalars(
        select(OutsourcedPanelExtraction)
        .where(OutsourcedPanelExtraction.outsourced_panel_table_id == table.id)
        .order_by(OutsourcedPanelExtraction.extracted_at.asc(), OutsourcedPanelExtraction.id.asc())
    ).all()
    return [
        ExtractionOut(
            id=str(ext.id),
            source_pdf_path=ext.source_pdf_path or '',
            page_label=ext.page_label or '',
            row_count=ext.row_count or 0,
            extracted_at=ext.extracted_at.isoformat() if ext.extracted_at else None,
        )
        for ext in extractions
    ]


@router.post('/orders/{order_id}/extractions')
def append_extraction(
    order_id: str,
    payload: AppendExtractionIn,
    db: Session = Depends(get_db),
    _actor=Depends(require_roles('admin', 'lab_manager', 'tech')),
):
    parsed = _parse_uuid(order_id, field='order_id')
    label = payload.panel_label.strip()
    source = payload.source_pdf_path.strip()
    if not label:
        raise HTTPException(status_code=400, detail='An outsourced panel must be selected.')
    if not source:
        raise HTTPException(status_code=400, detail='A source PDF path is required.')
    rows = _normalize_rows(payload.rows)
    table = _get_or_create_table(db, parsed, label, source)
    extraction = OutsourcedPanelExtraction(
        outsourced_panel_table_id=table.id,
        source_pdf_path=source,
        page_label=str(payload.page_label or '').strip(),
        row_count=len(rows),
    )
    db.add(extraction)
    db.flush()
    for row_index, cells in enumerate(rows):
        db.add(
            OutsourcedPanelRow(
                outsourced_panel_table_id=table.id,
                extraction_id=extraction.id,
                row_index=row_index,
                col_1=cells[0], col_2=cells[1], col_3=cells[2], col_4=cells[3], col_5=cells[4],
            )
        )
    db.commit()
    return {'extraction_id': str(extraction.id)}


@router.delete('/extractions/{extraction_id}')
def delete_extraction(
    extraction_id: str,
    db: Session = Depends(get_db),
    _actor=Depends(require_roles('admin', 'lab_manager', 'tech')),
):
    parsed = _parse_uuid(extraction_id, field='extraction_id')
    db.execute(delete(OutsourcedPanelRow).where(OutsourcedPanelRow.extraction_id == parsed))
    db.execute(delete(OutsourcedPanelExtraction).where(OutsourcedPanelExtraction.id == parsed))
    db.commit()
    return {'status': 'ok'}


@router.put('/orders/{order_id}/rows')
def replace_rows(
    order_id: str,
    payload: ReplaceRowsIn,
    db: Session = Depends(get_db),
    _actor=Depends(require_roles('admin', 'lab_manager', 'tech')),
):
    parsed = _parse_uuid(order_id, field='order_id')
    sections_by_label: dict[str, OutsourcedSectionIn] = {}
    for section in payload.sections:
        label = (section.panel_label or '').strip()
        if label:
            sections_by_label[label] = section

    existing = {
        table.panel_label.strip(): table
        for table in db.scalars(select(OutsourcedPanelTable).where(OutsourcedPanelTable.order_id == parsed)).all()
    }
    for label in set(sections_by_label) | set(existing):
        section = sections_by_label.get(label)
        rows = _normalize_rows(
            [
                [row.get('col_1'), row.get('col_2'), row.get('col_3'), row.get('col_4'), row.get('col_5')]
                for row in ((section.rows if section else []) or [])
            ]
        )
        table = existing.get(label)
        if table is None:
            source_pdf_path = str((section.source_pdf_path if section else '') or '').strip()
            table = OutsourcedPanelTable(order_id=parsed, panel_label=label, source_pdf_path=source_pdf_path)
            db.add(table)
            db.flush()
        else:
            table.updated_at = func.now()
        db.execute(delete(OutsourcedPanelRow).where(OutsourcedPanelRow.outsourced_panel_table_id == table.id))
        db.execute(delete(OutsourcedPanelExtraction).where(OutsourcedPanelExtraction.outsourced_panel_table_id == table.id))
        db.flush()
        if not rows:
            continue
        extraction = OutsourcedPanelExtraction(
            outsourced_panel_table_id=table.id,
            source_pdf_path=table.source_pdf_path or '',
            page_label='',
            row_count=len(rows),
        )
        db.add(extraction)
        db.flush()
        for row_index, cells in enumerate(rows):
            db.add(
                OutsourcedPanelRow(
                    outsourced_panel_table_id=table.id,
                    extraction_id=extraction.id,
                    row_index=row_index,
                    col_1=cells[0], col_2=cells[1], col_3=cells[2], col_4=cells[3], col_5=cells[4],
                )
            )
    db.commit()
    return {'status': 'ok'}
