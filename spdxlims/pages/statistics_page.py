from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from spdxlims.admin_excel import write_admin_export_workbook
from spdxlims.database import Database
from spdxlims.deployment import DeploymentService
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.statistics_service import StatisticsService


class StatisticsPage(DataAwarePage):
    """Operational analytics: order/test/panel volume, referral volume, inventory usage."""

    FILTER_DATE_MIN = QDate(2000, 1, 1)

    def __init__(self, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__()
        self.database = database
        self.deployment_service = deployment_service
        self.stats_service = StatisticsService(database, deployment_service)
        self._current_headers: list[str] = []
        self._current_rows: list[list[str]] = []

        # Each report: column definitions as (header translation key, dict key,
        # numeric?), whether it accepts the client filter, and the dimension the
        # second ("subject") filter is scoped to ("subject_kind"/"subject_label").
        self._reports: dict[str, dict[str, Any]] = {
            "test_volume": {
                "label": "Test volume",
                "columns": [
                    ("Code", "test_code", False),
                    ("Test", "test_name", False),
                    ("Category", "category", False),
                    ("Times Ordered", "times_ordered", True),
                ],
                "needs_client": True,
                "subject_kind": "test",
                "subject_label": "Test",
                "runner": self._run_test_volume,
            },
            "panel_volume": {
                "label": "Panel volume",
                "columns": [
                    ("Panel", "panel", False),
                    ("Times Ordered", "times_ordered", True),
                    ("Tests Included", "test_instances", True),
                ],
                "needs_client": True,
                "subject_kind": "panel",
                "subject_label": "Panel",
                "runner": self._run_panel_volume,
            },
            "client_volume": {
                "label": "Client volume",
                "columns": [
                    ("Client", "client_name", False),
                    ("Orders", "order_count", True),
                    ("Tests", "test_count", True),
                ],
                "needs_client": False,
                "subject_kind": "client",
                "subject_label": "Client",
                "runner": self._run_client_volume,
            },
            "doctor_volume": {
                "label": "Referring doctor volume",
                "columns": [
                    ("Doctor", "doctor_name", False),
                    ("Orders", "order_count", True),
                    ("Tests", "test_count", True),
                ],
                "needs_client": False,
                "subject_kind": "doctor",
                "subject_label": "Doctor",
                "runner": self._run_doctor_volume,
            },
            "inventory_usage": {
                "label": "Inventory usage",
                "columns": [
                    ("Item", "item_name", False),
                    ("SKU", "sku", False),
                    ("Unit", "unit", False),
                    ("Purchased", "purchased", True),
                    ("Consumed", "consumed", True),
                    ("Adjusted", "adjusted", True),
                    ("Net Change", "net_change", True),
                    ("On Hand", "on_hand", True),
                    ("Reorder Level", "reorder_level", True),
                ],
                "needs_client": False,
                "subject_kind": None,
                "subject_label": "Filter",
                "runner": self._run_inventory_usage,
            },
        }
        self._report_order = [
            "test_volume",
            "panel_volume",
            "client_volume",
            "doctor_volume",
            "inventory_usage",
        ]

        root = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        self.group = QGroupBox()
        self.group.setObjectName("recentPatientsGroup")
        layout = QVBoxLayout(self.group)

        form = QFormLayout()
        self.report_combo = QComboBox()
        self.report_combo.currentIndexChanged.connect(self._on_report_changed)
        self.client_filter = QComboBox()
        _today = QDate.currentDate()
        self.date_from = QDateEdit(_today.addMonths(-1))
        self.date_to = QDateEdit(_today)
        for widget in (self.date_from, self.date_to):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd")
            widget.setMinimumDate(self.FILTER_DATE_MIN)
            widget.setSpecialValueText(" ")
            widget.setMinimumWidth(160)
            widget.setMaximumWidth(190)
            widget.setMinimumHeight(38)
            widget.setStyleSheet("QDateEdit { padding-top: 2px; padding-bottom: 2px; }")

        # Subject filter picker shown next to the date range: choosing a doctor,
        # panel, or test adds it to the selected-subjects list below. Editable +
        # contains-completer to cope with long lists.
        self.subject_filter = QComboBox()
        self.subject_filter.setEditable(True)
        self.subject_filter.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.subject_filter.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.subject_filter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.subject_filter.setMinimumContentsLength(16)
        self.subject_filter.activated.connect(self._add_subject_from_combo)

        # The accumulated subjects (one or more panels/tests/doctors), removable.
        self.subject_list = QListWidget()
        self.subject_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.subject_list.setMaximumHeight(96)
        self.subject_list.itemDoubleClicked.connect(lambda item: self._remove_subject_item(item))
        self.remove_subject_button = QPushButton()
        self.remove_subject_button.clicked.connect(self._remove_selected_subjects)
        self.clear_subjects_button = QPushButton()
        self.clear_subjects_button.clicked.connect(self._clear_subjects)

        self.report_label = QLabel()
        self.date_range_label = QLabel()
        self.client_label = QLabel()
        self.subjects_row_label = QLabel()
        date_row = QWidget()
        date_layout = QHBoxLayout(date_row)
        date_layout.setContentsMargins(0, 0, 0, 0)
        self.from_caption = QLabel()
        self.to_caption = QLabel()
        self.subject_caption = QLabel()
        date_layout.addWidget(self.from_caption)
        date_layout.addWidget(self.date_from)
        date_layout.addWidget(self.to_caption)
        date_layout.addWidget(self.date_to)
        date_layout.addSpacing(12)
        date_layout.addWidget(self.subject_caption)
        date_layout.addWidget(self.subject_filter, 1)

        self.subjects_row = QWidget()
        subjects_layout = QHBoxLayout(self.subjects_row)
        subjects_layout.setContentsMargins(0, 0, 0, 0)
        subjects_layout.addWidget(self.subject_list, 1)
        subject_buttons = QVBoxLayout()
        subject_buttons.setContentsMargins(0, 0, 0, 0)
        subject_buttons.addWidget(self.remove_subject_button)
        subject_buttons.addWidget(self.clear_subjects_button)
        subject_buttons.addStretch(1)
        subjects_layout.addLayout(subject_buttons)

        form.addRow(self.report_label, self.report_combo)
        form.addRow(self.date_range_label, date_row)
        form.addRow(self.subjects_row_label, self.subjects_row)
        form.addRow(self.client_label, self.client_filter)
        layout.addLayout(form)

        actions = QHBoxLayout()
        self.run_button = QPushButton()
        self.run_button.clicked.connect(self.run_report)
        self.all_dates_button = QPushButton()
        self.all_dates_button.clicked.connect(self._clear_dates)
        self.export_button = QPushButton()
        self.export_button.clicked.connect(self.export_excel)
        actions.addWidget(self.run_button)
        actions.addWidget(self.all_dates_button)
        actions.addStretch(1)
        actions.addWidget(self.export_button)
        layout.addLayout(actions)

        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.table = QTableWidget(0, 0)
        self.table.setObjectName("recentPatientsTable")
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        root.addWidget(self.group, 1)

        self.retranslate_ui()
        self.refresh_choices()

    # ----- report runners (return list[dict]) -----
    def _run_test_volume(self) -> list[dict[str, Any]]:
        return self.stats_service.report_test_volume(*self._date_args(), client_id=self.client_filter.currentData(), subjects=self._subjects())

    def _run_panel_volume(self) -> list[dict[str, Any]]:
        return self.stats_service.report_panel_volume(*self._date_args(), client_id=self.client_filter.currentData(), subjects=self._subjects())

    def _run_client_volume(self) -> list[dict[str, Any]]:
        return self.stats_service.report_client_volume(*self._date_args(), subjects=self._subjects())

    def _run_doctor_volume(self) -> list[dict[str, Any]]:
        return self.stats_service.report_doctor_volume(*self._date_args(), subjects=self._subjects())

    def _run_inventory_usage(self) -> list[dict[str, Any]]:
        return self.stats_service.report_inventory_usage(*self._date_args())

    # ----- ui plumbing -----
    def retranslate_ui(self) -> None:
        self.summary.setText(tr("Operational reports: order, test, panel and referral volume plus inventory usage for a date range."))
        self.group.setTitle(tr("Statistics"))
        self.report_label.setText(tr("Report"))
        self.date_range_label.setText(tr("Date Range"))
        self.client_label.setText(tr("Client Filter"))
        self.from_caption.setText(tr("From"))
        self.to_caption.setText(tr("To"))
        self.subjects_row_label.setText(tr("Selected"))
        self.remove_subject_button.setText(tr("Remove"))
        self.clear_subjects_button.setText(tr("Clear"))
        self.run_button.setText(tr("Run Report"))
        self.all_dates_button.setText(tr("All Dates"))
        self.export_button.setText(tr("Export to Excel"))
        current_key = self.report_combo.currentData()
        self.report_combo.blockSignals(True)
        self.report_combo.clear()
        for key in self._report_order:
            self.report_combo.addItem(tr(self._reports[key]["label"]), key)
        index = self.report_combo.findData(current_key or self._report_order[0])
        self.report_combo.setCurrentIndex(index if index >= 0 else 0)
        self.report_combo.blockSignals(False)
        self._populate_subject_filter()
        self._update_filter_visibility()
        if self._current_headers:
            self._render_rows(self._current_headers, self._current_rows)

    def refresh_on_show(self) -> None:
        self.refresh_choices()

    def refresh_choices(self) -> None:
        self.set_combo_items(
            self.client_filter,
            [(label, client_id) for client_id, label in self.stats_service.list_client_choices(active_only=True)],
            placeholder=tr("All clients"),
            selected_data=self.client_filter.currentData(),
        )
        self._populate_subject_filter()

    def _populate_subject_filter(self) -> None:
        """Fill the second filter with only the current report's dimension."""
        kind = self._reports[self._current_report_key()].get("subject_kind")
        self.subject_filter.blockSignals(True)
        self.subject_filter.clear()
        self.subject_filter.addItem(tr("Add filter…"), None)
        for value, label in self._subject_options(kind):
            self.subject_filter.addItem(label, (kind, value))
        self.subject_filter.setCurrentIndex(0)
        self.subject_filter.blockSignals(False)

    def _subject_options(self, kind: str | None) -> list[tuple[Any, str]]:
        if kind == "test":
            return [(test_id, label) for test_id, label in self.stats_service.list_test_choices()]
        if kind == "panel":
            return [(forms, label) for forms, label in self.stats_service.list_panel_filter_options()]
        if kind == "doctor":
            return [(doctor_id, label) for doctor_id, label in self.stats_service.list_doctor_choices(active_only=True)]
        if kind == "client":
            return [(client_id, label) for client_id, label in self.stats_service.list_client_choices(active_only=True)]
        return []

    def _add_subject_from_combo(self, index: int) -> None:
        data = self.subject_filter.itemData(index)
        if data:
            self._add_subject(data[0], data[1], self.subject_filter.itemText(index))
        self.subject_filter.setCurrentIndex(0)

    def _add_subject(self, kind: str, value: Any, label: str) -> None:
        for i in range(self.subject_list.count()):
            existing = self.subject_list.item(i).data(Qt.UserRole)
            if existing and existing[0] == kind and str(existing[1]) == str(value):
                return  # already selected
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, (kind, value))
        self.subject_list.addItem(item)

    def _remove_subject_item(self, item: QListWidgetItem) -> None:
        self.subject_list.takeItem(self.subject_list.row(item))

    def _remove_selected_subjects(self) -> None:
        for item in self.subject_list.selectedItems():
            self.subject_list.takeItem(self.subject_list.row(item))

    def _clear_subjects(self) -> None:
        self.subject_list.clear()

    def _subjects(self) -> list[tuple[str, Any]]:
        subjects: list[tuple[str, Any]] = []
        for i in range(self.subject_list.count()):
            data = self.subject_list.item(i).data(Qt.UserRole)
            if data:
                subjects.append((data[0], data[1]))
        return subjects

    def _current_report_key(self) -> str:
        return str(self.report_combo.currentData() or self._report_order[0])

    def _on_report_changed(self, *_args: object) -> None:
        # Switching report changes the subject dimension, so reset the picker and
        # any previously selected subjects (a panel makes no sense for a doctor report).
        self._clear_subjects()
        self._populate_subject_filter()
        self._update_filter_visibility()

    def _update_filter_visibility(self) -> None:
        report = self._reports[self._current_report_key()]
        needs_client = bool(report["needs_client"])
        self.client_label.setVisible(needs_client)
        self.client_filter.setVisible(needs_client)
        # The second filter is scoped to the report's dimension; hide it for
        # reports that have no selectable dimension (inventory usage).
        has_subject = report.get("subject_kind") is not None
        self.subject_caption.setText(tr(report.get("subject_label") or "Filter"))
        self.subject_caption.setVisible(has_subject)
        self.subject_filter.setVisible(has_subject)
        self.subjects_row_label.setVisible(has_subject)
        self.subjects_row.setVisible(has_subject)

    def _date_args(self) -> tuple[str, str]:
        return self._filter_date_value(self.date_from), self._filter_date_value(self.date_to)

    def _filter_date_value(self, widget: QDateEdit) -> str:
        if widget.date() <= self.FILTER_DATE_MIN:
            return ""
        return widget.date().toString("yyyy-MM-dd")

    def _clear_dates(self) -> None:
        for widget in (self.date_from, self.date_to):
            widget.setDate(self.FILTER_DATE_MIN)

    def run_report(self) -> None:
        report = self._reports[self._current_report_key()]
        runner: Callable[[], list[dict[str, Any]]] = report["runner"]
        try:
            records = runner()
        except Exception as exc:  # noqa: BLE001 - surface any query failure to the user
            QMessageBox.critical(self, tr("Report Failed"), str(exc))
            return
        columns = report["columns"]
        headers = [tr(header) for header, _key, _numeric in columns]
        rows: list[list[str]] = []
        for record in records:
            row: list[str] = []
            for _header, key, numeric in columns:
                row.append(self._format_value(record.get(key), numeric))
            rows.append(row)
        self._current_headers = headers
        self._current_rows = rows
        self._render_rows(headers, rows)
        self.status.setText(tr("Rows: {count}", count=str(len(rows))))

    def _render_rows(self, headers: list[str], rows: list[list[str]]) -> None:
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.set_table_rows(self.table, rows)

    @staticmethod
    def _format_value(value: Any, numeric: bool) -> str:
        if value is None:
            return ""
        if numeric:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return str(value)
            if number == int(number):
                return str(int(number))
            return f"{number:.2f}"
        return str(value)

    def export_excel(self) -> None:
        if not self._current_headers or not self._current_rows:
            QMessageBox.warning(self, tr("Nothing to Export"), tr("Run a report before exporting."))
            return
        report = self._reports[self._current_report_key()]
        sheet_name = tr(report["label"])[:31] or "Report"
        default_name = f"{sheet_name}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, tr("Export to Excel"), default_name, tr("Excel File (*.xlsx)"))
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".xlsx":
            target = target.with_suffix(".xlsx")
        sheets = {sheet_name: [list(self._current_headers), *[list(row) for row in self._current_rows]]}
        try:
            written = write_admin_export_workbook(target, sheets)
        except Exception as exc:  # noqa: BLE001 - surface any export failure to the user
            QMessageBox.critical(self, tr("Export Failed"), str(exc))
            return
        QMessageBox.information(self, tr("Saved"), tr("Report exported: {path}", path=str(written)))
