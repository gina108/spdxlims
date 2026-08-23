from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spdxlims.db.panels import PANEL_KIND_CULTIVO, PANEL_KIND_FROTIS
from spdxlims.i18n import tr


class PanelLayoutDialog(QDialog):
    """Edits the report layout of a cultivo or frotis panel.

    The panel's own tests are the candidate rows: which of them belong to the
    gram-positive and gram-negative antibiograms, and what disc load each one
    prints. Nothing here changes what gets ordered or entered -- only how the
    panel is laid out on the report.
    """

    def __init__(
        self,
        kind: str,
        config: dict[str, Any],
        test_names: list[str],
        panel_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.kind = kind
        self.test_names = test_names
        self._config = dict(config)

        self.setModal(True)
        self.resize(760, 620)
        self.setWindowTitle(
            tr("Culture Report Layout") if kind == PANEL_KIND_CULTIVO else tr("Smear Report Layout")
        )

        root = QVBoxLayout(self)
        self.title_input = QLineEdit(str(config.get("title") or panel_name))
        self.method_note_input = QLineEdit(str(config.get("method_note") or ""))

        if kind == PANEL_KIND_CULTIVO:
            root.addWidget(self._build_culture_form(config))
            root.addWidget(self._build_antibiotics_table(config), 1)
        else:
            root.addWidget(self._build_frotis_form())
            root.addWidget(self._build_sections_table(config), 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # --- cultivo ---

    def _build_culture_form(self, config: dict[str, Any]) -> QWidget:
        group = QGroupBox(tr("Report Sections"))
        form = QFormLayout(group)
        form.setHorizontalSpacing(10)

        self.top_heading_input = QLineEdit(str(config.get("pathogens_heading") or ""))
        self.top_heading_input.setPlaceholderText(tr("Leave blank to omit this block"))
        self.isolate_combo = QComboBox()
        self.isolate_combo.addItem(tr("(none)"), "")
        for name in self.test_names:
            self.isolate_combo.addItem(name, name)
        index = self.isolate_combo.findData(str(config.get("isolate_name") or ""))
        self.isolate_combo.setCurrentIndex(index if index >= 0 else 0)
        self.isolate_label_input = QLineEdit(str(config.get("isolate_label") or ""))
        self.susceptibility_input = QLineEdit(str(config.get("susceptibility_heading") or ""))
        self.gram_pos_label_input = QLineEdit(str(config.get("gram_label_positive") or ""))
        self.gram_neg_label_input = QLineEdit(str(config.get("gram_label_negative") or ""))

        columns = QHBoxLayout()
        self.col1_input = QLineEdit(str(config.get("antibiogram_col_1") or ""))
        self.col2_input = QLineEdit(str(config.get("antibiogram_col_2") or ""))
        self.col3_input = QLineEdit(str(config.get("antibiogram_col_3") or ""))
        self.col3_input.setPlaceholderText(tr("Blank = no concentration column"))
        for widget in (self.col1_input, self.col2_input, self.col3_input):
            columns.addWidget(widget)
        columns_host = QWidget()
        columns_host.setLayout(columns)
        columns.setContentsMargins(0, 0, 0, 0)

        form.addRow(tr("Title band"), self.title_input)
        form.addRow(tr("Top block heading"), self.top_heading_input)
        helper = QLabel(tr("The rows under the top block are typed in by the tech on each order."))
        helper.setStyleSheet("color: #6b7480;")
        helper.setWordWrap(True)
        form.addRow("", helper)
        form.addRow(tr("Isolate field"), self.isolate_combo)
        form.addRow(tr("Isolate label"), self.isolate_label_input)
        form.addRow(tr("Antibiogram heading"), self.susceptibility_input)
        form.addRow(tr("Gram positive label"), self.gram_pos_label_input)
        form.addRow(tr("Gram negative label"), self.gram_neg_label_input)
        form.addRow(tr("Column titles"), columns_host)
        form.addRow(tr("Method note"), self.method_note_input)
        return group

    def _build_antibiotics_table(self, config: dict[str, Any]) -> QWidget:
        group = QGroupBox(tr("Antibiogram"))
        layout = QVBoxLayout(group)
        helper = QLabel(
            tr("Tick which antibiotics print for each gram. The order follows the panel's item order.")
        )
        helper.setWordWrap(True)
        helper.setStyleSheet("color: #6b7480;")
        layout.addWidget(helper)

        positive = {name.casefold() for name in config.get("antibiotic_names_positive") or []}
        negative = {name.casefold() for name in config.get("antibiotic_names_negative") or []}
        concentrations = config.get("antibiotic_concentrations") or {}

        self.antibiotics_table = QTableWidget(len(self.test_names), 4)
        self.antibiotics_table.setHorizontalHeaderLabels(
            [tr("Test"), tr("Gram +"), tr("Gram -"), tr("Concentration")]
        )
        self.antibiotics_table.verticalHeader().setVisible(False)
        self.antibiotics_table.setColumnWidth(0, 300)
        self.antibiotics_table.setColumnWidth(1, 70)
        self.antibiotics_table.setColumnWidth(2, 70)
        self.antibiotics_table.horizontalHeader().setStretchLastSection(True)
        self._gram_checks: list[tuple[QCheckBox, QCheckBox]] = []
        for row, name in enumerate(self.test_names):
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.antibiotics_table.setItem(row, 0, name_item)
            pos_check = QCheckBox()
            pos_check.setChecked(name.casefold() in positive)
            neg_check = QCheckBox()
            neg_check.setChecked(name.casefold() in negative)
            self.antibiotics_table.setCellWidget(row, 1, self._centered(pos_check))
            self.antibiotics_table.setCellWidget(row, 2, self._centered(neg_check))
            self.antibiotics_table.setItem(row, 3, QTableWidgetItem(str(concentrations.get(name, ""))))
            self._gram_checks.append((pos_check, neg_check))
        layout.addWidget(self.antibiotics_table)
        return group

    # --- frotis ---

    def _build_frotis_form(self) -> QWidget:
        group = QGroupBox(tr("Report Sections"))
        form = QFormLayout(group)
        form.addRow(tr("Title band"), self.title_input)
        form.addRow(tr("Method note"), self.method_note_input)
        return group

    def _build_sections_table(self, config: dict[str, Any]) -> QWidget:
        group = QGroupBox(tr("Narrative Sections"))
        layout = QVBoxLayout(group)
        helper = QLabel(tr("Tick the tests that print as narrative blocks. Tick none to print them all."))
        helper.setWordWrap(True)
        helper.setStyleSheet("color: #6b7480;")
        layout.addWidget(helper)
        selected = {name.casefold() for name in config.get("section_names") or []}
        self.sections_table = QTableWidget(len(self.test_names), 2)
        self.sections_table.setHorizontalHeaderLabels([tr("Test"), tr("Include")])
        self.sections_table.verticalHeader().setVisible(False)
        self.sections_table.setColumnWidth(0, 380)
        self.sections_table.horizontalHeader().setStretchLastSection(True)
        self._section_checks: list[QCheckBox] = []
        for row, name in enumerate(self.test_names):
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.sections_table.setItem(row, 0, name_item)
            check = QCheckBox()
            check.setChecked(name.casefold() in selected)
            self.sections_table.setCellWidget(row, 1, self._centered(check))
            self._section_checks.append(check)
        layout.addWidget(self.sections_table)
        return group

    @staticmethod
    def _centered(widget: QWidget) -> QWidget:
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(widget)
        return host

    def result_config(self) -> dict[str, Any]:
        if self.kind == PANEL_KIND_FROTIS:
            return {
                **self._config,
                "title": self.title_input.text().strip(),
                "method_note": self.method_note_input.text().strip(),
                "section_names": [
                    name for name, check in zip(self.test_names, self._section_checks) if check.isChecked()
                ],
            }
        positive: list[str] = []
        negative: list[str] = []
        concentrations: dict[str, str] = {}
        for row, name in enumerate(self.test_names):
            pos_check, neg_check = self._gram_checks[row]
            if pos_check.isChecked():
                positive.append(name)
            if neg_check.isChecked():
                negative.append(name)
            item = self.antibiotics_table.item(row, 3)
            value = (item.text() if item else "").strip()
            if value:
                concentrations[name] = value
        return {
            **self._config,
            "title": self.title_input.text().strip(),
            "pathogens_heading": self.top_heading_input.text().strip(),
            "isolate_name": str(self.isolate_combo.currentData() or ""),
            "isolate_label": self.isolate_label_input.text().strip(),
            "susceptibility_heading": self.susceptibility_input.text().strip(),
            "gram_label_positive": self.gram_pos_label_input.text().strip(),
            "gram_label_negative": self.gram_neg_label_input.text().strip(),
            "antibiogram_col_1": self.col1_input.text().strip(),
            "antibiogram_col_2": self.col2_input.text().strip(),
            "antibiogram_col_3": self.col3_input.text().strip(),
            "antibiotic_names_positive": positive,
            "antibiotic_names_negative": negative,
            "antibiotic_concentrations": concentrations,
            "method_note": self.method_note_input.text().strip(),
        }
