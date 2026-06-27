from __future__ import annotations

import ast as _ast
import importlib
import json
import operator as _operator
from decimal import Decimal, InvalidOperation
import re
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QEventLoop, QMarginsF, QSizeF, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QTextDocument
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database, InstrumentResultMappingRecord, ResultEntryRecord, ResultWorkflowRecord
from spdxlims.deployment import DeploymentService
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.pages.instrument_status_panel import InstrumentStatusPanel
from spdxlims.portal.result_service import PortalResultService
from spdxlims.portal.settings import PortalStore
from spdxlims.report_export import build_pdf_export_path
from spdxlims.report_layout import build_report_html
from spdxlims.report_service import ReportService
from spdxlims.result_service import ResultService
from spdxlims.whatsapp_templates import default_whatsapp_templates, get_whatsapp_templates
from spdxlims.whatsapp_phone import normalize_whatsapp_phone

try:
    from PySide6.QtWebEngineCore import QWebEnginePage
except ImportError:  # pragma: no cover
    QWebEnginePage = None

_FORMULA_OPS: dict = {
    _ast.Add: _operator.add,
    _ast.Sub: _operator.sub,
    _ast.Mult: _operator.mul,
    _ast.Div: _operator.truediv,
    _ast.USub: _operator.neg,
    _ast.UAdd: _operator.pos,
}


def _safe_eval_formula(formula: str, x: float) -> float:
    """Evaluate a simple arithmetic formula with variable x.
    If the formula starts with an operator (e.g. *1000, /10, +5, -2) x is implied."""
    normalized = formula.strip()
    if normalized and normalized[0] in ("*", "/", "+", "-") and "x" not in normalized:
        normalized = "x " + normalized
    def _eval(node: _ast.AST) -> float:
        if isinstance(node, _ast.Expression):
            return _eval(node.body)
        if isinstance(node, _ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, _ast.Name) and node.id == "x":
            return x
        if isinstance(node, _ast.BinOp) and type(node.op) in _FORMULA_OPS:
            return _FORMULA_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, _ast.UnaryOp) and type(node.op) in _FORMULA_OPS:
            return _FORMULA_OPS[type(node.op)](_eval(node.operand))
        raise ValueError(f"Unsupported expression: {type(node).__name__}")
    return _eval(_ast.parse(normalized, mode="eval"))


