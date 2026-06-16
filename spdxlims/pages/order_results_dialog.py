from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database, ResultEntryRecord
from spdxlims.deployment import DeploymentService
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.result_service import ResultService


class OrderResultsDialog(QDialog):
    def __init__(self, database: Database, order_id: int | str, deployment_service: DeploymentService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.order_id = order_id
        self.result_service = ResultService(database, deployment_service)
        self.current_entries: list[ResultEntryRecord] = []
        self.display_entries: list[dict[str, object]] = []
        self.current_entry: ResultEntryRecord | None = None
        self.collapsed_headings_by_order: dict[int, set[int]] = self._load_collapsed_headings()

        self.setModal(True)
        self.resize(980, 620)
        self.setWindowTitle(tr("Enter Results"))

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)
        root.addWidget(self._build_order_results(), 3)
        root.addWidget(self._build_entry_form(), 2)

        self.load_order()
        if self.results_table.rowCount() > 0:
            first_row = self._first_selectable_row()
            target_row = first_row if first_row >= 0 else 0
            self.results_table.selectRow(target_row)
            self.load_selected_entry()
            QTimer.singleShot(0, lambda: self._focus_result_editor(target_row))
    def _build_order_results(self) -> QWidget:
        self.order_group = QGroupBox(tr("Order Results"))
        layout = QVBoxLayout(self.order_group)
        self.order_summary = QLabel(tr("Loading order..."))
        self.order_summary.setWordWrap(True)
        layout.addWidget(self.order_summary)

        self.results_table = QTableWidget(0, 6)
        self.results_table.verticalHeader().setDefaultSectionSize(48)
        self.results_table.setHorizontalHeaderLabels([tr("Test"), tr("Result"), tr("Unit"), tr("Range"), tr("Flag"), tr("Status")])
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setColumnWidth(0, 190)
        self.results_table.setColumnWidth(1, 170)
        self.results_table.setColumnWidth(2, 90)
        self.results_table.setColumnWidth(3, 130)
        self.results_table.setColumnWidth(4, 100)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setSelectionMode(QTableWidget.SingleSelection)
        self.results_table.itemSelectionChanged.connect(self.load_selected_entry)
        self.results_table.cellDoubleClicked.connect(self.toggle_heading_row)
        self.results_table.setStyleSheet(
            """
            QTableWidget {
                background-color: #0D141D;
            }
            QTableWidget QLineEdit {
                background-color: #0D141D;
                color: #F4F7FB;
                border: 1px solid #243244;
                border-radius: 0px;
                padding: 0px 6px;
                min-height: 26px;
                font-size: 12pt;
                font-weight: 500;
                selection-background-color: #9B6CF3;
                selection-color: #FFFFFF;
            }
            QTableWidget QLineEdit:focus {
                border: 1px solid #9B6CF3;
                background-color: #0D141D;
            }
            QTableWidget QComboBox {
                background-color: #0D141D;
                color: #F4F7FB;
                border: 1px solid #243244;
                border-radius: 0px;
                padding: 0px 18px 0px 6px;
                min-height: 26px;
                font-size: 12pt;
                font-weight: 500;
            }
            QTableWidget QComboBox:focus {
                border: 1px solid #9B6CF3;
                background-color: #0D141D;
            }
            QTableWidget QComboBox QAbstractItemView {
                background-color: #0D141D;
                color: #F4F7FB;
                border: 1px solid #243244;
                outline: 0;
                selection-background-color: #5B2AA8;
                selection-color: #FFFFFF;
            }
            QTableWidget QComboBox QAbstractItemView::item {
                background-color: #0D141D;
                color: #F4F7FB;
                padding: 2px 8px;
                min-height: 16px;
            }
            QTableWidget QComboBox QAbstractItemView::item:selected {
                background-color: #5B2AA8;
                color: #FFFFFF;
            }
            QTableWidget QComboBox::drop-down {
                border: none;
                width: 18px;
            }
            QTableWidget QComboBox::down-arrow {
                image: none;
                width: 0px;
                height: 0px;
            }
            """
        )
        layout.addWidget(self.results_table)
        return self.order_group

    def _build_entry_form(self) -> QWidget:
        self.entry_group = QGroupBox(tr("Result Entry"))
        layout = QVBoxLayout(self.entry_group)
        form = QFormLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        self._entry_form = form
        self.test_name = QLineEdit()
        self.test_name.setReadOnly(True)
        self.result_value_text = QLineEdit()
        self.result_value_text.setObjectName("resultPrimaryInput")
        self.result_value_text.setPlaceholderText(tr("Enter result"))
        self.result_value_select = QComboBox()
        self.result_value_select.setObjectName("resultPrimaryInput")
        self.result_value_comment = QTextEdit()
        self.result_value_comment.setObjectName("resultPrimaryInput")
        self.result_value_comment.setPlaceholderText(tr("Enter result"))
        self.result_value_comment.setFixedHeight(36)
        self.result_value_comment.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.result_value_stack = QStackedWidget()
        self.result_value_stack.setFixedHeight(36)
        self.result_value_stack.addWidget(self.result_value_text)
        self.result_value_stack.addWidget(self.result_value_select)
        self.result_value_stack.addWidget(self.result_value_comment)
        self.unit = QLineEdit()
        self.lower_value = QLineEdit()
        self.upper_value = QLineEdit()
        self.reference_text = QTextEdit()
        self.reference_text.setFixedHeight(90)
        self.comments = QTextEdit()
        self.comments.setFixedHeight(90)
        self.flag_preview = QLineEdit()
        self.flag_preview.setReadOnly(True)
        self._entry_row_widgets: dict[str, tuple[QLabel, QWidget]] = {}

        self._add_entry_form_row("test", tr("Test"), self.test_name)
        self._add_entry_form_row("result", tr("Result"), self.result_value_stack)
        self._add_entry_form_row("unit", tr("Unit"), self.unit)
        self._add_entry_form_row("lower", tr("Lower"), self.lower_value)
        self._add_entry_form_row("upper", tr("Upper"), self.upper_value)
        self._add_entry_form_row("reference", tr("Reference"), self.reference_text)
        self._add_entry_form_row("comments", tr("Comments"), self.comments)
        self._add_entry_form_row("flag", tr("Flag"), self.flag_preview)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        close_button = QPushButton(tr("Close"))
        close_button.clicked.connect(self.accept)
        self.save_button = QPushButton(tr("Save Result"))
        self.save_button.clicked.connect(self.save_result)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        self._apply_result_editor_styles()
        return self.entry_group

    def _add_entry_form_row(self, key: str, label_text: str, widget: QWidget) -> None:
        label = QLabel(label_text)
        self._entry_row_widgets[key] = (label, widget)
        self._entry_form.addRow(label, widget)

    def _apply_result_editor_styles(self) -> None:
        self.result_value_stack.setStyleSheet(
            """
            QLineEdit#resultPrimaryInput,
            QTextEdit#resultPrimaryInput,
            QComboBox#resultPrimaryInput {
                background-color: #0D141D;
                border: 1px solid #243244;
                border-radius: 8px;
                padding: 3px 6px;
                color: #F4F7FB;
                font-size: 12pt;
                font-weight: 500;
            }
            QTextEdit#resultPrimaryInput {
                padding: 4px 6px;
            }
            QLineEdit#resultPrimaryInput:focus,
            QTextEdit#resultPrimaryInput:focus,
            QComboBox#resultPrimaryInput:focus {
                border: 1px solid #9B6CF3;
                background-color: #0D141D;
            }
            QLineEdit#resultPrimaryInput:disabled,
            QTextEdit#resultPrimaryInput:disabled,
            QComboBox#resultPrimaryInput:disabled {
                background-color: #1C2735;
                border-color: #243244;
                color: #697789;
            }
            QComboBox#resultPrimaryInput::drop-down {
                width: 30px;
                border: none;
            }
            """
        )

    def _set_result_editor_value(self, entry: ResultEntryRecord | None, value: str) -> None:
        if entry is not None and entry.item_type == "comment":
            self.result_value_comment.setPlainText(value)
            self.result_value_stack.setCurrentWidget(self.result_value_comment)
            return
        if entry is None or entry.item_type == "heading" or entry.result_kind != "select":
            self.result_value_text.setText(value)
            self.result_value_stack.setCurrentWidget(self.result_value_text)
            return
        options = self.database.deserialize_select_options(entry.select_options)
        self.result_value_select.blockSignals(True)
        self.result_value_select.clear()
        self.result_value_select.addItems(options)
        if value and self.result_value_select.findText(value) < 0:
            self.result_value_select.addItem(value)
        index = self.result_value_select.findText(value) if value else -1
        self.result_value_select.setCurrentIndex(index if index >= 0 else 0 if self.result_value_select.count() else -1)
        self.result_value_select.blockSignals(False)
        self.result_value_stack.setCurrentWidget(self.result_value_select)

    def _current_result_value(self) -> str:
        if self.result_value_stack.currentWidget() is self.result_value_select:
            return self.result_value_select.currentText()
        if self.result_value_stack.currentWidget() is self.result_value_comment:
            return self.result_value_comment.toPlainText()
        return self.result_value_text.text()

    def load_order(self) -> None:
        self.current_entries = self.result_service.get_order_entries(self.order_id)
        self.display_entries = self._build_display_entries()
        rows: list[tuple[str, str, str, str, str, str]] = []
        selected_row = -1
        current_order_test_id = self.current_entry.order_test_id if self.current_entry is not None else None
        indent_tests = False
        for row_index, display_entry in enumerate(self.display_entries):
            if display_entry.get("kind") == "outsourced_panel":
                panel_label = str(display_entry.get("panel_label") or "")
                rows.append((panel_label, tr("Open PDF Import"), "", "", "", tr("Outsourced")))
                continue
            entry = display_entry["entry"]
            if entry.item_type == "heading":
                indent_tests = True
                heading_prefix = "▸ " if entry.order_test_id in self._collapsed_headings() else "▾ "
                rows.append((f"{heading_prefix}{entry.test_name}", "", "", "", "", ""))
            else:
                label = f"    {entry.test_name}" if indent_tests else entry.test_name
                rows.append((label, entry.result_value or "", entry.unit or "", self._format_range(entry.lower_value, entry.upper_value, entry.reference_text), entry.flag or "", entry.test_status))
            if current_order_test_id is not None and entry.order_test_id == current_order_test_id:
                selected_row = row_index
        DataAwarePage.set_table_rows(self.results_table, rows)
        self.results_table.verticalHeader().setDefaultSectionSize(48)
        self._install_inline_result_widgets()
        self._apply_heading_visibility()
        self._style_heading_rows()
        if self.current_entries:
            first = self.current_entries[0]
            doctor_text = tr(" | Doctor: {doctor_name}", doctor_name=first.doctor_name) if getattr(first, "doctor_name", None) else ""
            self.order_summary.setText(tr("Order {order_number} for {patient_name}{doctor_text}", order_number=first.order_number, patient_name=first.patient_name, doctor_text=doctor_text))
            target_row = selected_row if selected_row >= 0 else self._first_selectable_row()
            if target_row >= 0:
                self.results_table.selectRow(target_row)
            else:
                self.clear_entry_form()
        else:
            self.order_summary.setText(tr("No tests found for this order."))
            self.clear_entry_form()



    def _apply_heading_visibility(self) -> None:
        hide_following = False
        for row_index, display_entry in enumerate(self.display_entries):
            if display_entry.get("kind") == "outsourced_panel":
                self.results_table.setRowHidden(row_index, False)
                continue
            entry = display_entry["entry"]
            if entry.item_type == "heading":
                hide_following = entry.order_test_id in self._collapsed_headings()
                self.results_table.setRowHidden(row_index, False)
            else:
                self.results_table.setRowHidden(row_index, hide_following)
                if entry.item_type == "comment":
                    hide_following = False

    def toggle_heading_row(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self.display_entries):
            return
        display_entry = self.display_entries[row]
        if display_entry.get("kind") != "entry":
            return
        entry = display_entry["entry"]
        if entry.item_type != "heading":
            return
        collapsed = self._collapsed_headings()
        if entry.order_test_id in collapsed:
            collapsed.remove(entry.order_test_id)
        else:
            collapsed.add(entry.order_test_id)
        self._save_collapsed_headings()
        self.load_order()



    def _load_collapsed_headings(self) -> dict[int, set[int]]:
        ui_state = self.database.get_ui_state()
        raw = ui_state.get("collapsed_headings_by_order", {})
        if not isinstance(raw, dict):
            return {}
        collapsed: dict[int, set[int]] = {}
        for order_id, values in raw.items():
            try:
                normalized_order_id = int(order_id)
            except (TypeError, ValueError):
                continue
            if not isinstance(values, list):
                continue
            collapsed[normalized_order_id] = {int(value) for value in values if isinstance(value, int) or isinstance(value, str) and str(value).isdigit()}
        return collapsed

    def _save_collapsed_headings(self) -> None:
        ui_state = self.database.get_ui_state()
        ui_state["collapsed_headings_by_order"] = {
            str(order_id): sorted(values)
            for order_id, values in self.collapsed_headings_by_order.items()
            if values
        }
        self.database.save_ui_state(ui_state)

    def _collapsed_headings(self) -> set[int]:
        return self.collapsed_headings_by_order.setdefault(self.order_id, set())

    def _style_heading_rows(self) -> None:
        heading_color = QColor("#2a3140")
        heading_text = QColor("#f5f7fa")
        heading_font = QFont()
        heading_font.setBold(True)
        for row_index, display_entry in enumerate(self.display_entries):
            if display_entry.get("kind") != "entry":
                continue
            entry = display_entry["entry"]
            if entry.item_type != "heading":
                continue
            for column_index in range(self.results_table.columnCount()):
                item = self.results_table.item(row_index, column_index)
                if item is None:
                    continue
                item.setBackground(heading_color)
                item.setForeground(heading_text)
                item.setFont(heading_font)
                if column_index > 0:
                    item.setText("")
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            widget = self.results_table.cellWidget(row_index, 1)
            if widget is not None:
                widget.hide()

    def _install_inline_result_widgets(self) -> None:
        for row_index, display_entry in enumerate(self.display_entries):
            self.results_table.removeCellWidget(row_index, 1)
            if display_entry.get("kind") != "entry":
                continue
            entry = display_entry["entry"]
            if entry.item_type == "heading":
                continue
            item = self.results_table.item(row_index, 1)
            if item is not None:
                item.setText("")
            container = QWidget()
            container.setStyleSheet("background: transparent;")
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 6)
            container_layout.setSpacing(0)

            if entry.result_kind == "select":
                editor = QComboBox()
                editor.setEditable(False)
                editor.setInsertPolicy(QComboBox.NoInsert)
                editor.setProperty("result_row", row_index)
                editor.installEventFilter(self)
                options = self.database.deserialize_select_options(entry.select_options)
                editor.blockSignals(True)
                editor.addItems(options)
                if entry.result_value and editor.findText(entry.result_value) < 0:
                    editor.addItem(entry.result_value)
                current_value = entry.result_value or entry.default_result_value or ""
                current_index = editor.findText(current_value) if current_value else -1
                if current_index >= 0:
                    editor.setCurrentIndex(current_index)
                elif editor.count():
                    editor.setCurrentIndex(0)
                editor.blockSignals(False)
                editor.currentTextChanged.connect(
                    lambda value, row=row_index: self._save_inline_result_value(row, value)
                )
                editor.currentTextChanged.connect(
                    lambda _value, row=row_index: self._select_result_row(row)
                )
            else:
                editor = QLineEdit(entry.result_value or entry.default_result_value or "")
                editor.setPlaceholderText(tr("Enter result"))
                editor.setClearButtonEnabled(False)
                editor.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                editor.setProperty("result_row", row_index)
                editor.installEventFilter(self)
                editor.editingFinished.connect(
                    lambda row=row_index, field=editor: self._save_inline_result_value(row, field.text())
                )
                editor.textEdited.connect(lambda _text, row=row_index: self._select_result_row(row))

            container_layout.addWidget(editor, 1, Qt.AlignVCenter)
            self.results_table.setCellWidget(row_index, 1, container)

    def _save_inline_result_value(self, row: int, value: str) -> None:
        if row < 0 or row >= len(self.display_entries):
            return
        display_entry = self.display_entries[row]
        if display_entry.get("kind") != "entry":
            return
        entry = display_entry["entry"]
        if entry.item_type == "heading":
            return
        current_value = entry.result_value or entry.default_result_value or ""
        if value == current_value:
            return
        self.database.save_result_entry(
            order_test_id=entry.order_test_id,
            result_value=value,
            unit=entry.unit or "",
            lower_value=entry.lower_value,
            upper_value=entry.upper_value,
            reference_text=entry.reference_text or "",
            comments=entry.comments or "",
            result_kind=entry.result_kind,
        )
        entry.result_value = value
        item = self.results_table.item(row, 1)
        if item is not None:
            item.setText("")
        if self.current_entry is not None and self.current_entry.order_test_id == entry.order_test_id:
            self._set_result_editor_value(entry, value)
            self.flag_preview.setText(entry.flag or "")

    def _select_result_row(self, row: int) -> None:
        if row < 0 or row >= len(self.display_entries):
            return
        if self.results_table.currentRow() != row:
            self.results_table.selectRow(row)

    def _focus_result_editor(self, row: int) -> None:
        if row < 0 or row >= len(self.display_entries):
            return
        widget = self.results_table.cellWidget(row, 1)
        if widget is None or widget.isHidden():
            return
        editor = widget.findChild(QLineEdit) or widget.findChild(QComboBox)
        if editor is None:
            return
        self.results_table.selectRow(row)
        editor.setFocus()
        if isinstance(editor, QLineEdit):
            editor.selectAll()

    def _move_result_editor_focus(self, start_row: int, step: int) -> bool:
        row = start_row + step
        while 0 <= row < len(self.display_entries):
            display_entry = self.display_entries[row]
            if display_entry.get("kind") != "entry":
                row += step
                continue
            entry = display_entry["entry"]
            if entry.item_type != "heading" and not self.results_table.isRowHidden(row):
                self._focus_result_editor(row)
                return True
            row += step
        return False

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if event.type() == QEvent.KeyPress and isinstance(watched, (QLineEdit, QComboBox)):
            row_data = watched.property("result_row")
            if isinstance(row_data, int):
                if isinstance(watched, QComboBox) and watched.view().isVisible():
                    return super().eventFilter(watched, event)
                if event.key() == Qt.Key_Down and self._move_result_editor_focus(row_data, 1):
                    return True
                if event.key() == Qt.Key_Up and self._move_result_editor_focus(row_data, -1):
                    return True
        return super().eventFilter(watched, event)

    def _first_selectable_row(self) -> int:
        for row_index, display_entry in enumerate(self.display_entries):
            if display_entry.get("kind") != "entry":
                continue
            entry = display_entry["entry"]
            if entry.item_type != "heading" and not self.results_table.isRowHidden(row_index):
                return row_index
        return -1

    def load_selected_entry(self) -> None:
        row = self.results_table.currentRow()
        if row < 0 or row >= len(self.display_entries):
            return
        display_entry = self.display_entries[row]
        if display_entry.get("kind") == "outsourced_panel":
            self._open_outsourced_panel_in_pdf(str(display_entry.get("panel_label") or ""))
            return
        entry = display_entry["entry"]
        self.current_entry = entry
        self.test_name.setText(entry.test_name)
        is_heading = entry.item_type == "heading"
        is_comment = entry.item_type == "comment"
        is_outsourced = bool(getattr(entry, "is_outsourced", 0))
        result_value = "" if is_heading else entry.result_value or entry.default_result_value or ""
        self._set_result_editor_value(entry, result_value)
        self.unit.setText("" if is_heading or is_comment or is_outsourced else entry.unit or "")
        self.lower_value.setText("" if is_heading or is_comment or is_outsourced or entry.lower_value is None else entry.lower_value)
        self.upper_value.setText("" if is_heading or is_comment or is_outsourced or entry.upper_value is None else entry.upper_value)
        self.reference_text.setPlainText("" if is_heading or is_comment or is_outsourced else entry.reference_text or "")
        self.comments.setPlainText("" if is_heading else entry.comments or "")
        self.flag_preview.setText("" if is_heading or is_comment or is_outsourced else entry.flag or "")
        self._set_entry_fields_enabled(not is_heading, is_comment=is_comment, is_outsourced=is_outsourced)

    def save_result(self) -> None:
        if self.current_entry is None:
            QMessageBox.warning(self, tr("Missing Data"), tr("Select a test entry first."))
            return
        if self.current_entry.item_type == "heading":
            QMessageBox.warning(self, tr("Missing Data"), tr("This row is a panel subheading."))
            return
        try:
            lower = self._optional_float(self.lower_value.text())
            upper = self._optional_float(self.upper_value.text())
        except ValueError:
            QMessageBox.warning(self, tr("Invalid Data"), tr("Lower and upper values must be numeric."))
            return

        self.database.save_result_entry(
            order_test_id=self.current_entry.order_test_id,
            result_value=self._current_result_value(),
            unit=self.unit.text(),
            lower_value=lower,
            upper_value=upper,
            reference_text=self.reference_text.toPlainText(),
            comments=self.comments.toPlainText(),
            result_kind=self.current_entry.result_kind,
        )
        self.load_order()
        QMessageBox.information(self, tr("Saved"), tr("Result saved."))

    def clear_entry_form(self) -> None:
        self.current_entry = None
        self.test_name.clear()
        self.result_value_text.clear()
        self.result_value_select.clear()
        self.result_value_comment.clear()
        self.result_value_stack.setCurrentWidget(self.result_value_text)
        self.unit.clear()
        self.lower_value.clear()
        self.upper_value.clear()
        self.reference_text.clear()
        self.comments.clear()
        self.flag_preview.clear()
        self._set_entry_fields_enabled(True)

    def _set_entry_fields_enabled(
        self,
        enabled: bool,
        is_comment: bool = False,
        is_outsourced: bool = False,
    ) -> None:
        self.result_value_text.setEnabled(enabled)
        self.result_value_select.setEnabled(enabled)
        self.result_value_comment.setEnabled(enabled)
        self.unit.setEnabled(enabled and not is_comment and not is_outsourced)
        self.lower_value.setEnabled(enabled and not is_comment and not is_outsourced)
        self.upper_value.setEnabled(enabled and not is_comment and not is_outsourced)
        self.reference_text.setEnabled(enabled and not is_comment and not is_outsourced)
        self.comments.setEnabled(enabled)
        self.save_button.setEnabled(enabled)
        self._set_entry_row_visible("unit", not is_outsourced)
        self._set_entry_row_visible("lower", not is_outsourced)
        self._set_entry_row_visible("upper", not is_outsourced)
        self._set_entry_row_visible("reference", not is_outsourced)
        self._set_entry_row_visible("flag", not is_outsourced)

    def _set_entry_row_visible(self, key: str, visible: bool) -> None:
        row = self._entry_row_widgets.get(key)
        if row is None:
            return
        label, widget = row
        label.setVisible(visible)
        widget.setVisible(visible)

    def _build_display_entries(self) -> list[dict[str, object]]:
        display_entries: list[dict[str, object]] = []
        seen_outsourced_panels: set[str] = set()
        for entry in self.current_entries:
            if bool(getattr(entry, "is_outsourced", 0)):
                panel_label = str(getattr(entry, "source_label", None) or entry.test_name or "").strip()
                if panel_label and panel_label not in seen_outsourced_panels:
                    display_entries.append({"kind": "outsourced_panel", "panel_label": panel_label})
                    seen_outsourced_panels.add(panel_label)
                continue
            display_entries.append({"kind": "entry", "entry": entry})
        return display_entries

    def _open_outsourced_panel_in_pdf(self, panel_label: str) -> None:
        current_order_id = int(self.order_id)
        candidates: list[QWidget] = []
        parent = self.parentWidget()
        while parent is not None:
            candidates.append(parent)
            parent = parent.parentWidget()
        window = self.window()
        if isinstance(window, QWidget):
            candidates.append(window)
        candidates.extend(widget for widget in QApplication.topLevelWidgets() if isinstance(widget, QWidget))
        seen_ids: set[int] = set()
        for candidate in candidates:
            candidate_id = id(candidate)
            if candidate_id in seen_ids:
                continue
            seen_ids.add(candidate_id)
            navigate = getattr(candidate, "navigate_to_pdf_target", None)
            if callable(navigate):
                navigate(current_order_id, panel_label)
                self.accept()
                return
        QMessageBox.warning(self, tr("Missing Selection"), tr("Could not open the PDF extractor from this window."))

    @staticmethod
    def _optional_float(value: str) -> str | None:
        normalized = value.strip()
        if not normalized:
            return None
        try:
            Decimal(normalized)
        except InvalidOperation as exc:
            raise ValueError(str(exc)) from exc
        return normalized

    @staticmethod
    def _format_range(lower: str | None, upper: str | None, reference_text: str | None) -> str:
        parts: list[str] = []
        if lower is not None or upper is not None:
            parts.append(f"{'' if lower is None else lower} - {'' if upper is None else upper}".strip())
        if reference_text:
            parts.append(reference_text)
        return " | ".join(part for part in parts if part)
