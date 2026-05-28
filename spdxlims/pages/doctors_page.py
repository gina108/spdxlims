from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
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

from spdxlims.database import Database, DoctorRecord
from spdxlims.deployment import DeploymentService
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.pages.orders_page import DoctorDialog
from spdxlims.provider_service import ProviderService


class ServerDoctorDialog(QDialog):
    def __init__(self, provider_service: ProviderService, parent: QWidget | None = None, doctor_id: int | str | None = None) -> None:
        super().__init__(parent)
        self.provider_service = provider_service
        self.doctor_id = doctor_id
        self._is_active = True
        self.setWindowTitle(tr('Edit Doctor') if doctor_id is not None else tr('New Doctor'))
        self.setModal(True)
        self.resize(420, 260)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.full_name = QLineEdit()
        self.license_number = QLineEdit()
        self.phone = QLineEdit()
        self.email = QLineEdit()
        form.addRow(tr('Doctor'), self.full_name)
        form.addRow(tr('License'), self.license_number)
        form.addRow(tr('Phone'), self.phone)
        form.addRow(tr('Email'), self.email)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.archive_button = QPushButton()
        self.archive_button.clicked.connect(self.toggle_archive)
        cancel = QPushButton(tr('Cancel'))
        cancel.clicked.connect(self.reject)
        save = QPushButton(tr('Update Doctor') if doctor_id is not None else tr('Save Doctor'))
        save.clicked.connect(self.save)
        buttons.addStretch(1)
        if doctor_id is not None:
            buttons.addWidget(self.archive_button)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        if doctor_id is not None:
            self._load()

    def _load(self) -> None:
        doctor = self.provider_service.get_doctor(self.doctor_id)
        if doctor is None:
            return
        self.full_name.setText(str(doctor.get('full_name') or ''))
        self.license_number.setText(str(doctor.get('license_number') or ''))
        self.phone.setText(str(doctor.get('phone') or ''))
        self.email.setText(str(doctor.get('email') or ''))
        self._is_active = bool(doctor.get('is_active', 1))
        self.archive_button.setText(tr('Archive Doctor') if self._is_active else tr('Unarchive Doctor'))

    def toggle_archive(self) -> None:
        if self.doctor_id is None:
            return
        try:
            if self._is_active:
                self.provider_service.archive_provider(self.doctor_id)
            else:
                self.provider_service.unarchive_provider(self.doctor_id)
        except RuntimeError as exc:
            QMessageBox.critical(self, tr('Save Failed'), str(exc))
            return
        self.accept()

    def save(self) -> None:
        if not self.full_name.text().strip():
            QMessageBox.warning(self, tr('Missing Data'), tr('Doctor name is required.'))
            return
        try:
            self.doctor_id = self.provider_service.save_doctor(
                {
                    'full_name': self.full_name.text(),
                    'license_number': self.license_number.text(),
                    'phone': self.phone.text(),
                    'email': self.email.text(),
                },
                self.doctor_id,
            )
        except RuntimeError as exc:
            QMessageBox.critical(self, tr('Save Failed'), str(exc))
            return
        self.accept()


