from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QWidget


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
        table.setUpdatesEnabled(False)
        table.setRowCount(len(rows))
        for row_index, row_values in enumerate(rows):
            for column_index, value in enumerate(row_values):
                table.setItem(row_index, column_index, QTableWidgetItem(value))
        table.setUpdatesEnabled(True)

    @staticmethod
    def build_order_status_indicator(status: str | None, *, all_results_entered: bool = False) -> QWidget:
        _STATUS_MAP: dict[str, tuple[str, str]] = {
            "draft":       ("#7f8a98", "Borrador"),
            "registered":  ("#7f8a98", "Registrada"),
            "in_progress": ("#f5c451", "En progreso"),
            "collected":   ("#f5c451", "Recolectada"),
            "in_lab":      ("#4db8ff", "En laboratorio"),
            "completed":   ("#4db8ff", "Completada"),
            "reported":    ("#3ddc84", "Reportada"),
            "amended":     ("#f5a742", "Corregida"),
        }
        normalized = str(status or "").strip()
        color, tooltip = _STATUS_MAP.get(normalized, ("#7f8a98", normalized or ""))
        if all_results_entered and color not in ("#3ddc84", "#4db8ff"):
            color = "#4db8ff"
        container = QWidget()
        container.setAttribute(Qt.WA_TranslucentBackground, True)
        container.setStyleSheet("background-color: transparent; border: none;")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        indicator = QLabel("●")
        indicator.setAlignment(Qt.AlignCenter)
        indicator.setStyleSheet(
            f"color: {color}; background-color: transparent; border: none; font-size: 28px; font-weight: 700;"
        )
        indicator.setToolTip(tooltip)
        layout.addWidget(indicator)
        return container

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
