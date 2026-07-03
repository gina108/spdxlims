from __future__ import annotations

import base64
import re
from datetime import datetime
from html import escape
from pathlib import Path

from PySide6.QtGui import QImage
from reportlab.graphics import renderSVG
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm

from spdxlims.i18n import tr

ResultRow = tuple[str, float, str] | tuple[str, float, str, str]

PAGE_FRAME_HEIGHT_MM = 289.0
PAGE_CONTENT_WIDTH_MM = 202.0
ESTIMATED_HEADER_HEIGHT_MM = 90.0
RESULT_ROW_UNIT_HEIGHT_MM = 5.6
FOOTER_SAFETY_GAP_MM = 8.0
GENERAL_COMMENTS_RESERVE_MM = 14.0
MIN_ROW_PAGE_LIMIT = 18.0
# The reference column is ~25% of the content width versus ~44% for the test
# name column (which `_estimated_line_units` defaults to at 48 chars/line), so a
# reference range wraps after roughly 27 characters.
REFERENCE_CHARS_PER_LINE = 27


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
    report_sex_format = str(preview.get("report_sex_format") or "short")
    report_date_format = str(preview.get("report_date_format") or "auto")
    show_doctor = bool(preview.get("report_show_doctor", True))
    show_client = bool(preview.get("report_show_client", True))
    show_sex = bool(preview.get("report_show_sex", True))
    show_age = bool(preview.get("report_show_age", True))
    show_dob = bool(preview.get("report_show_dob", True))
    show_ordered_at = bool(preview.get("report_show_ordered_at", True))
    show_reported_at = bool(preview.get("report_show_reported_at", True))
    doctor_col = str(preview.get("report_doctor_col") or "left")
    client_col = str(preview.get("report_client_col") or "left")
    sex_col = str(preview.get("report_sex_col") or "left")
    age_col = str(preview.get("report_age_col") or "right")
    dob_col = str(preview.get("report_dob_col") or "right")
    ordered_at_col = str(preview.get("report_ordered_at_col") or "right")
    reported_at_col = str(preview.get("report_reported_at_col") or "right")
    patient_sex = escape(_format_patient_sex(str(preview.get("patient_sex") or ""), report_sex_format))
    patient_dob_raw = str(preview.get("patient_dob") or "")
    patient_age_value_raw = preview.get("patient_age_value")
    patient_age_unit_raw = str(preview.get("patient_age_unit") or "")
    patient_dob = escape(_format_date(patient_dob_raw))
    doctor_name = escape(str(preview.get("doctor_name") or ""))
    client_name = escape(str(preview.get("client_name") or ""))
    ordered_at_raw = str(preview.get("ordered_at") or "")
    reported_at_raw = str(preview.get("reported_at") or "")
    ordered_at = escape(_format_report_datetime(ordered_at_raw, report_date_format))
    reported_at = escape(_format_report_datetime(reported_at_raw, report_date_format))
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
    report_font_family = _report_font_family(preview.get("report_font_family"))
    report_font_size = _bounded_int(preview.get("report_font_size"), 8, 18, 12)
    report_font_weight = "700" if bool(preview.get("report_font_bold")) else "400"
    abnormal_result_rule = ".results-body tr.abnormal-result td { font-weight: 700 !important; }" if bool(preview.get("report_abnormal_bold")) else ""
    subheading_font_family = _report_font_family(preview.get("report_subheading_font_family"))
    subheading_font_size = _bounded_int(preview.get("report_subheading_font_size"), 8, 18, 13)
    subheading_font_weight = "700" if bool(preview.get("report_subheading_font_bold", True)) else "400"
    footer_gap_mm = _bounded_int(preview.get("report_footer_gap_mm"), 0, 60, int(FOOTER_SAFETY_GAP_MM))

    rows: list[ResultRow] = []
    active_panel_group = ""
    for item in list(preview.get("items") or []):
        item_type = str(item.get("item_type") or "test")
        source_label = str(item.get("source_label") or "").strip()
        raw_test_name = str(item.get("test_name") or "")
        if item_type == "heading":
            raw_test_name = _normalize_panel_heading(raw_test_name)
            if not source_label:
                active_panel_group = raw_test_name.strip()
        if source_label:
            panel_group = active_panel_group or source_label
        elif item_type == "panel_meta":
            panel_group = active_panel_group
            active_panel_group = ""
        elif item_type == "heading":
            panel_group = active_panel_group
        else:
            panel_group = ""
        test_name = escape(raw_test_name)
        result_value = escape(_format_numeric_display(str(item.get("result_value") or "")))
        unit = escape(str(item.get("unit") or ""))
        lower_value = escape(_format_numeric_display(str(item.get("lower_value") or "")))
        upper_value = escape(_format_numeric_display(str(item.get("upper_value") or "")))
        reference_text = escape(str(item.get("reference_text") or "")).replace("\n", "<br>")
        raw_flag = str(item.get("flag") or "")
        flag = escape(_format_flag(raw_flag, flag_display_mode))
        row_class = ' class="abnormal-result"' if _is_abnormal_flag(raw_flag) else ""
        comments = escape(str(item.get("comments") or ""))
        range_text = " - ".join(part for part in [lower_value, upper_value] if part)
        if reference_text and not range_text:
            range_text = reference_text
        elif reference_text:
            range_text = f"{range_text} / {reference_text}"
        if item_type == "heading":
            row_html = f'<tr><td colspan="5" class="section">{test_name}</td></tr>'
            rows.append((row_html, 1.2, "heading", panel_group))
            continue
        if item_type == "comment":
            comment_value = comments or result_value
            if not comment_value:
                continue
            row_html = f'<tr><td colspan="5" class="comment"><strong>{test_name}</strong><br>{comment_value}</td></tr>'
            rows.append((row_html, 1.4 + _estimated_line_units(test_name + " " + comment_value), "comment", panel_group))
            continue
        if item_type == "panel_meta":
            meta_value = comments or result_value
            row_html = f'<tr><td colspan="5" class="panel-meta">{meta_value}</td></tr>'
            rows.append((row_html, 0.8 + _estimated_line_units(meta_value, chars_per_line=110), "panel_meta", panel_group))
            continue
        if str(item.get("result_kind") or "") == "image":
            images = list(item.get("images") or [])
            rows.append((
                f'<tr><td colspan="5" class="image-test-name"><strong>{test_name}</strong></td></tr>',
                1.0 + _estimated_line_units(raw_test_name),
                "test",
                panel_group,
            ))
            if not images:
                rows.append((
                    f'<tr><td colspan="5" class="subcomment">{escape(tr("No images"))}</td></tr>',
                    0.8,
                    "subcomment",
                    panel_group,
                ))
            for image in images:
                data = str(image.get("data") or "")
                if not data:
                    continue
                mime = escape(str(image.get("mime_type") or "image/png"), quote=True)
                caption = escape(str(image.get("caption") or ""))
                caption_html = f'<div class="image-caption">{caption}</div>' if caption else ""
                rows.append((
                    f'<tr><td colspan="5" class="result-image-cell">'
                    f'<img class="result-image" src="data:{mime};base64,{data}" style="width:62%; height:auto;">'
                    f'{caption_html}'
                    "</td></tr>",
                    17.0 + _estimated_line_units(caption),
                    "test",
                    panel_group,
                ))
            if comments:
                rows.append((f'<tr><td colspan="5" class="subcomment">{comments}</td></tr>', 0.8 + _estimated_line_units(comments), "subcomment", panel_group))
            continue
        row_html = (
            f"<tr{row_class}>"
            f"<td>{test_name}</td>"
            f"<td>{flag}</td>"
            f"<td>{result_value}</td>"
            f"<td>{unit}</td>"
            f"<td>{range_text}</td>"
            "</tr>"
        )
        row_text_units = max(
            _estimated_line_units(test_name),
            _estimated_line_units(range_text, chars_per_line=REFERENCE_CHARS_PER_LINE),
        )
        rows.append((row_html, 1.0 + row_text_units, "test", panel_group))
        if comments:
            rows.append((f'<tr><td colspan="5" class="subcomment">{comments}</td></tr>', 0.8 + _estimated_line_units(comments), "subcomment", panel_group))

    for section in outsourced_sections:
        panel_label = escape(_normalize_panel_heading(str(section.get("panel_label") or "")))
        section_rows: list[tuple[str, str]] = []
        for row in list(section.get("rows") or []):
            raw_values = [str(row.get(f"col_{index}") or "") for index in range(1, 6)]
            if not any(raw_values):
                continue
            # Column 2 is the flag (bandera); render it in the style chosen in
            # settings (arrows / asterisks / text), same as the entered rows.
            raw_flag = raw_values[1]
            display_values = list(raw_values)
            display_values[1] = _format_flag(raw_flag, flag_display_mode)
            values = [escape(value) for value in display_values]
            row_class = ' class="abnormal-result"' if _is_abnormal_flag(raw_flag) else ""
            section_rows.append(
                (
                    f"<tr{row_class}>"
                    f"<td>{values[0]}</td>"
                    f"<td>{values[1]}</td>"
                    f"<td>{values[2]}</td>"
                    f"<td>{values[3]}</td>"
                    f"<td>{values[4]}</td>"
                    "</tr>",
                    " ".join(value.strip() for value in raw_values),
                )
            )
        if not section_rows:
            continue
        rows.append((
            f'<tr><td colspan="5" class="section outsourced-section">{panel_label or escape(tr("Outsourced Panel"))}</td></tr>',
            1.2,
            "heading",
            panel_label,
        ))
        for section_row, section_text in section_rows:
            rows.append((section_row, 1.0 + _estimated_line_units(section_text), "outsourced", panel_label))

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
    _left_rows = f'<tr><td class="label">{escape(tr("Patient"))}:</td><td class="value">{patient_name}</td></tr>'
    _right_rows = f'<tr><td class="label">{escape(tr("Folio"))}:</td><td class="value highlight">{folio_value}</td></tr>'
    if show_doctor:
        _row = f'<tr><td class="label">{escape(tr("Doctor"))}:</td><td class="value">{doctor_name}</td></tr>'
        if doctor_col == "right":
            _right_rows += _row
        else:
            _left_rows += _row
    if show_client:
        _row = f'<tr><td class="label">{escape(tr("Origin"))}:</td><td class="value">{origin_value}</td></tr>'
        if client_col == "right":
            _right_rows += _row
        else:
            _left_rows += _row
    if show_sex:
        _row = f'<tr><td class="label">{escape(tr("Sex"))}:</td><td class="value">{patient_sex}</td></tr>'
        if sex_col == "right":
            _right_rows += _row
        else:
            _left_rows += _row
    if show_age:
        _row = f'<tr><td class="label">{escape(tr("Age"))}:</td><td class="value">{patient_age}</td></tr>'
        if age_col == "left":
            _left_rows += _row
        else:
            _right_rows += _row
    if show_dob:
        _row = f'<tr><td class="label">{escape(tr("DOB"))}:</td><td class="value">{patient_dob}</td></tr>'
        if dob_col == "left":
            _left_rows += _row
        else:
            _right_rows += _row
    if show_ordered_at:
        _row = f'<tr><td class="label">{escape(tr("Appointment Date"))}:</td><td class="value">{ordered_at}</td></tr>'
        if ordered_at_col == "left":
            _left_rows += _row
        else:
            _right_rows += _row
    if show_reported_at:
        _row = f'<tr><td class="label">{escape(tr("Print Date"))}:</td><td class="value">{reported_at or printed_at}</td></tr>'
        if reported_at_col == "left":
            _left_rows += _row
        else:
            _right_rows += _row
    info_grid_html = f"""
            <table class="info-grid" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                    <td width="44.5%">
                        <table class="info-block" width="100%" cellspacing="0" cellpadding="0">
                            {_left_rows}
                        </table>
                    </td>
                    <td width="37.5%">
                        <table class="info-block" width="100%" cellspacing="0" cellpadding="0">
                            {_right_rows}
                        </table>
                    </td>
                    <td class="qr-cell" width="18%">{qr_html}</td>
                </tr>
            </table>
    """
    page_footer_html = f'<div class="footer-banner">{footer_image}</div>' if footer_image else ""
    row_page_limit = _row_page_limit_for_footer(
        preview.get("footer_signature_image_path"),
        has_footer=bool(footer_image),
        has_general_comments=bool(general_comments),
        footer_gap_mm=footer_gap_mm,
        row_font_size=report_font_size,
    )
    paged_row_groups = _paginate_result_rows(rows, row_page_limit)
    paged_row_groups = _rebalance_paged_row_groups(paged_row_groups, row_page_limit)
    if not paged_row_groups:
        paged_row_groups = [[]]
    rendered_pages: list[str] = []
    total_pages = len(paged_row_groups)
    for index, page_rows in enumerate(paged_row_groups):
        page_header_html = f"""
        <div class="header-shell">
            {header_image and f'<table class="banner-table" width="100%" cellspacing="0" cellpadding="0"><tr><td>{header_image}</td></tr></table>' or top_summary}
            {info_grid_html}
            {_render_results_header(page_number=index + 1, total_pages=total_pages)}
        </div>
    """
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
        body {{ font-family: {report_font_family}; color: #1f2430; font-size: 12px; line-height: 1.35; }}
        .page {{ width: 100%; margin: 0; padding: 0; box-sizing: border-box; }}
        .report-page {{ width: 100%; box-sizing: border-box; page-break-before: auto; break-before: auto; page-break-inside: avoid; break-inside: avoid; }}
        .report-page-break {{ page-break-after: always; break-after: page; }}
        .page-frame {{ width: 100%; min-height: 289mm; height: 289mm; display: flex; flex-direction: column; box-sizing: border-box; }}
        .page-header {{ width: 100%; flex: 0 0 auto; }}
        .page-content {{ width: 100%; flex: 1 1 auto; min-height: 0; overflow: hidden; padding-bottom: {footer_gap_mm}mm; box-sizing: border-box; }}
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
        .results-header col.test-col, .results-body col.test-col {{ width: 44%; }}
        .results-header col.flag-col, .results-body col.flag-col {{ width: 5%; }}
        .results-header col.result-col, .results-body col.result-col {{ width: 16%; }}
        .results-header col.unit-col, .results-body col.unit-col {{ width: 10%; }}
        .results-header col.reference-col, .results-body col.reference-col {{ width: 25%; }}
        .results-header .results-title th {{ background: #d9d9d9; color: #20242b; text-align: center; font-size: 15px; font-weight: 700; padding: 7px 10px; border-bottom: 0; position: relative; }}
        .results-title-text {{ display: block; text-align: center; }}
        .results-page-number {{ position: absolute; right: 10px; top: 50%; transform: translateY(-50%); font-size: 10px; font-weight: 600; color: #4d5662; }}
        .results-header th {{ background: #e1e5ea; text-align: left; padding: 6px 8px; color: #2c323a; border-bottom: 1px solid #c8d0da; font-size: 13px; line-height: 1.1; }}
        .results-body td {{ padding: 4px 8px; border-bottom: 1px solid #dde3ea; font-size: {report_font_size}px; font-weight: {report_font_weight}; line-height: 1.1; vertical-align: top; word-wrap: break-word; }}
        .results-header th:nth-child(1), .results-body td:nth-child(1) {{ padding-right: 2px; }}
        .results-header th:nth-child(2) {{ text-align: right; padding-left: 0; padding-right: 1px; }}
        .results-body td:nth-child(2) {{ text-align: right; padding-left: 0; padding-right: 3px; white-space: nowrap; word-wrap: normal; overflow-wrap: normal; }}
        .results-header th:nth-child(3) {{ padding-right: 2px; }}
        .results-body td:nth-child(3) {{ padding-right: 2px; }}
        .results-header th:nth-child(4) {{ padding-left: 2px; padding-right: 4px; }}
        .results-body td:nth-child(4) {{ padding-left: 2px; padding-right: 4px; white-space: nowrap; word-wrap: normal; overflow-wrap: normal; }}
        .results-header th:nth-child(5) {{ padding-left: 2px; }}
        .results-body td:nth-child(5) {{ padding-left: 2px; }}
        .results-body tr {{ page-break-inside: avoid; break-inside: avoid; }}
        {abnormal_result_rule}
        .results-body td.section {{ background: #eef1f5; font-family: {subheading_font_family} !important; font-weight: {subheading_font_weight} !important; color: #223145; font-size: {subheading_font_size}px !important; line-height: 1.1; }}
        .comment {{ background: #f7f9fc; color: #314153; font-size: 13px; line-height: 1.1; }}
        .panel-meta {{ color: #4e5e72; font-size: 9px !important; line-height: 1.05 !important; font-style: italic; padding-top: 3px !important; padding-bottom: 3px !important; }}
        .subcomment {{ color: #4e5e72; font-size: 9px; line-height: 1.05; }}
        .results-body td.image-test-name {{ background: #eef1f5; font-family: {subheading_font_family} !important; font-weight: {subheading_font_weight} !important; color: #223145; font-size: {subheading_font_size}px !important; line-height: 1.1; }}
        .results-body td.result-image-cell {{ text-align: center; padding: 8px; }}
        .result-image {{ display: block; margin: 0 auto; width: 62%; max-width: 62%; height: auto; }}
        .image-caption {{ margin-top: 4px; font-size: 10px; color: #4e5e72; text-align: center; line-height: 1.2; }}
        .footer {{ margin-top: 18px; font-size: 10px; color: #4d5b6a; }}
        .outsourced-title {{ margin-top: 16px; }}
        .footer-banner {{ width: 100%; margin-top: 4px; }}
        .footer-image {{ display: block; width: 100%; max-width: none; max-height: none; height: auto; }}
        .director {{ margin-top: 12px; font-size: 10px; }}
        @media screen {{
            html, body {{ background: #eef2f6; }}
            body {{ padding: 12px 0; }}
            .page {{ width: 210mm; margin: 0 auto; }}
            .report-page {{
                width: 210mm;
                margin: 0 auto 14mm;
                padding: 4mm;
                background: #ffffff;
                box-sizing: border-box;
                box-shadow: 0 2px 10px rgba(31, 36, 48, 0.12);
                overflow: hidden;
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
            .results-body {{
                width: 100% !important;
                min-width: 100% !important;
                max-width: 100% !important;
                box-sizing: border-box;
            }}
            .results-header,
            .results-body,
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


def _row_page_limit_for_footer(
    footer_path: object,
    *,
    has_footer: bool,
    has_general_comments: bool,
    footer_gap_mm: int | float = FOOTER_SAFETY_GAP_MM,
    row_font_size: int | float = 12,
) -> float:
    if not has_footer:
        return 34.0
    footer_height_mm = _rendered_image_height_mm(footer_path, PAGE_CONTENT_WIDTH_MM) or 24.0
    available_mm = PAGE_FRAME_HEIGHT_MM - ESTIMATED_HEADER_HEIGHT_MM - footer_height_mm - float(footer_gap_mm)
    if has_general_comments:
        available_mm -= GENERAL_COMMENTS_RESERVE_MM
    row_height_mm = RESULT_ROW_UNIT_HEIGHT_MM * max(0.75, float(row_font_size) / 12.0)
    return max(MIN_ROW_PAGE_LIMIT, available_mm / row_height_mm)


def _bounded_int(value: object, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def _report_font_family(raw_value: object) -> str:
    primary = str(raw_value or "Segoe UI").strip() or "Segoe UI"
    safe_primary = "".join(character for character in primary if character.isalnum() or character in {" ", "-", "_"}).strip()
    if not safe_primary:
        safe_primary = "Segoe UI"
    return f'"{escape(safe_primary, quote=True)}", Arial, sans-serif'


def _rendered_image_height_mm(raw_path: object, rendered_width_mm: float) -> float | None:
    path = _local_image_path(raw_path)
    if path is None:
        return None
    image = QImage(str(path))
    if image.isNull() or image.width() <= 0:
        return None
    return rendered_width_mm * image.height() / image.width()


def _local_image_path(raw_path: object) -> Path | None:
    if not raw_path:
        return None
    value = str(raw_path).strip()
    if not value or value.startswith("http://") or value.startswith("https://"):
        return None
    if value.startswith("file:///"):
        value = value.removeprefix("file:///")
    path = Path(value)
    return path if path.exists() else None


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


def _format_numeric_display(value: str) -> str:
    if not value:
        return value
    try:
        clean = value.replace(",", "")
        if "." in clean:
            int_str, dec_str = clean.split(".", 1)
            return f"{int(int_str):,}.{dec_str}"
        return f"{int(clean):,}"
    except (ValueError, OverflowError):
        return value


def _format_patient_sex(raw: str, fmt: str) -> str:
    normalized = raw.strip().upper()
    if fmt == "full":
        return {"M": "MASCULINO", "F": "FEMENINO", "O": "OTRO"}.get(normalized, raw)
    if fmt == "medium":
        return {"M": "MASC", "F": "FEM", "O": "OTRO"}.get(normalized, raw)
    return raw


def _format_report_datetime(value: str, date_format: str) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return value
    if date_format == "date_only":
        return parsed.strftime("%d/%m/%Y")
    if date_format == "with_time":
        return parsed.strftime("%d/%m/%Y %H:%M")
    if parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0:
        return parsed.strftime("%d/%m/%Y")
    return parsed.strftime("%d/%m/%Y %H:%M")


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


def _is_abnormal_flag(flag_value: str) -> bool:
    normalized = flag_value.strip().lower()
    if not normalized or normalized in {"none", "normal", "normalo"}:
        return False
    return normalized in {
        "abnormal",
        "anormal",
        "low",
        "bajo",
        "l",
        "↓",
        "down",
        "high",
        "alto",
        "h",
        "↑",
        "up",
    }


def _estimated_line_units(value: str, *, chars_per_line: int = 48) -> float:
    total_lines = 0
    for segment in re.split(r"<br\s*/?>", value or ""):
        compact = " ".join(segment.split())
        if not compact:
            total_lines += 1
            continue
        total_lines += max(1, (len(compact) + chars_per_line - 1) // chars_per_line)
    return max(0.0, (total_lines - 1) * 0.6)


def _paginate_result_rows(
    rows: list[ResultRow],
    page_limit: float,
    *,
    keep_panels_together: bool = True,
) -> list[list[ResultRow]]:
    return _paginate_result_row_groups(rows, page_limit)


def _paginate_result_row_groups(rows: list[ResultRow], page_limit: float) -> list[list[ResultRow]]:
    chunks = _panel_chunks(rows)
    pages: list[list[ResultRow]] = []
    current_page: list[ResultRow] = []
    current_units = 0.0
    for chunk in chunks:
        chunk_units = _page_row_units(chunk)
        if chunk_units <= page_limit:
            if current_page and current_units + chunk_units > page_limit:
                pages.append(current_page)
                current_page = []
                current_units = 0.0
            current_page.extend(chunk)
            current_units += chunk_units
            continue
        for row in chunk:
            row_units = _row_units(row)
            if current_page and current_units + row_units > page_limit:
                pages.append(current_page)
                current_page = []
                current_units = 0.0
            current_page.append(row)
            current_units += row_units
    if current_page:
        pages.append(current_page)
    return pages


def _panel_chunks(rows: list[ResultRow]) -> list[list[ResultRow]]:
    chunks: list[list[ResultRow]] = []
    current_chunk: list[ResultRow] = []
    current_panel = ""
    for row in rows:
        panel_group = _row_panel_group(row)
        if panel_group and panel_group == current_panel:
            current_chunk.append(row)
            continue
        if current_chunk:
            chunks.append(current_chunk)
        current_chunk = [row]
        current_panel = panel_group
    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def _row_html(row: ResultRow) -> str:
    return row[0]


def _row_units(row: ResultRow) -> float:
    return row[1]


def _row_kind(row: ResultRow) -> str:
    return row[2]


def _row_panel_group(row: ResultRow) -> str:
    return row[3] if len(row) > 3 else ""


def _page_row_units(rows: list[ResultRow]) -> float:
    return sum(_row_units(row) for row in rows)


def _rebalance_paged_row_groups(
    pages: list[list[ResultRow]],
    page_limit: float,
) -> list[list[ResultRow]]:
    balanced_pages = [list(page) for page in pages]
    if len(balanced_pages) < 2:
        return balanced_pages
    for index in range(len(balanced_pages) - 2, -1, -1):
        left_page = balanced_pages[index]
        right_page = balanced_pages[index + 1]
        if not left_page or not right_page:
            continue
        _stabilize_page_boundary(left_page, right_page, page_limit)
    return balanced_pages


def _stabilize_page_boundary(
    left_page: list[ResultRow],
    right_page: list[ResultRow],
    page_limit: float,
) -> None:
    if not left_page or not right_page:
        return
    if _row_kind(right_page[0]) == "panel_meta":
        _move_previous_row_with_panel_meta(left_page, right_page)
        return
    if _row_kind(left_page[-1]) != "heading":
        return
    left_units = _page_row_units(left_page)
    moved_rows = 0
    while right_page and _row_kind(right_page[0]) != "heading":
        next_row = right_page[0]
        if left_units + _row_units(next_row) > page_limit:
            break
        left_page.append(right_page.pop(0))
        left_units += _row_units(next_row)
        moved_rows += 1
    if moved_rows == 0:
        right_page.insert(0, left_page.pop())


def _move_previous_row_with_panel_meta(
    left_page: list[ResultRow],
    right_page: list[ResultRow],
) -> None:
    if not left_page or not right_page or _row_kind(right_page[0]) != "panel_meta":
        return
    meta_group = _row_panel_group(right_page[0])
    if _row_kind(left_page[-1]) == "heading":
        return
    if meta_group and _row_panel_group(left_page[-1]) and _row_panel_group(left_page[-1]) != meta_group:
        return
    right_page.insert(0, left_page.pop())


def _render_results_header(page_number: int | None = None, total_pages: int | None = None) -> str:
    page_number_html = ""
    if page_number is not None and total_pages is not None:
        page_number_text = tr("Page {page_number} of {total_pages}", page_number=page_number, total_pages=total_pages)
        page_number_html = f'<span class="results-page-number">{escape(page_number_text)}</span>'
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
                        <th colspan="5"><span class="results-title-text">{escape(tr("Results Sheet"))}</span>{page_number_html}</th>
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


def _render_results_body(rows: list[ResultRow]) -> str:
    rendered_rows = "".join(_row_html(row) for row in rows)
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
