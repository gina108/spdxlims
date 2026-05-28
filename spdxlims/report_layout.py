from __future__ import annotations

import base64
import re
from datetime import datetime
from html import escape
from pathlib import Path

from reportlab.graphics import renderSVG
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm

from spdxlims.i18n import tr


def build_report_html(preview: dict[str, object]) -> str:
    header_image = _image_html(
        preview.get("header_image_path"),
        "header-image",
        inline_style="display:block; width:100%; height:auto;",
        width_attr=' width="100%"',
    )
    footer_image = _image_html(
        preview.get("footer_signature_image_path"),
        "footer-image",
        inline_style="display:block; width:100%; max-width:none; max-height:none; height:auto;",
        width_attr=' width="100%"',
    )
    order_number = escape(str(preview.get("order_number") or ""))
    accession_id = escape(str(preview.get("accession_id") or ""))
    sample_id = escape(str(preview.get("sample_id") or ""))
    patient_name = escape(str(preview.get("patient_name") or ""))
    patient_sex = escape(str(preview.get("patient_sex") or ""))
    patient_dob_raw = str(preview.get("patient_dob") or "")
    patient_age_value_raw = preview.get("patient_age_value")
    patient_age_unit_raw = str(preview.get("patient_age_unit") or "")
    patient_dob = escape(_format_date(patient_dob_raw))
    doctor_name = escape(str(preview.get("doctor_name") or ""))
    client_name = escape(str(preview.get("client_name") or ""))
    ordered_at_raw = str(preview.get("ordered_at") or "")
    reported_at_raw = str(preview.get("reported_at") or "")
    ordered_at = escape(_format_datetime(ordered_at_raw))
    reported_at = escape(_format_datetime(reported_at_raw))
    printed_at = escape(datetime.now().strftime("%d/%m/%Y %H:%M"))
    lab_name = escape(str(preview.get("lab_name") or ""))
    lab_address = escape(str(preview.get("lab_address") or ""))
    lab_phone = escape(str(preview.get("lab_phone") or ""))
    lab_email = escape(str(preview.get("lab_email") or ""))
    general_comments = escape(str(preview.get("general_comments") or "")).replace("\n", "<br>")
    patient_age = escape(_format_age(
        patient_dob_raw,
        ordered_at_raw or reported_at_raw,
        patient_age_value=patient_age_value_raw,
        patient_age_unit=patient_age_unit_raw,
    ))
    folio_value = accession_id or sample_id or order_number
    origin_value = client_name or lab_name
    qr_html = _qr_html(preview)
    flag_display_mode = str(preview.get("flag_display_mode") or "arrows")
    outsourced_sections = list(preview.get("outsourced_panels") or [])

    rows: list[tuple[str, float, str]] = []
    for item in list(preview.get("items") or []):
        item_type = str(item.get("item_type") or "test")
        raw_test_name = str(item.get("test_name") or "")
        if item_type == "heading":
            raw_test_name = _normalize_panel_heading(raw_test_name)
        test_name = escape(raw_test_name)
        result_value = escape(str(item.get("result_value") or ""))
        unit = escape(str(item.get("unit") or ""))
        lower_value = escape(str(item.get("lower_value") or ""))
        upper_value = escape(str(item.get("upper_value") or ""))
        reference_text = escape(str(item.get("reference_text") or ""))
        raw_flag = str(item.get("flag") or "")
        flag = escape(_format_flag(raw_flag, flag_display_mode))
        comments = escape(str(item.get("comments") or ""))
        range_text = " - ".join(part for part in [lower_value, upper_value] if part)
        if reference_text and not range_text:
            range_text = reference_text
        elif reference_text:
            range_text = f"{range_text} / {reference_text}"
        if item_type == "heading":
            row_html = f'<tr><td colspan="5" class="section">{test_name}</td></tr>'
            rows.append((row_html, 1.2, "heading"))
            continue
        if item_type == "comment":
            comment_value = comments or result_value
            row_html = f'<tr><td colspan="5" class="comment"><strong>{test_name}</strong><br>{comment_value}</td></tr>'
            rows.append((row_html, 1.4 + _estimated_line_units(test_name + " " + comment_value), "comment"))
            continue
        row_html = (
            "<tr>"
            f"<td>{test_name}</td>"
            f"<td>{flag}</td>"
            f"<td>{result_value}</td>"
            f"<td>{unit}</td>"
            f"<td>{range_text}</td>"
            "</tr>"
        )
        rows.append((row_html, 1.0 + _estimated_line_units(test_name), "test"))
        if comments:
            rows.append((f'<tr><td colspan="5" class="subcomment">{comments}</td></tr>', 0.8 + _estimated_line_units(comments), "subcomment"))

    for section in outsourced_sections:
        panel_label = escape(_normalize_panel_heading(str(section.get("panel_label") or "")))
        section_rows: list[tuple[str, str]] = []
        for row in list(section.get("rows") or []):
            raw_values = [str(row.get(f"col_{index}") or "") for index in range(1, 6)]
            values = [escape(value) for value in raw_values]
            if not any(values):
                continue
            section_rows.append(
                (
                    "<tr>"
                    + "".join(f"<td>{value}</td>" for value in values)
                    + "</tr>",
                    " ".join(value.strip() for value in raw_values),
                )
            )
        if not section_rows:
            continue
        rows.append((
            f'<tr><td colspan="5" class="section outsourced-section">{panel_label or escape(tr("Outsourced Panel"))}</td></tr>',
            1.2,
            "heading",
        ))
        for section_row, section_text in section_rows:
            rows.append((section_row, 1.0 + _estimated_line_units(section_text), "outsourced"))

    top_summary = (
        ""
        if header_image
        else (
            '<table class="top" width="100%" cellspacing="0" cellpadding="0">'
            "<tr>"
            f'<td class="brand" width="56%"><div class="brand-fallback">{lab_name}</div></td>'
            '<td class="title-block" width="44%">'
            f'<div class="lab-line">{lab_address}</div>'
            f'<div class="lab-line">{lab_phone}</div>'
            f'<div class="lab-line">{lab_email}</div>'
            "</td>"
            "</tr>"
            "</table>"
        )
    )
    info_grid_html = f"""
            <table class="info-grid" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                    <td width="42%">
                        <table class="info-block" width="100%" cellspacing="0" cellpadding="0">
                            <tr><td class="label">{escape(tr("Patient"))}:</td><td class="value">{patient_name}</td></tr>
                            <tr><td class="label">{escape(tr("Doctor"))}:</td><td class="value">{doctor_name}</td></tr>
                            <tr><td class="label">{escape(tr("Origin"))}:</td><td class="value">{origin_value}</td></tr>
                            <tr><td class="label">{escape(tr("Sex"))}:</td><td class="value">{patient_sex}</td></tr>
                            <tr><td class="label">{escape(tr("Age"))}:</td><td class="value">{patient_age}</td></tr>
                        </table>
                    </td>
                    <td width="40%">
                        <table class="info-block" width="100%" cellspacing="0" cellpadding="0">
                            <tr><td class="label">{escape(tr("Folio"))}:</td><td class="value highlight">{folio_value}</td></tr>
                            <tr><td class="label">{escape(tr("DOB"))}:</td><td class="value">{patient_dob}</td></tr>
                            <tr><td class="label">{escape(tr("Appointment Date"))}:</td><td class="value">{ordered_at}</td></tr>
                            <tr><td class="label">{escape(tr("Print Date"))}:</td><td class="value">{reported_at or printed_at}</td></tr>
                        </table>
                    </td>
                    <td class="qr-cell" width="18%">{qr_html}</td>
                </tr>
            </table>
    """
    page_header_html = f"""
        <div class="header-shell">
            {header_image and f'<table class="banner-table" width="100%" cellspacing="0" cellpadding="0"><tr><td>{header_image}</td></tr></table>' or top_summary}
            {info_grid_html}
            {_render_results_header()}
        </div>
    """
    page_footer_html = f'<div class="footer-banner">{footer_image}</div>' if footer_image else ""
    has_footer_extra_content = bool(general_comments)
    if footer_image:
        row_page_limit = 22.0 if has_footer_extra_content else 24.0
    else:
        row_page_limit = 31.0
    paged_row_groups = _paginate_result_rows(rows, row_page_limit)
    paged_row_groups = _rebalance_paged_row_groups(paged_row_groups, row_page_limit)
    if not paged_row_groups:
        paged_row_groups = [[]]
    rendered_pages: list[str] = []
    for index, page_rows in enumerate(paged_row_groups):
        extra_content = ""
        if index == len(paged_row_groups) - 1:
            extra_parts: list[str] = []
            if general_comments:
                extra_parts.append(f'<div class="footer"><div>{general_comments}</div></div>')
            extra_content = "".join(extra_parts)
        rendered_pages.append(
            _render_report_page(
                page_header_html,
                _render_results_body(page_rows),
                page_footer_html,
                extra_content=extra_content,
                page_break_after=index < len(paged_row_groups) - 1,
            )
        )
    rendered_pages_html = "".join(rendered_pages)

    return f"""<html><head><style>
        @page {{ size: A4; margin: 4mm; }}
        html, body {{ width: 100%; margin: 0; padding: 0; background: #ffffff; }}
        body {{ font-family: Segoe UI, Arial, sans-serif; color: #1f2430; font-size: 12px; line-height: 1.35; }}
        .page {{ width: 100%; margin: 0; padding: 0; box-sizing: border-box; }}
        .report-page {{ width: 100%; box-sizing: border-box; page-break-inside: avoid; }}
        .report-page-break {{ page-break-after: always; break-after: page; }}
        .page-frame {{ width: 100%; min-height: 289mm; height: 289mm; display: flex; flex-direction: column; box-sizing: border-box; }}
        .page-header {{ width: 100%; flex: 0 0 auto; }}
        .page-content {{ width: 100%; flex: 1 1 auto; min-height: 0; overflow: hidden; }}
        .page-footer {{ width: 100%; flex: 0 0 auto; margin-top: auto; padding-top: 4px; }}
        .header-shell {{ width: 100%; }}
        .banner-table {{ width: 100%; margin: -10px -4px 12px; }}
        .banner-table td {{ padding: 0; }}
        .top {{ width: 100%; border-collapse: collapse; margin-bottom: 10px; }}
        .top td {{ vertical-align: top; }}
        .brand {{ padding-right: 16px; }}
        .brand-fallback {{ font-size: 28px; font-weight: 700; color: #215d79; margin-top: 6px; }}
        .banner-table .header-image {{ display: block; width: 100%; max-width: none; max-height: none; height: auto; }}
        .header-image {{ display: block; width: 100%; max-width: 100%; max-height: none; height: auto; }}
        .title-block {{ text-align: right; }}
        .lab-line {{ font-size: 10px; color: #4a5564; line-height: 1.45; }}
        .info-grid {{ width: 100%; border-collapse: collapse; margin-bottom: 8px; table-layout: fixed; }}
        .info-grid > tbody > tr > td {{ vertical-align: top; padding: 2px 10px 2px 0; }}
        .info-block {{ width: 100%; border-collapse: collapse; }}
        .info-block td {{ padding: 2px 0; vertical-align: top; font-size: 15px; line-height: 1.1; }}
        .info-block .label {{ width: 34%; padding-right: 8px; }}
        .info-block .value {{ width: 66%; }}
        .label {{ font-weight: 700; color: #222833; white-space: nowrap; }}
        .value {{ color: #2c3440; }}
        .highlight {{ color: #d5673f; }}
        .qr-cell {{ text-align: right; padding-right: 0; padding-top: 0 !important; vertical-align: top; }}
        .qr-cell img {{ width: 110px; height: 110px; display: block; margin: -4px 0 0 auto; }}
        .qr-caption {{ font-size: 10px; color: #6b7480; line-height: 1.05; margin-top: 0; }}
        .section-title {{ background: #d9d9d9; color: #20242b; text-align: center; font-size: 15px; font-weight: 700; padding: 7px 10px; margin-top: 10px; }}
        .results-header, .results-body {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
        .results-header col.test-col, .results-body col.test-col {{ width: 48%; }}
        .results-header col.flag-col, .results-body col.flag-col {{ width: 3%; }}
        .results-header col.result-col, .results-body col.result-col {{ width: 16%; }}
        .results-header col.unit-col, .results-body col.unit-col {{ width: 12%; }}
        .results-header col.reference-col, .results-body col.reference-col {{ width: 21%; }}
        .results-header .results-title th {{ background: #d9d9d9; color: #20242b; text-align: center; font-size: 15px; font-weight: 700; padding: 7px 10px; border-bottom: 0; }}
        .results-header th {{ background: #e1e5ea; text-align: left; padding: 6px 8px; color: #2c323a; border-bottom: 1px solid #c8d0da; font-size: 13px; line-height: 1.1; }}
        .results-body td {{ padding: 4px 8px; border-bottom: 1px solid #dde3ea; font-size: 13px; line-height: 1.1; vertical-align: top; word-wrap: break-word; }}
        .results-header th:nth-child(1), .results-body td:nth-child(1) {{ padding-right: 2px; }}
        .results-header th:nth-child(2) {{ text-align: right; padding-left: 0; padding-right: 1px; }}
        .results-body td:nth-child(2) {{ text-align: right; padding-left: 0; padding-right: 1px; }}
        .results-header th:nth-child(3) {{ padding-right: 2px; }}
        .results-body td:nth-child(3) {{ padding-right: 2px; }}
        .results-header th:nth-child(4) {{ padding-left: 2px; padding-right: 4px; }}
        .results-body td:nth-child(4) {{ padding-left: 2px; padding-right: 4px; white-space: nowrap; word-wrap: normal; overflow-wrap: normal; }}
        .results-header th:nth-child(5) {{ padding-left: 2px; }}
        .results-body td:nth-child(5) {{ padding-left: 2px; }}
        .results-body tr {{ page-break-inside: avoid; break-inside: avoid; }}
        .section {{ background: #eef1f5; font-weight: 700; color: #223145; font-size: 13px; line-height: 1.1; }}
        .comment {{ background: #f7f9fc; color: #314153; font-size: 13px; line-height: 1.1; }}
        .subcomment {{ color: #4e5e72; font-size: 9px; line-height: 1.05; }}
        .footer {{ margin-top: 18px; font-size: 10px; color: #4d5b6a; }}
        .outsourced-title {{ margin-top: 16px; }}
        .outsourced-results {{ width: 100%; border-collapse: collapse; table-layout: fixed; margin-top: 4px; }}
        .outsourced-results td {{ padding: 4px 10px; border-bottom: 1px solid #dde3ea; font-size: 13px; line-height: 1.1; vertical-align: top; word-wrap: break-word; }}
        .outsourced-results td:nth-child(1) {{ width: 38%; }}
        .outsourced-results td:nth-child(2) {{ width: 14%; }}
        .outsourced-results td:nth-child(3) {{ width: 14%; }}
        .outsourced-results td:nth-child(4) {{ width: 14%; }}
        .outsourced-results td:nth-child(5) {{ width: 20%; }}
        .footer-banner {{ width: 100%; margin-top: 4px; }}
        .footer-image {{ display: block; width: 100%; max-width: none; max-height: none; height: auto; }}
        .director {{ margin-top: 12px; font-size: 10px; }}
        @media screen {{
            html, body {{ background: #eef2f6; }}
            body {{ padding: 12px 0; }}
            .page {{ width: 210mm; margin: 0 auto; }}
            .report-page {{
                width: 210mm;
                margin: 0 auto 12px;
                padding: 4mm;
                background: #ffffff;
                box-sizing: border-box;
                box-shadow: 0 2px 10px rgba(31, 36, 48, 0.12);
            }}
            .report-page:last-child {{ margin-bottom: 0; }}
            .page-frame {{ width: 202mm; min-width: 202mm; max-width: 202mm; }}
            .page-header,
            .page-content,
            .page-footer,
            .header-shell,
            .info-grid,
            .section-title,
            .results-header,
            .results-body,
            .outsourced-results {{
                width: 100% !important;
                min-width: 100% !important;
                max-width: 100% !important;
                box-sizing: border-box;
            }}
            .results-header,
            .results-body,
            .outsourced-results,
            .info-grid {{
                display: table;
            }}
            .section-title {{
                display: block;
            }}
        }}
    </style></head><body>
        <div class="page">
            {rendered_pages_html}
        </div>
    </body></html>"""


