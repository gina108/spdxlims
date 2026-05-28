from __future__ import annotations

import importlib
import json
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
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
from spdxlims.report_export import build_pdf_export_path
from spdxlims.report_layout import build_report_html
from spdxlims.report_service import ReportService
from spdxlims.result_service import ResultService
from spdxlims.whatsapp_templates import default_whatsapp_templates, get_whatsapp_templates

try:
    from PySide6.QtWebEngineCore import QWebEnginePage
except ImportError:  # pragma: no cover
    QWebEnginePage = None


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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._approved_clicked = False
        self._approved = approved
        self._html_renderer = html_renderer
        self._preview = dict(preview)
        self._approved_preview: dict[str, object] | None = None
        self._preview_dirty = False
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

        header_row = QHBoxLayout()
        header_label = QLabel(tr("Header Image"))
        self.header_combo = QComboBox()
        self.header_combo.addItem(tr("No Header Image"), "")
        for label, value in header_options:
            self.header_combo.addItem(label, value)
        selected_index = self.header_combo.findData(selected_header)
        self.header_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        self.header_combo.currentIndexChanged.connect(self._header_changed)
        header_row.addWidget(header_label)
        header_row.addWidget(self.header_combo, 1)
        layout.addLayout(header_row)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        close_button = QPushButton(tr("Close Preview"))
        close_button.clicked.connect(self.reject)
        button_row.addWidget(close_button)

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
    def approved_preview(self) -> dict[str, object] | None:
        return None if self._approved_preview is None else dict(self._approved_preview)

    @property
    def preview_changed(self) -> bool:
        return self._preview_dirty

    @property
    def current_preview(self) -> dict[str, object]:
        return dict(self._preview)

    def _approve_and_export(self) -> None:
        self._approved_clicked = True
        self._approved_preview = dict(self._preview)
        self.accept()

    def _header_changed(self) -> None:
        self._preview["header_image_path"] = self.selected_header
        self._preview_dirty = True
        self._set_preview_html(self._render_preview_html())

    def _edit_report(self) -> None:
        dialog = ReportEditorDialog(self._preview, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._preview = dialog.edited_preview
        self._preview["header_image_path"] = self.selected_header
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
    _ROW_COLUMNS = (
        "item_type",
        "test_name",
        "flag",
        "result_value",
        "unit",
        "reference_text",
        "comments",
    )

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
        self.items_table.setColumnWidth(2, 100)
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
            item_type_combo = QComboBox()
            item_type_combo.setStyleSheet(
                """
                QComboBox {
                    padding: 1px 8px 1px 6px;
                    margin: 0px;
                    min-height: 24px;
                }
                QComboBox::drop-down {
                    width: 18px;
                    border: none;
                }
                """
            )
            item_type_combo.addItem(tr("Test"), "test")
            item_type_combo.addItem(tr("Heading"), "heading")
            item_type_combo.addItem(tr("Comment"), "comment")
            current_index = item_type_combo.findData(str(item.get("item_type") or "test"))
            item_type_combo.setCurrentIndex(current_index if current_index >= 0 else 0)
            self.items_table.setCellWidget(row_index, 0, item_type_combo)
            self._set_table_text(row_index, 1, str(item.get("test_name") or ""), metadata=dict(item))
            self._set_table_text(row_index, 2, str(item.get("flag") or ""))
            self._set_table_text(row_index, 3, str(item.get("result_value") or ""))
            self._set_table_text(row_index, 4, str(item.get("unit") or ""))
            self._set_table_text(row_index, 5, str(item.get("reference_text") or ""))
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
            "flag": self._item_text(row, 2),
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
            index = combo.findData(str(row_data.get("item_type") or "test"))
            combo.setCurrentIndex(index if index >= 0 else 0)
        self._set_table_text(row, 1, str(row_data.get("test_name") or ""), metadata=dict(row_data.get("__source_item") or {}))
        self._set_table_text(row, 2, str(row_data.get("flag") or ""))
        self._set_table_text(row, 3, str(row_data.get("result_value") or ""))
        self._set_table_text(row, 4, str(row_data.get("unit") or ""))
        self._set_table_text(row, 5, str(row_data.get("reference_text") or ""))
        self._set_table_text(row, 6, str(row_data.get("comments") or ""))

    def _item_text(self, row: int, column: int) -> str:
        item = self.items_table.item(row, column)
        return item.text().strip() if item is not None else ""

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
                "flag": self._item_text(row_index, 2),
                "result_value": self._item_text(row_index, 3),
                "unit": self._item_text(row_index, 4),
                "reference_text": self._item_text(row_index, 5),
                "comments": self._item_text(row_index, 6),
                "sort_order": len(edited_items),
            }
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
    def _clone_preview(preview: dict[str, object]) -> dict[str, object]:
        cloned = dict(preview)
        cloned["items"] = [dict(item) for item in list(preview.get("items") or [])]
        return cloned


