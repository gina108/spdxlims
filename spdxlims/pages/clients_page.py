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
)

from spdxlims.database import ClientRecord, Database
from spdxlims.deployment import DeploymentService
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.pages.orders_page import ClientDialog
from spdxlims.provider_service import ProviderService


class ServerClientDialog(QDialog):
    def __init__(self, provider_service: ProviderService, parent=None, client_id: int | str | None = None) -> None:
        super().__init__(parent)
        self.provider_service = provider_service
        self.client_id = client_id
        self._is_active = True
        self.setWindowTitle(tr('Edit Client') if client_id is not None else tr('New Client'))
        self.setModal(True)
        self.resize(440, 300)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.phone = QLineEdit()
        self.email = QLineEdit()
        self.tax_id = QLineEdit()
        form.addRow(tr('Client'), self.name)
        form.addRow(tr('Phone'), self.phone)
        form.addRow(tr('Email'), self.email)
        form.addRow(tr('Tax ID (RFC)'), self.tax_id)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.archive_button = QPushButton()
        self.archive_button.clicked.connect(self.toggle_archive)
        cancel = QPushButton(tr('Cancel'))
        cancel.clicked.connect(self.reject)
        save = QPushButton(tr('Update Client') if client_id is not None else tr('Save Client'))
        save.clicked.connect(self.save)
        buttons.addStretch(1)
        if client_id is not None:
            buttons.addWidget(self.archive_button)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        if client_id is not None:
            self._load()

    def _load(self) -> None:
        client = self.provider_service.get_client(self.client_id)
        if client is None:
            return
        self.name.setText(str(client.get('name') or ''))
        self.phone.setText(str(client.get('phone') or ''))
        self.email.setText(str(client.get('email') or ''))
        self.tax_id.setText(str(client.get('tax_id') or ''))
        self._is_active = bool(client.get('is_active', 1))
        self.archive_button.setText(tr('Archive Client') if self._is_active else tr('Unarchive Client'))

    def toggle_archive(self) -> None:
        if self.client_id is None:
            return
        try:
            if self._is_active:
                self.provider_service.archive_provider(self.client_id)
            else:
                self.provider_service.unarchive_provider(self.client_id)
        except RuntimeError as exc:
            QMessageBox.critical(self, tr('Save Failed'), str(exc))
            return
        self.accept()

    def save(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, tr('Missing Data'), tr('Client name is required.'))
            return
        try:
            self.client_id = self.provider_service.save_client(
                {
                    'name': self.name.text(),
                    'phone': self.phone.text(),
                    'email': self.email.text(),
                    'tax_id': self.tax_id.text(),
                },
                self.client_id,
            )
        except RuntimeError as exc:
            QMessageBox.critical(self, tr('Save Failed'), str(exc))
            return
        self.accept()


class ClientsPage(DataAwarePage):
    def __init__(self, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__()
        self.database = database
        self.deployment_service = deployment_service
        self.provider_service = ProviderService(database, deployment_service)
        self.client_records: list[ClientRecord] = []
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
        self.new_button.clicked.connect(self.open_client_dialog)
        self.edit_button = QPushButton()
        self.edit_button.clicked.connect(self.edit_selected_client)
        top.addWidget(self.search, 1)
        top.addWidget(self.active_button)
        top.addWidget(self.archived_button)
        top.addWidget(self.all_button)
        top.addWidget(self.new_button)
        top.addWidget(self.edit_button)
        layout.addLayout(top)

        self.table = QTableWidget(0, 6)
        self.table.setObjectName('recentPatientsTable')
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.cellDoubleClicked.connect(lambda _row, _col: self.edit_selected_client())
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 280)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 180)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 120)
        self.table.setColumnWidth(5, 90)
        layout.addWidget(self.table)
        root.addWidget(self.group, 1)

        self.retranslate_ui()
        self.refresh_clients()

    def retranslate_ui(self) -> None:
        self.summary.setText(tr('Review customers and outstanding balances for administrative follow-up.'))
        self.warning_label.setText('')
        self.group.setTitle(tr('Clients'))
        self.search.setPlaceholderText(tr('Search customers'))
        self.active_button.setText(tr('Active Only'))
        self.archived_button.setText(tr('Archived Only'))
        self.all_button.setText(tr('All'))
        self.new_button.setText(tr('New Client'))
        self.edit_button.setText(tr('Edit Client'))
        self.table.setHorizontalHeaderLabels([tr('Client'), tr('Phone'), tr('Email'), tr('Tax ID (RFC)'), tr('CFDI Use'), tr('Status')])
        self.new_button.setEnabled(True)
        self.edit_button.setEnabled(True)

    def refresh_on_show(self) -> None:
        self.refresh_clients()

    def refresh_clients(self) -> None:
        self.client_records = self.provider_service.list_clients(status_filter='all')
        self.refresh_table()

    def refresh_table(self) -> None:
        rows = [
            (
                record.name,
                record.phone or '',
                record.email or '',
                record.tax_id or '',
                record.cfdi_use or '',
                '' if record.is_active else tr('Archived'),
            )
            for record in self._filtered_records()
        ]
        self.set_table_rows(self.table, rows)

    def _set_filter(self, status_filter: str) -> None:
        self.status_filter = status_filter
        self.refresh_table()

    def open_client_dialog(self) -> None:
        if self._uses_server():
            dialog = ServerClientDialog(self.provider_service, self)
            if dialog.exec() == QDialog.Accepted and dialog.client_id is not None:
                self.refresh_clients()
                self.notify_data_changed()
            return
        dialog = ClientDialog(self.database, self)
        if dialog.exec() == QDialog.Accepted and dialog.client_id is not None:
            self.refresh_clients()
            self.notify_data_changed()

    def edit_selected_client(self) -> None:
        if self._uses_server():
            row = self.table.currentRow()
            filtered = self._filtered_records()
            if row < 0 or row >= len(filtered):
                QMessageBox.warning(self, tr('Missing Selection'), tr('Select a client first.'))
                return
            dialog = ServerClientDialog(self.provider_service, self, client_id=filtered[row].id)
            if dialog.exec() == QDialog.Accepted and dialog.client_id is not None:
                self.refresh_clients()
                self.notify_data_changed()
            return
        row = self.table.currentRow()
        filtered = self._filtered_records()
        if row < 0 or row >= len(filtered):
            QMessageBox.warning(self, tr('Missing Selection'), tr('Select a client first.'))
            return
        dialog = ClientDialog(self.database, self, client_id=filtered[row].id)
        if dialog.exec() == QDialog.Accepted and dialog.client_id is not None:
            self.refresh_clients()
            self.notify_data_changed()

    def _filtered_records(self) -> list[ClientRecord]:
        query = self.search.text().strip().lower()
        result: list[ClientRecord] = []
        for record in self.client_records:
            if self.status_filter == 'active' and not record.is_active:
                continue
            if self.status_filter == 'archived' and record.is_active:
                continue
            haystack = ' '.join([
                record.name,
                record.phone or '',
                record.email or '',
                record.tax_id or '',
                record.cfdi_use or '',
            ]).lower()
            if query and query not in haystack:
                continue
            result.append(record)
        return result

    def _uses_server(self) -> bool:
        return self.deployment_service.load().mode == 'server'