def image_html(raw_path: object, css_class: str) -> str:
    return _image_html(raw_path, css_class)


def _image_html(raw_path: object, css_class: str, *, inline_style: str = "", width_attr: str = "") -> str:
    if not raw_path:
        return ""
    value = str(raw_path)
    style_attr = f' style="{escape(inline_style, quote=True)}"' if inline_style else ""
    if value.startswith("http://") or value.startswith("https://") or value.startswith("file:///"):
        return f'<img class="{css_class}" src="{escape(value, quote=True)}"{width_attr}{style_attr}>'
    candidate = Path(value)
    if not candidate.exists():
        return ""
    return f'<img class="{css_class}" src="{candidate.resolve().as_uri()}"{width_attr}{style_attr}>'


def _qr_html(preview: dict[str, object]) -> str:
    lab_name = str(preview.get("lab_name") or "").strip() or "LAB REPORT"
    qr_parts = [
        lab_name,
        f'ORDER:{str(preview.get("order_number") or "").strip()}',
        f'FOLIO:{str(preview.get("accession_id") or preview.get("sample_id") or "").strip()}',
        f'PATIENT:{str(preview.get("patient_name") or "").strip()}',
        f'REPORTED:{_format_datetime(str(preview.get("reported_at") or preview.get("ordered_at") or ""))}',
    ]
    qr_text = "\n".join(part for part in qr_parts if part and not part.endswith(":"))
    if not qr_text.strip():
        return ""
    widget = qr.QrCodeWidget(qr_text)
    bounds = widget.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    drawing = Drawing(36 * mm, 36 * mm, transform=[36 * mm / width, 0, 0, 36 * mm / height, 0, 0])
    drawing.add(widget)
    svg = renderSVG.drawToString(drawing)
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return (
        f'<img src="data:image/svg+xml;base64,{encoded}">'
        f'<div class="qr-caption">{escape(tr("Authenticity Certificate"))}</div>'
    )


