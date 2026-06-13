from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from spdxlims.database import Database, InstrumentResultMappingRecord
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage


class InstrumentMappingPage(DataAwarePage):
    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        self._mappings: list[InstrumentResultMappingRecord] = []
        self._profiles: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        group = QGroupBox()
        self._group = group
        layout = QVBoxLayout(group)

        filter_row = QHBoxLayout()
        self._profile_combo = QComboBox()
        self._profile_combo.currentIndexChanged.connect(self._refresh_table)
        filter_row.addWidget(self._profile_combo, 1)

        refresh_btn = QPushButton()
        self._refresh_btn = refresh_btn
        refresh_btn.clicked.connect(self.refresh_on_show)
        filter_row.addWidget(refresh_btn)
        layout.addLayout(filter_row)

        self._table = QTableWidget(0, 6)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(42)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.setColumnWidth(0, 150)
        self._table.setColumnWidth(3, 200)
        self._table.setColumnWidth(4, 130)
        self._table.setColumnWidth(5, 70)
        layout.addWidget(self._table, 1)

        action_row = QHBoxLayout()
        self._toggle_btn = QPushButton()
        self._toggle_btn.clicked.connect(self._toggle_selected)
        self._delete_btn = QPushButton()
        self._delete_btn.clicked.connect(self._delete_selected)
        action_row.addWidget(self._toggle_btn)
        action_row.addWidget(self._delete_btn)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self._status_label = QLabel()
        layout.addWidget(self._status_label)

        root.addWidget(group)
        self.retranslate_ui()
        self.refresh_on_show()

    def retranslate_ui(self) -> None:
        self._group.setTitle(tr("Instrument Result Mappings"))
        self._refresh_btn.setText(tr("Refresh"))
        self._toggle_btn.setText(tr("Toggle Active"))
        self._delete_btn.setText(tr("Delete"))
        self._table.setHorizontalHeaderLabels([
            tr("Profile"),
            tr("Raw Code"),
            tr("Raw Name"),
            tr("Mapped Test"),
            tr("Unit Override"),
            tr("Active"),
        ])

    def refresh_on_show(self) -> None:
        self._profiles = self.database.list_instrument_profiles()
        selected_profile = self._profile_combo.currentData()
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        self._profile_combo.addItem(tr("All Profiles"), "")
        for profile in self._profiles:
            self._profile_combo.addItem(profile, profile)
        index = self._profile_combo.findData(selected_profile)
        self._profile_combo.setCurrentIndex(index if index >= 0 else 0)
        self._profile_combo.blockSignals(False)
        self._refresh_table()

    def _refresh_table(self) -> None:
        profile_filter = self._profile_combo.currentData() or ""
        self._mappings = self.database.list_instrument_result_mappings(
            instrument_profile=profile_filter
        )
        self._table.setRowCount(len(self._mappings))
        for row, mapping in enumerate(self._mappings):
            self._set_row(row, mapping)
        count = len(self._mappings)
        self._status_label.setText(
            tr("{count} mapping(s)", count=count) if count else tr("No mappings saved yet.")
        )

    def _set_row(self, row: int, mapping: InstrumentResultMappingRecord) -> None:
        active = bool(mapping.is_active)
        color = Qt.white if active else Qt.darkGray

        def cell(text: str) -> QTableWidgetItem:
            item = QTableWidgetItem(text)
            item.setForeground(color)
            item.setData(Qt.UserRole, mapping.id)
            return item

        combo = QComboBox()
        profiles = list(self._profiles)
        if mapping.instrument_profile not in profiles:
            profiles.insert(0, mapping.instrument_profile)
        for profile in profiles:
            combo.addItem(profile, profile)
        combo.setCurrentIndex(combo.findData(mapping.instrument_profile))
        combo.currentIndexChanged.connect(
            lambda _idx, mid=mapping.id: self._on_profile_changed(mid, combo.currentData())
        )
        self._table.setCellWidget(row, 0, combo)

        self._table.setItem(row, 1, cell(mapping.raw_code))
        self._table.setItem(row, 2, cell(mapping.raw_name or ""))
        self._table.setItem(row, 3, cell(mapping.test_name))
        self._table.setItem(row, 4, cell(mapping.unit_override or ""))
        self._table.setItem(row, 5, cell(tr("Yes") if active else tr("No")))

    def _on_profile_changed(self, mapping_id: int, new_profile: str) -> None:
        if not new_profile:
            return
        self.database.update_instrument_result_mapping_profile(mapping_id, new_profile)
        self._status_label.setText(tr("Profile updated."))

    def _selected_mapping_id(self) -> int | None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._mappings):
            return None
        return self._mappings[row].id

    def _toggle_selected(self) -> None:
        mapping_id = self._selected_mapping_id()
        if mapping_id is None:
            QMessageBox.information(self, tr("No Selection"), tr("Select a mapping first."))
            return
        self.database.toggle_instrument_result_mapping_active(mapping_id)
        self._refresh_table()

    def _delete_selected(self) -> None:
        mapping_id = self._selected_mapping_id()
        if mapping_id is None:
            QMessageBox.information(self, tr("No Selection"), tr("Select a mapping first."))
            return
        row = self._table.currentRow()
        mapping = self._mappings[row]
        confirm = QMessageBox.question(
            self,
            tr("Delete Mapping"),
            tr(
                "Delete the mapping for {profile} / {code} → {test}?",
                profile=mapping.instrument_profile,
                code=mapping.raw_code,
                test=mapping.test_name,
            ),
        )
        if confirm != QMessageBox.Yes:
            return
        self.database.delete_instrument_result_mapping(mapping_id)
        self._refresh_table()
        self._status_label.setText(tr("Mapping deleted."))
