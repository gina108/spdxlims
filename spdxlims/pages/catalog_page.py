from __future__ import annotations

from decimal import Decimal, InvalidOperation

import re
import sqlite3
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
        QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spdxlims.catalog_excel import (
    PANEL_IMPORT_COLUMNS,
    TEST_IMPORT_COLUMNS,
    build_panel_export_sheets,
    build_test_export_sheets,
    read_panel_workbook_rows,
    read_test_workbook_rows,
    write_panel_export_workbook,
    write_panel_import_template,
    write_test_export_workbook,
    write_test_import_template,
)
from spdxlims.database import Database, PanelRecord, TestRecord
from spdxlims.db.panels import (
    PANEL_KIND_CULTIVO,
    PANEL_KIND_FROTIS,
    PANEL_KIND_RESULTADO,
)
from spdxlims.deployment import DeploymentService
from spdxlims.panel_service import PanelService
from spdxlims.i18n import tr
from spdxlims.test_service import TestService
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.pages.panel_layout_dialog import PanelLayoutDialog


class TestDialog(QDialog):
    def __init__(self, database: Database, test_service: TestService | None = None, test_id: int | str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.test_service = test_service
        self.test_id = test_id
        self._editing = test_id is not None
        self.pending_ranges: list[dict[str, Any]] = []
        self._loaded_specimen_type = ""
        self._loaded_method = ""

        self.setModal(True)
        self.resize(940, 560)
        self.setWindowTitle(tr("Edit Test") if test_id is not None else tr("Add Test"))

        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        form = QFormLayout()
        self.test_code = QLineEdit()
        self.test_name = QLineEdit()
        self.category_name = QComboBox()
        self.category_name.setEditable(False)
        self.result_kind = QComboBox()
        self.result_kind.addItem(tr("Numeric"), "numeric")
        self.result_kind.addItem(tr("Text"), "text")
        self.result_kind.addItem(tr("Selectable"), "select")
        self.result_kind.addItem(tr("Observation"), "observation")
        self.result_kind.currentIndexChanged.connect(self._update_select_fields_visibility)
        self.select_options = QTextEdit()
        self.select_options.setFixedHeight(90)
        self.default_result_value = QLineEdit()
        self.result_multiplier = QLineEdit()
        self.result_multiplier.setPlaceholderText(tr("e.g. 1000"))
        self.formula = QLineEdit()
        self.formula.setPlaceholderText(tr("e.g. [CHOLTOTAL] - [HDL] - ([TRIG] / 5)"))

        form.addRow(tr("Code"), self.test_code)
        form.addRow(tr("Name"), self.test_name)
        form.addRow(tr("Equipment"), self.category_name)
        form.addRow(tr("Result Kind"), self.result_kind)
        self.select_options_label = QLabel(tr("Dropdown Options"))
        self.default_result_label = QLabel(tr("Default Result"))
        form.addRow(self.select_options_label, self.select_options)
        form.addRow(self.default_result_label, self.default_result_value)
        self.result_multiplier_label = QLabel(tr("Result Multiplier"))
        form.addRow(self.result_multiplier_label, self.result_multiplier)
        self.formula_label = QLabel(tr("Derived Formula"))
        form.addRow(self.formula_label, self.formula)
        content_layout.addLayout(form)

        range_group = QGroupBox(tr("Reference Ranges"))
        range_layout = QVBoxLayout(range_group)
        range_form = QGridLayout()

        self.range_sex = QComboBox()
        self.range_sex.addItem(tr("Any"), "")
        self.range_sex.addItem(tr("Male"), "M")
        self.range_sex.addItem(tr("Female"), "F")
        self.range_sex.addItem(tr("Other"), "O")
        self.range_age_min = QLineEdit()
        self.range_age_max = QLineEdit()
        self.range_lower = QLineEdit()
        self.range_upper = QLineEdit()
        self.range_unit = QLineEdit()
        self.range_reference_text = QTextEdit()
        self.range_reference_text.setFixedHeight(60)

        range_form.addWidget(QLabel(tr("Sex")), 0, 0)
        range_form.addWidget(self.range_sex, 0, 1)
        range_form.addWidget(QLabel(tr("Age Min Days")), 0, 2)
        range_form.addWidget(self.range_age_min, 0, 3)
        range_form.addWidget(QLabel(tr("Age Max Days")), 0, 4)
        range_form.addWidget(self.range_age_max, 0, 5)
        range_form.addWidget(QLabel(tr("Lower")), 1, 0)
        range_form.addWidget(self.range_lower, 1, 1)
        range_form.addWidget(QLabel(tr("Upper")), 1, 2)
        range_form.addWidget(self.range_upper, 1, 3)
        range_form.addWidget(QLabel(tr("Unit")), 1, 4)
        range_form.addWidget(self.range_unit, 1, 5)
        range_form.addWidget(QLabel(tr("Reference Text")), 2, 0)
        range_form.addWidget(self.range_reference_text, 2, 1, 1, 5)
        range_layout.addLayout(range_form)

        range_buttons = QHBoxLayout()
        add_range_button = QPushButton(tr("Add Range"))
        add_range_button.clicked.connect(self.add_reference_range)
        clear_range_button = QPushButton(tr("Clear Range Fields"))
        clear_range_button.clicked.connect(self._clear_range_form)
        range_buttons.addStretch(1)
        range_buttons.addWidget(clear_range_button)
        range_buttons.addWidget(add_range_button)
        range_layout.addLayout(range_buttons)

        self.ranges_table = QTableWidget(0, 7)
        self.ranges_table.setHorizontalHeaderLabels([tr("Sex"), tr("Age Min"), tr("Age Max"), tr("Lower"), tr("Upper"), tr("Unit"), tr("Reference")])
        self.ranges_table.horizontalHeader().setStretchLastSection(True)
        self.ranges_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.ranges_table.setSelectionMode(QTableWidget.SingleSelection)
        self.ranges_table.itemSelectionChanged.connect(self._load_selected_range_into_form)
        range_layout.addWidget(self.ranges_table)

        remove_range_button = QPushButton(tr("Remove Selected Range"))
        remove_range_button.clicked.connect(self.remove_selected_range)
        range_layout.addWidget(remove_range_button, alignment=Qt.AlignRight)
        content_layout.addWidget(range_group)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        cancel_button = QPushButton(tr("Cancel"))
        cancel_button.clicked.connect(self.reject)
        self.archive_test_button = QPushButton()
        self.archive_test_button.clicked.connect(self.toggle_test_archive)
        save_button = QPushButton(tr("Update Test") if self._editing else tr("Save Test"))
        save_button.clicked.connect(self.save_test)
        buttons.addStretch(1)
        if self._editing:
            buttons.addWidget(self.archive_test_button)
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        root.addLayout(buttons)

        self._load_equipment_choices()
        self._update_select_fields_visibility()
        if self.test_id is not None:
            self._load_test()

    def _load_test(self) -> None:
        detail = self._get_test_detail(self.test_id)
        if detail is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("The selected test could not be loaded."))
            self.reject()
            return
        self.test_code.setText(detail["code"])
        self.test_name.setText(detail["name"])
        self._set_equipment_value(detail.get("category_name") or "")
        self._loaded_specimen_type = str(detail.get("specimen_type") or "")
        self._loaded_method = str(detail.get("method") or "")
        result_index = self.result_kind.findData(detail["result_kind"])
        if result_index >= 0:
            self.result_kind.setCurrentIndex(result_index)
        self.select_options.setPlainText("\n".join(self._deserialize_select_options(detail.get("select_options"))))
        self.default_result_value.setText(detail.get("default_result_value") or "")
        multiplier = detail.get("result_multiplier")
        self.result_multiplier.setText(str(multiplier) if multiplier is not None else "")
        self.formula.setText(detail.get("formula") or "")
        self._update_select_fields_visibility()
        self.pending_ranges = [dict(reference) for reference in detail.get("reference_ranges", [])]
        self._refresh_ranges_table()
        if self._editing:
            self.archive_test_button.setText(tr("Unarchive Test") if not detail.get("is_active") else tr("Archive Test"))

    def _get_test_detail(self, test_id: int | str | None) -> dict[str, Any] | None:
        if test_id is None:
            return None
        if self.test_service is not None:
            return self.test_service.get_test_detail(test_id)
        return self.database.get_test_detail(int(test_id))

    def _deserialize_select_options(self, raw_value: str | None) -> list[str]:
        if self.test_service is not None:
            return self.test_service.deserialize_select_options(raw_value)
        return self.database.deserialize_select_options(raw_value)

    def _create_test(self, payload: dict[str, Any], reference_ranges: list[dict[str, Any]]) -> None:
        if self.test_service is not None:
            self.test_service.create_test(payload, reference_ranges)
            return
        self.database.create_test(payload, reference_ranges)

    def _update_test(self, test_id: int | str | None, payload: dict[str, Any], reference_ranges: list[dict[str, Any]]) -> None:
        if test_id is None:
            return
        if self.test_service is not None:
            self.test_service.update_test(test_id, payload, reference_ranges)
            return
        self.database.update_test(int(test_id), payload, reference_ranges)

    def _archive_test(self, test_id: int | str | None) -> None:
        if test_id is None:
            return
        if self.test_service is not None:
            self.test_service.archive_test(test_id)
            return
        self.database.archive_test(int(test_id))

    def _unarchive_test(self, test_id: int | str | None) -> None:
        if test_id is None:
            return
        if self.test_service is not None:
            self.test_service.unarchive_test(test_id)
            return
        self.database.unarchive_test(int(test_id))

    def add_reference_range(self) -> None:
        try:
            reference = self._range_from_form()
        except ValueError as exc:
            QMessageBox.warning(self, tr("Invalid Range"), str(exc))
            return

        if not self._range_has_values(reference):
            QMessageBox.warning(self, tr("Missing Data"), tr("Add at least one value before saving the range."))
            return

        row = self.ranges_table.currentRow()
        if 0 <= row < len(self.pending_ranges):
            self.pending_ranges[row] = reference
        else:
            self.pending_ranges.append(reference)
        self._refresh_ranges_table()
        self._clear_range_form()

    def remove_selected_range(self) -> None:
        row = self.ranges_table.currentRow()
        if row < 0 or row >= len(self.pending_ranges):
            return
        self.pending_ranges.pop(row)
        self._refresh_ranges_table()

    def toggle_test_archive(self) -> None:
        if not self._editing or self.test_id is None:
            return
        detail = self._get_test_detail(self.test_id)
        if detail is None:
            return
        if detail.get("is_active"):
            if QMessageBox.question(self, tr("Archive Test"), tr("Archive this test?")) != QMessageBox.Yes:
                return
            try:
                self._archive_test(self.test_id)
            except ValueError as exc:
                QMessageBox.warning(self, tr("Archive Failed"), str(exc))
                return
        else:
            self._unarchive_test(self.test_id)
        self.accept()

    def save_test(self) -> None:
        if not self.test_code.text().strip() or not self.test_name.text().strip():
            QMessageBox.warning(self, tr("Missing Data"), tr("Test code and test name are required."))
            return

        result_kind = self.result_kind.currentData()
        select_options = [line.strip() for line in self.select_options.toPlainText().splitlines() if line.strip()]
        default_result_value = self.default_result_value.text().strip()
        if result_kind == "select":
            if not select_options:
                QMessageBox.warning(self, tr("Missing Data"), tr("Add at least one dropdown option for selectable tests."))
                return
            if default_result_value and default_result_value not in select_options:
                QMessageBox.warning(self, tr("Invalid Data"), tr("Default result must match one of the dropdown options."))
                return
        else:
            select_options = []

        multiplier_text = self.result_multiplier.text().strip()
        try:
            result_multiplier = float(multiplier_text) if multiplier_text else None
        except ValueError:
            QMessageBox.warning(self, tr("Invalid Data"), tr("Result multiplier must be a number."))
            return

        payload = {
            "code": self.test_code.text(),
            "name": self.test_name.text(),
            "category_name": self.category_name.currentText(),
            "specimen_type": self._loaded_specimen_type,
            "method": self._loaded_method,
            "result_kind": result_kind,
            "select_options": select_options,
            "default_result_value": default_result_value,
            "result_multiplier": result_multiplier,
            "formula": self.formula.text().strip() if result_kind == "numeric" else None,
        }

        try:
            self._commit_range_form_if_needed()
        except ValueError as exc:
            QMessageBox.warning(self, tr("Invalid Range"), str(exc))
            return

        try:
            if self.test_id is None:
                self._create_test(payload, self.pending_ranges)
            else:
                self._update_test(self.test_id, payload, self.pending_ranges)
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return

        self.accept()

    def _update_select_fields_visibility(self) -> None:
        is_select = self.result_kind.currentData() == "select"
        self.select_options_label.setVisible(is_select)
        self.select_options.setVisible(is_select)
        is_numeric = self.result_kind.currentData() == "numeric"
        self.result_multiplier_label.setVisible(is_numeric)
        self.result_multiplier.setVisible(is_numeric)
        self.formula_label.setVisible(is_numeric)
        self.formula.setVisible(is_numeric)

    def _load_equipment_choices(self) -> None:
        current_value = self.category_name.currentText().strip()
        self.category_name.clear()
        self.category_name.addItem("")
        for name in self._instrument_profile_choices():
            if name and self.category_name.findText(name) < 0:
                self.category_name.addItem(name)
        if current_value:
            self._set_equipment_value(current_value)
        elif self.category_name.count() == 2:
            self.category_name.setCurrentIndex(1)

    @staticmethod
    def _instrument_profile_choices() -> list[str]:
        root = Path(__file__).resolve().parents[2]
        profile_dirs = [
            root / "instrument-connectivity" / ".runtime" / "profiles",
            root / "instrument-connectivity" / "profiles",
            root / "instrument-connectivity" / "data" / "instrument-engine" / "profiles",
        ]
        choices: list[str] = []
        seen: set[str] = set()
        for profile_dir in profile_dirs:
            if not profile_dir.exists():
                continue
            for profile_path in sorted(profile_dir.glob("*.y*ml")):
                profile_name = TestDialog._profile_display_name(profile_path)
                if profile_name and profile_name.lower() not in seen:
                    choices.append(profile_name)
                    seen.add(profile_name.lower())
        return choices

    @staticmethod
    def _profile_display_name(profile_path: Path) -> str:
        profile_id = ""
        profile_name = ""
        try:
            lines = profile_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ""
        for line in lines:
            if not line or line[0].isspace() or ":" not in line:
                continue
            key, value = line.split(":", 1)
            normalized_key = key.strip()
            normalized_value = value.strip().strip('"').strip("'")
            if normalized_key == "id":
                profile_id = normalized_value
            elif normalized_key == "name":
                profile_name = normalized_value
        if profile_id.startswith("generic-"):
            return ""
        return profile_name or profile_id

    def _set_equipment_value(self, value: str) -> None:
        normalized = value.strip()
        index = self.category_name.findText(normalized)
        self.category_name.setCurrentIndex(index if index >= 0 else 0)

    def _refresh_ranges_table(self) -> None:
        rows = [
            (
                record["sex"] or tr("Any"),
                "" if record["age_min_days"] is None else str(record["age_min_days"]),
                "" if record["age_max_days"] is None else str(record["age_max_days"]),
                record["lower_value"] or "",
                record["upper_value"] or "",
                record["unit"],
                record["reference_text"] or "",
            )
            for record in self.pending_ranges
        ]
        DataAwarePage.set_table_rows(self.ranges_table, rows)
        if self.pending_ranges and self.ranges_table.currentRow() < 0:
            self.ranges_table.selectRow(0)

    def _clear_range_form(self) -> None:
        self.ranges_table.clearSelection()
        self.range_sex.setCurrentIndex(0)
        self.range_age_min.clear()
        self.range_age_max.clear()
        self.range_lower.clear()
        self.range_upper.clear()
        self.range_unit.clear()
        self.range_reference_text.clear()

    def _commit_range_form_if_needed(self) -> None:
        reference = self._range_from_form()
        if not self._range_has_values(reference):
            return
        row = self.ranges_table.currentRow()
        if 0 <= row < len(self.pending_ranges):
            self.pending_ranges[row] = reference
            return
        self.pending_ranges.append(reference)

    def _range_from_form(self) -> dict[str, Any]:
        return {
            "sex": self.range_sex.currentData(),
            "age_min_days": self._optional_int(self.range_age_min.text()),
            "age_max_days": self._optional_int(self.range_age_max.text()),
            "lower_value": self._optional_float(self.range_lower.text()),
            "upper_value": self._optional_float(self.range_upper.text()),
            "unit": self.range_unit.text().strip(),
            "reference_text": self.range_reference_text.toPlainText().strip(),
        }

    @staticmethod
    def _range_has_values(reference: dict[str, Any]) -> bool:
        return any(
            reference.get(key) not in (None, "")
            for key in ("age_min_days", "age_max_days", "lower_value", "upper_value", "unit", "reference_text")
        )

    def _load_selected_range_into_form(self) -> None:
        row = self.ranges_table.currentRow()
        if row < 0 or row >= len(self.pending_ranges):
            return
        record = self.pending_ranges[row]
        sex_index = self.range_sex.findData(record.get("sex") or "")
        self.range_sex.setCurrentIndex(sex_index if sex_index >= 0 else 0)
        self.range_age_min.setText("" if record.get("age_min_days") is None else str(record.get("age_min_days")))
        self.range_age_max.setText("" if record.get("age_max_days") is None else str(record.get("age_max_days")))
        self.range_lower.setText(str(record.get("lower_value") or ""))
        self.range_upper.setText(str(record.get("upper_value") or ""))
        self.range_unit.setText(str(record.get("unit") or ""))
        self.range_reference_text.setPlainText(str(record.get("reference_text") or ""))

    @staticmethod
    def _optional_int(value: str) -> int | None:
        normalized = value.strip()
        if not normalized:
            return None
        return int(normalized)

    @staticmethod
    def _optional_float(value: str) -> str | None:
        normalized = value.strip().replace(",", "")
        if not normalized:
            return None
        try:
            Decimal(normalized)
        except InvalidOperation as exc:
            raise ValueError(str(exc)) from exc
        return normalized


