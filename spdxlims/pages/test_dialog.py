from __future__ import annotations

from decimal import Decimal, InvalidOperation

import sqlite3
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database
from spdxlims.i18n import tr
from spdxlims.test_service import TestService
from spdxlims.pages.base_page import DataAwarePage


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
        self.result_kind.addItem(tr("Image"), "image")
        self.result_kind.currentIndexChanged.connect(self._update_select_fields_visibility)
        self.select_options = QTextEdit()
        self.select_options.setFixedHeight(90)
        self.default_result_value = QLineEdit()
        self.result_multiplier = QLineEdit()
        self.result_multiplier.setPlaceholderText(tr("e.g. 1000"))

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
        content_layout.addLayout(form)

        range_group = QGroupBox(tr("Reference Ranges"))
        self.range_group = range_group
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
        if result_kind == "image":
            # Image results have no inline default value.
            default_result_value = ""

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
        kind = self.result_kind.currentData()
        is_select = kind == "select"
        self.select_options_label.setVisible(is_select)
        self.select_options.setVisible(is_select)
        is_numeric = kind == "numeric"
        self.result_multiplier_label.setVisible(is_numeric)
        self.result_multiplier.setVisible(is_numeric)
        # Image results carry no default value or reference ranges.
        is_image = kind == "image"
        self.default_result_label.setVisible(not is_image)
        self.default_result_value.setVisible(not is_image)
        self.range_group.setVisible(not is_image)

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
