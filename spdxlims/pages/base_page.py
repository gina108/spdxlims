from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtWidgets import QComboBox, QTableWidget, QTableWidgetItem, QWidget


class DataAwarePage(QWidget):
    def notify_data_changed(self) -> None:
        refresh_all = getattr(self.window(), "refresh_all_pages", None)
        if callable(refresh_all):
            refresh_all(exclude=self)

    @staticmethod
    def set_table_rows(table: QTableWidget, rows: Sequence[Sequence[str]]) -> None:
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(42)
        table.setRowCount(len(rows))
        for row_index, row_values in enumerate(rows):
            for column_index, value in enumerate(row_values):
                table.setItem(row_index, column_index, QTableWidgetItem(value))

    @staticmethod
    def set_combo_items(
        combo: QComboBox,
        items: Sequence[tuple[str, Any]],
        *,
        placeholder: str,
        placeholder_data: Any = None,
        selected_data: Any = None,
    ) -> None:
        combo.clear()
        combo.addItem(placeholder, placeholder_data)
        selected_index = 0
        for label, data in items:
            combo.addItem(label, data)
            if data == selected_data:
                selected_index = combo.count() - 1
        combo.setCurrentIndex(selected_index)
