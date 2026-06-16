from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database, OrderBrowserRecord
from spdxlims.deployment import DeploymentService
from spdxlims.i18n import tr
from spdxlims.order_service import OrderService
from spdxlims.pages.base_page import DataAwarePage


class OrdersBrowserPage(DataAwarePage):
    def __init__(self, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__()
        self.database = database
        self.order_service = OrderService(database, deployment_service)
        self.current_records: list[OrderBrowserRecord] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        self.group = QGroupBox()
        layout = QVBoxLayout(self.group)

        self.helper = QLabel()
        self.helper.setWordWrap(True)
        layout.addWidget(self.helper)

        search_row = QWidget()
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(10)
        self.search_label = QLabel()
        self.search_input = QLineEdit()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self.refresh_on_show)
        self.search_input.textChanged.connect(lambda _: self._search_timer.start())
        search_layout.addWidget(self.search_label)
        search_layout.addWidget(self.search_input, 1)
        layout.addWidget(search_row)

        self.table = QTableWidget(0, 6)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        layout.addWidget(self.table, 1)
        root.addWidget(self.group, 1)

        self.retranslate_ui()
        self.refresh_on_show()

    def retranslate_ui(self) -> None:
        self.group.setTitle(tr("Orders"))
        self.helper.setText(tr("Search orders by patient name, order number, or client."))
        self.search_label.setText(tr("Search"))
        self.search_input.setPlaceholderText(tr("Search by patient, order number, or client"))
        self.table.setHorizontalHeaderLabels(
            [
                tr("Number"),
                tr("Patient"),
                tr("Client"),
                tr("Doctor"),
                tr("Status"),
                tr("Created"),
            ]
        )
        self._refresh_table()

    def refresh_on_show(self) -> None:
        try:
            self.current_records = self.order_service.search_orders(self.search_input.text())
        except RuntimeError:
            self.current_records = []
        self._refresh_table()

    def _refresh_table(self) -> None:
        self.table.clearContents()
        self.table.setRowCount(len(self.current_records))
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 250)
        self.table.setColumnWidth(2, 220)
        self.table.setColumnWidth(3, 220)
        self.table.setColumnWidth(4, 52)
        self.table.setColumnWidth(5, 150)

        for row_index, record in enumerate(self.current_records):
            self._set_item(row_index, 0, record.order_number)
            self._set_item(row_index, 1, record.patient_name)
            self._set_item(row_index, 2, record.client_name or "")
            self._set_item(row_index, 3, record.doctor_name or "")
            self.table.setCellWidget(row_index, 4, self.build_order_status_indicator(record.status))
            self._set_item(row_index, 5, self._format_order_date(record.order_date))

    def _set_item(self, row: int, column: int, value: str) -> None:
        item = QTableWidgetItem(value)
        item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.table.setItem(row, column, item)

    @staticmethod
    def _format_order_date(raw_value: str | None) -> str:
        value = str(raw_value or "").strip()
        if not value:
            return ""
        date_part = value.replace("T", " ").split(" ", 1)[0]
        chunks = date_part.split("-")
        if len(chunks) == 3:
            year, month, day = chunks
            return f"{day}-{month}-{year}"
        return date_part
