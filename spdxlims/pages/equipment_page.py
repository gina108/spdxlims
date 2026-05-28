from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage


class EquipmentPage(DataAwarePage):
    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database

        root = QHBoxLayout(self)

        self.form_group = QGroupBox()
        self.form_layout = QFormLayout(self.form_group)
        self.labels: dict[str, QLabel] = {}

        self.name = QLineEdit()
        self.equipment_type = QLineEdit()
        self.manufacturer = QLineEdit()
        self.model = QLineEdit()
        self.serial_number = QLineEdit()
        self.location = QLineEdit()
        self.status = QComboBox()
        self.last_maintenance_date = QLineEdit()
        self.next_maintenance_date = QLineEdit()
        self.notes = QTextEdit()
        self.notes.setMinimumHeight(96)
        self.save_button = QPushButton()
        self.save_button.clicked.connect(self.save_equipment)

        self._add_form_row("name", self.name)
        self._add_form_row("equipment_type", self.equipment_type)
        self._add_form_row("manufacturer", self.manufacturer)
        self._add_form_row("model", self.model)
        self._add_form_row("serial_number", self.serial_number)
        self._add_form_row("location", self.location)
        self._add_form_row("status", self.status)
        self._add_form_row("last_maintenance_date", self.last_maintenance_date)
        self._add_form_row("next_maintenance_date", self.next_maintenance_date)
        self._add_form_row("notes", self.notes)
        self.form_layout.addRow(self.save_button)

        self.table_group = QGroupBox()
        self.table_group.setObjectName("equipmentGroup")
        table_layout = QVBoxLayout(self.table_group)
        self.info = QLabel()
        self.table = QTableWidget(0, 7)
        self.table.setObjectName("equipmentTable")
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(320)

        table_layout.addWidget(self.info)
        table_layout.addWidget(self.table)

        root.addWidget(self.form_group, 2)
        root.addWidget(self.table_group, 3)

        self.retranslate_ui()
        self.refresh_equipment()

    def _add_form_row(self, key: str, field: QWidget) -> None:
        label = QLabel()
        self.labels[key] = label
        self.form_layout.addRow(label, field)

    def retranslate_ui(self) -> None:
        self.form_group.setTitle(tr("Register Equipment"))
        self.table_group.setTitle(tr("Lab Equipment"))
        self.info.setText(tr("Track analyzers, centrifuges, and other instruments in the local SQLite database."))
        self.labels["name"].setText(tr("Equipment Name"))
        self.labels["equipment_type"].setText(tr("Equipment Type"))
        self.labels["manufacturer"].setText(tr("Manufacturer"))
        self.labels["model"].setText(tr("Model"))
        self.labels["serial_number"].setText(tr("Serial Number"))
        self.labels["location"].setText(tr("Location"))
        self.labels["status"].setText(tr("Equipment Status"))
        self.labels["last_maintenance_date"].setText(tr("Last Maintenance"))
        self.labels["next_maintenance_date"].setText(tr("Next Maintenance"))
        self.labels["notes"].setText(tr("Notes"))
        self.save_button.setText(tr("Save Equipment"))
        self.last_maintenance_date.setPlaceholderText("YYYY-MM-DD")
        self.next_maintenance_date.setPlaceholderText("YYYY-MM-DD")
        current_status = self.status.currentData()
        self.status.clear()
        self.status.addItem(tr("Active"), "active")
        self.status.addItem(tr("Maintenance"), "maintenance")
        self.status.addItem(tr("Out of Service"), "out_of_service")
        self.status.addItem(tr("Retired"), "retired")
        status_index = self.status.findData(current_status)
        self.status.setCurrentIndex(status_index if status_index >= 0 else 0)
        self.table.setHorizontalHeaderLabels(
            [
                tr("Name"),
                tr("Type"),
                tr("Model"),
                tr("Serial"),
                tr("Location"),
                tr("Status"),
                tr("Next Maintenance"),
            ]
        )
        if self.table.rowCount() > 0:
            self.refresh_equipment()

    def save_equipment(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, tr("Missing Data"), tr("Equipment name is required."))
            return

        try:
            self.database.create_equipment(
                {
                    "name": self.name.text(),
                    "equipment_type": self.equipment_type.text(),
                    "manufacturer": self.manufacturer.text(),
                    "model": self.model.text(),
                    "serial_number": self.serial_number.text(),
                    "location": self.location.text(),
                    "status": self.status.currentData(),
                    "last_maintenance_date": self.last_maintenance_date.text(),
                    "next_maintenance_date": self.next_maintenance_date.text(),
                    "notes": self.notes.toPlainText(),
                }
            )
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return

        self._clear_form()
        self.refresh_equipment()
        self.notify_data_changed()

    def refresh_on_show(self) -> None:
        self.refresh_equipment()

    def refresh_equipment(self) -> None:
        records = self.database.list_equipment()
        rows = [
            (
                record.name,
                record.equipment_type or "",
                self._format_model(record.manufacturer, record.model),
                record.serial_number or "",
                record.location or "",
                self._format_status(record.status),
                record.next_maintenance_date or "",
            )
            for record in records
        ]
        self.set_table_rows(self.table, rows)

    def _clear_form(self) -> None:
        self.name.clear()
        self.equipment_type.clear()
        self.manufacturer.clear()
        self.model.clear()
        self.serial_number.clear()
        self.location.clear()
        self.status.setCurrentIndex(0)
        self.last_maintenance_date.clear()
        self.next_maintenance_date.clear()
        self.notes.clear()

    @staticmethod
    def _format_model(manufacturer: str | None, model: str | None) -> str:
        parts = [part for part in [manufacturer, model] if part]
        return " / ".join(parts)

    @staticmethod
    def _format_status(status: str) -> str:
        return tr(
            {
                "active": "Active",
                "maintenance": "Maintenance",
                "out_of_service": "Out of Service",
                "retired": "Retired",
            }.get(status, status)
        )
