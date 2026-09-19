from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import QBuffer, QEvent, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database, ResultEntryRecord
from spdxlims.db.panels import GRAM_NEGATIVE, GRAM_POSITIVE
from spdxlims.deployment import DeploymentService
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.result_service import ResultService
from spdxlims.theme import recolor


class OrderResultsDialog(QDialog):
    def __init__(self, database: Database, order_id: int | str, deployment_service: DeploymentService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.order_id = order_id
        self.result_service = ResultService(database, deployment_service)
        self.current_entries: list[ResultEntryRecord] = []
        self.display_entries: list[dict[str, object]] = []
        self.current_entry: ResultEntryRecord | None = None
        # Guards the culture editor's change signals while it is being populated.
        self._culture_loading = False
        self._culture_code = ""
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
            recolor(
                """
            QTableWidget {
                background-color: #20252B;
            }
            QTableWidget QLineEdit {
                background-color: #20252B;
                color: #F0F4FF;
                border: 1px solid #2E3640;
                border-radius: 0px;
                padding: 0px 6px;
                min-height: 26px;
                font-size: 12pt;
                font-weight: 500;
                selection-background-color: #BD93F9;
                selection-color: #FFFFFF;
            }
            QTableWidget QLineEdit:focus {
                border: 1px solid #BD93F9;
                background-color: #20252B;
            }
            QTableWidget QComboBox {
                background-color: #20252B;
                color: #F0F4FF;
                border: 1px solid #2E3640;
                border-radius: 0px;
                padding: 0px 18px 0px 6px;
                min-height: 26px;
                font-size: 12pt;
                font-weight: 500;
            }
            QTableWidget QComboBox:focus {
                border: 1px solid #BD93F9;
                background-color: #20252B;
            }
            QTableWidget QComboBox QAbstractItemView {
                background-color: #20252B;
                color: #F0F4FF;
                border: 1px solid #2E3640;
                outline: 0;
                selection-background-color: #7756BE;
                selection-color: #FFFFFF;
            }
            QTableWidget QComboBox QAbstractItemView::item {
                background-color: #20252B;
                color: #F0F4FF;
                padding: 2px 8px;
                min-height: 16px;
            }
            QTableWidget QComboBox QAbstractItemView::item:selected {
                background-color: #7756BE;
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
        )
        layout.addWidget(self.results_table)
        layout.addWidget(self._build_culture_group())
        return self.order_group

    def _build_culture_group(self) -> QWidget:
        """Gram choice and the free-form organism rows for a cultivo panel.

        These are not test results -- they live in order_culture_data -- so they
        need their own editor rather than a row in the results table. The whole
        group stays hidden unless the order actually contains a cultivo panel.
        """
        self.culture_group = QGroupBox(tr("Culture"))
        self.culture_group.setVisible(False)
        layout = QVBoxLayout(self.culture_group)
        layout.setSpacing(6)

        gram_row = QHBoxLayout()
        gram_row.setSpacing(8)
        self.culture_gram_combo = QComboBox()
        self.culture_gram_combo.addItem(tr("Gram positive"), GRAM_POSITIVE)
        self.culture_gram_combo.addItem(tr("Gram negative"), GRAM_NEGATIVE)
        self.culture_gram_combo.currentIndexChanged.connect(self._save_culture_data)
        gram_row.addWidget(QLabel(tr("Gram")))
        gram_row.addWidget(self.culture_gram_combo)
        gram_row.addStretch(1)
        self.culture_add_row_button = QPushButton(tr("Add Row"))
        self.culture_add_row_button.clicked.connect(self._add_culture_row)
        self.culture_remove_row_button = QPushButton(tr("Remove Row"))
        self.culture_remove_row_button.clicked.connect(self._remove_culture_row)
        gram_row.addWidget(self.culture_add_row_button)
        gram_row.addWidget(self.culture_remove_row_button)
        layout.addLayout(gram_row)

        self.culture_helper = QLabel(
            tr("Type the organisms searched and their result. Empty rows are left off the report.")
        )
        self.culture_helper.setWordWrap(True)
        self.culture_helper.setStyleSheet("color: #6b7480;")
        layout.addWidget(self.culture_helper)

        self.culture_table = QTableWidget(0, 2)
        self.culture_table.setHorizontalHeaderLabels([tr("Organism"), tr("Result")])
        self.culture_table.verticalHeader().setVisible(False)
        self.culture_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.culture_table.setSelectionMode(QTableWidget.SingleSelection)
        self.culture_table.setMinimumHeight(140)
        # The report prints these columns at 1/3 and 2/3; mirror that here so the
        # entry screen reads the same way as the printed result.
        header = self.culture_table.horizontalHeader()
        header.setStretchLastSection(True)
        self.culture_table.setColumnWidth(0, 200)
        self.culture_table.itemChanged.connect(self._on_culture_item_changed)
        layout.addWidget(self.culture_table)
        return self.culture_group

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
        self.result_value_image_button = QPushButton(tr("Manage Images"))
        self.result_value_image_button.setObjectName("resultPrimaryInput")
        self.result_value_image_button.clicked.connect(self._manage_current_entry_images)
        self.result_value_stack = QStackedWidget()
        self.result_value_stack.setFixedHeight(36)
        self.result_value_stack.addWidget(self.result_value_text)
        self.result_value_stack.addWidget(self.result_value_select)
        self.result_value_stack.addWidget(self.result_value_comment)
        self.result_value_stack.addWidget(self.result_value_image_button)
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
            recolor(
                """
            QLineEdit#resultPrimaryInput,
            QTextEdit#resultPrimaryInput,
            QComboBox#resultPrimaryInput {
                background-color: #20252B;
                border: 1px solid #2E3640;
                border-radius: 8px;
                padding: 3px 6px;
                color: #F0F4FF;
                font-size: 12pt;
                font-weight: 500;
            }
            QTextEdit#resultPrimaryInput {
                padding: 4px 6px;
            }
            QLineEdit#resultPrimaryInput:focus,
            QTextEdit#resultPrimaryInput:focus,
            QComboBox#resultPrimaryInput:focus {
                border: 1px solid #BD93F9;
                background-color: #20252B;
            }
            QLineEdit#resultPrimaryInput:disabled,
            QTextEdit#resultPrimaryInput:disabled,
            QComboBox#resultPrimaryInput:disabled {
                background-color: #252C34;
                border-color: #2E3640;
                color: #697789;
            }
            QComboBox#resultPrimaryInput::drop-down {
                width: 30px;
                border: none;
            }
            """
            )
        )

    def _set_result_editor_value(self, entry: ResultEntryRecord | None, value: str) -> None:
        if entry is not None and entry.item_type == "comment":
            self.result_value_comment.setPlainText(value)
            self.result_value_stack.setCurrentWidget(self.result_value_comment)
            return
        if entry is not None and entry.item_type != "heading" and entry.result_kind == "observation":
            self.result_value_comment.setPlainText(value)
            self.result_value_stack.setCurrentWidget(self.result_value_comment)
            return
        if entry is not None and entry.item_type != "heading" and entry.result_kind == "image":
            count = len(self.database.list_result_images(entry.order_test_id))
            self.result_value_image_button.setText(tr("Manage Images") + f" ({count})")
            self.result_value_stack.setCurrentWidget(self.result_value_image_button)
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
        self._refresh_culture_section()
        self._apply_observation_row_spans()
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



    # --- cultivo panel: gram choice + free-form organism rows ---

    def _culture_panel_code(self) -> str:
        """Panel code of the cultivo panel on this order, or '' if there is none.

        Culture data is stored locally per order, so this is skipped in server
        mode (where order_id is a UUID and the local helpers are unavailable).
        """
        lookup = getattr(self.database, "get_culture_panel_codes_by_name", None)
        if not callable(lookup):
            return ""
        try:
            int(self.order_id)
        except (TypeError, ValueError):
            return ""
        codes = lookup()
        if not codes:
            return ""
        # Order items carry labels like "NAME (CODE) - 3 tests"; normalize to the
        # bare panel name the same way the report pipeline does.
        normalize = getattr(self.database, "_normalize_report_panel_label", None)
        for entry in self.current_entries:
            raw = str(getattr(entry, "source_label", "") or "")
            label = (normalize(raw) if callable(normalize) else raw).strip().casefold()
            if label in codes:
                return codes[label]
        return ""

    def _refresh_culture_section(self) -> None:
        code = self._culture_panel_code()
        self._culture_code = code
        self.culture_group.setVisible(bool(code))
        if not code:
            return
        data = self.database.get_order_culture_data(int(self.order_id), code)
        index = self.culture_gram_combo.findData(data["gram"] or GRAM_POSITIVE)
        self._culture_loading = True
        try:
            self.culture_gram_combo.setCurrentIndex(index if index >= 0 else 0)
            rows = data["rows"] or []
            # Always leave one empty row so there is somewhere to type without
            # having to click Add Row first.
            self.culture_table.setRowCount(len(rows) + 1)
            for row_index, entry in enumerate(rows):
                self.culture_table.setItem(row_index, 0, QTableWidgetItem(entry["label"]))
                self.culture_table.setItem(row_index, 1, QTableWidgetItem(entry["value"]))
            self.culture_table.setItem(len(rows), 0, QTableWidgetItem(""))
            self.culture_table.setItem(len(rows), 1, QTableWidgetItem(""))
        finally:
            self._culture_loading = False

    def _collect_culture_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for row_index in range(self.culture_table.rowCount()):
            label_item = self.culture_table.item(row_index, 0)
            value_item = self.culture_table.item(row_index, 1)
            rows.append(
                {
                    "label": (label_item.text() if label_item else "").strip(),
                    "value": (value_item.text() if value_item else "").strip(),
                }
            )
        return rows

    def _save_culture_data(self) -> None:
        if getattr(self, "_culture_loading", False) or not getattr(self, "_culture_code", ""):
            return
        self.database.save_order_culture_data(
            int(self.order_id),
            self._culture_code,
            str(self.culture_gram_combo.currentData() or GRAM_POSITIVE),
            self._collect_culture_rows(),
        )

    def _on_culture_item_changed(self, _item: QTableWidgetItem) -> None:
        if getattr(self, "_culture_loading", False):
            return
        self._save_culture_data()
        # Keep a spare blank row at the bottom as the tech fills the last one in.
        last = self.culture_table.rowCount() - 1
        if last < 0:
            return
        label_item = self.culture_table.item(last, 0)
        value_item = self.culture_table.item(last, 1)
        if (label_item and label_item.text().strip()) or (value_item and value_item.text().strip()):
            self._add_culture_row()

    def _add_culture_row(self) -> None:
        self._culture_loading = True
        try:
            row_index = self.culture_table.rowCount()
            self.culture_table.setRowCount(row_index + 1)
            self.culture_table.setItem(row_index, 0, QTableWidgetItem(""))
            self.culture_table.setItem(row_index, 1, QTableWidgetItem(""))
        finally:
            self._culture_loading = False

    def _remove_culture_row(self) -> None:
        row_index = self.culture_table.currentRow()
        if row_index < 0:
            return
        self.culture_table.removeRow(row_index)
        if self.culture_table.rowCount() == 0:
            self._add_culture_row()
        self._save_culture_data()

    def _load_collapsed_headings(self) -> dict[int, set[int]]:
        # Only this dialog's own order is ever consulted, so read just that row
        # instead of loading every order's collapsed state.
        values = self.database.get_order_ui_value("collapsed_headings", self.order_id)
        if not isinstance(values, list):
            return {}
        normalized = {
            int(value)
            for value in values
            if isinstance(value, int) or (isinstance(value, str) and str(value).isdigit())
        }
        return {self.order_id: normalized}

    def _save_collapsed_headings(self) -> None:
        values = sorted(self.collapsed_headings_by_order.get(self.order_id, set()))
        if values:
            self.database.set_order_ui_value("collapsed_headings", self.order_id, values)
        else:
            self.database.delete_order_ui_value("collapsed_headings", self.order_id)

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

    def _apply_observation_row_spans(self) -> None:
        # Observation-kind entries have no unit/range/flag, so merge those
        # columns into the Result column for a two-column (name + wide text) look.
        for row_index, display_entry in enumerate(self.display_entries):
            if display_entry.get("kind") != "entry":
                self.results_table.setSpan(row_index, 1, 1, 1)
                continue
            entry = display_entry["entry"]
            is_observation = entry.item_type not in {"heading", "comment"} and entry.result_kind == "observation"
            self.results_table.setSpan(row_index, 1, 1, 4 if is_observation else 1)

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

            is_formula_test = bool(getattr(entry, 'formula', None))
            if entry.result_kind == "image":
                count = len(self.database.list_result_images(entry.order_test_id))
                editor = QPushButton(tr("Manage Images") + f" ({count})")
                editor.setProperty("result_row", row_index)
                editor.clicked.connect(
                    lambda _checked=False, oid=entry.order_test_id, name=entry.test_name, row=row_index: (
                        self._select_result_row(row),
                        self._open_image_manager(oid, name),
                    )
                )
            elif entry.result_kind == "select" and not is_formula_test:
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
                editor.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                editor.setProperty("result_row", row_index)
                if is_formula_test:
                    editor.setReadOnly(True)
                    editor.setEnabled(False)
                    editor.setPlaceholderText(tr("Calculated"))
                else:
                    editor.setPlaceholderText(tr("Enter result"))
                    editor.setClearButtonEnabled(False)
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
        try:
            self.result_service.save_result_entry(
                order_test_id=entry.order_test_id,
                result_value=value,
                unit=entry.unit or "",
                lower_value=entry.lower_value,
                upper_value=entry.upper_value,
                reference_text=entry.reference_text or "",
                comments=entry.comments or "",
                result_kind=entry.result_kind,
            )
        except RuntimeError as exc:
            QMessageBox.warning(self, tr("Save Failed"), str(exc))
            return
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
        is_formula = bool(getattr(entry, "formula", None))
        is_image = entry.item_type not in {"heading", "comment"} and entry.result_kind == "image"
        is_observation = entry.item_type not in {"heading", "comment"} and entry.result_kind == "observation"
        hide_range_fields = is_image or is_observation
        result_value = "" if is_heading else entry.result_value or entry.default_result_value or ""
        self._set_result_editor_value(entry, result_value)
        self.unit.setText("" if is_heading or is_comment or is_outsourced or hide_range_fields else entry.unit or "")
        self.lower_value.setText("" if is_heading or is_comment or is_outsourced or hide_range_fields or entry.lower_value is None else entry.lower_value)
        self.upper_value.setText("" if is_heading or is_comment or is_outsourced or hide_range_fields or entry.upper_value is None else entry.upper_value)
        self.reference_text.setPlainText("" if is_heading or is_comment or is_outsourced or hide_range_fields else entry.reference_text or "")
        self.comments.setPlainText("" if is_heading else entry.comments or "")
        self.flag_preview.setText("" if is_heading or is_comment or is_outsourced or hide_range_fields else entry.flag or "")
        self._set_entry_fields_enabled(not is_heading, is_comment=is_comment, is_outsourced=is_outsourced, is_formula=is_formula, is_image=hide_range_fields)

    def save_result(self) -> None:
        if self.current_entry is None:
            QMessageBox.warning(self, tr("Missing Data"), tr("Select a test entry first."))
            return
        if self.current_entry.item_type == "heading":
            QMessageBox.warning(self, tr("Missing Data"), tr("This row is a panel subheading."))
            return
        is_image = self.current_entry.result_kind == "image"
        try:
            lower = None if is_image else self._optional_float(self.lower_value.text())
            upper = None if is_image else self._optional_float(self.upper_value.text())
        except ValueError:
            QMessageBox.warning(self, tr("Invalid Data"), tr("Lower and upper values must be numeric."))
            return

        # For image results the value summary is maintained by the image manager;
        # the entry form only persists comments alongside it.
        result_value = self.current_entry.result_value or "" if is_image else self._current_result_value()
        try:
            self.result_service.save_result_entry(
                order_test_id=self.current_entry.order_test_id,
                result_value=result_value,
                unit="" if is_image else self.unit.text(),
                lower_value=lower,
                upper_value=upper,
                reference_text="" if is_image else self.reference_text.toPlainText(),
                comments=self.comments.toPlainText(),
                result_kind=self.current_entry.result_kind,
            )
        except RuntimeError as exc:
            QMessageBox.warning(self, tr("Save Failed"), str(exc))
            return
        self.load_order()
        QMessageBox.information(self, tr("Saved"), tr("Result saved."))

    def _manage_current_entry_images(self) -> None:
        if self.current_entry is None or self.current_entry.result_kind != "image":
            return
        self._open_image_manager(self.current_entry.order_test_id, self.current_entry.test_name)

    def _open_image_manager(self, order_test_id: int, test_name: str) -> None:
        dialog = ResultImageManagerDialog(self.database, order_test_id, test_name, parent=self)
        dialog.exec()
        # Reload so the result summary, inline button and detail panel reflect changes.
        self.load_order()

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
        is_formula: bool = False,
        is_image: bool = False,
    ) -> None:
        # `is_image` also covers 'observation' kind entries, which hide the same
        # range/unit/flag fields as image results (see load_selected_entry).
        result_editable = enabled and not is_formula
        self.result_value_text.setEnabled(result_editable)
        self.result_value_select.setEnabled(result_editable)
        self.result_value_comment.setEnabled(result_editable)
        self.result_value_image_button.setEnabled(enabled)
        self.unit.setEnabled(enabled and not is_comment and not is_outsourced and not is_image)
        self.lower_value.setEnabled(enabled and not is_comment and not is_outsourced and not is_image)
        self.upper_value.setEnabled(enabled and not is_comment and not is_outsourced and not is_image)
        self.reference_text.setEnabled(enabled and not is_comment and not is_outsourced and not is_image)
        self.comments.setEnabled(enabled)
        self.save_button.setEnabled(enabled and not is_formula)
        self._set_entry_row_visible("unit", not is_outsourced and not is_image)
        self._set_entry_row_visible("lower", not is_outsourced and not is_image)
        self._set_entry_row_visible("upper", not is_outsourced and not is_image)
        self._set_entry_row_visible("reference", not is_outsourced and not is_image)
        self._set_entry_row_visible("flag", not is_outsourced and not is_image)

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
        try:
            current_order_id = int(self.order_id)
        except (TypeError, ValueError):
            QMessageBox.warning(
                self,
                tr("Not Available"),
                tr("Opening outsourced panels in the PDF extractor is not available in server mode yet."),
            )
            return
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


_IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

# Cap the long edge of stored captures. The report displays images at ~80mm, so
# 2000px keeps print quality while shrinking raw multi-megapixel microscope files.
# Originals stay on the capture PC and can be emailed if a doctor needs to zoom.
_MAX_IMAGE_DIMENSION = 2000
_JPEG_QUALITY = 85


def _prepare_image_for_storage(data: bytes, suffix: str) -> tuple[bytes, str]:
    """Downscale oversized captures before storing; small images are kept as-is."""
    image = QImage()
    if not image.loadFromData(data):
        # Not decodable here (unusual format) — store the original bytes untouched.
        return data, _IMAGE_MIME_TYPES.get(suffix, "image/png")
    if max(image.width(), image.height()) <= _MAX_IMAGE_DIMENSION:
        # Already small enough; avoid re-encoding so we don't add artifacts.
        return data, _IMAGE_MIME_TYPES.get(suffix, "image/png")
    scaled = image.scaled(
        _MAX_IMAGE_DIMENSION,
        _MAX_IMAGE_DIMENSION,
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )
    buffer = QBuffer()
    buffer.open(QBuffer.WriteOnly)
    if scaled.hasAlphaChannel():
        scaled.save(buffer, "PNG")
        mime_type = "image/png"
    else:
        scaled.save(buffer, "JPEG", _JPEG_QUALITY)
        mime_type = "image/jpeg"
    encoded = bytes(buffer.data())
    buffer.close()
    # Keep the downscaled copy whenever we have one — its bounded dimensions give
    # predictable report sizing. Only fall back if encoding produced nothing.
    if not encoded:
        return data, _IMAGE_MIME_TYPES.get(suffix, "image/png")
    return encoded, mime_type


class ResultImageManagerDialog(QDialog):
    """Add, caption, reorder and remove the microscope captures for an image test."""

    def __init__(self, database: Database, order_test_id: int, test_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.order_test_id = order_test_id
        self.setModal(True)
        self.resize(560, 520)
        self.setWindowTitle(tr("Manage Images") + (f" — {test_name}" if test_name else ""))

        root = QVBoxLayout(self)
        root.addWidget(QLabel(test_name or tr("Images")))

        self.image_list = QListWidget()
        self.image_list.setViewMode(QListWidget.IconMode)
        self.image_list.setIconSize(QSize(140, 140))
        self.image_list.setResizeMode(QListWidget.Adjust)
        self.image_list.setMovement(QListWidget.Static)
        self.image_list.setSpacing(8)
        self.image_list.setWordWrap(True)
        self.image_list.itemDoubleClicked.connect(lambda _item: self._edit_caption())
        root.addWidget(self.image_list, 1)

        buttons = QHBoxLayout()
        add_button = QPushButton(tr("Add Image"))
        add_button.clicked.connect(self._add_images)
        self.caption_button = QPushButton(tr("Edit Caption"))
        self.caption_button.clicked.connect(self._edit_caption)
        self.remove_button = QPushButton(tr("Remove Image"))
        self.remove_button.clicked.connect(self._remove_image)
        self.up_button = QPushButton(tr("Move Up"))
        self.up_button.clicked.connect(lambda: self._move_image(-1))
        self.down_button = QPushButton(tr("Move Down"))
        self.down_button.clicked.connect(lambda: self._move_image(1))
        buttons.addWidget(add_button)
        buttons.addWidget(self.caption_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        buttons.addWidget(self.up_button)
        buttons.addWidget(self.down_button)
        root.addLayout(buttons)

        close_row = QHBoxLayout()
        close_button = QPushButton(tr("Close"))
        close_button.clicked.connect(self.accept)
        close_row.addStretch(1)
        close_row.addWidget(close_button)
        root.addLayout(close_row)

        self._reload_images()

    def _reload_images(self) -> None:
        self.image_list.clear()
        for image in self.database.list_result_images(self.order_test_id, include_data=True):
            pixmap = QPixmap()
            data = image.get("image_data")
            if data is not None:
                pixmap.loadFromData(bytes(data))
            caption = str(image.get("caption") or "")
            item = QListWidgetItem(caption or tr("Image"))
            if not pixmap.isNull():
                item.setIcon(pixmap.scaled(140, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            item.setData(Qt.UserRole, int(image["id"]))
            item.setTextAlignment(Qt.AlignHCenter)
            self.image_list.addItem(item)
        has_items = self.image_list.count() > 0
        self.caption_button.setEnabled(has_items)
        self.remove_button.setEnabled(has_items)
        self.up_button.setEnabled(has_items)
        self.down_button.setEnabled(has_items)

    def _add_images(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self,
            tr("Select Image"),
            "",
            tr("Image Files") + " (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff)",
        )
        if not paths:
            return
        added = 0
        for path in paths:
            file_path = Path(path)
            try:
                data = file_path.read_bytes()
            except OSError as exc:
                QMessageBox.warning(self, tr("Add Image"), str(exc))
                continue
            if not data:
                continue
            stored_data, mime_type = _prepare_image_for_storage(data, file_path.suffix.lower())
            self.database.add_result_image(self.order_test_id, stored_data, mime_type=mime_type, caption=file_path.stem)
            added += 1
        if added:
            self._reload_images()

    def _selected_image_id(self) -> int | None:
        item = self.image_list.currentItem()
        if item is None:
            return None
        return int(item.data(Qt.UserRole))

    def _edit_caption(self) -> None:
        item = self.image_list.currentItem()
        if item is None:
            return
        image_id = int(item.data(Qt.UserRole))
        current = "" if item.text() == tr("Image") else item.text()
        new_caption, ok = QInputDialog.getText(self, tr("Edit Caption"), tr("Caption"), text=current)
        if not ok:
            return
        self.database.update_result_image_caption(image_id, new_caption)
        self._reload_images()

    def _remove_image(self) -> None:
        image_id = self._selected_image_id()
        if image_id is None:
            return
        confirm = QMessageBox.question(
            self,
            tr("Remove Image"),
            tr("Remove this image?"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.database.delete_result_image(image_id)
        self._reload_images()

    def _move_image(self, step: int) -> None:
        row = self.image_list.currentRow()
        target = row + step
        if row < 0 or target < 0 or target >= self.image_list.count():
            return
        ordered_ids = [int(self.image_list.item(index).data(Qt.UserRole)) for index in range(self.image_list.count())]
        ordered_ids[row], ordered_ids[target] = ordered_ids[target], ordered_ids[row]
        self.database.reorder_result_images(self.order_test_id, ordered_ids)
        self._reload_images()
        self.image_list.setCurrentRow(target)