class DoctorsPage(DataAwarePage):
    def __init__(self, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__()
        self.database = database
        self.deployment_service = deployment_service
        self.provider_service = ProviderService(database, deployment_service)
        self.doctor_records: list[DoctorRecord] = []
        self.status_filter = 'active'

        root = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        root.addWidget(self.warning_label)

        self.group = QGroupBox()
        self.group.setObjectName('recentPatientsGroup')
        layout = QVBoxLayout(self.group)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.textChanged.connect(self.refresh_table)
        self.active_button = QPushButton()
        self.active_button.clicked.connect(lambda: self._set_filter('active'))
        self.archived_button = QPushButton()
        self.archived_button.clicked.connect(lambda: self._set_filter('archived'))
        self.all_button = QPushButton()
        self.all_button.clicked.connect(lambda: self._set_filter('all'))
        self.new_button = QPushButton()
        self.new_button.clicked.connect(self.open_doctor_dialog)
        self.edit_button = QPushButton()
        self.edit_button.clicked.connect(self.edit_selected_doctor)
        top.addWidget(self.search, 1)
        top.addWidget(self.active_button)
        top.addWidget(self.archived_button)
        top.addWidget(self.all_button)
        top.addWidget(self.new_button)
        top.addWidget(self.edit_button)
        layout.addLayout(top)

        self.table = QTableWidget(0, 5)
        self.table.setObjectName('recentPatientsTable')
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.cellDoubleClicked.connect(lambda _row, _col: self.edit_selected_doctor())
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 280)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 180)
        self.table.setColumnWidth(4, 90)
        layout.addWidget(self.table)
        root.addWidget(self.group, 1)

        self.retranslate_ui()
        self.refresh_doctors()

    def retranslate_ui(self) -> None:
        self.summary.setText(tr('Maintain active and archived doctors used during order entry.'))
        self.warning_label.setText('')
        self.group.setTitle(tr('Doctors'))
        self.search.setPlaceholderText(tr('Search doctors'))
        self.active_button.setText(tr('Active Only'))
        self.archived_button.setText(tr('Archived Only'))
        self.all_button.setText(tr('All'))
        self.new_button.setText(tr('New Doctor'))
        self.edit_button.setText(tr('Edit Doctor'))
        self.table.setHorizontalHeaderLabels([tr('Doctor'), tr('License'), tr('Phone'), tr('Email'), tr('Status')])
        self.new_button.setEnabled(True)
        self.edit_button.setEnabled(True)

    def refresh_on_show(self) -> None:
        self.refresh_doctors()

    def refresh_doctors(self) -> None:
        self.doctor_records = self.provider_service.list_doctors(status_filter='all')
        self.refresh_table()

    def refresh_table(self) -> None:
        query = self.search.text().strip().lower()
        rows = []
        for record in self.doctor_records:
            if self.status_filter == 'active' and not record.is_active:
                continue
            if self.status_filter == 'archived' and record.is_active:
                continue
            haystack = ' '.join([record.full_name, record.license_number or '', record.phone or '', record.email or '']).lower()
            if query and query not in haystack:
                continue
            rows.append((record.full_name, record.license_number or '', record.phone or '', record.email or '', '' if record.is_active else tr('Archived')))
        self.set_table_rows(self.table, rows)

    def _set_filter(self, status_filter: str) -> None:
        self.status_filter = status_filter
        self.refresh_table()

    def open_doctor_dialog(self) -> None:
        if self._uses_server():
            dialog = ServerDoctorDialog(self.provider_service, self)
            if dialog.exec() == QDialog.Accepted and dialog.doctor_id is not None:
                self.refresh_doctors()
                self.notify_data_changed()
            return
        dialog = DoctorDialog(self.database, self)
        if dialog.exec() == QDialog.Accepted and dialog.doctor_id is not None:
            self.refresh_doctors()
            self.notify_data_changed()

    def edit_selected_doctor(self) -> None:
        if self._uses_server():
            row = self.table.currentRow()
            filtered = self._filtered_records()
            if row < 0 or row >= len(filtered):
                QMessageBox.warning(self, tr('Missing Selection'), tr('Select a doctor first.'))
                return
            dialog = ServerDoctorDialog(self.provider_service, self, doctor_id=filtered[row].id)
            if dialog.exec() == QDialog.Accepted and dialog.doctor_id is not None:
                self.refresh_doctors()
                self.notify_data_changed()
            return
        row = self.table.currentRow()
        filtered = self._filtered_records()
        if row < 0 or row >= len(filtered):
            QMessageBox.warning(self, tr('Missing Selection'), tr('Select a doctor first.'))
            return
        dialog = DoctorDialog(self.database, self, doctor_id=filtered[row].id)
        if dialog.exec() == QDialog.Accepted and dialog.doctor_id is not None:
            self.refresh_doctors()
            self.notify_data_changed()

    def _filtered_records(self) -> list[DoctorRecord]:
        query = self.search.text().strip().lower()
        result: list[DoctorRecord] = []
        for record in self.doctor_records:
            if self.status_filter == 'active' and not record.is_active:
                continue
            if self.status_filter == 'archived' and record.is_active:
                continue
            haystack = ' '.join([record.full_name, record.license_number or '', record.phone or '', record.email or '']).lower()
            if query and query not in haystack:
                continue
            result.append(record)
        return result

    def _uses_server(self) -> bool:
        return self.deployment_service.load().mode == 'server'
