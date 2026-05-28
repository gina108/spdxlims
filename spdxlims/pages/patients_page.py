from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database, PatientRecord
from spdxlims.deployment import DeploymentService
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.patient_dialog import PatientDialog
from spdxlims.patient_service import PatientService


class PatientsPage(DataAwarePage):
    def __init__(self, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__()
        self.database = database
        self.patient_service = PatientService(database, deployment_service)
        self.patient_records: list[PatientRecord] = []
        self.status_filter = 'active'

        root = QVBoxLayout(self)

        header = QHBoxLayout()
        self.summary = QLabel()
        self.status_filter_label = QLabel()
        self.status_filter_combo = QComboBox()
        self.status_filter_combo.currentIndexChanged.connect(self._change_status_filter)
        self.add_patient_button = QPushButton()
        self.add_patient_button.clicked.connect(self.open_patient_dialog)
        self.edit_patient_button = QPushButton()
        self.edit_patient_button.clicked.connect(self.edit_selected_patient)
        header.addWidget(self.summary, 1)
        header.addWidget(self.status_filter_label)
        header.addWidget(self.status_filter_combo)
        header.addWidget(self.add_patient_button)
        header.addWidget(self.edit_patient_button)
        root.addLayout(header)

        content = QHBoxLayout()
        content.addWidget(self._build_recent_group(), 1)
        content.addWidget(self._build_all_group(), 1)
        root.addLayout(content, 1)

        self.retranslate_ui()
        self.refresh_patients()

    def _build_recent_group(self) -> QWidget:
        self.recent_group = QGroupBox()
        self.recent_group.setObjectName("recentPatientsGroup")
        layout = QVBoxLayout(self.recent_group)

        self.recent_info = QLabel()
        self.recent_info.setWordWrap(True)
        self.recent_search = QLineEdit()
        self.recent_search.textChanged.connect(self._apply_filters)
        self.recent_table = QTableWidget(0, 7)
        self.recent_table.setObjectName("recentPatientsTable")
        self.recent_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.recent_table.setSelectionMode(QTableWidget.SingleSelection)
        self.recent_table.cellDoubleClicked.connect(lambda _row, _col: self.edit_selected_recent_patient())
        self.recent_table.horizontalHeader().setStretchLastSection(True)
        self.recent_table.setMinimumHeight(320)

        layout.addWidget(self.recent_info)
        layout.addWidget(self.recent_search)
        layout.addWidget(self.recent_table)
        return self.recent_group

    def _build_all_group(self) -> QWidget:
        self.all_group = QGroupBox()
        self.all_group.setObjectName("recentPatientsGroup")
        layout = QVBoxLayout(self.all_group)

        self.all_info = QLabel()
        self.all_info.setWordWrap(True)
        self.all_search = QLineEdit()
        self.all_search.textChanged.connect(self._apply_filters)
        self.all_table = QTableWidget(0, 7)
        self.all_table.setObjectName("recentPatientsTable")
        self.all_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.all_table.setSelectionMode(QTableWidget.SingleSelection)
        self.all_table.cellDoubleClicked.connect(lambda _row, _col: self.edit_selected_all_patient())
        self.all_table.horizontalHeader().setStretchLastSection(True)
        self.all_table.setMinimumHeight(320)

        layout.addWidget(self.all_info)
        layout.addWidget(self.all_search)
        layout.addWidget(self.all_table)
        return self.all_group

    def retranslate_ui(self) -> None:
        self.summary.setText(tr("Use this page to find recent patients, search the full list, or register a new patient."))
        self.status_filter_label.setText(tr("Show"))
        current_status = self.status_filter_combo.currentData()
        self.status_filter_combo.clear()
        self.status_filter_combo.addItem(tr("Active Only"), 'active')
        self.status_filter_combo.addItem(tr("Archived Only"), 'archived')
        self.status_filter_combo.addItem(tr("All"), 'all')
        status_index = self.status_filter_combo.findData(current_status or self.status_filter)
        self.status_filter_combo.setCurrentIndex(status_index if status_index >= 0 else 0)
        self.add_patient_button.setText(tr("New Patient"))
        self.edit_patient_button.setText(tr("Edit Patient"))

        self.recent_group.setTitle(tr("Recent Patients"))
        self.recent_info.setText(tr("Recently added patients appear here for quick access."))
        self.recent_search.setPlaceholderText(tr("Search recent patients"))

        self.all_group.setTitle(tr("All Patients"))
        self.all_info.setText(tr("Search the full local patient directory."))
        self.all_search.setPlaceholderText(tr("Search all patients"))

        headers = [tr("ID"), tr("First Name"), tr("Last Name"), tr("Middle Name"), tr("Sex"), tr("Age"), tr("DOB")]
        self.recent_table.setHorizontalHeaderLabels(headers)
        self.all_table.setHorizontalHeaderLabels(headers)

    def open_patient_dialog(self) -> None:
        dialog = PatientDialog(self.patient_service, self)
        if dialog.exec() == QDialog.Accepted and dialog.patient_id is not None:
            self.refresh_patients()
            self.notify_data_changed()

    def edit_selected_recent_patient(self) -> None:
        row = self.recent_table.currentRow()
        recent_records = self.patient_records[:20]
        filtered = self._filter_records(recent_records, self.recent_search.text().strip().lower())
        if row < 0 or row >= len(filtered):
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a patient first."))
            return
        self._open_patient_editor(filtered[row].id)

    def edit_selected_all_patient(self) -> None:
        row = self.all_table.currentRow()
        filtered = self._filter_records(self.patient_records, self.all_search.text().strip().lower())
        if row < 0 or row >= len(filtered):
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a patient first."))
            return
        self._open_patient_editor(filtered[row].id)

    def edit_selected_patient(self) -> None:
        if self.recent_table.hasFocus() and self.recent_table.currentRow() >= 0:
            self.edit_selected_recent_patient()
            return
        if self.all_table.currentRow() >= 0:
            self.edit_selected_all_patient()
            return
        QMessageBox.warning(self, tr("Missing Selection"), tr("Select a patient first."))

    def _open_patient_editor(self, patient_id: int | str) -> None:
        dialog = PatientDialog(self.patient_service, self, patient_id=patient_id)
        if dialog.exec() == QDialog.Accepted and dialog.patient_id is not None:
            self.refresh_patients()
            self.notify_data_changed()

    def refresh_on_show(self) -> None:
        self.refresh_patients()

    def refresh_patients(self) -> None:
        try:
            self.patient_records = self.patient_service.list_patients(status_filter=self.status_filter)
        except RuntimeError as exc:
            self.patient_records = []
            QMessageBox.warning(self, tr("Connection Test"), str(exc))
        self._apply_filters()

    def _change_status_filter(self) -> None:
        self.status_filter = str(self.status_filter_combo.currentData() or 'active')
        self.refresh_patients()

    def _apply_filters(self) -> None:
        recent_query = self.recent_search.text().strip().lower()
        all_query = self.all_search.text().strip().lower()

        recent_records = self.patient_records[:20]
        self.set_table_rows(self.recent_table, [self._patient_row(record) for record in self._filter_records(recent_records, recent_query)])
        self.set_table_rows(self.all_table, [self._patient_row(record) for record in self._filter_records(self.patient_records, all_query)])

    def _filter_records(self, records: list[PatientRecord], query: str) -> list[PatientRecord]:
        if not query:
            return records
        return [record for record in records if query in self._patient_search_text(record)]

    def _patient_search_text(self, record: PatientRecord) -> str:
        parts = [
            str(record.id),
            record.patient_code or "",
            record.first_name,
            record.last_name,
            record.middle_name or "",
            record.sex or "",
            record.phone or "",
            record.date_of_birth or "",
            self._format_age(record.age_value, record.age_unit),
        ]
        return " ".join(parts).lower()

    def _patient_row(self, record: PatientRecord) -> tuple[str, str, str, str, str, str, str]:
        return (
            str(record.id),
            record.first_name,
            record.last_name,
            record.middle_name or "",
            record.sex or "",
            self._format_age(record.age_value, record.age_unit),
            record.date_of_birth or "",
        )

    @staticmethod
    def _format_age(age_value: int | None, age_unit: str | None) -> str:
        if age_value is None or not age_unit:
            return ""
        return f"{age_value} {tr(age_unit)}"