def _format_date(value: str) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return value
    return parsed.strftime("%d/%m/%Y")


def _format_datetime(value: str) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return value
    if parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0:
        return parsed.strftime("%d/%m/%Y")
    return parsed.strftime("%d/%m/%Y %H:%M")


def _parse_datetime(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _format_age(
    patient_dob: str,
    reference_datetime: str,
    *,
    patient_age_value: object = None,
    patient_age_unit: str = "",
) -> str:
    dob = _parse_datetime(patient_dob)
    reference = _parse_datetime(reference_datetime) or datetime.now()
    if dob is None:
        return _format_stored_age(patient_age_value, patient_age_unit)
    years = reference.year - dob.year - ((reference.month, reference.day) < (dob.month, dob.day))
    if years >= 2:
        return tr("{years} years", years=years)
    months = (reference.year - dob.year) * 12 + reference.month - dob.month
    if reference.day < dob.day:
        months -= 1
    if months >= 1:
        return tr("{months} months", months=months)
    days = max((reference.date() - dob.date()).days, 0)
    return tr("{days} days", days=days)


def _format_stored_age(age_value: object, age_unit: str) -> str:
    try:
        normalized_value = int(age_value)
    except (TypeError, ValueError):
        return ""
    normalized_unit = (age_unit or "").strip().lower()
    if normalized_value < 0 or not normalized_unit:
        return ""
    if normalized_unit == "years":
        return tr("{years} years", years=normalized_value)
    if normalized_unit == "months":
        return tr("{months} months", months=normalized_value)
    if normalized_unit == "days":
        return tr("{days} days", days=normalized_value)
    return f"{normalized_value} {normalized_unit}"


def _normalize_panel_heading(value: str) -> str:
    label = value.strip()
    if not label:
        return ""
    return re.sub(r"(?:\s*-\s*\d+\s+tests)+\s*$", "", label, flags=re.IGNORECASE).strip()


def _format_flag(flag_value: str, display_mode: str) -> str:
    normalized = flag_value.strip().lower()
    if not normalized or normalized in {"none", "normal", "normalo"}:
        return ""
    low_values = {"low", "bajo", "l", "↓", "down"}
    high_values = {"high", "alto", "h", "↑", "up"}
    if display_mode == "asterisks":
        if normalized in low_values:
            return "*"
        if normalized in high_values:
            return "**"
    if display_mode == "text":
        if normalized in low_values:
            return tr("Low")
        if normalized in high_values:
            return tr("High")
    if normalized in low_values:
        return "↓"
    if normalized in high_values:
        return "↑"
    return flag_value.strip()


def _estimated_line_units(value: str) -> float:
    compact = " ".join((value or "").split())
    if not compact:
        return 0.0
    estimated_lines = max(1, (len(compact) + 47) // 48)
    return max(0.0, (estimated_lines - 1) * 0.6)


def _paginate_result_rows(rows: list[tuple[str, float, str]], page_limit: float) -> list[list[tuple[str, float, str]]]:
    pages: list[list[tuple[str, float, str]]] = []
    current_page: list[tuple[str, float, str]] = []
    current_units = 0.0
    for row_html, row_units, row_kind in rows:
        if current_page and current_units + row_units > page_limit:
            pages.append(current_page)
            current_page = []
            current_units = 0.0
        current_page.append((row_html, row_units, row_kind))
        current_units += row_units
    if current_page:
        pages.append(current_page)
    return pages


def _page_row_units(rows: list[tuple[str, float, str]]) -> float:
    return sum(row_units for _row_html, row_units, _row_kind in rows)


def _rebalance_paged_row_groups(
    pages: list[list[tuple[str, float, str]]],
    page_limit: float,
) -> list[list[tuple[str, float, str]]]:
    balanced_pages = [list(page) for page in pages]
    if len(balanced_pages) < 2:
        return balanced_pages
    for index in range(len(balanced_pages) - 2, -1, -1):
        left_page = balanced_pages[index]
        right_page = balanced_pages[index + 1]
        if not left_page or not right_page:
            continue
        while len(left_page) > 1:
            left_units = _page_row_units(left_page)
            right_units = _page_row_units(right_page)
            candidate_row = left_page[-1]
            candidate_units = candidate_row[1]
            current_gap = abs(left_units - right_units)
            projected_gap = abs((left_units - candidate_units) - (right_units + candidate_units))
            if projected_gap >= current_gap:
                break
            right_page.insert(0, left_page.pop())
        _stabilize_page_boundary(left_page, right_page, page_limit)
    return balanced_pages


def _stabilize_page_boundary(
    left_page: list[tuple[str, float, str]],
    right_page: list[tuple[str, float, str]],
    page_limit: float,
) -> None:
    if not left_page or not right_page:
        return
    if left_page[-1][2] != "heading":
        return
    left_units = _page_row_units(left_page)
    moved_rows = 0
    while right_page and right_page[0][2] != "heading":
        next_row = right_page[0]
        if left_units + next_row[1] > page_limit:
            break
        left_page.append(right_page.pop(0))
        left_units += next_row[1]
        moved_rows += 1
    if moved_rows == 0:
        right_page.insert(0, left_page.pop())


def _render_results_header() -> str:
    return f"""
            <table class="results-header">
                <colgroup>
                    <col class="test-col">
                    <col class="flag-col">
                    <col class="result-col">
                    <col class="unit-col">
                    <col class="reference-col">
                </colgroup>
                <thead>
                    <tr class="results-title">
                        <th colspan="5">{escape(tr("Results Sheet"))}</th>
                    </tr>
                    <tr>
                        <th>{escape(tr("Test"))}</th>
                        <th></th>
                        <th>{escape(tr("Result"))}</th>
                        <th>{escape(tr("Unit"))}</th>
                        <th>{escape(tr("Reference"))}</th>
                    </tr>
                </thead>
            </table>
    """


def _render_results_body(rows: list[tuple[str, float, str]]) -> str:
    rendered_rows = "".join(row_html for row_html, _row_units, _row_kind in rows)
    return f"""
            <table class="results-body">
                <colgroup>
                    <col class="test-col">
                    <col class="flag-col">
                    <col class="result-col">
                    <col class="unit-col">
                    <col class="reference-col">
                </colgroup>
                <tbody>
                {rendered_rows}
                </tbody>
            </table>
    """


def _render_report_page(
    header_html: str,
    body_html: str,
    footer_html: str,
    *,
    extra_content: str = "",
    page_break_after: bool,
) -> str:
    page_class = "report-page report-page-break" if page_break_after else "report-page"
    return f"""
            <div class="{page_class}">
                <div class="page-frame">
                    <div class="page-header">
                        {header_html}
                    </div>
                    <div class="page-content">
                        {body_html}
                        {extra_content}
                    </div>
                    <div class="page-footer">
                        {footer_html}
                    </div>
                </div>
            </div>
    """
