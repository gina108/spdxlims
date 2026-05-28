from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)

from spdxlims.client_pricing_excel import (
    build_client_price_sheets,
    parse_optional_price,
    read_client_price_matrix,
    write_client_price_workbook,
)
from spdxlims.database import ClientRecord, Database, TestRecord
from spdxlims.deployment import DeploymentService
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.pages.catalog_page import TestDialog
from spdxlims.test_service import TestService


class PricesPage(DataAwarePage):
    def __init__(self, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__()
        self.database = database
        self.deployment_service = deployment_service
        self.test_service = TestService(database, deployment_service)
        self.test_records: list[TestRecord] = []
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
        self.export_client_prices_button = QPushButton()
        self.export_client_prices_button.clicked.connect(self.export_client_prices)
        self.import_client_prices_button = QPushButton()
        self.import_client_prices_button.clicked.connect(self.import_client_prices)
        self.edit_button = QPushButton()
        self.edit_button.clicked.connect(self.edit_selected_test)
        top.addWidget(self.search, 1)
        top.addWidget(self.active_button)
        top.addWidget(self.archived_button)
        top.addWidget(self.all_button)
        top.addWidget(self.export_client_prices_button)
        top.addWidget(self.import_client_prices_button)
        top.addWidget(self.edit_button)
        layout.addLayout(top)

        self.table = QTableWidget(0, 5)
        self.table.setObjectName('recentPatientsTable')
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.cellDoubleClicked.connect(lambda _row, _col: self.edit_selected_test())
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        root.addWidget(self.group, 1)

        self.retranslate_ui()
        self.refresh_prices()

    def retranslate_ui(self) -> None:
        self.summary.setText(tr('Review and update the full price list for tests.'))
        self.warning_label.setText(tr('Client price workbook import/export is only available in local mode.') if self._uses_server() else '')
        self.group.setTitle(tr('Prices'))
        self.search.setPlaceholderText(tr('Search tests'))
        self.active_button.setText(tr('Active Only'))
        self.archived_button.setText(tr('Archived Only'))
        self.all_button.setText(tr('All'))
        self.export_client_prices_button.setText(tr('Export Client Prices'))
        self.import_client_prices_button.setText(tr('Import Client Prices'))
        self.edit_button.setText(tr('Edit Selected Test'))
        self.table.setHorizontalHeaderLabels([tr('Code'), tr('Name'), tr('Category'), tr('Price'), tr('Status')])
        workbook_enabled = not self._uses_server()
        self.export_client_prices_button.setEnabled(workbook_enabled)
        self.import_client_prices_button.setEnabled(workbook_enabled)

    def refresh_on_show(self) -> None:
        self.refresh_prices()

    def refresh_prices(self) -> None:
        try:
            self.test_records = self.test_service.list_tests(status_filter='all')
        except RuntimeError as exc:
            self.test_records = []
            QMessageBox.warning(self, tr('Connection Test'), str(exc))
        self.client_records = [] if self._uses_server() else self.database.list_clients(status_filter='all')
        self.refresh_table()

    def refresh_table(self) -> None:
        rows = []
        for record in self._filtered_records():
            rows.append((
                record.code,
                record.name,
                record.category_name or '',
                self._format_price(record.price),
                '' if record.is_active else tr('Archived'),
            ))
        self.set_table_rows(self.table, rows)

    def edit_selected_test(self) -> None:
        row = self.table.currentRow()
        filtered = self._filtered_records()
        if row < 0 or row >= len(filtered):
            QMessageBox.warning(self, tr('Missing Selection'), tr('Select a test first.'))
            return
        dialog = TestDialog(self.database, self.test_service, filtered[row].id, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_prices()
            self.notify_data_changed()

    def export_client_prices(self) -> None:
        if self._uses_server():
            return
        path, _ = QFileDialog.getSaveFileName(self, tr('Save Client Price Workbook'), 'client_prices.xlsx', tr('Excel Workbook (*.xlsx)'))
        if not path:
            return
        overrides = self.database.list_client_test_price_overrides()
        sheets = build_client_price_sheets(self.test_records, self.client_records, overrides)
        target = write_client_price_workbook(path, sheets)
        QMessageBox.information(self, tr('Exported'), tr('Client price workbook saved: {path}', path=str(target)))

    def import_client_prices(self) -> None:
        if self._uses_server():
            return
        path, _ = QFileDialog.getOpenFileName(self, tr('Import Client Prices'), '', tr('Excel Workbook (*.xlsx)'))
        if not path:
            return
        try:
            rows, client_columns = read_client_price_matrix(path)
            updates = self._build_client_price_updates(rows, client_columns)
        except ValueError as exc:
            QMessageBox.critical(self, tr('Import Failed'), str(exc))
            return
        updated_count, cleared_count = self.database.apply_client_test_price_overrides(updates)
        QMessageBox.information(
            self,
            tr('Imported'),
            tr('Client prices imported. Updated: {updated_count}, Cleared: {cleared_count}', updated_count=updated_count, cleared_count=cleared_count),
        )

    def _build_client_price_updates(self, rows: list[dict[str, str]], client_columns: list[tuple[int, str]]) -> dict[tuple[int, int], float | None]:
        known_client_ids = {record.id for record in self.client_records}
        unknown_clients = [label for client_id, label in client_columns if client_id not in known_client_ids]
        if unknown_clients:
            raise ValueError(tr('Unknown clients in workbook: {clients}', clients=', '.join(unknown_clients)))
        code_map = {record.code: record.id for record in self.test_records}
        updates: dict[tuple[int, int], float | None] = {}
        for row in rows:
            test_code = row.get('test_code', '').strip()
            if not test_code:
                continue
            test_id = code_map.get(test_code)
            if test_id is None:
                raise ValueError(tr('Unknown test code in workbook: {code}', code=test_code))
            for client_id, _label in client_columns:
                header = f'client:{client_id}:{_label}'
                try:
                    price = parse_optional_price(row.get(header, ''))
                except ValueError as exc:
                    row_number = row.get('__row_number__', '?')
                    raise ValueError(tr('Invalid price in row {row_number} for test {code}.', row_number=row_number, code=test_code)) from exc
                updates[(client_id, test_id)] = price
        return updates

    def _set_filter(self, status_filter: str) -> None:
        self.status_filter = status_filter
        self.refresh_table()

    def _filtered_records(self) -> list[TestRecord]:
        query = self.search.text().strip().lower()
        result: list[TestRecord] = []
        for record in self.test_records:
            if self.status_filter == 'active' and not record.is_active:
                continue
            if self.status_filter == 'archived' and record.is_active:
                continue
            haystack = ' '.join([record.code, record.name, record.category_name or '']).lower()
            if query and query not in haystack:
                continue
            result.append(record)
        return result

    @staticmethod
    def _format_price(price: float | None) -> str:
        if price in (None, ''):
            return ''
        try:
            return f"{float(price):.2f}"
        except (TypeError, ValueError):
            return str(price)

    def _uses_server(self) -> bool:
        return self.deployment_service.load().mode == 'server'