class ResultsPage(DataAwarePage):
    APPROVALS_KEY = "results_report_approvals"
    ORDER_HEADERS_KEY = "results_report_headers"
    WHATSAPP_SENT_KEY = "results_whatsapp_sent"
    LINKED_INSTRUMENT_CAPTURES_KEY = "results_linked_instrument_captures"

    def __init__(
        self,
        database: Database,
        deployment_service: DeploymentService,
        *,
        show_instruments: bool = False,
        show_review: bool = True,
    ) -> None:
        super().__init__()
        self.database = database
        self.deployment_service = deployment_service
        self.result_service = ResultService(database, deployment_service)
        self.report_service = ReportService(database, deployment_service)
        self.show_instruments = show_instruments
        self.show_review = show_review
        self.current_orders: list[ResultWorkflowRecord] = []
        self.previewed_orders: set[int] = set()
        self.instrument_captures: list[dict[str, object]] = []
        self.instrument_result: dict[str, object] | None = None
        self.instrument_order_entries: list[ResultEntryRecord] = []
        self.engine_url = "http://127.0.0.1:9088"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        if self.show_instruments:
            root.addWidget(self._build_instrument_group())
        if self.show_review:
            root.addWidget(self._build_queue_group())

        self.retranslate_ui()
        self.refresh_on_show()

    def _build_instrument_group(self) -> QWidget:
        self.instrument_group = QGroupBox()
        layout = QVBoxLayout(self.instrument_group)

        self.instrument_summary_label = QLabel()
        self.instrument_summary_label.setWordWrap(True)
        layout.addWidget(self.instrument_summary_label)

        controls = QHBoxLayout()
        self.instrument_profile_input = QLineEdit()
        self.instrument_profile_input.setMinimumWidth(180)
        self.refresh_instrument_button = QPushButton()
        self.refresh_instrument_button.clicked.connect(self.refresh_instrument_captures)
        self.replay_instrument_button = QPushButton()
        self.replay_instrument_button.clicked.connect(self.preview_instrument_capture)
        controls.addWidget(QLabel(tr("Profile")))
        controls.addWidget(self.instrument_profile_input)
        self.hide_empty_instrument_captures_checkbox = QCheckBox()
        self.hide_empty_instrument_captures_checkbox.setChecked(True)
        self.hide_empty_instrument_captures_checkbox.stateChanged.connect(lambda _state: self.refresh_instrument_captures())
        controls.addWidget(self.hide_empty_instrument_captures_checkbox)
        controls.addWidget(self.refresh_instrument_button)
        controls.addWidget(self.replay_instrument_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.instrument_captures_table = QTableWidget(0, 7)
        self.instrument_captures_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.instrument_captures_table.setSelectionMode(QTableWidget.SingleSelection)
        self.instrument_captures_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.instrument_captures_table.verticalHeader().setDefaultSectionSize(38)
        self.instrument_captures_table.itemSelectionChanged.connect(self._instrument_capture_selection_changed)
        capture_header = self.instrument_captures_table.horizontalHeader()
        capture_header.setSectionResizeMode(0, QHeaderView.Fixed)
        capture_header.setSectionResizeMode(1, QHeaderView.Fixed)
        capture_header.setSectionResizeMode(2, QHeaderView.Fixed)
        capture_header.setSectionResizeMode(3, QHeaderView.Fixed)
        capture_header.setSectionResizeMode(4, QHeaderView.Fixed)
        capture_header.setSectionResizeMode(5, QHeaderView.Stretch)
        capture_header.setSectionResizeMode(6, QHeaderView.Fixed)
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
        layout.addWidget(self.instrument_observations_table)

        link_row = QHBoxLayout()
        self.instrument_order_combo = QComboBox()
        self.instrument_order_combo.setMinimumWidth(420)
        self.link_instrument_button = QPushButton()
        self.link_instrument_button.clicked.connect(self.link_instrument_capture_to_order)
        link_row.addWidget(QLabel(tr("Order")))
        link_row.addWidget(self.instrument_order_combo, 1)
        link_row.addWidget(self.link_instrument_button)
        layout.addLayout(link_row)

        mapping_row = QHBoxLayout()
        self.instrument_target_test_combo = QComboBox()
        self.instrument_target_test_combo.setMinimumWidth(420)
        self.save_instrument_mapping_button = QPushButton()
        self.save_instrument_mapping_button.clicked.connect(self.save_selected_instrument_mapping)
        self.instrument_order_combo.currentIndexChanged.connect(self._refresh_instrument_target_test_choices)
        mapping_row.addWidget(QLabel(tr("Map To")))
        mapping_row.addWidget(self.instrument_target_test_combo, 1)
        mapping_row.addWidget(self.save_instrument_mapping_button)
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

    def retranslate_ui(self) -> None:
        if self.show_instruments:
            self.instrument_group.setTitle(tr("Instrument Results"))
            self.instrument_summary_label.setText(
                tr("Load recent machine captures, preview the results, map analyzer codes to order tests, then link the selected capture to the correct order.")
            )
            self.instrument_profile_input.setPlaceholderText(tr("All profiles"))
            self.refresh_instrument_button.setText(tr("Refresh Captures"))
            self.replay_instrument_button.setText(tr("Preview Capture"))
            self.hide_empty_instrument_captures_checkbox.setText(tr("Only captures with data"))
            self.link_instrument_button.setText(tr("Link to Order"))
            self.save_instrument_mapping_button.setText(tr("Save Mapping"))
            self.instrument_captures_table.setHorizontalHeaderLabels(
                [tr("Received"), tr("Sample"), tr("Patient"), tr("Capture"), tr("Device"), tr("Preview"), tr("Profile")]
            )
            self.instrument_observations_table.setHorizontalHeaderLabels(
                [tr("Code"), tr("Test"), tr("Result"), tr("Unit"), tr("Status")]
            )
        if self.show_review:
            self.queue_group.setTitle(tr("Results Review"))
            self.summary_label.setText(tr("Pending report approvals and WhatsApp delivery are managed here."))
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
            self._refresh_instrument_order_choices()
            self.refresh_instrument_captures()
        if self.show_review:
            self._refresh_table()

    def refresh_instrument_captures(self) -> None:
        profile_id = self.instrument_profile_input.text().strip()
        linked = self._linked_instrument_capture_ids()
        hide_empty = self.hide_empty_instrument_captures_checkbox.isChecked()
        limit = 500 if hide_empty else 50
        query = f"/api/v1/captures?limit={limit}"
        if profile_id:
            query += f"&profile_id={quote(profile_id)}"
        try:
            captures = self._instrument_request_json(query)
        except Exception as exc:
            self.instrument_captures = []
            self.instrument_result = None
            self._refresh_instrument_tables()
            self.instrument_status_label.setText(tr("Instrument engine is offline or unavailable: {error}", error=str(exc)))
            return
        if not isinstance(captures, list):
            captures = []
        self.instrument_captures = [
            dict(capture)
            for capture in captures
            if (
                isinstance(capture, dict)
                and str(capture.get("id") or "") not in linked
                and (not hide_empty or self._capture_has_data(capture))
            )
        ]
        self.instrument_result = None
        self._refresh_instrument_tables()
        if hide_empty:
            self.instrument_status_label.setText(
                tr("Loaded {count} pending instrument captures with data.", count=len(self.instrument_captures))
            )
        else:
            self.instrument_status_label.setText(
                tr("Loaded {count} pending instrument captures.", count=len(self.instrument_captures))
            )

    def preview_instrument_capture(self) -> None:
        capture = self._selected_instrument_capture()
        if capture is None:
            QMessageBox.information(self, tr("Missing Selection"), tr("Select an instrument capture first."))
            return
        capture_id = str(capture.get("id") or "").strip()
        profile_id = str(capture.get("profile_id") or self.instrument_profile_input.text().strip() or "urinalysis-com6")
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
        profile_id = str(capture.get("profile_id") or self.instrument_profile_input.text().strip() or "urinalysis-com6")
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
        self.instrument_status_label.setText(
            tr(
                "Saved mapping: {profile} {code} -> {test}.",
                profile=profile_id,
                code=raw_code,
                test=target_entry.test_name,
            )
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
        entries = [entry for entry in self.database.get_order_result_entries(int(order_id)) if entry.item_type == "test"]
        order_test_codes = self.database.list_order_test_codes(int(order_id))
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
        capture_id = str(capture.get("id") or "").strip()
        profile_id = str(capture.get("profile_id") or "").strip()
        device_id = str(capture.get("device_id") or "").strip()
        for obs in observations:
            code = self._observation_raw_code(obs)
            mapping = self.database.resolve_instrument_result_mapping(
                instrument_profile=profile_id or self.instrument_profile_input.text().strip(),
                device_id=device_id,
                raw_code=code,
                specimen_type=str(obs.get("specimen_type") or obs.get("sample_type") or ""),
                panel_hint=str(obs.get("panel_hint") or obs.get("panel") or ""),
            )
            if mapping is None:
                for candidate_entry in entries:
                    candidate_mapping = self.database.resolve_instrument_result_mapping(
                        instrument_profile=profile_id or self.instrument_profile_input.text().strip(),
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
                unmatched_codes.append(code or tr("unknown"))
                continue
            result_value = self._instrument_observation_value(obs, entry.result_kind)
            unit = str(
                (mapping.unit_override if mapping is not None else "")
                or obs.get("units_normalized")
                or obs.get("units_raw")
                or entry.unit
                or ""
            ).strip()
            reference_text = (
                mapping.reference_range_override
                if mapping is not None and mapping.reference_range_override
                else entry.reference_text or ""
            )
            comment = self._instrument_link_comment(capture_id, profile_id, device_id, code, mapping)
            self.database.save_result_entry(
                order_test_id=int(entry.order_test_id),
                result_value=result_value,
                unit=unit,
                lower_value=entry.lower_value,
                upper_value=entry.upper_value,
                reference_text=reference_text,
                comments=comment,
                result_kind=entry.result_kind,
            )
            imported_count += 1
        if imported_count == 0:
            QMessageBox.warning(
                self,
                tr("Import Failed"),
                tr("No order tests matched the instrument codes: {codes}", codes=", ".join(unmatched_codes)),
            )
            return
        self._mark_instrument_capture_linked(capture_id, int(order_id))
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
        self.instrument_captures_table.blockSignals(True)
        self.instrument_captures_table.clearContents()
        self.instrument_captures_table.setRowCount(len(self.instrument_captures))
        self.instrument_captures_table.setColumnWidth(0, 135)
        self.instrument_captures_table.setColumnWidth(1, 105)
        self.instrument_captures_table.setColumnWidth(2, 150)
        self.instrument_captures_table.setColumnWidth(3, 125)
        self.instrument_captures_table.setColumnWidth(4, 90)
        self.instrument_captures_table.setColumnWidth(6, 120)
        for row_index, capture in enumerate(self.instrument_captures):
            self._set_instrument_capture_item(row_index, 0, self._format_capture_datetime(str(capture.get("received_at") or "")), capture)
            self._set_instrument_capture_item(row_index, 1, self._capture_sample_id(capture), capture)
            self._set_instrument_capture_item(row_index, 2, self._capture_patient_name(capture), capture)
            self._set_instrument_capture_item(row_index, 3, str(capture.get("id") or ""), capture)
            self._set_instrument_capture_item(row_index, 4, str(capture.get("device_id") or ""), capture)
            self._set_instrument_capture_item(row_index, 5, self._capture_preview(capture), capture)
            self._set_instrument_capture_item(row_index, 6, str(capture.get("profile_id") or ""), capture)
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
        self.instrument_observations_table.setColumnWidth(2, 110)
        self.instrument_observations_table.setColumnWidth(3, 90)
        self.instrument_observations_table.setColumnWidth(4, 100)
        capture = self._selected_instrument_capture() or {}
        profile_id = str(capture.get("profile_id") or self.instrument_profile_input.text().strip() or "")
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
            self._set_observation_item(row_index, 2, self._instrument_observation_value(obs, "text"))
            self._set_observation_item(row_index, 3, str(obs.get("units_normalized") or obs.get("units_raw") or ""))
            self._set_observation_item(row_index, 4, status)

    def _instrument_capture_selection_changed(self) -> None:
        self.instrument_result = self._instrument_result_from_capture(self._selected_instrument_capture() or {})
        self._refresh_instrument_observations_table()

    def _set_instrument_capture_item(self, row: int, column: int, value: str, capture: dict[str, object]) -> None:
        item = QTableWidgetItem(value)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        item.setData(Qt.UserRole, capture)
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

    def _linked_instrument_capture_ids(self) -> set[str]:
        ui_state = self.database.get_ui_state()
        raw = ui_state.get(self.LINKED_INSTRUMENT_CAPTURES_KEY, {})
        if not isinstance(raw, dict):
            return set()
        return {str(capture_id) for capture_id in raw.keys()}

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
        value = str(raw_value or "").strip().replace("T", " ")
        if not value:
            return ""
        value = value.replace("Z", "")
        return value[:16]

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
        if result_kind == "numeric" and obs.get("value_numeric") is not None:
            return f"{float(obs['value_numeric']):g}"
        for key in ("value_text", "value_raw", "value_numeric"):
            value = obs.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    @classmethod
    def _observation_raw_code(cls, obs: dict[str, object]) -> str:
        return cls._normalize_test_code(str(obs.get("instrument_test_code") or obs.get("mapped_lis_test_id") or ""))

    @staticmethod
    def _instrument_link_comment(
        capture_id: str,
        profile_id: str,
        device_id: str,
        code: str,
        mapping: InstrumentResultMappingRecord | None = None,
    ) -> str:
        payload = {
            "source": "instrument",
            "capture_id": capture_id,
            "profile": profile_id,
            "device": device_id,
            "instrument_code": code,
        }
        if mapping is not None:
            payload["mapping_id"] = mapping.id
            payload["mapped_test_code"] = mapping.test_code
        return json.dumps(
            payload,
            ensure_ascii=True,
        )

    def _refresh_table(self) -> None:
        self.orders_table.clearContents()
        self.orders_table.setRowCount(len(self.current_orders))
        self.orders_table.setColumnWidth(0, 104)
        self.orders_table.setColumnWidth(1, 74)
        self.orders_table.setColumnWidth(2, 210)
        self.orders_table.setColumnWidth(3, 160)
        self.orders_table.setColumnWidth(4, 104)
        self.orders_table.setColumnWidth(5, 52)
        self.orders_table.setColumnWidth(6, 104)
        self.orders_table.setColumnWidth(7, 104)

        approvals = self._approved_versions()
        for row_index, order in enumerate(self.current_orders):
            self._set_item(row_index, 0, self._format_order_date(order.order_date))
            self._set_item(row_index, 1, order.order_number)
            self._set_item(row_index, 2, order.patient_name)
            self._set_item(row_index, 3, order.client_name or "")

            approved = approvals.get(order.id) == int(order.report_version or 0) and int(order.report_version or 0) > 0

            preview_button = QPushButton(tr("Preview Report"))
            preview_button.setStyleSheet(self._results_action_button_style())
            preview_button.clicked.connect(lambda _checked=False, order_id=order.id: self.preview_report(order_id))
            self.orders_table.setCellWidget(row_index, 4, self._build_centered_cell_widget(preview_button))

            self.orders_table.setCellWidget(row_index, 5, self._build_status_indicator(approved, order.id in self.previewed_orders))

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

    def _build_status_indicator(self, approved: bool, previewed: bool) -> QWidget:
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
            "color: #14171c;"
            "border: 1px solid #bd93f9;"
            "border-radius: 7px;"
            "padding: 2px 6px;"
            "font-weight: 600;"
            "font-size: 10px;"
            "min-height: 22px;"
            "max-height: 26px;"
            "min-width: 72px;"
            "}"
            "QPushButton:hover {"
            "background-color: #caa8fb;"
            "border-color: #caa8fb;"
            "}"
            "QPushButton:pressed {"
            "background-color: #a97cf2;"
            "border-color: #a97cf2;"
            "}"
            "QPushButton:disabled {"
            "background-color: #39424d;"
            "border-color: #39424d;"
            "color: #98a0a8;"
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
        preview["header_image_path"] = selected_header
        order = self._find_order(order_id)
        current_version = int(order.report_version or 0) if order is not None else int(preview.get("report_version") or 0)
        approved = self._approved_versions().get(order_id) == current_version and current_version > 0
        dialog = ReportPreviewDialog(
            preview,
            self._build_report_html,
            can_approve=True,
            approved=approved,
            header_options=self._header_options(),
            selected_header=selected_header,
            parent=self,
        )
        dialog.exec()
        self._save_selected_header_for_order(order_id, dialog.selected_header)
        if dialog.approved_clicked:
            self.approve_report(order_id, preview_override=dialog.approved_preview, export_pdf=True)
            return
        if approved and dialog.preview_changed:
            self.approve_report(
                order_id,
                preview_override=dialog.current_preview,
                export_pdf=False,
                success_message=tr("Approved report changes saved. WhatsApp sending will use the updated report."),
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
        try:
            self.report_service.finalize_report(order_id, header_image_path=selected_header, preview_override=preview_override)
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
        exported_path: Path | None = None
        if export_pdf:
            exported_path = self._export_report_pdf_for_whatsapp(order_id)
            if exported_path is not None:
                self._reveal_file_in_explorer(exported_path)
        QMessageBox.information(
            self,
            tr("Saved"),
            success_message
            if success_message
            else (
                tr("Report approved and PDF exported. WhatsApp sending is now enabled.")
                if exported_path is not None
                else tr("Report approved. WhatsApp sending is now enabled.")
            ),
        )

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
        normalized_phone = "".join(character for character in phone if character.isdigit())
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
        return build_report_html(preview)


class InstrumentResultsPage(ResultsPage):
    def __init__(self, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__(
            database,
            deployment_service,
            show_instruments=True,
            show_review=False,
        )
