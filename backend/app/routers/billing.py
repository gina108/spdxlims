from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.deps import require_roles
from app.db.session import get_db
from app.models.models import Invoice, InvoiceLine, LabOrder, OrderItem, Provider, ProviderPrice, TestCatalog
from app.routers.common import actor_from_header

router = APIRouter(dependencies=[Depends(require_roles("admin", "lab_manager"))])


def _pick_price(db: Session, provider_id: UUID, test_id: UUID, as_of: date) -> Decimal | None:
    row = db.scalars(
        select(ProviderPrice)
        .where(
            ProviderPrice.provider_id == provider_id,
            ProviderPrice.test_id == test_id,
            ProviderPrice.effective_from <= as_of,
            or_(ProviderPrice.effective_to.is_(None), ProviderPrice.effective_to >= as_of),
        )
        .order_by(ProviderPrice.effective_from.desc())
    ).first()
    return Decimal(row.price) if row else None


@router.post("/drafts/generate")
def generate_drafts(
    period_start: date = Query(...),
    period_end: date = Query(...),
    db: Session = Depends(get_db),
    actor: UUID | None = Depends(actor_from_header),
):
    if actor is None:
        raise HTTPException(status_code=400, detail="x-user-id header required")
    if period_end < period_start:
        raise HTTPException(status_code=400, detail="period_end must be >= period_start")

    orders = db.scalars(
        select(LabOrder).where(
            LabOrder.client_id.is_not(None),
            LabOrder.status.in_(["completed", "reported"]),
            LabOrder.ordered_at >= period_start,
            LabOrder.ordered_at < (period_end + timedelta(days=1)),
        )
    ).all()

    grouped: dict[UUID, list[LabOrder]] = {}
    for order in orders:
        grouped.setdefault(order.client_id, []).append(order)

    created = 0
    for provider_id, provider_orders in grouped.items():
        exists = db.scalars(
            select(Invoice).where(
                Invoice.provider_id == provider_id,
                Invoice.period_start == period_start,
                Invoice.period_end == period_end,
            )
        ).first()
        if exists:
            continue

        invoice = Invoice(
            provider_id=provider_id,
            period_start=period_start,
            period_end=period_end,
            status="draft",
            created_by=actor,
            subtotal=Decimal("0"),
            tax=Decimal("0"),
            total=Decimal("0"),
        )
        db.add(invoice)
        db.flush()

        subtotal = Decimal("0")
        for order in provider_orders:
            items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
            for item in items:
                test = db.get(TestCatalog, item.test_id)
                unit_price = _pick_price(db, provider_id, item.test_id, period_end)
                if unit_price is None:
                    continue
                line_total = unit_price
                line = InvoiceLine(
                    invoice_id=invoice.id,
                    order_id=order.id,
                    order_item_id=item.id,
                    test_code=test.code,
                    description=test.name,
                    qty=Decimal("1"),
                    unit_price=unit_price,
                    line_total=line_total,
                )
                db.add(line)
                subtotal += line_total

        invoice.subtotal = subtotal
        invoice.tax = Decimal("0")
        invoice.total = subtotal
        created += 1
        log_audit(
            db,
            actor_user_id=actor,
            entity="invoice",
            entity_id=str(invoice.id),
            action="draft_generate",
            after_json={"period_start": str(period_start), "period_end": str(period_end), "provider_id": str(provider_id)},
        )

    db.commit()
    return {"created": created}


@router.get("/invoices")
def list_invoices(
    status: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    db: Session = Depends(get_db),
):
    q = select(Invoice, Provider.legal_name).join(Provider, Provider.id == Invoice.provider_id)
    if status:
        q = q.where(Invoice.status == status)
    if period_start:
        q = q.where(Invoice.period_start >= period_start)
    if period_end:
        q = q.where(Invoice.period_end <= period_end)
    rows = db.execute(q.order_by(Invoice.created_at.desc())).all()
    return [
        {
            "id": str(inv.id),
            "provider_id": str(inv.provider_id),
            "provider_name": provider_name,
            "period_start": inv.period_start,
            "period_end": inv.period_end,
            "status": inv.status,
            "subtotal": str(inv.subtotal),
            "tax": str(inv.tax),
            "total": str(inv.total),
            "issue_date": inv.issue_date,
            "due_date": inv.due_date,
        }
        for inv, provider_name in rows
    ]


@router.post("/invoices/{invoice_id}/recalculate")
def recalculate_invoice(invoice_id: UUID, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="invoice not found")
    if invoice.status != "draft":
        raise HTTPException(status_code=409, detail="only draft invoices can be recalculated")

    subtotal = Decimal("0")
    lines = db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id)).all()
    for line in lines:
        subtotal += Decimal(line.line_total)

    before = {"subtotal": str(invoice.subtotal), "total": str(invoice.total)}
    invoice.subtotal = subtotal
    invoice.tax = Decimal("0")
    invoice.total = subtotal
    log_audit(db, actor_user_id=actor, entity="invoice", entity_id=str(invoice.id), action="recalculate", before_json=before, after_json={"subtotal": str(subtotal), "total": str(subtotal)})
    db.commit()
    return {"id": str(invoice.id), "subtotal": str(invoice.subtotal), "total": str(invoice.total)}


@router.post("/invoices/{invoice_id}/issue")
def issue_invoice(invoice_id: UUID, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="invoice not found")
    if invoice.status != "draft":
        raise HTTPException(status_code=409, detail="invoice must be draft")

    invoice.status = "issued"
    invoice.issue_date = date.today()
    due_days = db.get(Provider, invoice.provider_id).billing_terms_days
    invoice.due_date = invoice.issue_date + timedelta(days=due_days)
    log_audit(db, actor_user_id=actor, entity="invoice", entity_id=str(invoice.id), action="issue", after_json={"issue_date": str(invoice.issue_date), "due_date": str(invoice.due_date)})
    db.commit()
    return {"id": str(invoice.id), "status": invoice.status}


@router.post("/invoices/{invoice_id}/mark-paid")
def mark_paid(invoice_id: UUID, db: Session = Depends(get_db), actor: UUID | None = Depends(actor_from_header)):
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="invoice not found")
    if invoice.status not in {"issued", "draft"}:
        raise HTTPException(status_code=409, detail="invoice cannot be marked paid")

    invoice.status = "paid"
    log_audit(db, actor_user_id=actor, entity="invoice", entity_id=str(invoice.id), action="mark_paid")
    db.commit()
    return {"id": str(invoice.id), "status": invoice.status}


@router.get("/reports/monthly")
def monthly_report(period_start: date, period_end: date, db: Session = Depends(get_db)):
    rows = db.execute(
        select(Invoice.status, Invoice.total).where(
            and_(
                Invoice.period_start >= period_start,
                Invoice.period_end <= period_end,
            )
        )
    ).all()
    totals: dict[str, Decimal] = {"draft": Decimal("0"), "issued": Decimal("0"), "paid": Decimal("0"), "void": Decimal("0")}
    for status, total in rows:
        totals[status] = totals.get(status, Decimal("0")) + Decimal(total)
    return {k: str(v) for k, v in totals.items()}


