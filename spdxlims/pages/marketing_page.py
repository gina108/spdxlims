from __future__ import annotations

from datetime import date, datetime
from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from spdxlims.admin_excel import build_marketing_list_sheet, write_admin_export_workbook
from spdxlims.database import Database
from spdxlims.deployment import DeploymentService
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage


class MarketingListPage(DataAwarePage):
    """Build a follow-up/marketing contact list of patients whose selected
    analytes came back out of range (high or low), with Excel export."""

    FILTER_DATE_MIN = QDate(2000, 1, 1)
    COLUMN_COUNT = 8

    def __init__(self, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__()
        self.database = database
        self.deployment_service = deployment_service
        self.test_choices: list[tuple[int, str]] = []
        self.result_rows: list[dict[str, Any]] = []

        root = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        controls = QHBoxLayout()
        controls.addWidget(self._build_analyte_group(), 1)
        controls.addWidget(self._build_filter_group())
        root.addLayout(controls)

        self.results_table = QTableWidget(0, self.COLUMN_COUNT)
        self.results_table.setObjectName('recentPatientsTable')
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        root.addWidget(self.results_table, 1)

        button_row = QHBoxLayout()
        self.result_summary = QLabel()
        self.result_summary.setWordWrap(True)
        button_row.addWidget(self.result_summary, 1)
        self.export_button = QPushButton()
        self.export_button.clicked.connect(self.export_marketing_list)
        button_row.addWidget(self.export_button)
        root.addLayout(button_row)

        self.retranslate_ui()
        self.refresh_data()

    def _build_analyte_group(self) -> QWidget:
        self.analyte_group = QGroupBox()
        self.analyte_group.setObjectName('recentPatientsGroup')
        layout = QVBoxLayout(self.analyte_group)
        self.analyte_info = QLabel()
        self.analyte_info.setWordWrap(True)
        layout.addWidget(self.analyte_info)
        self.analyte_search = QLineEdit()
        self.analyte_search.textChanged.connect(self._filter_analyte_list)
        layout.addWidget(self.analyte_search)
        select_row = QHBoxLayout()
        self.select_all_button = QPushButton()
        self.select_all_button.clicked.connect(lambda: self._set_visible_checked(True))
        self.clear_selection_button = QPushButton()
        self.clear_selection_button.clicked.connect(lambda: self._set_visible_checked(False))
        select_row.addWidget(self.select_all_button)
        select_row.addWidget(self.clear_selection_button)
        select_row.addStretch(1)
        layout.addLayout(select_row)
        self.analyte_list = QListWidget()
        layout.addWidget(self.analyte_list)
        return self.analyte_group

    def _build_filter_group(self) -> QWidget:
        self.filter_group = QGroupBox()
        self.filter_group.setObjectName('recentPatientsGroup')
        layout = QVBoxLayout(self.filter_group)
        self.filter_info = QLabel()
        self.filter_info.setWordWrap(True)
        layout.addWidget(self.filter_info)
        today = QDate.currentDate()
        self.date_from = QDateEdit(today.addYears(-1))
        self.date_to = QDateEdit(today)
        for label_key, widget in (('From', self.date_from), ('To', self.date_to)):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat('yyyy-MM-dd')
            widget.setMinimumDate(self.FILTER_DATE_MIN)
            row = QHBoxLayout()
            field_label = QLabel(tr(label_key))
            field_label.setMinimumWidth(48)
            row.addWidget(field_label)
            row.addWidget(widget, 1)
            layout.addLayout(row)
        self.phone_only_checkbox = QCheckBox()
        layout.addWidget(self.phone_only_checkbox)
        self.generate_button = QPushButton()
        self.generate_button.clicked.connect(self.generate_list)
        layout.addWidget(self.generate_button)
        layout.addStretch(1)
        return self.filter_group

    def retranslate_ui(self) -> None:
        self.summary.setText(
            tr('Build a follow-up contact list of patients whose selected analytes came back out of range.')
        )
        self.analyte_group.setTitle(tr('Analytes'))
        self.analyte_info.setText(tr('Pick one or more analytes. A patient is listed when any selected analyte is high or low.'))
        self.analyte_search.setPlaceholderText(tr('Search analytes'))
        self.select_all_button.setText(tr('Select All'))
        self.clear_selection_button.setText(tr('Clear Selection'))
        self.filter_group.setTitle(tr('Filters'))
        self.filter_info.setText(tr('Limit results by order date, then generate the list.'))
        self.phone_only_checkbox.setText(tr('Only patients with a phone number'))
        self.generate_button.setText(tr('Generate List'))
        self.export_button.setText(tr('Export to Excel'))
        self.results_table.setHorizontalHeaderLabels(self._column_headers())
        self._update_result_summary()

    def _column_headers(self) -> list[str]:
        return [
            tr('Patient'),
            tr('Phone'),
            tr('Email'),
            tr('Sex'),
            tr('Age'),
            tr('Abnormal Analytes'),
            tr('Abnormal Results'),
            tr('Last Result Date'),
        ]

    def refresh_on_show(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        previously_checked = self._checked_test_ids()
        self.test_choices = self.database.list_test_choices()
        self._populate_analyte_list(previously_checked)

    def _populate_analyte_list(self, checked_ids: set[int]) -> None:
        self.analyte_list.clear()
        for test_id, label in self.test_choices:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, test_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if test_id in checked_ids else Qt.Unchecked)
            self.analyte_list.addItem(item)
        self._filter_analyte_list()

    def _filter_analyte_list(self) -> None:
        query = self.analyte_search.text().strip().lower()
        for row in range(self.analyte_list.count()):
            item = self.analyte_list.item(row)
            item.setHidden(bool(query) and query not in item.text().lower())

    def _set_visible_checked(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.analyte_list.count()):
            item = self.analyte_list.item(row)
            if not item.isHidden():
                item.setCheckState(state)

    def _checked_test_ids(self) -> set[int]:
        checked: set[int] = set()
        for row in range(self.analyte_list.count()):
            item = self.analyte_list.item(row)
            if item.checkState() == Qt.Checked:
                checked.add(int(item.data(Qt.UserRole)))
        return checked

    def _filter_date_value(self, widget: QDateEdit) -> str:
        if widget.date() <= self.FILTER_DATE_MIN:
            return ''
        return widget.date().toString('yyyy-MM-dd')

    def generate_list(self) -> None:
        test_ids = sorted(self._checked_test_ids())
        if not test_ids:
            QMessageBox.warning(self, tr('Missing Selection'), tr('Select at least one analyte.'))
            return
        self.result_rows = self.database.list_marketing_abnormal_patients(
            test_ids,
            self._filter_date_value(self.date_from),
            self._filter_date_value(self.date_to),
        )
        if self.phone_only_checkbox.isChecked():
            self.result_rows = [row for row in self.result_rows if str(row.get('phone') or '').strip()]
        self.set_table_rows(self.results_table, [self._row_cells(row) for row in self.result_rows])
        self._update_result_summary()

    def _row_cells(self, row: dict[str, Any]) -> list[str]:
        return [
            str(row.get('patient_name') or ''),
            str(row.get('phone') or ''),
            str(row.get('email') or ''),
            self._format_sex(str(row.get('sex') or '')),
            self._format_age(row),
            self._format_abnormal_tests(str(row.get('abnormal_tests') or '')),
            str(row.get('abnormal_count') or 0),
            str(row.get('last_date') or ''),
        ]

    @staticmethod
    def _format_sex(sex: str) -> str:
        return {'M': tr('Male'), 'F': tr('Female'), 'O': tr('Other')}.get(sex, sex)

    @staticmethod
    def _format_abnormal_tests(raw: str) -> str:
        if not raw:
            return ''
        labels = {'high': tr('high'), 'low': tr('low')}
        parts: list[str] = []
        for entry in raw.split(','):
            entry = entry.strip()
            for flag, translated in labels.items():
                if entry.endswith(f'({flag})'):
                    entry = entry[: -(len(flag) + 2)].strip() + f' ({translated})'
                    break
            parts.append(entry)
        return ', '.join(parts)

    @staticmethod
    def _format_age(row: dict[str, Any]) -> str:
        dob = str(row.get('date_of_birth') or '').strip()
        if dob:
            try:
                born = datetime.strptime(dob, '%Y-%m-%d').date()
                today = date.today()
                years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
                if years >= 0:
                    return tr('{count} y', count=str(years))
            except ValueError:
                pass
        age_value = row.get('age_value')
        age_unit = str(row.get('age_unit') or '').strip()
        if age_value is None:
            return ''
        unit_label = {'years': tr('y'), 'months': tr('mo'), 'days': tr('d')}.get(age_unit, age_unit)
        return f'{age_value} {unit_label}'.strip()

    def _update_result_summary(self) -> None:
        self.result_summary.setText(
            tr('{count} patients match', count=str(len(self.result_rows)))
        )

    def export_marketing_list(self) -> None:
        if not self.result_rows:
            QMessageBox.warning(self, tr('Nothing to Export'), tr('Generate a list before exporting.'))
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr('Save Marketing List'),
            'marketing_list.xlsx',
            tr('Excel Workbook (*.xlsx)'),
        )
        if not path:
            return
        sheets = build_marketing_list_sheet(
            self._column_headers(),
            [self._row_cells(row) for row in self.result_rows],
        )
        target = write_admin_export_workbook(path, sheets)
        QMessageBox.information(self, tr('Saved'), tr('Marketing list saved: {path}', path=str(target)))