class ReportPreviewDialog(QDialog):
    def __init__(
        self,
        preview: dict[str, object],
        html_renderer,
        *,
        can_approve: bool,
        approved: bool,
        header_options: list[tuple[str, str]],
        selected_header: str,
        footer_options: list[tuple[str, str]] | None = None,
        selected_footer: str = "",
        reset_fetcher: Callable[[], dict[str, object] | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._approved_clicked = False
        self._approved = approved
        self._can_approve = can_approve
        self._html_renderer = html_renderer
        self._preview = dict(preview)
        self._approved_preview: dict[str, object] | None = None
        self._preview_dirty = False
        self._was_reset = False
        self._reset_fetcher = reset_fetcher
        self._web_view_class: type[QWidget] | None | bool = False
        self.preview_widget: QWidget
        self._preview_html_setter: Callable[..., None] | None = None
        self._preview_uses_webengine = False
        self.setModal(True)
        self.resize(1020, 760)

        layout = QVBoxLayout(self)

        summary = QLabel(
            tr(
                "Order {order_number} report preview",
                order_number=str(preview.get("order_number") or ""),
            )
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        help_label = QLabel(tr("Preview and approve the report before sending it."))
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        image_row = QHBoxLayout()
        header_label = QLabel(tr("Header Image"))
        self.header_combo = QComboBox()
        self.header_combo.addItem(tr("No Header Image"), "")
        for label, value in header_options:
            self.header_combo.addItem(label, value)
        selected_index = self.header_combo.findData(selected_header)
        self.header_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        self.header_combo.currentIndexChanged.connect(self._header_changed)
        footer_label = QLabel(tr("Footer Image"))
        self.footer_combo = QComboBox()
        self.footer_combo.addItem(tr("No Footer Image"), "")
        for label, value in (footer_options or []):
            self.footer_combo.addItem(label, value)
        selected_footer_index = self.footer_combo.findData(selected_footer)
        self.footer_combo.setCurrentIndex(selected_footer_index if selected_footer_index >= 0 else 0)
        self.footer_combo.currentIndexChanged.connect(self._footer_changed)
        image_row.addWidget(header_label)
        image_row.addWidget(self.header_combo, 1)
        image_row.addSpacing(16)
        image_row.addWidget(footer_label)
        image_row.addWidget(self.footer_combo, 1)
        layout.addLayout(image_row)

        fields_row = QHBoxLayout()
        fields_row.addWidget(QLabel(tr("Header Fields")))
        _field_defs = [
            ("report_show_doctor", tr("Doctor")),
            ("report_show_client", tr("Origin")),
            ("report_show_sex", tr("Sex")),
            ("report_show_age", tr("Age")),
            ("report_show_dob", tr("DOB")),
            ("report_show_ordered_at", tr("Appt. Date")),
            ("report_show_reported_at", tr("Print Date")),
        ]
        self._header_field_checkboxes: dict[str, QCheckBox] = {}
        for key, label in _field_defs:
            cb = QCheckBox(label)
            cb.setChecked(bool(self._preview.get(key, True)))
            cb.stateChanged.connect(lambda _state, k=key, c=cb: self._header_field_changed(k, c))
            self._header_field_checkboxes[key] = cb
            fields_row.addWidget(cb)
        fields_row.addStretch(1)
        layout.addLayout(fields_row)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        close_button = QPushButton(tr("Close Preview"))
        close_button.clicked.connect(self.reject)
        button_row.addWidget(close_button)

        if reset_fetcher is not None:
            self.refresh_button = QPushButton(tr("Refresh from Server"))
            self.refresh_button.setToolTip(tr("Reload report from the latest patient data and test results, discarding any manual edits."))
            self.refresh_button.clicked.connect(self._refresh_from_server)
            button_row.addWidget(self.refresh_button)

        self.edit_button = QPushButton(tr("Edit Report"))
        self.edit_button.setEnabled(can_approve)
        self.edit_button.clicked.connect(self._edit_report)
        button_row.addWidget(self.edit_button)

        self.approve_button = QPushButton(tr("Approved") if approved else tr("Approve and Export PDF"))
        self.approve_button.setEnabled(can_approve and not approved)
        self.approve_button.clicked.connect(self._approve_and_export)
        button_row.addWidget(self.approve_button)

        layout.addLayout(button_row)

        self.preview_widget = self._build_preview_widget()
        self._set_preview_html(self._render_preview_html())
        layout.addWidget(self.preview_widget, 1)

    @property
    def approved_clicked(self) -> bool:
        return self._approved_clicked

    @property
    def selected_header(self) -> str:
        return str(self.header_combo.currentData() or "")

    @property
    def selected_footer(self) -> str:
        return str(self.footer_combo.currentData() or "")

    @property
    def approved_preview(self) -> dict[str, object] | None:
        return None if self._approved_preview is None else dict(self._approved_preview)

    @property
    def preview_changed(self) -> bool:
        return self._preview_dirty

    @property
    def was_reset(self) -> bool:
        return self._was_reset

    @property
    def current_preview(self) -> dict[str, object]:
        return dict(self._preview)

    def _refresh_from_server(self) -> None:
        if self._reset_fetcher is None:
            return
        fresh = self._reset_fetcher()
        if fresh is None:
            QMessageBox.warning(self, tr("Refresh Failed"), tr("Could not load the latest report data for this order."))
            return
        fresh["header_image_path"] = self.selected_header
        fresh["footer_signature_image_path"] = self.selected_footer
        for key, checkbox in self._header_field_checkboxes.items():
            fresh[key] = checkbox.isChecked()
        self._preview = dict(fresh)
        self._was_reset = True
        self._preview_dirty = True
        self._approved = False
        self.approve_button.setText(tr("Approve and Export PDF"))
        self.approve_button.setEnabled(self._can_approve)
        self._set_preview_html(self._render_preview_html())

    def _approve_and_export(self) -> None:
        self._approved_clicked = True
        self._approved_preview = dict(self._preview)
        self.accept()

    def _header_changed(self) -> None:
        self._preview["header_image_path"] = self.selected_header
        self._preview_dirty = True
        self._set_preview_html(self._render_preview_html())

    def _footer_changed(self) -> None:
        self._preview["footer_signature_image_path"] = self.selected_footer
        self._preview_dirty = True
        self._set_preview_html(self._render_preview_html())

    def _header_field_changed(self, key: str, checkbox: QCheckBox) -> None:
        self._preview[key] = checkbox.isChecked()
        self._preview_dirty = True
        self._set_preview_html(self._render_preview_html())

    def _edit_report(self) -> None:
        dialog = ReportEditorDialog(self._preview, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._preview = dialog.edited_preview
        self._preview["header_image_path"] = self.selected_header
        self._preview["footer_signature_image_path"] = self.selected_footer
        self._preview_dirty = True
        self._set_preview_html(self._render_preview_html())

    def _render_preview_html(self) -> str:
        return self._html_renderer(self._preview)

    def _build_preview_widget(self) -> QWidget:
        web_view_class = self._get_web_view_class()
        if web_view_class is not None:
            preview_widget = web_view_class()
            preview_widget.setStyleSheet("background:#ffffff; border:1px solid #c9d1dc;")
            self._configure_web_preview(preview_widget)
            self._preview_html_setter = preview_widget.setHtml
            self._preview_uses_webengine = True
            return preview_widget

        preview_widget = QTextEdit()
        preview_widget.setReadOnly(True)
        preview_widget.setStyleSheet("background:#ffffff; color:#111111; border:1px solid #c9d1dc;")
        self._preview_html_setter = preview_widget.setHtml
        self._preview_uses_webengine = False
        return preview_widget

    def _get_web_view_class(self) -> type[QWidget] | None:
        if self._web_view_class is not False:
            return self._web_view_class if self._web_view_class is not True else None
        try:
            module = importlib.import_module("PySide6.QtWebEngineWidgets")
        except ImportError:  # pragma: no cover
            self._web_view_class = True
            return None
        self._web_view_class = getattr(module, "QWebEngineView", None) or True
        return self._web_view_class if self._web_view_class is not True else None

    def _configure_web_preview(self, preview_widget: QWidget) -> None:
        settings = getattr(preview_widget, "settings", None)
        if not callable(settings):
            return
        preview_settings = settings()
        web_attribute = getattr(preview_settings, "WebAttribute", None)
        if web_attribute is None:
            return
        local_access = getattr(web_attribute, "LocalContentCanAccessFileUrls", None)
        remote_access = getattr(web_attribute, "LocalContentCanAccessRemoteUrls", None)
        if local_access is not None:
            preview_settings.setAttribute(local_access, True)
        if remote_access is not None:
            preview_settings.setAttribute(remote_access, True)

    def _set_preview_html(self, html: str) -> None:
        if self._preview_html_setter is None:
            return
        if self._preview_uses_webengine:
            self._preview_html_setter(html, QUrl.fromLocalFile(str(Path.cwd())))
            return
        self._preview_html_setter(html)


class ReportEditorDialog(QDialog):
    _FLAG_OPTIONS = (
        ("", "None"),
        ("none", "None"),
        ("low", "Low"),
        ("normal", "Normal"),
        ("high", "High"),
        ("abnormal", "Abnormal"),
    )
    _ROW_COLUMNS = (
        "item_type",
        "test_name",
        "flag",
        "result_value",
        "unit",
        "reference_text",
        "comments",
    )
    _ITEM_TYPE_COLORS: dict[str, tuple[str, str, str]] = {
        "test":    ("#A8B3C2", "#21272D", "#2E3640"),
        "heading": ("#C9A8FF", "#1E1242", "#7756BE"),
        "comment": ("#697789", "#20252B", "#252C34"),
    }

    def __init__(self, preview: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preview = self._clone_preview(preview)
        self.setModal(True)
        self.resize(1100, 820)
        self.setWindowTitle(tr("Edit Report"))

        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        help_label = QLabel(tr("Edit only the report rows before approving it. You can update test fields and remove full rows."))
        help_label.setWordWrap(True)
        top_row.addWidget(help_label, 1)
        top_row.addStretch(1)
        cancel_button = QPushButton(tr("Cancel"))
        cancel_button.clicked.connect(self.reject)
        top_row.addWidget(cancel_button)
        save_button = QPushButton(tr("Apply Changes"))
        save_button.clicked.connect(self._apply_and_close)
        top_row.addWidget(save_button)
        layout.addLayout(top_row)

        table_actions = QHBoxLayout()
        table_actions.addWidget(QLabel(tr("Report Rows")))
        table_actions.addStretch(1)

        add_row_button = QPushButton(tr("Fila en blanca"))
        add_row_button.clicked.connect(self._add_blank_row)
        table_actions.addWidget(add_row_button)

        remove_button = QPushButton(tr("Delete Selected Row"))
        remove_button.clicked.connect(self._remove_selected_row)
        table_actions.addWidget(remove_button)

        move_up_button = QPushButton(tr("Move Up"))
        move_up_button.clicked.connect(lambda: self._move_selected_row(-1))
        table_actions.addWidget(move_up_button)

        move_down_button = QPushButton(tr("Move Down"))
        move_down_button.clicked.connect(lambda: self._move_selected_row(1))
        table_actions.addWidget(move_down_button)
        layout.addLayout(table_actions)

        self.items_table = QTableWidget(0, len(self._ROW_COLUMNS))
        self.items_table.setHorizontalHeaderLabels(
            [
                tr("Item Type"),
                tr("Test"),
                tr("Flag"),
                tr("Result"),
                tr("Unit"),
                tr("Reference"),
                tr("Comments"),
            ]
        )
        self.items_table.setColumnWidth(0, 140)
        self.items_table.setColumnWidth(1, 170)
        self.items_table.setColumnWidth(2, 145)
        self.items_table.setColumnWidth(3, 100)
        self.items_table.setColumnWidth(4, 90)
        self.items_table.setColumnWidth(5, 120)
        self.items_table.horizontalHeader().setStretchLastSection(True)
        self.items_table.verticalHeader().setDefaultSectionSize(44)
        layout.addWidget(self.items_table, 1)

        self._populate_items_table()

    @property
    def edited_preview(self) -> dict[str, object]:
        return self._clone_preview(self._preview)

    def _populate_items_table(self) -> None:
        items = list(self._preview.get("items") or [])
        self.items_table.setRowCount(len(items))
        for row_index, item in enumerate(items):
            item_type_combo = self._make_type_combo()
            current_type = str(item.get("item_type") or "test")
            current_index = item_type_combo.findData(current_type)
            item_type_combo.setCurrentIndex(current_index if current_index >= 0 else 0)
            self._style_type_combo(item_type_combo, current_type)
            item_type_combo.currentIndexChanged.connect(
                lambda _idx, c=item_type_combo: self._style_type_combo(c, str(c.currentData() or "test"))
            )
            self.items_table.setCellWidget(row_index, 0, item_type_combo)
            self._set_table_text(row_index, 1, str(item.get("test_name") or ""), metadata=dict(item))
            self._set_flag_combo(row_index, str(item.get("flag") or ""))
            self._set_table_text(row_index, 3, str(item.get("result_value") or ""))
            self._set_table_text(row_index, 4, str(item.get("unit") or ""))
            self._set_table_text(row_index, 5, self._display_reference_text(item))
            self._set_table_text(row_index, 6, str(item.get("comments") or ""))

    def _set_table_text(self, row: int, column: int, value: str, metadata: dict[str, object] | None = None) -> None:
        item = QTableWidgetItem(value)
        if metadata is not None:
            item.setData(Qt.UserRole, metadata)
        self.items_table.setItem(row, column, item)

    def _remove_selected_row(self) -> None:
        row = self.items_table.currentRow()
        if row < 0:
            return
        self.items_table.removeRow(row)

    def _add_blank_row(self) -> None:
        row = self.items_table.rowCount()
        self.items_table.insertRow(row)
        item_type_combo = self._make_type_combo()
        self._style_type_combo(item_type_combo, "test")
        item_type_combo.currentIndexChanged.connect(
            lambda _idx, c=item_type_combo: self._style_type_combo(c, str(c.currentData() or "test"))
        )
        self.items_table.setCellWidget(row, 0, item_type_combo)
        self._set_table_text(row, 1, "", metadata={})
        self._set_flag_combo(row, "")
        self._set_table_text(row, 3, "")
        self._set_table_text(row, 4, "")
        self._set_table_text(row, 5, "")
        self._set_table_text(row, 6, "")
        self.items_table.setCurrentCell(row, 1)

    def _move_selected_row(self, offset: int) -> None:
        row = self.items_table.currentRow()
        if row < 0:
            return
        new_row = row + offset
        if new_row < 0 or new_row >= self.items_table.rowCount():
            return
        row_data = self._take_row_data(row)
        other_data = self._take_row_data(new_row)
        self._restore_row_data(row, other_data)
        self._restore_row_data(new_row, row_data)
        self.items_table.setCurrentCell(new_row, 1)

    def _take_row_data(self, row: int) -> dict[str, object]:
        combo = self.items_table.cellWidget(row, 0)
        item_type = combo.currentData() if isinstance(combo, QComboBox) else "test"
        values = {
            "item_type": str(item_type or "test"),
            "test_name": self._item_text(row, 1),
            "flag": self._flag_value(row),
            "result_value": self._item_text(row, 3),
            "unit": self._item_text(row, 4),
            "reference_text": self._item_text(row, 5),
            "comments": self._item_text(row, 6),
            "__source_item": self._item_metadata(row, 1),
        }
        return values

    def _restore_row_data(self, row: int, row_data: dict[str, object]) -> None:
        combo = self.items_table.cellWidget(row, 0)
        if isinstance(combo, QComboBox):
            item_type = str(row_data.get("item_type") or "test")
            index = combo.findData(item_type)
            combo.setCurrentIndex(index if index >= 0 else 0)
            self._style_type_combo(combo, item_type)
        self._set_table_text(row, 1, str(row_data.get("test_name") or ""), metadata=dict(row_data.get("__source_item") or {}))
        self._set_flag_combo(row, str(row_data.get("flag") or ""))
        self._set_table_text(row, 3, str(row_data.get("result_value") or ""))
        self._set_table_text(row, 4, str(row_data.get("unit") or ""))
        self._set_table_text(row, 5, str(row_data.get("reference_text") or ""))
        self._set_table_text(row, 6, str(row_data.get("comments") or ""))

    def _item_text(self, row: int, column: int) -> str:
        item = self.items_table.item(row, column)
        return item.text().strip() if item is not None else ""

    def _set_flag_combo(self, row: int, value: str) -> None:
        combo = QComboBox()
        combo.setMinimumWidth(120)
        for flag_value, label in self._FLAG_OPTIONS:
            combo.addItem(tr(label), flag_value)
        normalized = (value or "").strip().lower()
        index = combo.findData(normalized)
        combo.setCurrentIndex(index if index >= 0 else 0)
        self.items_table.setCellWidget(row, 2, combo)

    def _make_type_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.addItem(tr("Test"), "test")
        combo.addItem(tr("Heading"), "heading")
        combo.addItem(tr("Comment"), "comment")
        return combo

    @staticmethod
    def _style_combo(combo: QComboBox, color: str, bg: str, border: str) -> None:
        combo.setStyleSheet(f"""
            QComboBox {{
                color: {color};
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 4px;
                margin: 4px 6px;
                padding: 2px 22px 2px 8px;
                font-weight: 600;
            }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {color};
                margin-right: 6px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #20252B;
                border: 1px solid #2E3640;
                color: #F0F4FF;
                selection-background-color: #341F5C;
                outline: 0;
            }}
        """)

    @classmethod
    def _style_type_combo(cls, combo: QComboBox, value: str) -> None:
        color, bg, border = cls._ITEM_TYPE_COLORS.get(value, cls._ITEM_TYPE_COLORS["test"])
        cls._style_combo(combo, color, bg, border)

    def _flag_value(self, row: int) -> str:
        combo = self.items_table.cellWidget(row, 2)
        if isinstance(combo, QComboBox):
            return str(combo.currentData() or "")
        return self._item_text(row, 2)

    def _item_metadata(self, row: int, column: int) -> dict[str, object]:
        item = self.items_table.item(row, column)
        if item is None:
            return {}
        metadata = item.data(Qt.UserRole)
        return dict(metadata) if isinstance(metadata, dict) else {}

    def _apply_and_close(self) -> None:
        edited_items: list[dict[str, object]] = []
        for row_index in range(self.items_table.rowCount()):
            combo = self.items_table.cellWidget(row_index, 0)
            item_type = str(combo.currentData() or "test") if isinstance(combo, QComboBox) else "test"
            source_item = self._item_metadata(row_index, 1)
            item = {
                **source_item,
                "item_type": item_type,
                "test_name": self._item_text(row_index, 1),
                "flag": self._flag_value(row_index),
                "result_value": self._item_text(row_index, 3),
                "unit": self._item_text(row_index, 4),
                "comments": self._item_text(row_index, 6),
                "sort_order": len(edited_items),
            }
            self._apply_edited_reference(item, self._item_text(row_index, 5), source_item)
            if item_type in {"heading", "comment"}:
                item["order_test_id"] = None
                item["flag"] = ""
                item["result_value"] = "" if item_type == "heading" else item["result_value"]
                item["unit"] = ""
                item["reference_text"] = ""
                item["lower_value"] = ""
                item["upper_value"] = ""
            edited_items.append(item)

        reportable_items = [item for item in edited_items if item.get("item_type") != "heading"]
        if not reportable_items:
            QMessageBox.warning(self, tr("Missing Selection"), tr("No report could be generated for this order."))
            return

        self._preview["items"] = edited_items
        self.accept()

    @staticmethod
    def _display_reference_text(item: dict[str, object]) -> str:
        reference_text = str(item.get("reference_text") or "").strip()
        lower_value = str(item.get("lower_value") or "").strip()
        upper_value = str(item.get("upper_value") or "").strip()
        range_text = " - ".join(part for part in (lower_value, upper_value) if part)
        if reference_text and range_text:
            return f"{range_text} / {reference_text}"
        return reference_text or range_text

    @classmethod
    def _apply_edited_reference(cls, item: dict[str, object], edited_text: str, source_item: dict[str, object]) -> None:
        edited_text = edited_text.strip()
        original_reference = str(source_item.get("reference_text") or "").strip()
        if edited_text == cls._display_reference_text(source_item):
            item["reference_text"] = original_reference
            return
        lower_value, upper_value = cls._parse_reference_range_text(edited_text)
        if lower_value is not None or upper_value is not None:
            item["lower_value"] = lower_value or ""
            item["upper_value"] = upper_value or ""
            item["reference_text"] = ""
            return
        item["lower_value"] = ""
        item["upper_value"] = ""
        item["reference_text"] = edited_text

    @staticmethod
    def _parse_reference_range_text(value: str) -> tuple[str | None, str | None]:
        normalized = value.strip()
        if not normalized:
            return None, None
        decimal_pattern = r"[+-]?\d+(?:\.\d+)?"
        match = re.fullmatch(rf"\s*({decimal_pattern})\s*(?:-|–|—|a|to)\s*({decimal_pattern})\s*", normalized, flags=re.IGNORECASE)
        if match:
            return match.group(1), match.group(2)
        match = re.fullmatch(rf"\s*(?:<=|≤|<)\s*({decimal_pattern})\s*", normalized)
        if match:
            return None, match.group(1)
        match = re.fullmatch(rf"\s*(?:>=|≥|>)\s*({decimal_pattern})\s*", normalized)
        if match:
            return match.group(1), None
        return None, None

    @staticmethod
    def _clone_preview(preview: dict[str, object]) -> dict[str, object]:
        cloned = dict(preview)
        cloned["items"] = [dict(item) for item in list(preview.get("items") or [])]
        return cloned


class ResultsPage(DataAwarePage):
    APPROVALS_KEY = "results_report_approvals"
    ORDER_HEADERS_KEY = "results_report_headers"
    ORDER_FOOTERS_KEY = "results_report_footers"
    WHATSAPP_SENT_KEY = "results_whatsapp_sent"
    LINKED_INSTRUMENT_CAPTURES_KEY = "results_linked_instrument_captures"

    def __init__(
        self,
        database: Database,
        deployment_service: DeploymentService,
        *,
        data_dir: Path | None = None,
        show_instruments: bool = False,
        show_review: bool = True,
    ) -> None:
        super().__init__()
        self.database = database
        self.deployment_service = deployment_service
        self.result_service = ResultService(database, deployment_service)
        self.report_service = ReportService(database, deployment_service)
        self._portal_results = PortalResultService(PortalStore(data_dir or (Path.cwd() / "data")))
        self.show_instruments = show_instruments
        self.show_review = show_review
        self.current_orders: list[ResultWorkflowRecord] = []
        self.previewed_orders: set[int] = set()
        self.instrument_captures: list[dict[str, object]] = []
        self._instrument_captures_cache: dict[str, dict[str, object]] = self.database.load_instrument_captures_cache()
        self.instrument_result: dict[str, object] | None = None
        self.instrument_order_entries: list[ResultEntryRecord] = []
        self.engine_url = "http://127.0.0.1:9088"
        # {profile_id: {NORM_CODE: {qualifier_prefix: display_label}}}
        self._profile_semiquant_maps: dict[str, dict[str, dict[str, str]]] = {}

        if self.show_instruments:
            outer = QHBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(14)
            left_col = QVBoxLayout()
            left_col.setContentsMargins(0, 0, 0, 0)
            left_col.setSpacing(14)
            left_col.addWidget(self._build_instrument_group())
            if self.show_review:
                left_col.addWidget(self._build_queue_group())
            outer.addLayout(left_col, 1)
            self._status_panel = InstrumentStatusPanel()
            self._status_panel.log_message.connect(self.instrument_status_label.setText)
            outer.addWidget(self._status_panel)
        else:
            root = QVBoxLayout(self)
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(14)
            if self.show_review:
                root.addWidget(self._build_queue_group())

        if self.show_instruments:
            from PySide6.QtCore import QTimer
            self._auto_import_timer = QTimer(self)
            self._auto_import_timer.setInterval(30000)
            self._auto_import_timer.timeout.connect(self._auto_import_pending)
            self._auto_import_timer.start()

        self.retranslate_ui()
        self.refresh_on_show()

    def _build_instrument_group(self) -> QWidget:
        self.instrument_group = QGroupBox()
        layout = QVBoxLayout(self.instrument_group)

        self.instrument_summary_label = QLabel()
        self.instrument_summary_label.setWordWrap(True)
        layout.addWidget(self.instrument_summary_label)

        controls = QHBoxLayout()
        self.instrument_profile_input = QComboBox()
        self.instrument_profile_input.setMinimumWidth(180)
        self.instrument_profile_input.currentIndexChanged.connect(self.refresh_instrument_captures)
        self.refresh_instrument_button = QPushButton()
        self.refresh_instrument_button.clicked.connect(self.refresh_instrument_captures)
        self.reimport_recent_button = QPushButton()
        self.reimport_recent_button.clicked.connect(self.reimport_recent_captures)
        self.replay_instrument_button = QPushButton()
        self.replay_instrument_button.clicked.connect(self.preview_instrument_capture)
        self.instrument_order_combo = QComboBox()
        self.instrument_order_combo.setMinimumWidth(280)
        self.link_instrument_button = QPushButton()
        self.link_instrument_button.clicked.connect(self.link_instrument_capture_to_order)
        self.hide_empty_instrument_captures_checkbox = QCheckBox()
        self.hide_empty_instrument_captures_checkbox.setChecked(True)
        self.hide_empty_instrument_captures_checkbox.stateChanged.connect(lambda _state: self.refresh_instrument_captures())
        controls.addWidget(QLabel(tr("Profile")))
        controls.addWidget(self.instrument_profile_input)
        controls.addWidget(self.hide_empty_instrument_captures_checkbox)
        controls.addWidget(self.refresh_instrument_button)
        controls.addWidget(self.reimport_recent_button)
        controls.addSpacing(12)
        controls.addWidget(QLabel(tr("Order")))
        controls.addWidget(self.instrument_order_combo, 1)
        controls.addWidget(self.link_instrument_button)
        layout.addLayout(controls)

        self.instrument_captures_table = QTableWidget(0, 6)
        self.instrument_captures_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.instrument_captures_table.setSelectionMode(QTableWidget.SingleSelection)
        self.instrument_captures_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.instrument_captures_table.verticalHeader().setDefaultSectionSize(38)
        self.instrument_captures_table.itemSelectionChanged.connect(self._instrument_capture_selection_changed)
        capture_header = self.instrument_captures_table.horizontalHeader()
        capture_header.setSectionResizeMode(0, QHeaderView.Fixed)
        capture_header.setSectionResizeMode(1, QHeaderView.Fixed)
        capture_header.setSectionResizeMode(2, QHeaderView.Stretch)
        capture_header.setSectionResizeMode(3, QHeaderView.Fixed)
        capture_header.setSectionResizeMode(4, QHeaderView.Fixed)
        capture_header.setSectionResizeMode(5, QHeaderView.Fixed)
        layout.addWidget(self.instrument_captures_table)

        self.instrument_observations_table = QTableWidget(0, 5)
        self.instrument_observations_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.instrument_observations_table.setSelectionMode(QTableWidget.SingleSelection)
        self.instrument_observations_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.instrument_observations_table.verticalHeader().setDefaultSectionSize(34)
        observation_header = self.instrument_observations_table.horizontalHeader()
        observation_header.setSectionResizeMode(0, QHeaderView.Fixed)
        observation_header.setSectionResizeMode(1, QHeaderView.Stretch)
        observation_header.setSectionResizeMode(2, QHeaderView.Fixed)
        observation_header.setSectionResizeMode(3, QHeaderView.Fixed)
        observation_header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.instrument_observations_table.itemSelectionChanged.connect(
            self._instrument_observation_selection_changed
        )
        layout.addWidget(self.instrument_observations_table)

        self.instrument_order_combo.currentIndexChanged.connect(self._refresh_instrument_target_test_choices)
        self.instrument_target_test_combo = QComboBox()
        self.instrument_target_test_combo.setMinimumWidth(420)
        self.save_instrument_mapping_button = QPushButton()
        self.save_instrument_mapping_button.clicked.connect(self.save_selected_instrument_mapping)
        self.remove_instrument_mapping_button = QPushButton()
        self.remove_instrument_mapping_button.clicked.connect(self.remove_selected_instrument_mapping)

        if self.show_review:
            mapping_row = QHBoxLayout()
            mapping_row.addWidget(QLabel(tr("Map To")))
            mapping_row.addWidget(self.instrument_target_test_combo, 1)
            mapping_row.addWidget(self.save_instrument_mapping_button)
            mapping_row.addWidget(self.remove_instrument_mapping_button)
            layout.addLayout(mapping_row)

        self.instrument_status_label = QLabel()
        self.instrument_status_label.setWordWrap(True)
        layout.addWidget(self.instrument_status_label)
        return self.instrument_group

    def _build_queue_group(self) -> QWidget:
        self.queue_group = QGroupBox()
        layout = QVBoxLayout(self.queue_group)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.review_search = QLineEdit()
        self.review_search.setPlaceholderText(tr("Search by order number or patient name"))
        self.review_search.setClearButtonEnabled(True)
        self.review_search.textChanged.connect(self._refresh_table)
        layout.addWidget(self.review_search)

        self.orders_table = QTableWidget(0, 8)
        self.orders_table.setFont(QFont("Segoe UI", 10))
        self.orders_table.setSelectionMode(QTableWidget.NoSelection)
        self.orders_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.orders_table.setFocusPolicy(Qt.NoFocus)
        self.orders_table.setWordWrap(False)
        self.orders_table.verticalHeader().setDefaultSectionSize(48)
        header = self.orders_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setFont(QFont("Segoe UI", 10))
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        header.setSectionResizeMode(6, QHeaderView.Fixed)
        header.setSectionResizeMode(7, QHeaderView.Fixed)
        layout.addWidget(self.orders_table, 1)
        return self.queue_group

    def auto_start(self) -> None:
        if hasattr(self, "_status_panel"):
            self._status_panel.auto_start()

    def retranslate_ui(self) -> None:
        if hasattr(self, "_status_panel"):
            self._status_panel.retranslate_ui()
        if self.show_instruments:
            self.instrument_group.setTitle(tr("Instrument Results"))
            self.instrument_summary_label.setText(
                tr("Load recent machine captures, preview the results, map analyzer codes to order tests, then link the selected capture to the correct order.")
            )
            self.refresh_instrument_button.setText(tr("Refresh Captures"))
            self.reimport_recent_button.setText(tr("Reimport Last 20"))
            self.hide_empty_instrument_captures_checkbox.setText(tr("Only captures with data"))
            self.link_instrument_button.setText(tr("Link to Order"))
            self.save_instrument_mapping_button.setText(tr("Save Mapping"))
            self.remove_instrument_mapping_button.setText(tr("Remove Mapping"))
            self.instrument_captures_table.setHorizontalHeaderLabels(
                [tr("Received"), tr("Sample"), tr("Patient"), tr("Device"), tr("Profile"), tr("Status")]
            )
            self.instrument_observations_table.setHorizontalHeaderLabels(
                [tr("Code"), tr("Test"), tr("Result"), tr("Unit"), tr("Status")]
            )
        if self.show_review:
            self.queue_group.setTitle(tr("Results Review"))
            self.summary_label.setText(tr("Pending report approvals and WhatsApp delivery are managed here."))
            self.review_search.setPlaceholderText(tr("Search by order number or patient name"))
            self.orders_table.setHorizontalHeaderLabels(
                [
                    tr("Order Date"),
                    tr("Number"),
                    tr("Patient"),
                    tr("Client"),
                    tr("Preview Report"),
                    tr("Status"),
                    tr("Send Patient"),
                    tr("Send Client"),
                ]
            )
            self._refresh_table()

    def refresh_on_show(self) -> None:
        self.current_orders = self.database.list_results_workflow_orders()
        if self.show_instruments:
            self._refresh_instrument_profile_choices()
            self._refresh_instrument_order_choices()
            self.refresh_instrument_captures()
            if hasattr(self, "_status_panel"):
                self._status_panel.refresh_status()
        if self.show_review:
            self._refresh_table()

    def _refresh_instrument_profile_choices(self) -> None:
        current = self.instrument_profile_input.currentData()
        self.instrument_profile_input.blockSignals(True)
        self.instrument_profile_input.clear()
        self.instrument_profile_input.addItem(tr("All profiles"), "")
        for profile in self.database.list_instrument_profiles():
            self.instrument_profile_input.addItem(profile, profile)
        index = self.instrument_profile_input.findData(current)
        self.instrument_profile_input.setCurrentIndex(index if index >= 0 else 0)
        self.instrument_profile_input.blockSignals(False)

    def refresh_instrument_captures(self) -> None:
        profile_id = self.instrument_profile_input.currentData() or ""
        hide_empty = self.hide_empty_instrument_captures_checkbox.isChecked()
        query = "/api/v1/captures?limit=500"
        if profile_id:
            query += f"&profile_id={quote(profile_id)}"
        try:
            fresh = self._instrument_request_json(query)
        except Exception as exc:
            self.instrument_result = None
            all_cached = sorted(
                self._instrument_captures_cache.values(),
                key=lambda c: str(c.get("received_at") or ""),
                reverse=True,
            )
            self.instrument_captures = [
                c for c in all_cached
                if (not hide_empty or self._capture_has_data(c))
                and (not profile_id or str(c.get("profile_id") or "") == profile_id)
            ]
            self._refresh_instrument_tables()
            self.instrument_status_label.setText(tr("Instrument engine is offline or unavailable: {error}", error=str(exc)))
            return
        if not isinstance(fresh, list):
            fresh = []
        # Merge new captures into the in-memory cache so older ones don't
        # disappear when the engine's rolling window pushes them off the limit.
        _existing_ids = set(self._instrument_captures_cache.keys())
        for capture in fresh:
            if isinstance(capture, dict):
                cid = str(capture.get("id") or "")
                if cid:
                    self._instrument_captures_cache[cid] = dict(capture)
        _new_captures = [
            self._instrument_captures_cache[cid]
            for cid in self._instrument_captures_cache
            if cid not in _existing_ids
        ]
        if _new_captures:
            self.database.upsert_instrument_captures_cache(_new_captures)
        # Build the display list from the full cache, sorted newest-first.
        all_captures = sorted(
            self._instrument_captures_cache.values(),
            key=lambda c: str(c.get("received_at") or ""),
            reverse=True,
        )
        self.instrument_captures = [
            c for c in all_captures
            if (not hide_empty or self._capture_has_data(c))
            and (not profile_id or str(c.get("profile_id") or "") == profile_id)
        ]
        self.instrument_result = None
        self._fetch_profile_semiquant_maps()
        self._refresh_instrument_tables()
        linked_count = sum(
            1 for c in self.instrument_captures
            if str(c.get("id") or "") in self._linked_instrument_capture_ids()
        )
        pending_count = len(self.instrument_captures) - linked_count
        self.instrument_status_label.setText(
            tr(
                "{total} captures — {pending} pending, {linked} imported.",
                total=len(self.instrument_captures),
                pending=pending_count,
                linked=linked_count,
            )
        )

    def preview_instrument_capture(self) -> None:
        capture = self._selected_instrument_capture()
        if capture is None:
            QMessageBox.information(self, tr("Missing Selection"), tr("Select an instrument capture first."))
            return
        capture_id = str(capture.get("id") or "").strip()
        profile_id = str(capture.get("profile_id") or self.instrument_profile_input.currentData() or "" or "urinalysis-com6")
        try:
            payload = self._instrument_request_json(
                "/api/v1/replay",
                method="POST",
                body={"capture_id": capture_id, "profile_id": profile_id},
            )
        except Exception as exc:
            QMessageBox.critical(self, tr("Import Failed"), str(exc))
            return
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            QMessageBox.warning(self, tr("Missing Data"), tr("The instrument engine did not return parsed results for this capture."))
            return
        self.instrument_result = result
        self._refresh_instrument_observations_table()
        observations = self._instrument_observations()
        self.instrument_status_label.setText(
            tr("Previewed capture {capture_id}: {count} observations.", capture_id=capture_id, count=len(observations))
        )

    def save_selected_instrument_mapping(self) -> None:
        capture = self._selected_instrument_capture()
        if capture is None:
            QMessageBox.information(self, tr("Missing Selection"), tr("Select an instrument capture first."))
            return
        if self.instrument_result is None:
            self.preview_instrument_capture()
            if self.instrument_result is None:
                return
        obs = self._selected_instrument_observation()
        if obs is None:
            QMessageBox.information(self, tr("Missing Selection"), tr("Select an observation to map."))
            return
        target = self.instrument_target_test_combo.currentData()
        if target is None:
            QMessageBox.information(self, tr("Missing Selection"), tr("Select the order test this observation should update."))
            return
        target_entry = next((entry for entry in self.instrument_order_entries if int(entry.order_test_id) == int(target)), None)
        if target_entry is None:
            QMessageBox.warning(self, tr("Missing Data"), tr("The selected order test is no longer available."))
            return
        profile_id = str(capture.get("profile_id") or self.instrument_profile_input.currentData() or "" or "urinalysis-com6")
        device_id = str(capture.get("device_id") or "")
        raw_code = self._observation_raw_code(obs)
        if not raw_code:
            QMessageBox.warning(self, tr("Missing Data"), tr("The selected observation does not have an instrument code."))
            return
        self.database.save_instrument_result_mapping(
            instrument_profile=profile_id,
            device_id=device_id,
            raw_code=raw_code,
            raw_name=str(obs.get("test_name") or obs.get("name") or ""),
            specimen_type=str(obs.get("specimen_type") or obs.get("sample_type") or target_entry.specimen_type or ""),
            panel_hint=str(obs.get("panel_hint") or obs.get("panel") or target_entry.source_label or ""),
            test_id=int(target_entry.test_id),
            unit_override=str(obs.get("units_normalized") or obs.get("units_raw") or target_entry.unit or ""),
            reference_range_override=target_entry.reference_text or "",
        )
        self._refresh_instrument_observations_table()
        self._instrument_observation_selection_changed()
        self.instrument_status_label.setText(
            tr(
                "Saved mapping: {profile} {code} -> {test}.",
                profile=profile_id,
                code=raw_code,
                test=target_entry.test_name,
            )
        )

    def remove_selected_instrument_mapping(self) -> None:
        capture = self._selected_instrument_capture()
        if capture is None:
            QMessageBox.information(self, tr("Missing Selection"), tr("Select an instrument capture first."))
            return
        obs = self._selected_instrument_observation()
        if obs is None:
            QMessageBox.information(self, tr("Missing Selection"), tr("Select an observation to unmap."))
            return
        profile_id = str(capture.get("profile_id") or self.instrument_profile_input.currentData() or "" or "")
        device_id = str(capture.get("device_id") or "")
        code = self._observation_raw_code(obs)
        mapping = self.database.resolve_instrument_result_mapping(
            instrument_profile=profile_id,
            device_id=device_id,
            raw_code=code,
            specimen_type=str(obs.get("specimen_type") or obs.get("sample_type") or ""),
            panel_hint=str(obs.get("panel_hint") or obs.get("panel") or ""),
        )
        if mapping is None:
            self.instrument_status_label.setText(tr("No mapping found for this observation."))
            return
        self.database.delete_instrument_result_mapping(mapping.id)
        self._refresh_instrument_observations_table()
        self.instrument_target_test_combo.setCurrentIndex(0)
        self.instrument_status_label.setText(
            tr("Removed mapping: {profile} {code}.", profile=profile_id, code=code)
        )

    def link_instrument_capture_to_order(self) -> None:
        capture = self._selected_instrument_capture()
        if capture is None:
            QMessageBox.information(self, tr("Missing Selection"), tr("Select an instrument capture first."))
            return
        if self.instrument_result is None:
            self.preview_instrument_capture()
            if self.instrument_result is None:
                return
        order_id = self.instrument_order_combo.currentData()
        if order_id is None:
            QMessageBox.information(self, tr("Missing Selection"), tr("Select the order to receive these instrument results."))
            return
        observations = self._instrument_observations()
        if not observations:
            QMessageBox.warning(self, tr("Missing Data"), tr("No observations were found in the selected capture."))
            return
        if self.result_service.uses_server_backend():
            self._link_server_instrument_capture(capture, order_id)
            return
        capture_id = str(capture.get("id") or "").strip()
        imported_count, unmatched_codes = self._apply_capture_to_order(
            capture, observations, int(order_id)
        )
        if imported_count == 0:
            QMessageBox.warning(
                self,
                tr("Import Failed"),
                tr("No order tests matched the instrument codes: {codes}", codes=", ".join(unmatched_codes)),
            )
            return
        self._mark_instrument_capture_linked(capture_id, int(order_id))
        self.current_orders = self.database.list_results_workflow_orders()
        if self.show_review:
            self._refresh_table()
        self.refresh_instrument_captures()
        detail = ""
        if unmatched_codes:
            detail = "\n" + tr("Unmatched codes: {codes}", codes=", ".join(unmatched_codes))
        QMessageBox.information(
            self,
            tr("Imported"),
            tr("Linked {count} instrument results to the selected order.", count=imported_count) + detail,
        )

    def _link_server_instrument_capture(self, capture: dict[str, object], order_id: object) -> None:
        capture_id = str(capture.get("id") or "").strip()
        try:
            response = self.deployment_service.request_json(
                "POST",
                "/api/results/import-instrument",
                {"order_id": str(order_id), "result": self.instrument_result or {}},
            )
        except RuntimeError as exc:
            QMessageBox.warning(self, tr("Import Failed"), str(exc))
            return
        if not isinstance(response, dict):
            QMessageBox.warning(self, tr("Import Failed"), tr("Server did not return an import summary."))
            return
        imported_count = int(response.get("imported_count") or 0)
        unmatched_codes = [str(code) for code in response.get("unmatched_codes") or []]
        self._mark_instrument_capture_linked(capture_id, str(order_id))
        self.current_orders = self.database.list_results_workflow_orders()
        self._refresh_table()
        self.refresh_instrument_captures()
        detail = ""
        if unmatched_codes:
            detail = "\n" + tr("Unmatched codes: {codes}", codes=", ".join(unmatched_codes))
        QMessageBox.information(
            self,
            tr("Imported"),
            tr("Linked {count} instrument results to the selected order.", count=imported_count) + detail,
        )

    def _apply_capture_to_order(
        self,
        capture: dict[str, object],
        observations: list[dict[str, object]],
        order_id: int,
    ) -> tuple[int, list[str]]:
        profile_id = str(capture.get("profile_id") or "").strip()
        device_id = str(capture.get("device_id") or "").strip()
        capture_id = str(capture.get("id") or "").strip()
        entries = [entry for entry in self.database.get_order_result_entries(order_id) if entry.item_type == "test"]
        order_test_codes = self.database.list_order_test_codes(order_id)
        entries_by_test_id = {int(entry.test_id): entry for entry in entries}
        entries_by_code: dict[str, ResultEntryRecord] = {}
        for entry in entries:
            code = self._normalize_test_code(order_test_codes.get(int(entry.order_test_id), ""))
            if code:
                entries_by_code[code] = entry
        for entry in entries:
            code = self._extract_code_from_test_name(entry.test_name)
            if code:
                entries_by_code[code] = entry
        imported_count = 0
        unmatched_codes: list[str] = []
        for obs in observations:
            code = self._observation_raw_code(obs)
            mapping = self.database.resolve_instrument_result_mapping(
                instrument_profile=profile_id,
                device_id=device_id,
                raw_code=code,
                specimen_type=str(obs.get("specimen_type") or obs.get("sample_type") or ""),
                panel_hint=str(obs.get("panel_hint") or obs.get("panel") or ""),
            )
            if mapping is None:
                for candidate_entry in entries:
                    candidate_mapping = self.database.resolve_instrument_result_mapping(
                        instrument_profile=profile_id,
                        device_id=device_id,
                        raw_code=code,
                        specimen_type=candidate_entry.specimen_type or "",
                        panel_hint=candidate_entry.source_label or "",
                    )
                    if candidate_mapping is not None and candidate_mapping.test_id == candidate_entry.test_id:
                        mapping = candidate_mapping
                        break
            entry = entries_by_test_id.get(mapping.test_id) if mapping is not None else None
            if entry is None:
                entry = entries_by_code.get(code)
            if entry is None:
                # Fall back to the engine's profile mapping (e.g. CM250 "COL L" ->
                # "CM250-COL"): match the mapped LIS test id against the order's own
                # test codes. This lets file-drop analyzers whose codes are mapped
                # only in the profile YAML import without a hand-saved per-code
                # mapping in the Results page.
                mapped_code = self._normalize_test_code(str(obs.get("mapped_lis_test_id") or ""))
                if mapped_code and mapped_code != code:
                    entry = entries_by_code.get(mapped_code)
            if entry is None:
                unmatched_codes.append(code or tr("unknown"))
                continue
            result_value = self._instrument_observation_value(obs, entry.result_kind)
            if mapping is not None and result_value:
                slice_start = mapping.value_slice_start
                slice_end = mapping.value_slice_end
                if slice_start is not None or slice_end is not None:
                    py_start = (slice_start - 1) if slice_start is not None else 0
                    py_end = slice_end if slice_end is not None else None
                    result_value = result_value[py_start:py_end].strip()
            value_formula = mapping.value_formula if mapping is not None else None
            multiplier = (mapping.value_multiplier if mapping is not None and mapping.value_multiplier else None) or entry.result_multiplier
            if entry.result_kind == "numeric" and result_value:
                if value_formula:
                    try:
                        raw = float(Decimal(result_value.replace(",", "")))
                        transformed = Decimal(str(_safe_eval_formula(value_formula, raw)))
                        formatted = format(transformed, "f")
                        if "." in formatted:
                            int_part, dec_part = formatted.split(".", 1)
                            result_value = formatted if dec_part.rstrip("0") else int_part
                        else:
                            result_value = formatted
                    except (ValueError, TypeError, InvalidOperation, ZeroDivisionError):
                        pass
                elif multiplier:
                    try:
                        multiplied = Decimal(result_value.replace(",", "")) * Decimal(str(multiplier))
                        formatted = format(multiplied, "f")
                        if "." in formatted:
                            int_part, dec_part = formatted.split(".", 1)
                            result_value = formatted if dec_part.rstrip("0") else int_part
                        else:
                            result_value = formatted
                    except (ValueError, TypeError, InvalidOperation):
                        pass
            decimal_places = mapping.decimal_places if mapping is not None else None
            if decimal_places is not None and entry.result_kind == "numeric" and result_value:
                try:
                    result_value = str(round(Decimal(result_value.replace(",", "")), decimal_places))
                except (ValueError, TypeError, InvalidOperation):
                    pass
            unit = str(entry.unit or "").strip()
            reference_text = (
                mapping.reference_range_override
                if mapping is not None and mapping.reference_range_override
                else entry.reference_text or ""
            )
            self.database.save_result_entry(
                order_test_id=int(entry.order_test_id),
                result_value=result_value,
                unit=unit,
                lower_value=entry.lower_value,
                upper_value=entry.upper_value,
                reference_text=reference_text,
                comments="",
                result_kind=entry.result_kind,
            )
            imported_count += 1
        return imported_count, unmatched_codes

    def _auto_import_pending(self) -> None:
        if self.result_service.uses_server_backend():
            return
        linked = self._linked_instrument_capture_ids()
        imported_total = 0
        for capture in list(self.instrument_captures):
            capture_id = str(capture.get("id") or "").strip()
            if capture_id in linked:
                continue
            result = self._instrument_result_from_capture(capture)
            if result is None:
                continue
            message = result.get("message")
            if not isinstance(message, dict):
                continue
            patient_id = str(message.get("patient_id") or "").strip()
            sample_id = str(message.get("sample_id") or "").strip()
            accession_id = str(message.get("accession_id") or "").strip()
            order_number = str(message.get("analyzer_run_id") or "").strip()
            if not patient_id and not sample_id and not accession_id and not order_number:
                continue
            profile_id = str(capture.get("profile_id") or "").strip()
            match_cfg = self.database.get_instrument_order_match(profile_id) if profile_id else None
            if match_cfg is not None and not match_cfg.auto_import:
                continue
            if match_cfg is not None:
                _field_values = {
                    "sample_id": sample_id,
                    "accession_id": accession_id,
                    "analyzer_run_id": order_number,
                    "patient_id": patient_id,
                }
                order_id = self.database.find_order_by_instrument_ids(
                    **{match_cfg.order_field: _field_values.get(match_cfg.instrument_field, "")}
                )
            else:
                order_id = self.database.find_order_by_instrument_ids(
                    sample_id=sample_id,
                    accession_id=accession_id,
                    order_number=order_number,
                    patient_id=patient_id,
                )
            if order_id is None:
                continue
            observations = []
            observations_raw = message.get("observations")
            if isinstance(observations_raw, list):
                observations = [dict(o) for o in observations_raw if isinstance(o, dict)]
            if not observations:
                continue
            imported_count, _ = self._apply_capture_to_order(capture, observations, order_id)
            if imported_count > 0:
                self._mark_instrument_capture_linked(capture_id, order_id)
                imported_total += imported_count
        if imported_total > 0:
            self.current_orders = self.database.list_results_workflow_orders()
            if self.show_review:
                self._refresh_table()
            self.refresh_instrument_captures()
            self.instrument_status_label.setText(
                tr("Auto-imported {count} result(s) from instrument captures.", count=imported_total)
            )

    def reimport_recent_captures(self) -> None:
        if self.result_service.uses_server_backend():
            QMessageBox.information(self, tr("Not Available"), tr("Reimport is only available in local mode."))
            return
        profile_id = self.instrument_profile_input.currentData() or ""
        candidates = [
            c for c in self.instrument_captures
            if (not profile_id or str(c.get("profile_id") or "") == profile_id)
            and self._capture_has_data(c)
        ][:20]
        if not candidates:
            self.instrument_status_label.setText(tr("No captures to reimport."))
            return
        imported_total = 0
        unmatched_total: list[str] = []
        no_order: list[str] = []
        for capture in candidates:
            capture_id = str(capture.get("id") or "").strip()
            result = self._instrument_result_from_capture(capture)
            if result is None:
                continue
            message = result.get("message")
            if not isinstance(message, dict):
                continue
            patient_id = str(message.get("patient_id") or "").strip()
            sample_id = str(message.get("sample_id") or "").strip()
            accession_id = str(message.get("accession_id") or "").strip()
            order_number = str(message.get("analyzer_run_id") or "").strip()
            if not patient_id and not sample_id and not accession_id and not order_number:
                continue
            cap_profile = str(capture.get("profile_id") or "").strip()
            match_cfg = self.database.get_instrument_order_match(cap_profile) if cap_profile else None
            if match_cfg is not None:
                _field_values = {
                    "sample_id": sample_id,
                    "accession_id": accession_id,
                    "analyzer_run_id": order_number,
                    "patient_id": patient_id,
                }
                order_id = self.database.find_order_by_instrument_ids(
                    **{match_cfg.order_field: _field_values.get(match_cfg.instrument_field, "")}
                )
            else:
                order_id = self.database.find_order_by_instrument_ids(
                    sample_id=sample_id,
                    accession_id=accession_id,
                    order_number=order_number,
                    patient_id=patient_id,
                )
            if order_id is None:
                no_order.append(sample_id or accession_id or order_number or capture_id[:8])
                continue
            observations = []
            observations_raw = message.get("observations")
            if isinstance(observations_raw, list):
                observations = [dict(o) for o in observations_raw if isinstance(o, dict)]
            if not observations:
                continue
            imported_count, unmatched = self._apply_capture_to_order(capture, observations, order_id)
            unmatched_total.extend(unmatched)
            if imported_count > 0:
                self._mark_instrument_capture_linked(capture_id, order_id)
                imported_total += imported_count
        self.current_orders = self.database.list_results_workflow_orders()
        if self.show_review:
            self._refresh_table()
        self.refresh_instrument_captures()
        parts = [tr("Reimported {count} result(s).", count=imported_total)]
        if no_order:
            parts.append(tr("{n} capture(s) had no matching order.", n=len(no_order)))
        if unmatched_total:
            parts.append(tr("Unmatched codes: {codes}.", codes=", ".join(sorted(set(unmatched_total)))))
        self.instrument_status_label.setText("  ".join(parts))

    def _refresh_instrument_order_choices(self) -> None:
        selected = self.instrument_order_combo.currentData()
        self.instrument_order_combo.clear()
        self.instrument_order_combo.addItem(tr("Select order"), None)
        for order in self.current_orders:
            label = f"{order.order_number} - {order.patient_name} - {self._format_order_date(order.order_date)}"
            self.instrument_order_combo.addItem(label, order.id)
        if selected is not None:
            index = self.instrument_order_combo.findData(selected)
            if index >= 0:
                self.instrument_order_combo.setCurrentIndex(index)
        self._refresh_instrument_target_test_choices()

    def _refresh_instrument_target_test_choices(self) -> None:
        selected = self.instrument_target_test_combo.currentData()
        self.instrument_target_test_combo.clear()
        self.instrument_order_entries = []
        order_id = self.instrument_order_combo.currentData()
        if order_id is None:
            self.instrument_target_test_combo.addItem(tr("Select order first"), None)
            return
        self.instrument_order_entries = [
            entry
            for entry in self.database.get_order_result_entries(int(order_id))
            if entry.item_type == "test"
        ]
        order_test_codes = self.database.list_order_test_codes(int(order_id))
        self.instrument_target_test_combo.addItem(tr("Select target test"), None)
        for entry in self.instrument_order_entries:
            test_code = str(order_test_codes.get(int(entry.order_test_id), "") or "").strip()
            test_label = f"{test_code} - {entry.test_name}" if test_code else entry.test_name
            label = f"{test_label} ({entry.specimen_type or entry.source_label or entry.order_number})"
            self.instrument_target_test_combo.addItem(label, entry.order_test_id)
        if selected is not None:
            index = self.instrument_target_test_combo.findData(selected)
            if index >= 0:
                self.instrument_target_test_combo.setCurrentIndex(index)

    def _refresh_instrument_tables(self) -> None:
        linked_map = self._linked_instrument_captures()
        self.instrument_captures_table.blockSignals(True)
        self.instrument_captures_table.clearContents()
        self.instrument_captures_table.setRowCount(len(self.instrument_captures))
        self.instrument_captures_table.setColumnWidth(0, 160)
        self.instrument_captures_table.setColumnWidth(1, 105)
        self.instrument_captures_table.setColumnWidth(3, 90)
        self.instrument_captures_table.setColumnWidth(4, 120)
        self.instrument_captures_table.setColumnWidth(5, 160)
        for row_index, capture in enumerate(self.instrument_captures):
            capture_id = str(capture.get("id") or "")
            link_info = linked_map.get(capture_id)
            is_linked = link_info is not None
            if is_linked:
                order_id = link_info.get("order_id")
                order = next((o for o in self.current_orders if str(o.id) == str(order_id)), None)
                status_text = f"✓ {order.order_number}" if order else tr("Imported")
            else:
                status_text = tr("Pending")
            self._set_instrument_capture_item(row_index, 0, self._format_capture_datetime(str(capture.get("received_at") or "")), capture, linked=is_linked)
            self._set_instrument_capture_item(row_index, 1, self._capture_sample_id(capture), capture, linked=is_linked)
            self._set_instrument_capture_item(row_index, 2, self._capture_patient_name(capture), capture, linked=is_linked)
            self._set_instrument_capture_item(row_index, 3, str(capture.get("device_id") or ""), capture, linked=is_linked)
            self._set_instrument_capture_item(row_index, 4, str(capture.get("profile_id") or ""), capture, linked=is_linked)
            self._set_instrument_capture_item(row_index, 5, status_text, capture, linked=is_linked)
        self.instrument_captures_table.blockSignals(False)
        if self.instrument_captures and self.instrument_captures_table.currentRow() < 0:
            self.instrument_captures_table.selectRow(0)
        self.instrument_result = self._instrument_result_from_capture(self._selected_instrument_capture() or {})
        self._refresh_instrument_observations_table()

    def _refresh_instrument_observations_table(self) -> None:
        observations = self._instrument_observations()
        self.instrument_observations_table.clearContents()
        self.instrument_observations_table.setRowCount(len(observations))
        self.instrument_observations_table.setColumnWidth(0, 90)
        self.instrument_observations_table.setColumnWidth(2, 120)
        self.instrument_observations_table.setColumnWidth(3, 90)
        self.instrument_observations_table.setColumnWidth(4, 100)
        capture = self._selected_instrument_capture() or {}
        profile_id = str(capture.get("profile_id") or self.instrument_profile_input.currentData() or "" or "")
        device_id = str(capture.get("device_id") or "")
        for row_index, obs in enumerate(observations):
            code = self._observation_raw_code(obs)
            mapping = self.database.resolve_instrument_result_mapping(
                instrument_profile=profile_id,
                device_id=device_id,
                raw_code=code,
                specimen_type=str(obs.get("specimen_type") or obs.get("sample_type") or ""),
                panel_hint=str(obs.get("panel_hint") or obs.get("panel") or ""),
            )
            status = mapping.test_name if mapping is not None else str(obs.get("result_status") or "")
            self._set_observation_item(row_index, 0, code)
            self._set_observation_item(row_index, 1, str(obs.get("instrument_test_name") or obs.get("test_name") or obs.get("name") or ""))
            self._set_observation_item(row_index, 2, self._display_observation_value(obs, code, profile_id))
            self._set_observation_item(row_index, 3, str(obs.get("units_normalized") or obs.get("units_raw") or ""))
            self._set_observation_item(row_index, 4, status)

    def _instrument_capture_selection_changed(self) -> None:
        self.instrument_result = self._instrument_result_from_capture(self._selected_instrument_capture() or {})
        self._refresh_instrument_observations_table()
        self._instrument_observation_selection_changed()
        capture = self._selected_instrument_capture()
        capture_id = str(capture.get("id") or "") if capture else ""
        linked_order_id = None
        if capture_id:
            linked_map = self._linked_instrument_captures()
            entry = linked_map.get(capture_id)
            if isinstance(entry, dict):
                linked_order_id = entry.get("order_id")
        self.instrument_order_combo.blockSignals(True)
        if linked_order_id is not None:
            index = self.instrument_order_combo.findData(linked_order_id)
            self.instrument_order_combo.setCurrentIndex(index if index >= 0 else 0)
        else:
            self.instrument_order_combo.setCurrentIndex(0)
        self.instrument_order_combo.blockSignals(False)
        self._refresh_instrument_target_test_choices()

    def _instrument_observation_selection_changed(self) -> None:
        obs = self._selected_instrument_observation()
        if obs is None:
            return
        capture = self._selected_instrument_capture() or {}
        profile_id = str(capture.get("profile_id") or self.instrument_profile_input.currentData() or "" or "")
        device_id = str(capture.get("device_id") or "")
        code = self._observation_raw_code(obs)
        mapping = self.database.resolve_instrument_result_mapping(
            instrument_profile=profile_id,
            device_id=device_id,
            raw_code=code,
            specimen_type=str(obs.get("specimen_type") or obs.get("sample_type") or ""),
            panel_hint=str(obs.get("panel_hint") or obs.get("panel") or ""),
        )
        if mapping is not None:
            index = self.instrument_target_test_combo.findData(mapping.test_id)
            if index >= 0:
                self.instrument_target_test_combo.setCurrentIndex(index)
                return
        self.instrument_target_test_combo.setCurrentIndex(0)

    def _set_instrument_capture_item(self, row: int, column: int, value: str, capture: dict[str, object], *, linked: bool = False) -> None:
        from PySide6.QtGui import QColor
        item = QTableWidgetItem(value)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        item.setData(Qt.UserRole, capture)
        if linked:
            item.setForeground(QColor("#5ad08c"))
        self.instrument_captures_table.setItem(row, column, item)

    def _set_observation_item(self, row: int, column: int, value: str) -> None:
        item = QTableWidgetItem(value)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.instrument_observations_table.setItem(row, column, item)

    def _selected_instrument_capture(self) -> dict[str, object] | None:
        row = self.instrument_captures_table.currentRow()
        if row < 0 and self.instrument_captures:
            row = 0
            self.instrument_captures_table.selectRow(0)
        if row < 0:
            return None
        item = self.instrument_captures_table.item(row, 0)
        metadata = item.data(Qt.UserRole) if item is not None else None
        return dict(metadata) if isinstance(metadata, dict) else None

    def _selected_instrument_observation(self) -> dict[str, object] | None:
        observations = self._instrument_observations()
        row = self.instrument_observations_table.currentRow()
        if row < 0 and observations:
            row = 0
            self.instrument_observations_table.selectRow(0)
        if row < 0 or row >= len(observations):
            return None
        return dict(observations[row])

    def _instrument_observations(self) -> list[dict[str, object]]:
        result = self.instrument_result or self._instrument_result_from_capture(self._selected_instrument_capture() or {})
        if result is None:
            return []
        message = result.get("message")
        if not isinstance(message, dict):
            return []
        observations = message.get("observations")
        if not isinstance(observations, list):
            return []
        return [dict(obs) for obs in observations if isinstance(obs, dict)]

    def _instrument_result_from_capture(self, capture: dict[str, object]) -> dict[str, object] | None:
        parsed = capture.get("parsed_json")
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, str) and parsed.strip():
            try:
                loaded = json.loads(parsed)
            except json.JSONDecodeError:
                return None
            return loaded if isinstance(loaded, dict) else None
        return None

    def _instrument_request_json(self, path: str, *, method: str = "GET", body: dict[str, object] | None = None) -> object:
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request_obj = urllib.request.Request(f"{self.engine_url}{path}", data=data, headers=headers, method=method)
        attempts = 4 if method == "GET" else 1
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(request_obj, timeout=6) as response:
                    raw = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                if exc.code == 400 and "SQLITE_BUSY" in detail and attempt < attempts - 1:
                    time.sleep(0.35 * (attempt + 1))
                    continue
                raise RuntimeError(detail or f"Instrument engine returned HTTP {exc.code}.") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise RuntimeError(str(getattr(exc, "reason", exc))) from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(tr("Instrument engine returned invalid JSON.")) from exc

    def _linked_instrument_captures(self) -> dict[str, dict]:
        ui_state = self.database.get_ui_state()
        raw = ui_state.get(self.LINKED_INSTRUMENT_CAPTURES_KEY, {})
        if not isinstance(raw, dict):
            return {}
        return {str(k): v for k, v in raw.items() if isinstance(v, dict)}

    def _linked_instrument_capture_ids(self) -> set[str]:
        return set(self._linked_instrument_captures().keys())

    def _mark_instrument_capture_linked(self, capture_id: str, order_id: int) -> None:
        if not capture_id:
            return
        ui_state = self.database.get_ui_state()
        raw = ui_state.get(self.LINKED_INSTRUMENT_CAPTURES_KEY, {})
        linked = dict(raw) if isinstance(raw, dict) else {}
        linked[capture_id] = {"order_id": order_id, "linked_at": datetime.now().isoformat(timespec="seconds")}
        ui_state[self.LINKED_INSTRUMENT_CAPTURES_KEY] = linked
        self.database.save_ui_state(ui_state)

    @staticmethod
    def _capture_preview(capture: dict[str, object]) -> str:
        text = str(capture.get("normalized_text") or capture.get("decoded_text") or "").strip()
        text = " ".join(text.split())
        return text[:140]

    @staticmethod
    def _capture_message(capture: dict[str, object]) -> dict[str, object]:
        result = ResultsPage._instrument_result_from_capture_static(capture)
        message = result.get("message") if isinstance(result, dict) else None
        return dict(message) if isinstance(message, dict) else {}

    @staticmethod
    def _instrument_result_from_capture_static(capture: dict[str, object]) -> dict[str, object] | None:
        parsed = capture.get("parsed_json")
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, str) and parsed.strip():
            try:
                loaded = json.loads(parsed)
            except json.JSONDecodeError:
                return None
            return loaded if isinstance(loaded, dict) else None
        return None

    @classmethod
    def _capture_sample_id(cls, capture: dict[str, object]) -> str:
        message = cls._capture_message(capture)
        value = str(message.get("sample_id") or message.get("analyzer_run_id") or "").strip()
        if value:
            return value
        obr = cls._hl7_segment(capture, "OBR")
        if obr:
            fields = obr.split("|")
            for index in (3, 2):
                if len(fields) > index and fields[index].strip():
                    return fields[index].strip()
        return ""

    @classmethod
    def _capture_patient_name(cls, capture: dict[str, object]) -> str:
        message = cls._capture_message(capture)
        value = message.get("patient_name") or message.get("patient") or ""
        if not value:
            # File-drop profiles (e.g. CM250) carry the patient name in metadata.
            metadata = message.get("metadata")
            if isinstance(metadata, dict):
                value = metadata.get("patient_name") or metadata.get("patient") or ""
        if isinstance(value, dict):
            family = str(value.get("family") or value.get("last") or "").strip()
            given = str(value.get("given") or value.get("first") or "").strip()
            return " ".join(part for part in [given, family] if part)
        patient = str(value).strip()
        if patient:
            return patient
        pid = cls._hl7_segment(capture, "PID")
        if not pid:
            return ""
        fields = pid.split("|")
        if len(fields) <= 5:
            return ""
        parts = fields[5].split("^")
        family = parts[0].strip() if parts else ""
        given = parts[1].strip() if len(parts) > 1 else ""
        return " ".join(part for part in [given, family] if part)

    @staticmethod
    def _hl7_segment(capture: dict[str, object], segment_id: str) -> str:
        text = str(capture.get("normalized_text") or capture.get("decoded_text") or "")
        normalized = text.replace("\r", "\n").replace("\x0b", "\n").replace("\x1c", "\n")
        prefix = f"{segment_id}|"
        for line in normalized.splitlines():
            cleaned = line.strip()
            if cleaned.startswith(prefix):
                return cleaned
        return ""

    @staticmethod
    def _capture_has_data(capture: dict[str, object]) -> bool:
        text = str(capture.get("normalized_text") or capture.get("decoded_text") or "")
        visible = "".join(character for character in text if character.isprintable()).strip()
        if not visible:
            return False
        if visible in {"\x02", "\x03", "\x05", "\x06", "\x15", "\x1c"}:
            return False
        return len(visible) > 1

    @staticmethod
    def _format_capture_datetime(raw_value: str) -> str:
        value = str(raw_value or "").strip()
        if not value:
            return ""
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return value.replace("T", " ").replace("Z", "")[:16]

    @staticmethod
    def _normalize_test_code(value: str) -> str:
        return "".join(character for character in value.upper().strip() if character.isalnum() or character in {"-", "_"})

    @classmethod
    def _extract_code_from_test_name(cls, test_name: str) -> str:
        text = str(test_name or "")
        if "(" in text and ")" in text:
            candidate = text.rsplit("(", 1)[-1].split(")", 1)[0]
            return cls._normalize_test_code(candidate)
        return ""

    @staticmethod
    def _instrument_observation_value(obs: dict[str, object], result_kind: str) -> str:
        if result_kind == "numeric":
            # Prefer the raw string from the instrument so trailing zeros are preserved
            # (e.g. "1.020" must not become "1.02" via float conversion)
            for key in ("value_raw", "value_text"):
                raw = obs.get(key)
                if raw is not None:
                    s = str(raw).strip().replace(",", "")
                    if s:
                        try:
                            float(s)
                            return s
                        except ValueError:
                            pass
            if obs.get("value_numeric") is not None:
                val = float(obs["value_numeric"])
                return str(int(val)) if val == int(val) else str(val)
            return ""
        for key in ("value_text", "value_raw", "value_numeric"):
            value = obs.get(key)
            if value is not None and str(value).strip():
                s = str(value).strip()
                return s.split("^")[0].strip() if "^" in s else s
        return ""

    def _fetch_profile_semiquant_maps(self) -> None:
        try:
            data = self._instrument_request_json("/api/v1/profiles")
        except Exception:
            return
        result: dict[str, dict[str, dict[str, str]]] = {}
        for profile in (data.get("profiles") or [] if isinstance(data, dict) else []):
            pid = str(profile.get("id") or "")
            if not pid:
                continue
            code_map: dict[str, dict[str, str]] = {}
            mapping = profile.get("mapping") or {}
            for tm in (mapping.get("test_mappings") or []):
                sq = tm.get("semiquant_map")
                if not sq or not isinstance(sq, dict):
                    continue
                pattern = str(tm.get("pattern") or "").strip().upper()
                if not pattern:
                    continue
                code_map[pattern] = {k: str(v.get("display") or "") for k, v in sq.items() if isinstance(v, dict)}
            if code_map:
                result[pid] = code_map
        self._profile_semiquant_maps = result

    @staticmethod
    def _extract_qualifier(raw: str) -> str:
        tokens = (raw or "").split()
        if not tokens:
            return ""
        q = tokens[0]
        if q in ("-", "+") and len(tokens) > 1:
            nxt = tokens[1]
            if nxt and not (nxt[0].isdigit() or nxt[0] == "."):
                q += nxt
        return q

    @staticmethod
    def _is_raw_machine_value(raw: str) -> bool:
        q = ResultsPage._extract_qualifier(raw)
        if not q:
            return False
        return q.startswith("-") or q.startswith("+") or q.endswith("+")

    def _display_observation_value(self, obs: dict[str, object], code: str, profile_id: str) -> str:
        text = self._instrument_observation_value(obs, "text")
        if not self._is_raw_machine_value(text):
            return text
        code_map = (self._profile_semiquant_maps.get(profile_id) or {})
        sq = code_map.get(code.upper()) or {}
        if not sq:
            return text
        q = self._extract_qualifier(text)
        for key in sorted(sq.keys(), key=len, reverse=True):
            if q.lower().startswith(key.lower()):
                return sq[key]
        return text

    @classmethod
    def _observation_raw_code(cls, obs: dict[str, object]) -> str:
        return cls._normalize_test_code(str(obs.get("instrument_test_code") or obs.get("mapped_lis_test_id") or ""))

    def _refresh_table(self) -> None:
        query = self.review_search.text().strip().casefold() if hasattr(self, "review_search") else ""
        filtered_orders = [
            o for o in self.current_orders
            if not query
            or query in (o.order_number or "").casefold()
            or query in (o.patient_name or "").casefold()
        ]
        self.orders_table.clearContents()
        self.orders_table.setRowCount(len(filtered_orders))
        self.orders_table.setColumnWidth(0, 104)
        self.orders_table.setColumnWidth(1, 74)
        self.orders_table.setColumnWidth(2, 210)
        self.orders_table.setColumnWidth(3, 160)
        self.orders_table.setColumnWidth(4, 104)
        self.orders_table.setColumnWidth(5, 52)
        self.orders_table.setColumnWidth(6, 104)
        self.orders_table.setColumnWidth(7, 104)

        approvals = self._approved_versions()
        for row_index, order in enumerate(filtered_orders):
            self._set_item(row_index, 0, self._format_order_date(order.order_date))
            self._set_item(row_index, 1, order.order_number)
            self._set_item(row_index, 2, order.patient_name)
            self._set_item(row_index, 3, order.client_name or "")

            approved = (
                approvals.get(order.id) == int(order.report_version or 0)
                and int(order.report_version or 0) > 0
                and not int(order.report_outdated or 0)
            )
            ready = int(order.result_count or 0) > 0 and int(order.completed_result_count or 0) >= int(order.result_count or 0)

            preview_button = QPushButton(tr("Preview Report"))
            preview_button.setStyleSheet(self._results_action_button_style())
            preview_button.clicked.connect(lambda _checked=False, order_id=order.id: self.preview_report(order_id))
            self.orders_table.setCellWidget(row_index, 4, self._build_centered_cell_widget(preview_button))

            self.orders_table.setCellWidget(row_index, 5, self._build_status_indicator(approved, order.id in self.previewed_orders, ready))

            send_patient_button = QPushButton(tr("Send Patient"))
            send_patient_button.setEnabled(approved and bool((order.patient_phone or "").strip()))
            send_patient_button.setToolTip(tr("Send the approved report notification to the patient via WhatsApp."))
            if self._was_whatsapp_sent(order.id, "patient", int(order.report_version or 0)):
                send_patient_button.setStyleSheet(self._sent_action_button_style())
            else:
                send_patient_button.setStyleSheet(self._results_action_button_style())
            send_patient_button.clicked.connect(lambda _checked=False, order_id=order.id: self.send_to_patient(order_id))
            self.orders_table.setCellWidget(row_index, 6, self._build_centered_cell_widget(send_patient_button))

            send_client_button = QPushButton(tr("Send Client"))
            send_client_button.setEnabled(approved and bool((order.client_phone or "").strip()))
            send_client_button.setToolTip(tr("Send the approved report notification to the client via WhatsApp."))
            if self._was_whatsapp_sent(order.id, "client", int(order.report_version or 0)):
                send_client_button.setStyleSheet(self._sent_action_button_style())
            else:
                send_client_button.setStyleSheet(self._results_action_button_style())
            send_client_button.clicked.connect(lambda _checked=False, order_id=order.id: self.send_to_client(order_id))
            self.orders_table.setCellWidget(row_index, 7, self._build_centered_cell_widget(send_client_button))

    def _set_item(self, row: int, column: int, value: str) -> None:
        item = QTableWidgetItem(value)
        item.setFont(QFont("Segoe UI", 10))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.orders_table.setItem(row, column, item)

    def _build_status_indicator(self, approved: bool, previewed: bool, ready: bool = False) -> QWidget:
        container = QWidget()
        container.setAttribute(Qt.WA_TranslucentBackground, True)
        container.setStyleSheet("background-color: transparent; border: none;")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)

        indicator = QLabel("●")
        indicator.setAlignment(Qt.AlignCenter)
        if approved:
            color = "#3ddc84"
            tooltip = tr("Approved")
        elif ready:
            color = "#4db8ff"
            tooltip = tr("Ready to approve")
        elif previewed:
            color = "#f5c451"
            tooltip = tr("Previewed")
        else:
            color = "#7f8a98"
            tooltip = tr("Pending")
        indicator.setStyleSheet(
            f"color: {color}; background-color: transparent; border: none; font-size: 28px; font-weight: 700;"
        )
        indicator.setToolTip(tooltip)
        layout.addWidget(indicator)
        return container

    def _build_centered_cell_widget(self, widget: QWidget) -> QWidget:
        container = QWidget()
        container.setAttribute(Qt.WA_TranslucentBackground, True)
        container.setStyleSheet("background-color: transparent; border: none;")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(widget, 0, Qt.AlignCenter)
        return container

    def _results_action_button_style(self) -> str:
        return (
            "QPushButton {"
            "background-color: #bd93f9;"
            "color: #1a1a1a;"
            "border: none;"
            "border-radius: 7px;"
            "padding: 2px 6px;"
            "font-weight: 800;"
            "font-size: 10px;"
            "min-height: 22px;"
            "max-height: 26px;"
            "min-width: 72px;"
            "}"
            "QPushButton:hover {"
            "background-color: #caa9fa;"
            "}"
            "QPushButton:pressed {"
            "background-color: #a77de6;"
            "}"
            "QPushButton:disabled {"
            "background-color: #252930;"
            "border: none;"
            "color: #4a5568;"
            "}"
        )

    def _sent_action_button_style(self) -> str:
        return (
            "QPushButton {"
            "background-color: #245d3a;"
            "color: #e8ecf1;"
            "border: 1px solid #3ddc84;"
            "border-radius: 7px;"
            "padding: 2px 6px;"
            "font-weight: 600;"
            "font-size: 10px;"
            "min-height: 22px;"
            "max-height: 26px;"
            "min-width: 72px;"
            "}"
            "QPushButton:hover {"
            "background-color: #2d7147;"
            "border-color: #49e391;"
            "}"
            "QPushButton:pressed {"
            "background-color: #214f32;"
            "border-color: #36c575;"
            "}"
            "QPushButton:disabled {"
            "background-color: #39424d;"
            "border-color: #39424d;"
            "color: #98a0a8;"
            "}"
        )

    def _approved_versions(self) -> dict[int, int]:
        ui_state = self.database.get_ui_state()
        raw = ui_state.get(self.APPROVALS_KEY, {})
        if not isinstance(raw, dict):
            return {}
        approvals: dict[int, int] = {}
        for order_id, report_version in raw.items():
            try:
                approvals[int(order_id)] = int(report_version)
            except (TypeError, ValueError):
                continue
        return approvals

    def _save_approved_version(self, order_id: int, report_version: int) -> None:
        approvals = self._approved_versions()
        approvals[order_id] = report_version
        ui_state = self.database.get_ui_state()
        ui_state[self.APPROVALS_KEY] = {str(key): value for key, value in approvals.items()}
        self.database.save_ui_state(ui_state)

    def _selected_header_for_order(self, order_id: int, preview: dict[str, object]) -> str:
        ui_state = self.database.get_ui_state()
        raw = ui_state.get(self.ORDER_HEADERS_KEY, {})
        if isinstance(raw, dict):
            stored = raw.get(str(order_id))
            if isinstance(stored, str):
                return stored
        branding = self.database.get_report_branding_options()
        preview_header = str(preview.get("header_image_path") or "").strip()
        if preview_header:
            return preview_header
        return str(branding.get("selected_header") or "")

    def _save_selected_header_for_order(self, order_id: int, header_path: str) -> None:
        ui_state = self.database.get_ui_state()
        raw = ui_state.get(self.ORDER_HEADERS_KEY, {})
        mappings = dict(raw) if isinstance(raw, dict) else {}
        mappings[str(order_id)] = header_path.strip()
        ui_state[self.ORDER_HEADERS_KEY] = mappings
        self.database.save_ui_state(ui_state)

    def _sent_versions(self) -> dict[str, dict[int, int]]:
        ui_state = self.database.get_ui_state()
        raw = ui_state.get(self.WHATSAPP_SENT_KEY, {})
        if not isinstance(raw, dict):
            return {"patient": {}, "client": {}}
        normalized: dict[str, dict[int, int]] = {"patient": {}, "client": {}}
        for recipient in ("patient", "client"):
            recipient_raw = raw.get(recipient, {})
            if not isinstance(recipient_raw, dict):
                continue
            for order_id, report_version in recipient_raw.items():
                try:
                    normalized[recipient][int(order_id)] = int(report_version)
                except (TypeError, ValueError):
                    continue
        return normalized

    def _save_sent_version(self, order_id: int, recipient: str, report_version: int) -> None:
        sent_versions = self._sent_versions()
        recipient_versions = sent_versions.setdefault(recipient, {})
        recipient_versions[order_id] = report_version
        ui_state = self.database.get_ui_state()
        ui_state[self.WHATSAPP_SENT_KEY] = {
            key: {str(order_key): version for order_key, version in values.items()}
            for key, values in sent_versions.items()
        }
        self.database.save_ui_state(ui_state)

    def _was_whatsapp_sent(self, order_id: int, recipient: str, report_version: int) -> bool:
        if report_version <= 0:
            return False
        return self._sent_versions().get(recipient, {}).get(order_id) == report_version

    def _header_options(self) -> list[tuple[str, str]]:
        branding = self.database.get_report_branding_options()
        options: list[tuple[str, str]] = []
        for raw_path in branding.get("headers", []):
            value = str(raw_path or "").strip()
            if not value:
                continue
            options.append((Path(value).name or value, value))
        return options

    def _footer_options(self) -> list[tuple[str, str]]:
        branding = self.database.get_report_branding_options()
        options: list[tuple[str, str]] = []
        for raw_path in branding.get("footers", []):
            value = str(raw_path or "").strip()
            if not value:
                continue
            options.append((Path(value).name or value, value))
        return options

    def _selected_footer_for_order(self, order_id: int, preview: dict[str, object]) -> str:
        ui_state = self.database.get_ui_state()
        raw = ui_state.get(self.ORDER_FOOTERS_KEY, {})
        if isinstance(raw, dict):
            stored = raw.get(str(order_id))
            if isinstance(stored, str):
                return stored
        branding = self.database.get_report_branding_options()
        preview_footer = str(preview.get("footer_signature_image_path") or "").strip()
        if preview_footer:
            return preview_footer
        return str(branding.get("selected_footer") or "")

    def _save_selected_footer_for_order(self, order_id: int, footer_path: str) -> None:
        ui_state = self.database.get_ui_state()
        raw = ui_state.get(self.ORDER_FOOTERS_KEY, {})
        mappings = dict(raw) if isinstance(raw, dict) else {}
        mappings[str(order_id)] = footer_path.strip()
        ui_state[self.ORDER_FOOTERS_KEY] = mappings
        self.database.save_ui_state(ui_state)

    def _find_order(self, order_id: int) -> ResultWorkflowRecord | None:
        for order in self.current_orders:
            if order.id == order_id:
                return order
        return None

    def preview_report(self, order_id: int) -> None:
        preview = self.report_service.get_saved_report_preview(order_id) or self.report_service.get_live_report_preview(order_id)
        if preview is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("No report could be generated for this order."))
            return
        self.previewed_orders.add(order_id)
        selected_header = self._selected_header_for_order(order_id, preview)
        selected_footer = self._selected_footer_for_order(order_id, preview)
        preview["header_image_path"] = selected_header
        preview["footer_signature_image_path"] = selected_footer
        order = self._find_order(order_id)
        current_version = int(order.report_version or 0) if order is not None else int(preview.get("report_version") or 0)
        approved = (
            self._approved_versions().get(order_id) == current_version
            and current_version > 0
            and not int((order.report_outdated if order is not None else 0) or 0)
        )
        preview_with_layout = {**self.database.get_report_layout_settings(), **preview}

        def _reset_fetcher() -> dict[str, object] | None:
            try:
                self.report_service.delete_saved_report(order_id)
            except Exception:
                pass
            approvals = self._approved_versions()
            approvals.pop(order_id, None)
            ui_state = self.database.get_ui_state()
            ui_state[self.APPROVALS_KEY] = {str(k): v for k, v in approvals.items()}
            self.database.save_ui_state(ui_state)
            live = self.report_service.get_live_report_preview(order_id)
            if live is None:
                return None
            return {**self.database.get_report_layout_settings(), **live}

        dialog = ReportPreviewDialog(
            preview_with_layout,
            self._build_report_html,
            can_approve=True,
            approved=approved,
            header_options=self._header_options(),
            selected_header=selected_header,
            footer_options=self._footer_options(),
            selected_footer=selected_footer,
            reset_fetcher=_reset_fetcher,
            parent=self,
        )
        dialog.exec()
        self._save_selected_header_for_order(order_id, dialog.selected_header)
        self._save_selected_footer_for_order(order_id, dialog.selected_footer)
        if dialog.was_reset and not dialog.approved_clicked:
            self.refresh_on_show()
            self.notify_data_changed()
            return
        if dialog.approved_clicked:
            self.approve_report(order_id, preview_override=dialog.approved_preview, export_pdf=True)
            return
        if approved and dialog.preview_changed:
            try:
                self.report_service.finalize_report(
                    order_id,
                    header_image_path=dialog.selected_header,
                    footer_signature_image_path=dialog.selected_footer,
                    preview_override=dialog.current_preview,
                )
            except Exception as exc:
                QMessageBox.critical(self, tr("Save Failed"), str(exc))
                return
            approvals = self._approved_versions()
            approvals.pop(order_id, None)
            ui_state = self.database.get_ui_state()
            ui_state[self.APPROVALS_KEY] = {str(k): v for k, v in approvals.items()}
            self.database.save_ui_state(ui_state)
            self.refresh_on_show()
            self.notify_data_changed()
            QMessageBox.information(
                self,
                tr("Changes Saved"),
                tr("Report changes saved as a new version. Please re-approve to export the updated report."),
            )
            return
        self._refresh_table()

    def approve_report(
        self,
        order_id: int,
        *,
        preview_override: dict[str, object] | None = None,
        export_pdf: bool = False,
        success_message: str | None = None,
    ) -> None:
        if order_id not in self.previewed_orders:
            QMessageBox.information(self, tr("Missing Selection"), tr("Preview the report before approving it."))
            return
        selected_header = self._selected_header_for_order(order_id, {})
        selected_footer = self._selected_footer_for_order(order_id, {})
        if preview_override is not None:
            if "header_image_path" in preview_override:
                selected_header = str(preview_override["header_image_path"] or "")
            if "footer_signature_image_path" in preview_override:
                selected_footer = str(preview_override["footer_signature_image_path"] or "")
        try:
            self.report_service.finalize_report(order_id, header_image_path=selected_header, footer_signature_image_path=selected_footer, preview_override=preview_override)
        except Exception as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        saved_preview = self.report_service.get_saved_report_preview(order_id)
        if saved_preview is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("No report could be generated for this order."))
            return
        report_version = int(saved_preview.get("report_version") or 0)
        if report_version <= 0:
            QMessageBox.warning(self, tr("Missing Selection"), tr("No report could be generated for this order."))
            return
        self._save_approved_version(order_id, report_version)
        self.refresh_on_show()
        self.notify_data_changed()

        # Render the approved PDF at most once, then reuse it for the local export
        # and/or the portal upload.
        portal_linked = self._portal_results.is_linked(order_id)
        pdf_path: Path | None = None
        if export_pdf or portal_linked:
            pdf_path = self._export_report_pdf_for_whatsapp(order_id)

        portal_status = ""
        if portal_linked and pdf_path is not None:
            try:
                portal_status = self._portal_results.publish(order_id, Path(pdf_path).read_bytes())
            except OSError:
                portal_status = ""

        # Approving never opens the export folder. The PDF is still generated (for
        # the portal upload, and so WhatsApp export is ready); the Explorer reveal
        # now happens only when a report is actually sent via WhatsApp.
        if portal_linked:
            message = {
                "uploaded": tr("Report approved and published to the client portal."),
                "queued": tr(
                    "Report approved. The portal was unreachable; the result is queued and will be sent automatically."
                ),
            }.get(portal_status, tr("Report approved, but the PDF could not be generated to publish to the portal."))
        else:
            message = (
                success_message
                if success_message
                else (
                    tr("Report approved and PDF exported. WhatsApp sending is now enabled.")
                    if pdf_path is not None
                    else tr("Report approved. WhatsApp sending is now enabled.")
                )
            )
        QMessageBox.information(self, tr("Saved"), message)

    def send_to_patient(self, order_id: int) -> None:
        order = self._find_order(order_id)
        if order is None or not (order.patient_phone or "").strip():
            QMessageBox.warning(self, tr("Missing Data"), tr("Phone number not available for this contact."))
            return
        message = self._build_whatsapp_message(
            "patient",
            name=order.patient_name,
            patient_name=order.patient_name,
            order_number=order.order_number,
        )
        self._open_whatsapp(order.patient_phone or "", message, order_id, recipient="patient")

    def send_to_client(self, order_id: int) -> None:
        order = self._find_order(order_id)
        if order is None or not (order.client_phone or "").strip():
            QMessageBox.warning(self, tr("Missing Data"), tr("Phone number not available for this contact."))
            return
        message = self._build_whatsapp_message(
            "client",
            name=order.client_name or "",
            patient_name=order.patient_name,
            order_number=order.order_number,
        )
        self._open_whatsapp(order.client_phone or "", message, order_id, recipient="client")

    def _open_whatsapp(self, phone: str, message: str, order_id: int, *, recipient: str) -> None:
        normalized_phone = normalize_whatsapp_phone(phone, self.database.get_whatsapp_country_code())
        if not normalized_phone:
            QMessageBox.warning(self, tr("Missing Data"), tr("Phone number not available for this contact."))
            return
        if not QDesktopServices.openUrl(QUrl(f"https://wa.me/{normalized_phone}?text={quote(message)}")):
            return
        pdf_path = self._export_report_pdf_for_whatsapp(order_id)
        if pdf_path is not None:
            self._reveal_file_in_explorer(pdf_path)
        order = self._find_order(order_id)
        if order is not None:
            self._save_sent_version(order_id, recipient, int(order.report_version or 0))
            self._refresh_table()

    def _export_report_pdf_for_whatsapp(self, order_id: int) -> Path | None:
        preview = self.report_service.get_saved_report_preview(order_id) or self.report_service.get_live_report_preview(order_id)
        if preview is None:
            return None
        report_version = int(preview.get("report_version") or 0)
        pdf_path = build_pdf_export_path(
            self.database,
            preview,
            suffix=f"_v{report_version}" if report_version > 0 else "",
        )
        reports_dir = pdf_path.parent
        reports_dir.mkdir(parents=True, exist_ok=True)
        html = self._build_report_html(preview)
        webengine_pdf = self._export_report_pdf_with_webengine(html, pdf_path)
        if webengine_pdf is not None:
            return webengine_pdf
        document = QTextDocument()
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.A4))
        printer.setPageMargins(QMarginsF(4, 4, 4, 4), QPageLayout.Millimeter)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(str(pdf_path))
        paint_rect = printer.pageLayout().paintRectPoints()
        if not paint_rect.isEmpty():
            document.setPageSize(QSizeF(paint_rect.size()))
            document.setTextWidth(float(paint_rect.width()))
        document.setDocumentMargin(0)
        document.setHtml(html)
        print_document = getattr(document, "print", None) or getattr(document, "print_", None)
        if print_document is None:
            raise AttributeError("QTextDocument does not expose a supported print method.")
        print_document(printer)
        return pdf_path

    def _build_whatsapp_message(self, recipient: str, **values: str) -> str:
        templates = get_whatsapp_templates(self.database)
        template = templates.get(recipient) or ""
        try:
            return template.format(**values)
        except KeyError:
            defaults = default_whatsapp_templates()
            return (defaults.get(recipient) or template).format(
                name=values.get("name", ""),
                patient_name=values.get("patient_name", ""),
                order_number=values.get("order_number", ""),
            )

    def _export_report_pdf_with_webengine(self, html: str, pdf_path: Path) -> Path | None:
        if QWebEnginePage is None:
            return None
        page = QWebEnginePage(self)
        loop = QEventLoop(self)
        timeout = QTimer(self)
        timeout.setSingleShot(True)
        state = {"loaded": False, "printed": False, "success": False}
        layout = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(4, 4, 4, 4), QPageLayout.Millimeter)

        def finish() -> None:
            if loop.isRunning():
                loop.quit()

        def handle_load_finished(ok: bool) -> None:
            state["loaded"] = ok
            if not ok:
                finish()
                return
            try:
                page.printToPdf(str(pdf_path), layout)
            except TypeError:
                page.printToPdf(str(pdf_path))

        def handle_pdf_finished(_file_path: str, success: bool) -> None:
            state["printed"] = True
            state["success"] = success
            finish()

        timeout.timeout.connect(finish)
        page.loadFinished.connect(handle_load_finished)
        page.pdfPrintingFinished.connect(handle_pdf_finished)
        page.setHtml(html, QUrl.fromLocalFile(str(Path.cwd())) )
        timeout.start(15000)
        loop.exec()
        timeout.stop()
        page.deleteLater()
        if state["loaded"] and state["printed"] and state["success"] and pdf_path.exists():
            return pdf_path
        return None

    @staticmethod
    def _reveal_file_in_explorer(file_path: Path) -> None:
        try:
            subprocess.Popen(["explorer", f"/select,{file_path}"])
        except OSError:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path.parent)))

    @staticmethod
    def _format_order_date(raw_value: str | None) -> str:
        value = str(raw_value or "").strip()
        if not value:
            return ""
        date_text = value.replace("T", " ")[:10]
        parts = date_text.split("-")
        if len(parts) == 3:
            year, month, day = parts
            if len(year) == 4:
                return f"{day}-{month}-{year}"
        return date_text

    def _build_report_html(self, preview: dict[str, object]) -> str:
        return build_report_html({**self.database.get_report_layout_settings(), **preview})


class InstrumentResultsPage(ResultsPage):
    def __init__(self, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__(
            database,
            deployment_service,
            show_instruments=True,
            show_review=False,
        )