class ImportPreviewDialog(QDialog):
    def __init__(self, title: str, summary_lines: list[str], detail_lines: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.resize(640, 460)
        self.setWindowTitle(title)

        root = QVBoxLayout(self)
        summary = QLabel("\n".join(summary_lines))
        summary.setWordWrap(True)
        root.addWidget(summary)

        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlainText("\n".join(detail_lines) if detail_lines else tr("No row issues were found."))
        root.addWidget(self.details)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setText(tr("Import"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)


class PanelDialog(QDialog):
    def __init__(self, database: Database, panel_service: PanelService | None = None, panel_id: int | str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.panel_service = panel_service
        self.panel_id = panel_id
        self._editing = panel_id is not None
        self.pending_items: list[dict[str, Any]] = []
        self._all_test_choices: list[tuple[str, str]] | list[tuple[int, str]] = []

        self.setModal(True)
        self.resize(760, 560)
        self.setWindowTitle(tr("Edit Panel") if panel_id is not None else tr("Add Panel"))

        root = QVBoxLayout(self)
        form_row = QHBoxLayout()
        form_row.setSpacing(12)
        self.panel_code = QLineEdit()
        self.panel_name = QLineEdit()
        self.panel_specimen_type = QLineEdit()
        self.panel_method = QLineEdit()
        panel_code_label = QLabel(tr("Panel Code"))
        panel_name_label = QLabel(tr("Panel Name"))
        form_row.addWidget(panel_code_label)
        form_row.addWidget(self.panel_code, 1)
        form_row.addWidget(panel_name_label)
        form_row.addWidget(self.panel_name, 3)
        root.addLayout(form_row)
        meta_row = QHBoxLayout()
        meta_row.setSpacing(12)
        meta_row.addWidget(QLabel(tr("Specimen Type")))
        meta_row.addWidget(self.panel_specimen_type, 1)
        meta_row.addWidget(QLabel(tr("Methodology")))
        meta_row.addWidget(self.panel_method, 1)
        root.addLayout(meta_row)

        # Report layout for this panel. 'resultado' is the standard
        # ESTUDIO/RESULTADO/UNIDAD/REFERENCIA grid; the other two render the
        # banded microbiology layouts (see report_layout.py).
        kind_row = QHBoxLayout()
        kind_row.setSpacing(12)
        self.panel_kind_combo = QComboBox()
        self.panel_kind_combo.addItem(tr("Resultado"), PANEL_KIND_RESULTADO)
        self.panel_kind_combo.addItem(tr("Cultivo"), PANEL_KIND_CULTIVO)
        self.panel_kind_combo.addItem(tr("Frotis"), PANEL_KIND_FROTIS)
        self.panel_kind_combo.currentIndexChanged.connect(self._update_kind_help)
        self.panel_kind_help = QLabel()
        self.panel_kind_help.setWordWrap(True)
        self.panel_kind_help.setStyleSheet("color: #6b7480;")
        self.configure_layout_button = QPushButton(tr("Configure Layout..."))
        self.configure_layout_button.clicked.connect(self.open_layout_dialog)
        kind_row.addWidget(QLabel(tr("Report Type")))
        kind_row.addWidget(self.panel_kind_combo)
        kind_row.addWidget(self.configure_layout_button)
        kind_row.addWidget(self.panel_kind_help, 1)
        root.addLayout(kind_row)
        # Layout config is edited in the dialog and held here until save, so a
        # cancelled panel edit does not leave a half-written config behind.
        self._pending_layout_config: dict[str, Any] | None = None
        self._update_kind_help()

        content = QHBoxLayout()

        available_group = QGroupBox(tr("Available Tests"))
        available_group.setMinimumWidth(300)
        available_layout = QVBoxLayout(available_group)
        available_helper = QLabel(tr("Double click on a test to add it to the panel."))
        available_helper.setWordWrap(True)
        available_layout.addWidget(available_helper)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(tr("Search")))
        self.test_search = QLineEdit()
        self.test_search.setPlaceholderText(tr("Filter available tests"))
        self.test_search.textChanged.connect(self._filter_test_choices)
        search_row.addWidget(self.test_search, 1)
        available_layout.addLayout(search_row)
        self.available_tests = QListWidget()
        self.available_tests.setMinimumWidth(280)
        self.available_tests.setSelectionMode(QAbstractItemView.SingleSelection)
        self.available_tests.itemDoubleClicked.connect(lambda _item: self.add_selected_test())
        available_layout.addWidget(self.available_tests)
        content.addWidget(available_group, 4)

        items_group = QGroupBox(tr("Panel Items"))
        items_layout = QVBoxLayout(items_group)
        items_helper = QLabel(tr("Add tests, subheadings, and panel comments, then arrange them in the order they should appear."))
        items_helper.setWordWrap(True)
        items_layout.addWidget(items_helper)

        buttons = QHBoxLayout()
        add_test_button = QPushButton(tr("Add Selected Test"))
        add_test_button.clicked.connect(self.add_selected_test)
        add_heading_button = QPushButton(tr("Add Subheading"))
        add_heading_button.clicked.connect(self.add_subheading)
        add_comment_button = QPushButton(tr("Add Comment Section"))
        add_comment_button.clicked.connect(self.add_comment_section)
        buttons.addWidget(add_test_button)
        buttons.addWidget(add_heading_button)
        buttons.addWidget(add_comment_button)
        buttons.addStretch(1)
        items_layout.addLayout(buttons)

        self.panel_items = QListWidget()
        self.panel_items.setSelectionMode(QAbstractItemView.SingleSelection)
        items_layout.addWidget(self.panel_items)

        item_actions = QHBoxLayout()
        move_up_button = QPushButton(tr("Move Up"))
        move_up_button.clicked.connect(lambda: self._move_item(-1))
        move_down_button = QPushButton(tr("Move Down"))
        move_down_button.clicked.connect(lambda: self._move_item(1))
        remove_button = QPushButton(tr("Remove Selected Item"))
        remove_button.clicked.connect(self.remove_selected_item)
        item_actions.addWidget(move_up_button)
        item_actions.addWidget(move_down_button)
        item_actions.addStretch(1)
        item_actions.addWidget(remove_button)
        items_layout.addLayout(item_actions)
        content.addWidget(items_group, 5)

        root.addLayout(content)

        buttons = QHBoxLayout()
        cancel_button = QPushButton(tr("Cancel"))
        cancel_button.clicked.connect(self.reject)
        self.archive_panel_button = QPushButton()
        self.archive_panel_button.clicked.connect(self.toggle_panel_archive)
        save_button = QPushButton(tr("Update Panel") if self._editing else tr("Save Panel"))
        save_button.clicked.connect(self.save_panel)
        buttons.addStretch(1)
        if self._editing:
            buttons.addWidget(self.archive_panel_button)
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        root.addLayout(buttons)

        detail = self._get_panel_detail(self.panel_id, include_inactive=True) if self.panel_id is not None else None
        if self.panel_id is not None:
            if detail is None:
                QMessageBox.warning(self, tr("Missing Selection"), tr("The selected panel could not be loaded."))
                self.reject()
                return
            self.panel_code.setText(detail["code"])
            self.panel_name.setText(detail["name"])
            self.panel_specimen_type.setText(detail.get("specimen_type") or "")
            self.panel_method.setText(detail.get("method") or "")
            self.pending_items = [dict(item) for item in detail.get("items", [])]
            self.archive_panel_button.setText(tr("Unarchive Panel") if not detail.get("is_active") else tr("Archive Panel"))
            get_kind = getattr(self.database, "get_panel_kind", None)
            if callable(get_kind):
                try:
                    kind_index = self.panel_kind_combo.findData(get_kind(int(self.panel_id)))
                except (TypeError, ValueError):
                    kind_index = -1
                if kind_index >= 0:
                    self.panel_kind_combo.setCurrentIndex(kind_index)
            self._update_kind_help()

        self._load_test_choices()
        self._refresh_panel_items()

    def _update_kind_help(self) -> None:
        helps = {
            PANEL_KIND_RESULTADO: tr("Standard table: study, result, unit, and reference range."),
            PANEL_KIND_CULTIVO: tr("Culture layout: pathogens searched, isolated agent, and antibiogram."),
            PANEL_KIND_FROTIS: tr("Smear layout: a title band followed by narrative sections."),
        }
        kind = self.selected_panel_kind()
        self.panel_kind_help.setText(helps.get(kind, ""))
        # Only the banded layouts have anything to configure.
        self.configure_layout_button.setEnabled(kind != PANEL_KIND_RESULTADO)

    def _panel_test_names(self) -> list[str]:
        """Bare test names of the panel's items, in panel order."""
        names: list[str] = []
        for item in self.pending_items:
            if str(item.get("item_type") or "test") != "test":
                continue
            label = self._display_test_label(str(item.get("label") or ""))
            if label and label not in names:
                names.append(label)
        return names

    def _current_layout_config(self) -> dict[str, Any]:
        if self._pending_layout_config is not None:
            return self._pending_layout_config
        get_config = getattr(self.database, "get_panel_layout_config", None)
        if self.panel_id is not None and callable(get_config):
            try:
                return get_config(int(self.panel_id)) or {}
            except (TypeError, ValueError):
                return {}
        return {}

    def open_layout_dialog(self) -> None:
        kind = self.selected_panel_kind()
        if kind == PANEL_KIND_RESULTADO:
            return
        names = self._panel_test_names()
        if not names:
            QMessageBox.warning(
                self,
                tr("Missing Data"),
                tr("Add the panel's tests first, then configure the layout."),
            )
            return
        dialog = PanelLayoutDialog(
            kind,
            self._current_layout_config(),
            names,
            panel_name=self.panel_name.text().strip(),
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            self._pending_layout_config = dialog.result_config()

    def selected_panel_kind(self) -> str:
        return str(self.panel_kind_combo.currentData() or PANEL_KIND_RESULTADO)

    def _apply_panel_kind(self, panel_id: int | str | None) -> None:
        """Persist the chosen report layout after the panel row exists.

        create_panel/update_panel do not carry the kind, so it is written in a
        second step. Only local (non-server) panels have a layout to set.
        """
        if panel_id is None:
            return
        setter = getattr(self.database, "set_panel_kind", None)
        if not callable(setter):
            return
        kind = self.selected_panel_kind()
        if self._pending_layout_config is not None:
            existing = dict(self._pending_layout_config)
        else:
            existing = {}
            get_config = getattr(self.database, "get_panel_layout_config", None)
            if callable(get_config):
                try:
                    existing = get_config(int(panel_id)) or {}
                except (TypeError, ValueError):
                    existing = {}
        # Seed the title from the panel name so a new cultivo/frotis panel
        # renders its band immediately, before any further configuration.
        if kind != PANEL_KIND_RESULTADO and not existing.get("title"):
            existing = {**existing, "title": self.panel_name.text().strip()}
        try:
            setter(int(panel_id), kind, existing if kind != PANEL_KIND_RESULTADO else None)
        except (TypeError, ValueError):
            pass

    def _resolve_saved_panel_id(self) -> int | str | None:
        """create_panel returns nothing, so look the new panel up by its code."""
        lookup = getattr(self.database, "get_panel_id_by_code", None)
        if not callable(lookup):
            return None
        return lookup(self.panel_code.text().strip())

    def _list_test_choices(self) -> list[tuple[str, str]] | list[tuple[int, str]]:
        if self.panel_service is not None:
            return self.panel_service.list_test_choices()
        return self.database.list_test_choices()

    def _get_panel_detail(self, panel_id: int | str | None, *, include_inactive: bool = False) -> dict[str, Any] | None:
        if panel_id is None:
            return None
        if self.panel_service is not None:
            return self.panel_service.get_panel_detail(panel_id, include_inactive=include_inactive)
        return self.database.get_panel_detail(int(panel_id), include_inactive=include_inactive)

    def _create_panel(self, code: str, name: str, panel_items: list[dict[str, Any]], specimen_type: str, method: str) -> None:
        if self.panel_service is not None:
            self.panel_service.create_panel(code, name, panel_items, specimen_type=specimen_type, method=method)
            return
        self.database.create_panel(code, name, panel_items, specimen_type=specimen_type, method=method)

    def _update_panel(self, panel_id: int | str | None, code: str, name: str, panel_items: list[dict[str, Any]], specimen_type: str, method: str) -> None:
        if panel_id is None:
            return
        if self.panel_service is not None:
            self.panel_service.update_panel(panel_id, code, name, panel_items, specimen_type=specimen_type, method=method)
            return
        self.database.update_panel(int(panel_id), code, name, panel_items, specimen_type=specimen_type, method=method)

    def _archive_panel(self, panel_id: int | str | None) -> None:
        if panel_id is None:
            return
        if self.panel_service is not None:
            self.panel_service.archive_panel(panel_id)
            return
        self.database.archive_panel(int(panel_id))

    def _unarchive_panel(self, panel_id: int | str | None) -> None:
        if panel_id is None:
            return
        if self.panel_service is not None:
            self.panel_service.unarchive_panel(panel_id)
            return
        self.database.unarchive_panel(int(panel_id))

    def _load_test_choices(self) -> None:
        self._all_test_choices = list(self._list_test_choices())
        self._filter_test_choices()

    def _filter_test_choices(self) -> None:
        self.available_tests.clear()
        query = self.test_search.text().strip().lower() if hasattr(self, "test_search") else ""
        for test_id, label in self._all_test_choices:
            if query and query not in str(label).lower():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, test_id)
            self.available_tests.addItem(item)

    def _refresh_panel_items(self) -> None:
        self.panel_items.clear()
        for item in self.pending_items:
            if item.get("item_type") == "heading":
                label = f'{tr("Heading")}: {item.get("heading_text") or item.get("label") or ""}'
            elif item.get("item_type") == "comment":
                label = f'{tr("Comment")}: {item.get("heading_text") or item.get("label") or ""}'
            else:
                label = self._display_test_label(str(item.get("label") or ""))
            list_item = QListWidgetItem(label)
            list_item.setData(Qt.UserRole, dict(item))
            self.panel_items.addItem(list_item)

    def add_selected_test(self) -> None:
        item = self.available_tests.currentItem()
        if item is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a test to add."))
            return
        test_id = item.data(Qt.UserRole)
        if any(existing.get("item_type") == "test" and existing.get("test_id") == test_id for existing in self.pending_items):
            return
        self.pending_items.append({"item_type": "test", "test_id": test_id, "label": self._display_test_label(item.text())})
        self._refresh_panel_items()
        self.panel_items.setCurrentRow(self.panel_items.count() - 1)

    @staticmethod
    def _display_test_label(label: str) -> str:
        return re.sub(r"\s+\([A-Z0-9_-]{1,20}\)$", "", label.strip()).strip()

    def add_subheading(self) -> None:
        heading_text, accepted = QInputDialog.getText(self, tr("Add Subheading"), tr("Enter Subheading"))
        if not accepted:
            return
        heading_text = heading_text.strip()
        if not heading_text:
            QMessageBox.warning(self, tr("Missing Data"), tr("Subheading text is required."))
            return
        self.pending_items.append({"item_type": "heading", "heading_text": heading_text, "label": heading_text})
        self._refresh_panel_items()
        self.panel_items.setCurrentRow(self.panel_items.count() - 1)

    def add_comment_section(self) -> None:
        comment_text, accepted = QInputDialog.getText(self, tr("Add Comment Section"), tr("Enter Comment Section Label"), text=tr("Comments"))
        if not accepted:
            return
        comment_text = comment_text.strip()
        if not comment_text:
            QMessageBox.warning(self, tr("Missing Data"), tr("Comment section label is required."))
            return
        self.pending_items.append({"item_type": "comment", "heading_text": comment_text, "label": comment_text})
        self._refresh_panel_items()
        self.panel_items.setCurrentRow(self.panel_items.count() - 1)

    def remove_selected_item(self) -> None:
        row = self.panel_items.currentRow()
        if row < 0 or row >= len(self.pending_items):
            return
        self.pending_items.pop(row)
        self._refresh_panel_items()
        if self.panel_items.count() > 0:
            self.panel_items.setCurrentRow(min(row, self.panel_items.count() - 1))

    def _move_item(self, offset: int) -> None:
        row = self.panel_items.currentRow()
        new_row = row + offset
        if row < 0 or new_row < 0 or new_row >= len(self.pending_items):
            return
        self.pending_items[row], self.pending_items[new_row] = self.pending_items[new_row], self.pending_items[row]
        self._refresh_panel_items()
        self.panel_items.setCurrentRow(new_row)

    def toggle_panel_archive(self) -> None:
        if not self._editing or self.panel_id is None:
            return
        detail = self._get_panel_detail(self.panel_id, include_inactive=True)
        if detail is None:
            return
        if detail.get("is_active"):
            if QMessageBox.question(self, tr("Archive Panel"), tr("Archive this panel?")) != QMessageBox.Yes:
                return
            self._archive_panel(self.panel_id)
        else:
            self._unarchive_panel(self.panel_id)
        self.accept()

    def save_panel(self) -> None:
        if not self.panel_code.text().strip() or not self.panel_name.text().strip():
            QMessageBox.warning(self, tr("Missing Data"), tr("Panel code and panel name are required."))
            return
        if not self.pending_items:
            QMessageBox.warning(self, tr("Missing Data"), tr("Select at least one item for the panel."))
            return

        try:
            if self.panel_id is None:
                self._create_panel(self.panel_code.text(), self.panel_name.text(), self.pending_items, self.panel_specimen_type.text(), self.panel_method.text())
                saved_id = self._resolve_saved_panel_id()
            else:
                self._update_panel(self.panel_id, self.panel_code.text(), self.panel_name.text(), self.pending_items, self.panel_specimen_type.text(), self.panel_method.text())
                saved_id = self.panel_id
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return

        self._apply_panel_kind(saved_id)
        self.accept()


class CatalogPage(DataAwarePage):
    def __init__(self, database: Database, *, mode: str = "catalog", deployment_service: DeploymentService | None = None) -> None:
        super().__init__()
        self.database = database
        self.mode = mode
        self.deployment_service = deployment_service
        self.panel_service = PanelService(database, deployment_service) if deployment_service is not None else None
        self.test_service = TestService(database, deployment_service) if deployment_service is not None else None
        self.test_records: list[TestRecord] = []
        self.filtered_test_records: list[TestRecord] = []
        self.panel_records: list[PanelRecord] = []
        self.filtered_panel_records: list[PanelRecord] = []
        self.status_filter = "active"
        self.catalog_error_message = ""

        root = QHBoxLayout(self)
        if self.mode in {"catalog", "tests"}:
            root.addWidget(self._build_tests_group(), 1)
        if self.mode in {"catalog", "panels"}:
            root.addWidget(self._build_panels_group(), 1)

        self.retranslate_ui()
        self.refresh_catalog()

    def _test_service_for_dialog(self) -> TestService | None:
        if self.test_service is not None and self.test_service.uses_server_backend() and self.mode in {"catalog", "tests"}:
            return self.test_service
        return None

    def _list_tests(self, *, status_filter: str) -> list[TestRecord]:
        if self._test_service_for_dialog() is not None:
            return self.test_service.list_tests(status_filter=status_filter)
        return self.database.list_tests(status_filter=status_filter)

    def _get_test_detail_for_catalog(self, test_id: int | str | None) -> dict[str, Any] | None:
        if test_id is None:
            return None
        if self._test_service_for_dialog() is not None:
            return self.test_service.get_test_detail(test_id)
        return self.database.get_test_detail(int(test_id))

    def _panel_service_for_dialog(self) -> PanelService | None:
        if self.panel_service is not None and self.panel_service.uses_server_backend() and self.mode in {"catalog", "panels"}:
            return self.panel_service
        return None

    def _list_panels(self, *, status_filter: str) -> list[PanelRecord]:
        if self._panel_service_for_dialog() is not None:
            return self.panel_service.list_panels(status_filter=status_filter)
        return self.database.list_panels(status_filter=status_filter)

    def _get_panel_detail(self, panel_id: int | str | None, *, include_inactive: bool = False) -> dict[str, Any] | None:
        if panel_id is None:
            return None
        if self._panel_service_for_dialog() is not None:
            return self.panel_service.get_panel_detail(panel_id, include_inactive=include_inactive)
        return self.database.get_panel_detail(int(panel_id), include_inactive=include_inactive)

    def _build_tests_group(self) -> QWidget:
        self.tests_group = QGroupBox()
        self.tests_group.setObjectName("catalogTestsGroup")
        layout = QVBoxLayout(self.tests_group)

        self.tests_helper = QLabel()
        self.tests_helper.setWordWrap(True)
        layout.addWidget(self.tests_helper)

        buttons = QHBoxLayout()
        self.filter_combo = QComboBox()
        self.filter_combo.currentIndexChanged.connect(self._change_status_filter)
        self.add_test_button = QPushButton()
        self.add_test_button.clicked.connect(self.open_add_test_dialog)
        self.edit_test_button = QPushButton()
        self.edit_test_button.clicked.connect(self.open_edit_test_dialog)
        self.import_tests_button = QPushButton()
        self.import_tests_button.clicked.connect(self.import_tests_from_excel)
        self.download_test_template_button = QPushButton()
        self.download_test_template_button.clicked.connect(self.download_test_template)
        self.export_tests_button = QPushButton()
        self.export_tests_button.clicked.connect(self.export_tests_to_excel)
        buttons.addWidget(self.filter_combo)
        buttons.addWidget(self.add_test_button)
        buttons.addWidget(self.edit_test_button)
        buttons.addWidget(self.import_tests_button)
        buttons.addWidget(self.download_test_template_button)
        buttons.addWidget(self.export_tests_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.tests_search = QLineEdit()
        self.tests_search.textChanged.connect(self._refresh_tests_table)
        layout.addWidget(self.tests_search)

        self.tests_table = QTableWidget(0, 5)
        self.tests_table.setObjectName("catalogTestsTable")
        self.tests_table.horizontalHeader().setStretchLastSection(False)
        self.tests_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.tests_table.setSelectionMode(QTableWidget.SingleSelection)
        self.tests_table.itemSelectionChanged.connect(self._update_test_action_buttons)
        self.tests_table.cellDoubleClicked.connect(lambda _row, _col: self.open_edit_test_dialog())
        self.tests_table.setColumnWidth(0, 140)
        self.tests_table.setColumnWidth(1, 340)
        self.tests_table.setColumnWidth(2, 150)
        self.tests_table.setColumnWidth(3, 110)
        self.tests_table.setColumnWidth(4, 90)
        layout.addWidget(self.tests_table)
        return self.tests_group

    def _build_panels_group(self) -> QWidget:
        self.panels_group = QGroupBox()
        self.panels_group.setObjectName("catalogPanelsGroup")
        layout = QVBoxLayout(self.panels_group)

        self.panels_helper = QLabel()
        self.panels_helper.setWordWrap(True)
        layout.addWidget(self.panels_helper)

        buttons = QHBoxLayout()
        self.panels_filter_combo = QComboBox()
        self.panels_filter_combo.currentIndexChanged.connect(self._change_status_filter)
        self.add_panel_button = QPushButton()
        self.add_panel_button.clicked.connect(self.open_add_panel_dialog)
        self.edit_panel_button = QPushButton()
        self.edit_panel_button.clicked.connect(self.open_edit_panel_dialog)
        self.import_panels_button = QPushButton()
        self.import_panels_button.clicked.connect(self.import_panels_from_excel)
        self.download_panel_template_button = QPushButton()
        self.download_panel_template_button.clicked.connect(self.download_panel_template)
        self.export_panels_button = QPushButton()
        self.export_panels_button.clicked.connect(self.export_panels_to_excel)
        buttons.addWidget(self.panels_filter_combo)
        buttons.addWidget(self.add_panel_button)
        buttons.addWidget(self.edit_panel_button)
        buttons.addWidget(self.import_panels_button)
        buttons.addWidget(self.download_panel_template_button)
        buttons.addWidget(self.export_panels_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.panels_search = QLineEdit()
        self.panels_search.textChanged.connect(self._refresh_panels_table)
        layout.addWidget(self.panels_search)

        self.panels_table = QTableWidget(0, 3)
        self.panels_table.setObjectName("catalogPanelsTable")
        self.panels_table.horizontalHeader().setStretchLastSection(False)
        self.panels_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.panels_table.setSelectionMode(QTableWidget.SingleSelection)
        self.panels_table.itemSelectionChanged.connect(self._update_panel_action_buttons)
        self.panels_table.cellDoubleClicked.connect(lambda _row, _col: self.open_edit_panel_dialog())
        self.panels_table.setColumnWidth(0, 160)
        self.panels_table.setColumnWidth(1, 260)
        self.panels_table.setColumnWidth(2, 520)
        layout.addWidget(self.panels_table)
        return self.panels_group

    def retranslate_ui(self) -> None:
        if hasattr(self, "tests_group"):
            title = tr("All Tests") if self.mode != "tests" else tr("Tests")
            self.tests_group.setTitle(title)
            self.filter_combo.clear()
            self.filter_combo.addItem(tr("Active Only"), "active")
            self.filter_combo.addItem(tr("Archived Only"), "archived")
            self.filter_combo.addItem(tr("All"), "all")
            current_index = self.filter_combo.findData(self.status_filter)
            if current_index >= 0:
                self.filter_combo.setCurrentIndex(current_index)
            self.add_test_button.setText(tr("Add Test"))
            self.edit_test_button.setText(tr("Edit Selected Test"))
            self.import_tests_button.setText(tr("Import Tests"))
            self.download_test_template_button.setText(tr("Test Template"))
            self.export_tests_button.setText(tr("Export Tests"))
            self.tests_search.setPlaceholderText(tr("Search tests"))
            self.tests_table.setHorizontalHeaderLabels([tr("Code"), tr("Name"), tr("Specimen"), tr("Kind"), tr("Ranges")])
        if hasattr(self, "panels_group"):
            title = tr("All Panels") if self.mode != "panels" else tr("Panels")
            self.panels_group.setTitle(title)
            self.panels_filter_combo.clear()
            self.panels_filter_combo.addItem(tr("Active Only"), "active")
            self.panels_filter_combo.addItem(tr("Archived Only"), "archived")
            self.panels_filter_combo.addItem(tr("All"), "all")
            current_index = self.panels_filter_combo.findData(self.status_filter)
            if current_index >= 0:
                self.panels_filter_combo.setCurrentIndex(current_index)
            self.add_panel_button.setText(tr("Add Panel"))
            self.edit_panel_button.setText(tr("Edit Selected Panel"))
            self.import_panels_button.setText(tr("Import Panels"))
            self.download_panel_template_button.setText(tr("Panel Template"))
            self.export_panels_button.setText(tr("Export Panels"))
            self.panels_search.setPlaceholderText(tr("Search panels"))
            self.panels_table.setHorizontalHeaderLabels([tr("Code"), tr("Name"), tr("Included Tests")])
        self._update_catalog_helper_text()
        self.refresh_catalog()

    def refresh_on_show(self) -> None:
        self.refresh_catalog()

    def refresh_catalog(self) -> None:
        try:
            self.test_records = self._list_tests(status_filter=self.status_filter)
            self.panel_records = self._list_panels(status_filter=self.status_filter)
            self.catalog_error_message = ""
        except RuntimeError:
            self.test_records = []
            self.panel_records = []
            self.catalog_error_message = tr("The server could not be reached. Check the server connection or switch to local mode.")
        if hasattr(self, "tests_table"):
            self._refresh_tests_table()
        if hasattr(self, "panels_table"):
            self._refresh_panels_table()
        self._update_catalog_helper_text()

    def _update_catalog_helper_text(self) -> None:
        suffix = f"\n\n{self.catalog_error_message}" if self.catalog_error_message else ""
        if hasattr(self, "tests_helper"):
            self.tests_helper.setText(
                tr("Manage the full test catalog. Use the buttons below to add or edit a test.") + suffix
            )
        if hasattr(self, "panels_helper"):
            self.panels_helper.setText(
                tr("Manage the full panel catalog. Use the buttons below to add or edit a panel.") + suffix
            )

    def open_add_test_dialog(self) -> None:
        dialog = TestDialog(self.database, test_service=self._test_service_for_dialog(), parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_catalog()
            self.notify_data_changed()

    def open_edit_test_dialog(self) -> None:
        test_id = self._selected_test_id()
        if test_id is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a test to edit."))
            return
        dialog = TestDialog(self.database, test_service=self._test_service_for_dialog(), test_id=test_id, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_catalog()
            self.notify_data_changed()

    def open_add_panel_dialog(self) -> None:
        dialog = PanelDialog(self.database, panel_service=self._panel_service_for_dialog(), parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_catalog()
            self.notify_data_changed()

    def open_edit_panel_dialog(self) -> None:
        panel_id = self._selected_panel_id()
        if panel_id is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a panel to edit."))
            return
        dialog = PanelDialog(self.database, panel_service=self._panel_service_for_dialog(), panel_id=panel_id, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_catalog()
            self.notify_data_changed()

    def _change_status_filter(self) -> None:
        sender = self.sender()
        if sender is getattr(self, "panels_filter_combo", None):
            self.status_filter = str(self.panels_filter_combo.currentData() or "active")
        else:
            self.status_filter = str(self.filter_combo.currentData() or "active")
        self.refresh_catalog()


    def download_test_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("Save Test Template"), "test_import_template.xlsx", tr("Excel Workbook (*.xlsx)"))
        if not path:
            return
        try:
            target = write_test_import_template(path)
        except OSError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        QMessageBox.information(self, tr("Saved"), tr("Test template saved: {path}", path=str(target)))

    def download_panel_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("Save Panel Template"), "panel_import_template.xlsx", tr("Excel Workbook (*.xlsx)"))
        if not path:
            return
        try:
            target = write_panel_import_template(path)
        except OSError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        QMessageBox.information(self, tr("Saved"), tr("Panel template saved: {path}", path=str(target)))


    def export_tests_to_excel(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("Save Test Export"), "tests_export.xlsx", tr("Excel Workbook (*.xlsx)"))
        if not path:
            return
        test_details = []
        for record in self.filtered_test_records:
            if record.code.startswith("__PANEL_"):
                continue
            detail = self._get_test_detail_for_catalog(record.id)
            if detail is not None:
                test_details.append(detail)
        if not test_details:
            QMessageBox.information(self, tr("Nothing To Export"), tr("No tests matched the current filter."))
            return
        try:
            target = write_test_export_workbook(path, build_test_export_sheets(test_details))
        except OSError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        QMessageBox.information(self, tr("Saved"), tr("Test export saved: {path}", path=str(target)))

    def export_panels_to_excel(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("Save Panel Export"), "panels_export.xlsx", tr("Excel Workbook (*.xlsx)"))
        if not path:
            return
        panel_details = []
        for record in self.panel_records:
            detail = self._get_panel_detail(record.id, include_inactive=True)
            if detail is not None:
                panel_details.append(detail)
        if not panel_details:
            QMessageBox.information(self, tr("Nothing To Export"), tr("No panels matched the current filter."))
            return
        try:
            target = write_panel_export_workbook(path, build_panel_export_sheets(panel_details))
        except OSError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        QMessageBox.information(self, tr("Saved"), tr("Panel export saved: {path}", path=str(target)))


    def export_selected_test_to_excel(self) -> None:
        record = self._selected_test_record()
        if record is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a test to export."))
            return
        detail = self._get_test_detail_for_catalog(record.id)
        if detail is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("The selected test could not be loaded."))
            return
        suggested_name = f"{detail['code']}_test.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, tr("Save Selected Test Export"), suggested_name, tr("Excel Workbook (*.xlsx)"))
        if not path:
            return
        try:
            target = write_test_export_workbook(path, build_test_export_sheets([detail]))
        except OSError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        QMessageBox.information(self, tr("Saved"), tr("Test export saved: {path}", path=str(target)))

    def export_selected_panel_to_excel(self) -> None:
        record = self._selected_panel_record()
        if record is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a panel to export."))
            return
        detail = self._get_panel_detail(record.id, include_inactive=True)
        if detail is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("The selected panel could not be loaded."))
            return
        suggested_name = f"{detail['code']}_panel.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, tr("Save Selected Panel Export"), suggested_name, tr("Excel Workbook (*.xlsx)"))
        if not path:
            return
        try:
            target = write_panel_export_workbook(path, build_panel_export_sheets([detail]))
        except OSError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        QMessageBox.information(self, tr("Saved"), tr("Panel export saved: {path}", path=str(target)))

    def import_tests_from_excel(self) -> None:
        if self._test_service_for_dialog() is not None:
            QMessageBox.information(self, tr("Not Available Yet"), tr("Test Excel import is not available yet in server mode."))
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("Import Tests"), "", tr("Excel Workbook (*.xlsx)"))
        if not path:
            return
        mode = self._choose_import_mode(tr("tests"))
        if mode is None:
            return
        try:
            rows = read_test_workbook_rows(path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, tr("Import Failed"), str(exc))
            return
        plan = self._build_test_import_plan(rows, mode)
        if not self._confirm_import_plan(tr("Preview Test Import"), plan):
            return
        self._apply_test_import_plan(plan)

    def import_panels_from_excel(self) -> None:
        if self._panel_service_for_dialog() is not None:
            QMessageBox.information(self, tr("Not Available Yet"), tr("Panel Excel import is not available yet in server mode."))
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("Import Panels"), "", tr("Excel Workbook (*.xlsx)"))
        if not path:
            return
        mode = self._choose_import_mode(tr("panels"))
        if mode is None:
            return
        try:
            rows = read_panel_workbook_rows(path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, tr("Import Failed"), str(exc))
            return
        plan = self._build_panel_import_plan(rows, mode)
        if not self._confirm_import_plan(tr("Preview Panel Import"), plan):
            return
        self._apply_panel_import_plan(plan)

    def _choose_import_mode(self, entity_label: str) -> str | None:
        label, accepted = QInputDialog.getItem(
            self,
            tr("Import Mode"),
            tr("Choose how to import {entity_label}.", entity_label=entity_label),
            [tr("Add and update by code"), tr("Add new only")],
            0,
            False,
        )
        if not accepted:
            return None
        return "upsert" if label == tr("Add and update by code") else "create"

    @staticmethod
    def _sheet_row_label(row: dict[str, str], default_row_number: int) -> str:
        sheet_name = row.get("__sheet_name__", "").strip()
        row_number = row.get("__row_number__", "").strip() or str(default_row_number)
        return f"{sheet_name} row {row_number}" if sheet_name else f"Row {row_number}"

    def _build_test_import_plan(self, rows: list[dict[str, str]], mode: str) -> dict[str, Any]:
        missing = [column for column in TEST_IMPORT_COLUMNS if rows and column not in rows[0]]
        existing_codes = {record.code: record.id for record in self.test_records}
        errors: list[str] = []
        prepared_by_code: dict[str, dict[str, Any]] = {}
        skipped_codes: set[str] = set()
        for row_number, row in enumerate(rows, start=2):
            code = row.get("code", "").strip()
            name = row.get("name", "").strip()
            result_kind = row.get("result_kind", "").strip().lower() or "text"
            if not code or not name:
                errors.append(f"{self._sheet_row_label(row, row_number)}: code and name are required.")
                continue
            if result_kind not in {"numeric", "text", "select", "observation"}:
                errors.append(f"{self._sheet_row_label(row, row_number)}: result_kind must be numeric, text, select, or observation.")
                continue
            select_options = self._split_options(row.get("select_options", ""))
            default_result = row.get("default_result", "").strip()
            if result_kind == "select":
                if not select_options:
                    errors.append(f"{self._sheet_row_label(row, row_number)}: selectable tests need select_options.")
                    continue
                if default_result and default_result not in select_options:
                    errors.append(f"{self._sheet_row_label(row, row_number)}: default_result must match one of the select_options.")
                    continue
            else:
                select_options = []
                default_result = ""
            try:
                age_min_days = self._optional_int(row.get("age_min_days", ""))
                age_max_days = self._optional_int(row.get("age_max_days", ""))
                lower_value = self._optional_float(row.get("lower_value", ""))
                upper_value = self._optional_float(row.get("upper_value", ""))
            except ValueError as exc:
                errors.append(f"{self._sheet_row_label(row, row_number)}: {exc}")
                continue
            equipment_name = row.get("equipment", row.get("category", "")).strip()
            payload = {
                "code": code,
                "name": name,
                "category_name": equipment_name,
                "specimen_type": row.get("specimen_type", "").strip(),
                "method": row.get("method", "").strip(),
                "result_kind": result_kind,
                "select_options": select_options,
                "default_result_value": default_result,
            }
            reference_ranges: list[dict[str, Any]] = []
            if any(row.get(key, "").strip() for key in ("range_sex", "age_min_days", "age_max_days", "lower_value", "upper_value", "unit", "reference_text")):
                reference_ranges.append({
                    "sex": row.get("range_sex", "").strip() or None,
                    "age_min_days": age_min_days,
                    "age_max_days": age_max_days,
                    "lower_value": lower_value,
                    "upper_value": upper_value,
                    "unit": row.get("unit", "").strip(),
                    "reference_text": row.get("reference_text", "").strip() or None,
                })
            existing_id = existing_codes.get(code)
            action = "create" if existing_id is None else "update"
            if mode == "create" and existing_id is not None:
                skipped_codes.add(code)
                continue
            existing_entry = prepared_by_code.get(code)
            if existing_entry is None:
                prepared_by_code[code] = {
                    "code": code,
                    "payload": payload,
                    "reference_ranges": reference_ranges,
                    "existing_id": existing_id,
                    "action": action,
                }
                continue
            if existing_entry["payload"] != payload:
                errors.append(f"{self._sheet_row_label(row, row_number)}: repeated code {code} must keep the same non-range fields.")
                continue
            existing_entry["reference_ranges"].extend(reference_ranges)
        prepared = list(prepared_by_code.values())
        return {
            "kind": "tests",
            "missing": missing,
            "errors": errors,
            "prepared": prepared,
            "skipped_count": len(skipped_codes),
            "row_count": len(rows),
        }

    def _apply_test_import_plan(self, plan: dict[str, Any]) -> None:
        created_count = 0
        updated_count = 0
        failed_entries: list[str] = []
        for entry in plan["prepared"]:
            try:
                if entry["existing_id"] is None:
                    self.database.create_test(entry["payload"], entry["reference_ranges"])
                    created_count += 1
                else:
                    self.database.update_test(entry["existing_id"], entry["payload"], entry["reference_ranges"])
                    updated_count += 1
            except sqlite3.IntegrityError as exc:
                failed_entries.append(f"{entry['code']} - {entry['payload']['name']}: {exc}")
        if not created_count and not updated_count and failed_entries:
            QMessageBox.critical(self, tr("Import Failed"), self._format_import_errors(failed_entries))
            return
        self.refresh_catalog()
        self.notify_data_changed()
        message = tr(
            "Imported tests. Created: {created_count}, Updated: {updated_count}, Skipped: {skipped_count}",
            created_count=created_count,
            updated_count=updated_count,
            skipped_count=plan["skipped_count"] + len(failed_entries),
        )
        if failed_entries:
            message += "\n\nFailed entries:\n" + self._format_import_errors(failed_entries)
            QMessageBox.warning(self, tr("Import Failed"), message)
            return
        QMessageBox.information(self, tr("Imported"), message)

    def _build_panel_import_plan(self, rows: list[dict[str, str]], mode: str) -> dict[str, Any]:
        missing = [column for column in PANEL_IMPORT_COLUMNS if rows and column not in rows[0]]
        test_code_map = {record.code: record.id for record in self.test_records}
        all_panel_records = self.database.list_panels(status_filter="all")
        panel_code_map = {record.code: record.id for record in all_panel_records}
        grouped: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        skipped_count = 0
        for row_number, row in enumerate(rows, start=2):
            panel_code = row.get("panel_code", "").strip()
            panel_name = row.get("panel_name", "").strip()
            item_type = row.get("item_type", "").strip().lower()
            if not panel_code or not panel_name or not item_type:
                errors.append(f"{self._sheet_row_label(row, row_number)}: panel_code, panel_name, and item_type are required.")
                continue
            if item_type not in {"test", "heading", "comment"}:
                errors.append(f"{self._sheet_row_label(row, row_number)}: item_type must be test, heading, or comment.")
                continue
            try:
                item_order = self._optional_int(row.get("item_order", ""))
            except ValueError as exc:
                errors.append(f"{self._sheet_row_label(row, row_number)}: {exc}")
                continue
            if item_order is None:
                errors.append(f"{self._sheet_row_label(row, row_number)}: item_order is required.")
                continue
            specimen_type = row.get("specimen_type", "").strip()
            methodology = row.get("metodologia", row.get("methodology", row.get("method", ""))).strip()
            panel_entry = grouped.setdefault(panel_code, {"name": panel_name, "specimen_type": specimen_type, "method": methodology, "rows": [], "row_numbers": []})
            if panel_entry["name"] != panel_name:
                errors.append(f"{self._sheet_row_label(row, row_number)}: panel_name does not match other rows for panel_code {panel_code}.")
                continue
            if specimen_type and panel_entry["specimen_type"] != specimen_type:
                errors.append(f"{self._sheet_row_label(row, row_number)}: specimen_type does not match other rows for panel_code {panel_code}.")
                continue
            if methodology and panel_entry["method"] != methodology:
                errors.append(f"{self._sheet_row_label(row, row_number)}: metodologia does not match other rows for panel_code {panel_code}.")
                continue
            if item_type == "test":
                test_code = row.get("test_code", "").strip()
                if not test_code:
                    errors.append(f"{self._sheet_row_label(row, row_number)}: test items require test_code.")
                    continue
                test_id = test_code_map.get(test_code)
                if test_id is None:
                    errors.append(f"{self._sheet_row_label(row, row_number)}: unknown test_code {test_code}.")
                    continue
                item = {"item_type": "test", "test_id": test_id, "label": row.get("label", "").strip() or f"{test_code}"}
            else:
                label = row.get("label", "").strip()
                if not label:
                    errors.append(f"{self._sheet_row_label(row, row_number)}: {item_type} items require label.")
                    continue
                item = {"item_type": item_type, "heading_text": label, "label": label}
            panel_entry["rows"].append((item_order, item))
            panel_entry["row_numbers"].append(row_number)
        prepared: list[dict[str, Any]] = []
        for panel_code, panel_entry in grouped.items():
            existing_id = panel_code_map.get(panel_code)
            action = "create" if existing_id is None else "update"
            if mode == "create" and existing_id is not None:
                skipped_count += 1
                continue
            prepared.append({
                "panel_code": panel_code,
                "panel_name": panel_entry["name"],
                "specimen_type": panel_entry["specimen_type"],
                "method": panel_entry["method"],
                "panel_items": [item for _sort_order, item in sorted(panel_entry["rows"], key=lambda pair: pair[0])],
                "existing_id": existing_id,
                "action": action,
                "row_numbers": panel_entry["row_numbers"],
            })
        return {
            "kind": "panels",
            "missing": missing,
            "errors": errors,
            "prepared": prepared,
            "skipped_count": skipped_count,
            "row_count": len(rows),
        }

    def _apply_panel_import_plan(self, plan: dict[str, Any]) -> None:
        created_count = 0
        updated_count = 0
        for entry in plan["prepared"]:
            try:
                if entry["existing_id"] is None:
                    self.database.create_panel(entry["panel_code"], entry["panel_name"], entry["panel_items"], specimen_type=entry["specimen_type"], method=entry["method"])
                    created_count += 1
                else:
                    self.database.update_panel(entry["existing_id"], entry["panel_code"], entry["panel_name"], entry["panel_items"], specimen_type=entry["specimen_type"], method=entry["method"])
                    updated_count += 1
            except sqlite3.IntegrityError as exc:
                QMessageBox.critical(self, tr("Import Failed"), str(exc))
                return
        self.refresh_catalog()
        self.notify_data_changed()
        QMessageBox.information(self, tr("Imported"), tr("Imported panels. Created: {created_count}, Updated: {updated_count}, Skipped: {skipped_count}", created_count=created_count, updated_count=updated_count, skipped_count=plan["skipped_count"]))

    def _confirm_import_plan(self, title: str, plan: dict[str, Any]) -> bool:
        missing = plan.get("missing", [])
        errors = plan.get("errors", [])
        prepared = plan.get("prepared", [])
        summary_lines = [
            tr("Rows read: {row_count}", row_count=plan.get("row_count", 0)),
            tr("Ready to import: {count}", count=len(prepared)),
            tr("Will create: {count}", count=sum(1 for entry in prepared if entry.get("action") == "create")),
            tr("Will update: {count}", count=sum(1 for entry in prepared if entry.get("action") == "update")),
            tr("Will skip: {count}", count=plan.get("skipped_count", 0)),
            tr("Errors: {count}", count=len(errors) + len(missing)),
        ]
        detail_lines: list[str] = []
        if missing:
            detail_lines.append(tr("Missing columns: {columns}", columns=", ".join(missing)))
        if errors:
            detail_lines.extend(errors)
        if prepared:
            detail_lines.append("")
            detail_lines.append(tr("Planned changes:"))
            if plan.get("kind") == "tests":
                detail_lines.extend(f"[{entry['action']}] {entry['code']} - {entry['payload']['name']}" for entry in prepared[:30])
            else:
                detail_lines.extend(f"[{entry['action']}] {entry['panel_code']} - {entry['panel_name']}" for entry in prepared[:30])
            if len(prepared) > 30:
                detail_lines.append(tr("... {count} more", count=len(prepared) - 30))
        dialog = ImportPreviewDialog(title, summary_lines, detail_lines, parent=self)
        ok_button = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
        ok_button.setEnabled(not missing and bool(prepared))
        return dialog.exec() == QDialog.Accepted and ok_button.isEnabled()

    @staticmethod
    def _split_options(raw_value: str) -> list[str]:
        normalized = raw_value.replace("|", "\n")
        return [part.strip() for part in normalized.splitlines() if part.strip()]

    @staticmethod
    def _optional_int(value: str) -> int | None:
        normalized = value.strip()
        if not normalized:
            return None
        return int(normalized)

    @staticmethod
    def _optional_float(value: str) -> str | None:
        normalized = value.strip().replace(",", "")
        if not normalized:
            return None
        try:
            Decimal(normalized)
        except InvalidOperation as exc:
            raise ValueError(str(exc)) from exc
        return normalized

    @staticmethod
    def _format_import_errors(errors: list[str]) -> str:
        preview = errors[:10]
        message = "\n".join(preview)
        if len(errors) > 10:
            message += f"\n... {len(errors) - 10} more"
        return message

    def _refresh_tests_table(self) -> None:
        self.filtered_test_records = self._filtered_test_records()
        rows = [
            (
                f"{record.code}{' (' + tr('Archived') + ')' if not record.is_active else ''}",
                record.name,
                record.specimen_type or "",
                record.result_kind,
                str(record.range_count),
            )
            for record in self.filtered_test_records
        ]
        self.set_table_rows(self.tests_table, rows)
        self._update_test_action_buttons()

    def _filtered_test_records(self) -> list[TestRecord]:
        query = self.tests_search.text().strip().lower() if hasattr(self, "tests_search") else ""
        if not query:
            return list(self.test_records)
        terms = [term for term in query.split() if term]
        matches: list[TestRecord] = []
        for record in self.test_records:
            haystack = " ".join([
                record.code,
                record.name,
                record.category_name or "",
                record.specimen_type or "",
                record.method or "",
                record.result_kind,
            ]).lower()
            if all(term in haystack for term in terms):
                matches.append(record)
        return matches

    def _filtered_panel_records(self) -> list[PanelRecord]:
        query = self.panels_search.text().strip().lower() if hasattr(self, "panels_search") else ""
        if not query:
            return list(self.panel_records)
        terms = [term for term in query.split() if term]
        matches: list[PanelRecord] = []
        for record in self.panel_records:
            haystack = " ".join([
                record.code,
                record.name,
                record.test_names or "",
            ]).lower()
            if all(term in haystack for term in terms):
                matches.append(record)
        return matches

    def _refresh_panels_table(self) -> None:
        self.filtered_panel_records = self._filtered_panel_records()
        rows = [
            (
                f"{record.code}{' (' + tr('Archived') + ')' if not record.is_active else ''}",
                record.name,
                record.test_names or "",
            )
            for record in self.filtered_panel_records
        ]
        self.set_table_rows(self.panels_table, rows)
        self._update_panel_action_buttons()

    def _selected_test_id(self) -> int | None:
        row = self.tests_table.currentRow()
        if row < 0 or row >= len(self.filtered_test_records):
            return None
        return self.filtered_test_records[row].id

    def _selected_panel_id(self) -> int | None:
        row = self.panels_table.currentRow()
        if row < 0 or row >= len(self.filtered_panel_records):
            return None
        return self.filtered_panel_records[row].id

    def _selected_test_record(self) -> TestRecord | None:
        row = self.tests_table.currentRow()
        if row < 0 or row >= len(self.filtered_test_records):
            return None
        return self.filtered_test_records[row]

    def _selected_panel_record(self) -> PanelRecord | None:
        row = self.panels_table.currentRow()
        if row < 0 or row >= len(self.filtered_panel_records):
            return None
        return self.filtered_panel_records[row]

    def _update_test_action_buttons(self) -> None:
        record = self._selected_test_record()
        has_selection = record is not None
        self.edit_test_button.setEnabled(has_selection)

    def _update_panel_action_buttons(self) -> None:
        record = self._selected_panel_record()
        has_selection = record is not None
        self.edit_panel_button.setEnabled(has_selection)



