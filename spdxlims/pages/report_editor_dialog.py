from __future__ import annotations

import re

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spdxlims.i18n import tr
from spdxlims.theme import recolor


class ReportEditorDialog(QDialog):
    _FLAG_OPTIONS = (
        ("", "None"),
        ("none", "None"),
        ("low", "Low"),
        ("normal", "Normal"),
        ("high", "High"),
        ("abnormal", "Abnormal"),
    )
    _ROW_COLUMNS = (
        "item_type",
        "test_name",
        "flag",
        "result_value",
        "unit",
        "reference_text",
        "comments",
    )
    _ITEM_TYPE_COLORS: dict[str, tuple[str, str, str]] = {
        "test":    ("#A8B3C2", "#21272D", "#2E3640"),
        "heading": ("#C9A8FF", "#1E1242", "#7756BE"),
        "comment": ("#697789", "#20252B", "#252C34"),
    }

    def __init__(self, preview: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preview = self._clone_preview(preview)
        self.setModal(True)
        self.resize(1100, 820)
        self.setWindowTitle(tr("Edit Report"))

        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        help_label = QLabel(tr("Edit only the report rows before approving it. You can update test fields and remove full rows."))
        help_label.setWordWrap(True)
        top_row.addWidget(help_label, 1)
        top_row.addStretch(1)
        cancel_button = QPushButton(tr("Cancel"))
        cancel_button.clicked.connect(self.reject)
        top_row.addWidget(cancel_button)
        save_button = QPushButton(tr("Apply Changes"))
        save_button.clicked.connect(self._apply_and_close)
        top_row.addWidget(save_button)
        layout.addLayout(top_row)

        table_actions = QHBoxLayout()
        table_actions.addWidget(QLabel(tr("Report Rows")))
        table_actions.addStretch(1)

        add_row_button = QPushButton(tr("Fila en blanca"))
        add_row_button.clicked.connect(self._add_blank_row)
        table_actions.addWidget(add_row_button)

        remove_button = QPushButton(tr("Delete Selected Row"))
        remove_button.clicked.connect(self._remove_selected_row)
        table_actions.addWidget(remove_button)

        move_up_button = QPushButton(tr("Move Up"))
        move_up_button.clicked.connect(lambda: self._move_selected_row(-1))
        table_actions.addWidget(move_up_button)

        move_down_button = QPushButton(tr("Move Down"))
        move_down_button.clicked.connect(lambda: self._move_selected_row(1))
        table_actions.addWidget(move_down_button)
        layout.addLayout(table_actions)

        self.items_table = QTableWidget(0, len(self._ROW_COLUMNS))
        self.items_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.items_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.items_table.setHorizontalHeaderLabels(
            [
                tr("Item Type"),
                tr("Test"),
                tr("Flag"),
                tr("Result"),
                tr("Unit"),
                tr("Reference"),
                tr("Comments"),
            ]
        )
        self.items_table.setColumnWidth(0, 140)
        self.items_table.setColumnWidth(1, 170)
        self.items_table.setColumnWidth(2, 145)
        self.items_table.setColumnWidth(3, 100)
        self.items_table.setColumnWidth(4, 90)
        self.items_table.setColumnWidth(5, 120)
        self.items_table.horizontalHeader().setStretchLastSection(True)
        self.items_table.verticalHeader().setDefaultSectionSize(44)
        self.items_table.installEventFilter(self)
        layout.addWidget(self.items_table, 1)

        self._populate_items_table()

    def eventFilter(self, obj: object, event) -> bool:
        if obj is self.items_table and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                self._remove_selected_row()
                return True
        return super().eventFilter(obj, event)

    @property
    def edited_preview(self) -> dict[str, object]:
        return self._clone_preview(self._preview)

    def _populate_items_table(self) -> None:
        items = list(self._preview.get("items") or [])
        self.items_table.setRowCount(len(items))
        for row_index, item in enumerate(items):
            item_type_combo = self._make_type_combo()
            current_type = str(item.get("item_type") or "test")
            current_index = item_type_combo.findData(current_type)
            item_type_combo.setCurrentIndex(current_index if current_index >= 0 else 0)
            self._style_type_combo(item_type_combo, current_type)
            item_type_combo.currentIndexChanged.connect(
                lambda _idx, c=item_type_combo: self._style_type_combo(c, str(c.currentData() or "test"))
            )
            self.items_table.setCellWidget(row_index, 0, item_type_combo)
            self._set_table_text(row_index, 1, str(item.get("test_name") or ""), metadata=dict(item))
            self._set_flag_combo(row_index, str(item.get("flag") or ""))
            self._set_table_text(row_index, 3, str(item.get("result_value") or ""))
            self._set_table_text(row_index, 4, str(item.get("unit") or ""))
            self._set_table_text(row_index, 5, self._display_reference_text(item))
            self._set_table_text(row_index, 6, str(item.get("comments") or ""))

    def _set_table_text(self, row: int, column: int, value: str, metadata: dict[str, object] | None = None) -> None:
        item = QTableWidgetItem(value)
        if metadata is not None:
            item.setData(Qt.UserRole, metadata)
        self.items_table.setItem(row, column, item)

    def _remove_selected_row(self) -> None:
        row = self.items_table.currentRow()
        if row < 0:
            return
        self.items_table.removeRow(row)

    def _add_blank_row(self) -> None:
        row = self.items_table.rowCount()
        self.items_table.insertRow(row)
        item_type_combo = self._make_type_combo()
        self._style_type_combo(item_type_combo, "test")
        item_type_combo.currentIndexChanged.connect(
            lambda _idx, c=item_type_combo: self._style_type_combo(c, str(c.currentData() or "test"))
        )
        self.items_table.setCellWidget(row, 0, item_type_combo)
        self._set_table_text(row, 1, "", metadata={})
        self._set_flag_combo(row, "")
        self._set_table_text(row, 3, "")
        self._set_table_text(row, 4, "")
        self._set_table_text(row, 5, "")
        self._set_table_text(row, 6, "")
        self.items_table.setCurrentCell(row, 1)

    def _move_selected_row(self, offset: int) -> None:
        row = self.items_table.currentRow()
        if row < 0:
            return
        new_row = row + offset
        if new_row < 0 or new_row >= self.items_table.rowCount():
            return
        row_data = self._take_row_data(row)
        other_data = self._take_row_data(new_row)
        self._restore_row_data(row, other_data)
        self._restore_row_data(new_row, row_data)
        self.items_table.setCurrentCell(new_row, 1)

    def _take_row_data(self, row: int) -> dict[str, object]:
        combo = self.items_table.cellWidget(row, 0)
        item_type = combo.currentData() if isinstance(combo, QComboBox) else "test"
        values = {
            "item_type": str(item_type or "test"),
            "test_name": self._item_text(row, 1),
            "flag": self._flag_value(row),
            "result_value": self._item_text(row, 3),
            "unit": self._item_text(row, 4),
            "reference_text": self._item_text(row, 5),
            "comments": self._item_text(row, 6),
            "__source_item": self._item_metadata(row, 1),
        }
        return values

    def _restore_row_data(self, row: int, row_data: dict[str, object]) -> None:
        combo = self.items_table.cellWidget(row, 0)
        if isinstance(combo, QComboBox):
            item_type = str(row_data.get("item_type") or "test")
            index = combo.findData(item_type)
            combo.setCurrentIndex(index if index >= 0 else 0)
            self._style_type_combo(combo, item_type)
        self._set_table_text(row, 1, str(row_data.get("test_name") or ""), metadata=dict(row_data.get("__source_item") or {}))
        self._set_flag_combo(row, str(row_data.get("flag") or ""))
        self._set_table_text(row, 3, str(row_data.get("result_value") or ""))
        self._set_table_text(row, 4, str(row_data.get("unit") or ""))
        self._set_table_text(row, 5, str(row_data.get("reference_text") or ""))
        self._set_table_text(row, 6, str(row_data.get("comments") or ""))

    def _item_text(self, row: int, column: int) -> str:
        item = self.items_table.item(row, column)
        return item.text().strip() if item is not None else ""

    def _set_flag_combo(self, row: int, value: str) -> None:
        combo = QComboBox()
        combo.setMinimumWidth(120)
        for flag_value, label in self._FLAG_OPTIONS:
            combo.addItem(tr(label), flag_value)
        normalized = (value or "").strip().lower()
        index = combo.findData(normalized)
        combo.setCurrentIndex(index if index >= 0 else 0)
        self.items_table.setCellWidget(row, 2, combo)

    def _make_type_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.addItem(tr("Test"), "test")
        combo.addItem(tr("Heading"), "heading")
        combo.addItem(tr("Comment"), "comment")
        return combo

    @staticmethod
    def _style_combo(combo: QComboBox, color: str, bg: str, border: str) -> None:
        combo.setStyleSheet(recolor(f"""
            QComboBox {{
                color: {color};
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 4px;
                margin: 4px 6px;
                padding: 2px 22px 2px 8px;
                font-weight: 600;
            }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {color};
                margin-right: 6px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #20252B;
                border: 1px solid #2E3640;
                color: #F0F4FF;
                selection-background-color: #341F5C;
                outline: 0;
            }}
        """))

    @classmethod
    def _style_type_combo(cls, combo: QComboBox, value: str) -> None:
        color, bg, border = cls._ITEM_TYPE_COLORS.get(value, cls._ITEM_TYPE_COLORS["test"])
        cls._style_combo(combo, color, bg, border)

    def _flag_value(self, row: int) -> str:
        combo = self.items_table.cellWidget(row, 2)
        if isinstance(combo, QComboBox):
            return str(combo.currentData() or "")
        return self._item_text(row, 2)

    def _item_metadata(self, row: int, column: int) -> dict[str, object]:
        item = self.items_table.item(row, column)
        if item is None:
            return {}
        metadata = item.data(Qt.UserRole)
        return dict(metadata) if isinstance(metadata, dict) else {}

    def _apply_and_close(self) -> None:
        edited_items: list[dict[str, object]] = []
        for row_index in range(self.items_table.rowCount()):
            combo = self.items_table.cellWidget(row_index, 0)
            item_type = str(combo.currentData() or "test") if isinstance(combo, QComboBox) else "test"
            source_item = self._item_metadata(row_index, 1)
            item = {
                **source_item,
                "item_type": item_type,
                "test_name": self._item_text(row_index, 1),
                "flag": self._flag_value(row_index),
                "result_value": self._item_text(row_index, 3),
                "unit": self._item_text(row_index, 4),
                "comments": self._item_text(row_index, 6),
                "sort_order": len(edited_items),
            }
            self._apply_edited_reference(item, self._item_text(row_index, 5), source_item)
            if item_type in {"heading", "comment"}:
                item["order_test_id"] = None
                item["flag"] = ""
                item["result_value"] = "" if item_type == "heading" else item["result_value"]
                item["unit"] = ""
                item["reference_text"] = ""
                item["lower_value"] = ""
                item["upper_value"] = ""
            edited_items.append(item)

        reportable_items = [item for item in edited_items if item.get("item_type") != "heading"]
        if not reportable_items:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr("Missing Selection"), tr("No report could be generated for this order."))
            return

        self._preview["items"] = edited_items
        self.accept()

    @staticmethod
    def _display_reference_text(item: dict[str, object]) -> str:
        reference_text = str(item.get("reference_text") or "").strip()
        lower_value = str(item.get("lower_value") or "").strip()
        upper_value = str(item.get("upper_value") or "").strip()
        range_text = " - ".join(part for part in (lower_value, upper_value) if part)
        if reference_text and range_text:
            return f"{range_text} / {reference_text}"
        return reference_text or range_text

    @classmethod
    def _apply_edited_reference(cls, item: dict[str, object], edited_text: str, source_item: dict[str, object]) -> None:
        edited_text = edited_text.strip()
        original_reference = str(source_item.get("reference_text") or "").strip()
        if edited_text == cls._display_reference_text(source_item):
            item["reference_text"] = original_reference
            return
        lower_value, upper_value = cls._parse_reference_range_text(edited_text)
        if lower_value is not None or upper_value is not None:
            item["lower_value"] = lower_value or ""
            item["upper_value"] = upper_value or ""
            item["reference_text"] = ""
            return
        item["lower_value"] = ""
        item["upper_value"] = ""
        item["reference_text"] = edited_text

    @staticmethod
    def _parse_reference_range_text(value: str) -> tuple[str | None, str | None]:
        normalized = value.strip()
        if not normalized:
            return None, None
        decimal_pattern = r"[+-]?\d+(?:\.\d+)?"
        match = re.fullmatch(rf"\s*({decimal_pattern})\s*(?:-|–|—|a|to)\s*({decimal_pattern})\s*", normalized, flags=re.IGNORECASE)
        if match:
            return match.group(1), match.group(2)
        match = re.fullmatch(rf"\s*(?:<=|≤|<)\s*({decimal_pattern})\s*", normalized)
        if match:
            return None, match.group(1)
        match = re.fullmatch(rf"\s*(?:>=|≥|>)\s*({decimal_pattern})\s*", normalized)
        if match:
            return match.group(1), None
        return None, None

    @staticmethod
    def _clone_preview(preview: dict[str, object]) -> dict[str, object]:
        cloned = dict(preview)
        cloned["items"] = [dict(item) for item in list(preview.get("items") or [])]
        return cloned
