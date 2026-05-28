from __future__ import annotations

from decimal import Decimal, InvalidOperation

import sqlite3
from datetime import datetime

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QTextDocument
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QSizePolicy,
    QWidget,
)

from spdxlims.database import Database, OrderSummaryRecord, ResultEntryRecord
from spdxlims.deployment import DeploymentService
from spdxlims.niimbot_client import NIIMBOTClient, NIIMBOTClientError
from spdxlims.patient_dialog import PatientDialog as SharedPatientDialog
from spdxlims.patient_service import PatientService
from spdxlims.order_service import OrderService
from spdxlims.order_excel import read_order_workbook_rows, write_order_import_template
from spdxlims.result_service import ResultService
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.sat_catalogs import REGIMEN_FISCAL_OPTIONS, USO_CFDI_OPTIONS


ORDER_ACTION_BUTTON_WIDTH = 110
ORDER_LIST_COLUMNS: list[tuple[str, str]] = [
    ("order_number", "Number"),
    ("patient_name", "Patient"),
    ("status", "Status"),
    ("created_at", "Created"),
]


class PatientDialog(QDialog):
    def __init__(self, database: Database, parent: QWidget | None = None, patient_id: int | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.patient_id: int | None = patient_id
        self._editing = patient_id is not None
        self.setWindowTitle(tr("Edit Patient") if self._editing else tr("New Patient"))
        self.setModal(True)
        self.resize(420, 520)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.first_name = QLineEdit()
        self.last_name = QLineEdit()
        self.middle_name = QLineEdit()
        self.sex = QComboBox()
        self.sex.addItem("", "")
        self.sex.addItem(tr("Male"), "M")
        self.sex.addItem(tr("Female"), "F")
        self.sex.addItem(tr("Other"), "O")
        self.date_of_birth = QLineEdit()
        self.date_of_birth.setPlaceholderText("YYYY-MM-DD")
        self.age_value = QLineEdit()
        self.age_value.setPlaceholderText("e.g. 35")
        self.age_unit = QComboBox()
        self.age_unit.addItem(tr("Years"), "years")
        self.age_unit.addItem(tr("Months"), "months")
        self.age_unit.addItem(tr("Days"), "days")
        self.phone = QLineEdit()
        self.email = QLineEdit()
        self.address = QLineEdit()

        form.addRow(tr("First Name"), self.first_name)
        form.addRow(tr("Last Name"), self.last_name)
        form.addRow(tr("Middle Name"), self.middle_name)
        form.addRow(tr("Sex"), self.sex)
        form.addRow(tr("Date of Birth"), self.date_of_birth)
        form.addRow(tr("Age"), self.age_value)
        form.addRow(tr("Age Unit"), self.age_unit)
        form.addRow(tr("Phone"), self.phone)
        form.addRow(tr("Email"), self.email)
        form.addRow(tr("Address"), self.address)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        cancel = QPushButton(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        self.archive_button = QPushButton(tr("Archive Patient"))
        self.archive_button.clicked.connect(self.archive_patient)
        self.archive_button.setVisible(self._editing)
        save = QPushButton(tr("Update Patient") if self._editing else tr("Save Patient"))
        save.clicked.connect(self.save_patient)
        buttons.addStretch(1)
        if self._editing:
            buttons.addWidget(self.archive_button)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        if self._editing and self.patient_id is not None:
            self._load_patient()

    def _load_patient(self) -> None:
        patient = self.database.get_patient(self.patient_id)
        if patient is None:
            return
        self.first_name.setText(patient.get('first_name') or '')
        self.last_name.setText(patient.get('last_name') or '')
        self.middle_name.setText(patient.get('middle_name') or '')
        sex_index = self.sex.findData(patient.get('sex') or '')
        self.sex.setCurrentIndex(sex_index if sex_index >= 0 else 0)
        self.date_of_birth.setText(patient.get('date_of_birth') or '')
        self.age_value.setText(str(patient.get('age_value')) if patient.get('age_value') is not None else '')
        age_unit_index = self.age_unit.findData(patient.get('age_unit') or '')
        self.age_unit.setCurrentIndex(age_unit_index if age_unit_index >= 0 else 0)
        self.phone.setText(patient.get('phone') or '')
        self.email.setText(patient.get('email') or '')
        self.address.setText(patient.get('address') or '')

    def archive_patient(self) -> None:
        if not self._editing or self.patient_id is None:
            return
        answer = QMessageBox.question(
            self,
            tr("Archive Patient"),
            tr("Archive this patient? The patient will be hidden from normal lists."),
        )
        if answer != QMessageBox.Yes:
            return
        self.database.archive_patient(self.patient_id)
        self.accept()

    def save_patient(self) -> None:
        if not self.first_name.text().strip() or not self.last_name.text().strip():
            QMessageBox.warning(self, tr("Missing Data"), tr("First name and last name are required."))
            return
        age_value_text = self.age_value.text().strip()
        if not self.date_of_birth.text().strip() and not age_value_text:
            QMessageBox.warning(self, tr("Missing Data"), tr("Enter either date of birth or age."))
            return
        try:
            age_value = int(age_value_text) if age_value_text else None
        except ValueError:
            QMessageBox.warning(self, tr("Invalid Age"), tr("Age must be a whole number."))
            return
        try:
            payload = {
                "first_name": self.first_name.text(),
                "last_name": self.last_name.text(),
                "middle_name": self.middle_name.text(),
                "sex": self.sex.currentData(),
                "date_of_birth": self.date_of_birth.text(),
                "age_value": age_value,
                "age_unit": self.age_unit.currentData() if age_value is not None else None,
                "phone": self.phone.text(),
                "email": self.email.text(),
                "address": self.address.text(),
            }
            if self._editing and self.patient_id is not None:
                self.database.update_patient(self.patient_id, payload)
            else:
                self.patient_id = self.database.create_patient(payload)
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        self.accept()


class DoctorDialog(QDialog):
    def __init__(self, database: Database, parent: QWidget | None = None, doctor_id: int | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.doctor_id: int | None = doctor_id
        self._editing = doctor_id is not None
        self.setWindowTitle(tr("Edit Doctor") if self._editing else tr("New Doctor"))
        self.setModal(True)
        self.resize(420, 260)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.full_name = QLineEdit()
        self.license_number = QLineEdit()
        self.phone = QLineEdit()
        self.email = QLineEdit()

        form.addRow(tr("Doctor"), self.full_name)
        form.addRow(tr("License"), self.license_number)
        form.addRow(tr("Phone"), self.phone)
        form.addRow(tr("Email"), self.email)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        cancel = QPushButton(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        self.archive_doctor_button = QPushButton()
        self.archive_doctor_button.clicked.connect(self.toggle_doctor_archive)
        save = QPushButton(tr("Update Doctor") if self._editing else tr("Save Doctor"))
        save.clicked.connect(self.save_doctor)
        buttons.addStretch(1)
        if self._editing:
            buttons.addWidget(self.archive_doctor_button)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        if self._editing and self.doctor_id is not None:
            self._load_doctor()

    def _load_doctor(self) -> None:
        doctor = self.database.get_doctor(self.doctor_id)
        if doctor is None:
            return
        self.full_name.setText(doctor.full_name)
        self.license_number.setText(doctor.license_number or '')
        self.phone.setText(doctor.phone or '')
        self.email.setText(doctor.email or '')
        self.archive_doctor_button.setText(tr("Unarchive Doctor") if not doctor.is_active else tr("Archive Doctor"))

    def toggle_doctor_archive(self) -> None:
        if not self._editing or self.doctor_id is None:
            return
        doctor = self.database.get_doctor(self.doctor_id)
        if doctor is None:
            return
        if doctor.is_active:
            answer = QMessageBox.question(self, tr("Archive Doctor"), tr("Archive this doctor?"))
            if answer != QMessageBox.Yes:
                return
            self.database.archive_doctor(self.doctor_id)
        else:
            self.database.unarchive_doctor(self.doctor_id)
        self.accept()

    def save_doctor(self) -> None:
        if not self.full_name.text().strip():
            QMessageBox.warning(self, tr("Missing Data"), tr("Doctor name is required."))
            return
        try:
            payload = {
                "full_name": self.full_name.text(),
                "license_number": self.license_number.text(),
                "phone": self.phone.text(),
                "email": self.email.text(),
            }
            if self._editing and self.doctor_id is not None:
                self.database.update_doctor(self.doctor_id, payload)
            else:
                self.doctor_id = self.database.create_doctor(payload)
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        self.accept()


class ClientDialog(QDialog):
    def __init__(self, database: Database, parent: QWidget | None = None, client_id: int | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.client_id: int | None = client_id
        self._editing = client_id is not None
        self.setWindowTitle(tr("Edit Client") if self._editing else tr("New Client"))
        self.setModal(True)
        self.resize(440, 360)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name = QLineEdit()
        self.phone = QLineEdit()
        self.email = QLineEdit()
        self.tax_id = QLineEdit()
        self.fiscal_regime = QComboBox()
        self.postal_code = QLineEdit()
        self.cfdi_use = QComboBox()
        self.fiscal_regime.addItem('', '')
        for code, label in REGIMEN_FISCAL_OPTIONS:
            self.fiscal_regime.addItem(label, code)
        self.cfdi_use.addItem('', '')
        for code, label in USO_CFDI_OPTIONS:
            self.cfdi_use.addItem(label, code)

        form.addRow(tr("Client"), self.name)
        form.addRow(tr("Phone"), self.phone)
        form.addRow(tr("Email"), self.email)
        form.addRow(tr("Tax ID (RFC)"), self.tax_id)
        form.addRow(tr("Fiscal Regime"), self.fiscal_regime)
        form.addRow(tr("Postal Code"), self.postal_code)
        form.addRow(tr("CFDI Use"), self.cfdi_use)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        cancel = QPushButton(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        self.archive_client_button = QPushButton()
        self.archive_client_button.clicked.connect(self.toggle_client_archive)
        save = QPushButton(tr("Update Client") if self._editing else tr("Save Client"))
        save.clicked.connect(self.save_client)
        buttons.addStretch(1)
        if self._editing:
            buttons.addWidget(self.archive_client_button)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        if self._editing and self.client_id is not None:
            self._load_client()

    def _load_client(self) -> None:
        client = self.database.get_client(self.client_id)
        if client is None:
            return
        self.name.setText(client.name)
        self.phone.setText(client.phone or '')
        self.email.setText(client.email or '')
        self.tax_id.setText(client.tax_id or '')
        fiscal_index = self.fiscal_regime.findData(client.fiscal_regime or '')
        self.fiscal_regime.setCurrentIndex(fiscal_index if fiscal_index >= 0 else 0)
        self.postal_code.setText(client.postal_code or '')
        cfdi_index = self.cfdi_use.findData(client.cfdi_use or '')
        self.cfdi_use.setCurrentIndex(cfdi_index if cfdi_index >= 0 else 0)
        self.archive_client_button.setText(tr("Unarchive Client") if not client.is_active else tr("Archive Client"))

    def toggle_client_archive(self) -> None:
        if not self._editing or self.client_id is None:
            return
        client = self.database.get_client(self.client_id)
        if client is None:
            return
        if client.is_active:
            answer = QMessageBox.question(self, tr("Archive Client"), tr("Archive this client?"))
            if answer != QMessageBox.Yes:
                return
            self.database.archive_client(self.client_id)
        else:
            self.database.unarchive_client(self.client_id)
        self.accept()

    def save_client(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, tr("Missing Data"), tr("Client name is required."))
            return
        try:
            payload = {
                "name": self.name.text(),
                "phone": self.phone.text(),
                "email": self.email.text(),
                "tax_id": self.tax_id.text(),
                "fiscal_regime": self.fiscal_regime.currentData(),
                "postal_code": self.postal_code.text(),
                "cfdi_use": self.cfdi_use.currentData(),
            }
            if self._editing and self.client_id is not None:
                self.database.update_client(self.client_id, payload)
            else:
                self.client_id = self.database.create_client(payload)
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        self.accept()


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
            self.results_table.selectRow(0)
            self.load_selected_entry()
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


class OrderLabelsDialog(QDialog):
    _CODE39_PATTERNS = {
        '0': 'nnnwwnwnn', '1': 'wnnwnnnnw', '2': 'nnwwnnnnw', '3': 'wnwwnnnnn',
        '4': 'nnnwwnnnw', '5': 'wnnwwnnnn', '6': 'nnwwwnnnn', '7': 'nnnwnnwnw',
        '8': 'wnnwnnwnn', '9': 'nnwwnnwnn', 'A': 'wnnnnwnnw', 'B': 'nnwnnwnnw',
        'C': 'wnwnnwnnn', 'D': 'nnnnwwnnw', 'E': 'wnnnwwnnn', 'F': 'nnwnwwnnn',
        'G': 'nnnnnwwnw', 'H': 'wnnnnwwnn', 'I': 'nnwnnwwnn', 'J': 'nnnnwwwnn',
        'K': 'wnnnnnnww', 'L': 'nnwnnnnww', 'M': 'wnwnnnnwn', 'N': 'nnnnwnnww',
        'O': 'wnnnwnnwn', 'P': 'nnwnwnnwn', 'Q': 'nnnnnnwww', 'R': 'wnnnnnwwn',
        'S': 'nnwnnnwwn', 'T': 'nnnnwnwwn', 'U': 'wwnnnnnnw', 'V': 'nwwnnnnnw',
        'W': 'wwwnnnnnn', 'X': 'nwnnwnnnw', 'Y': 'wwnnwnnnn', 'Z': 'nwwnwnnnn',
        '-': 'nwnnnnwnw', '.': 'wwnnnnwnn', ' ': 'nwwnnnwnn', '$': 'nwnwnwnnn',
        '/': 'nwnwnnnwn', '+': 'nwnnnwnwn', '%': 'nnnwnwnwn', '*': 'nwnnwnwnn',
    }

    def __init__(self, database: Database, order_id: int | None = None, label_rows: list[dict[str, object]] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.order_id = order_id
        self.label_rows: list[dict[str, object]] = list(label_rows or [])
        self.client_id: int | None = None
        self._loading_preferences = False
        self.show_barcode = True
        self.show_patient_name = True
        self.setWindowTitle(tr("Print Labels"))
        self.setModal(True)
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(
                min(860, max(720, available.width() - 120)),
                min(620, max(520, available.height() - 120)),
            )
        else:
            self.resize(820, 620)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        self.info = QLabel()
        self.info.setWordWrap(True)
        root.addWidget(self.info)

        controls = QGridLayout()
        controls.setVerticalSpacing(8)
        controls.setHorizontalSpacing(10)
        self.size_combo = QComboBox()
        self.size_combo.currentIndexChanged.connect(self._refresh_preview)
        self.size_combo.addItem('40 x 20 mm', 'vial_small')
        self.size_combo.addItem('50 x 20 mm', 'tube_small')
        self.size_combo.addItem('50 x 25 mm', 'small')
        self.size_combo.addItem('50 x 30 mm', 'small_tall')
        self.size_combo.addItem('62 x 30 mm', 'medium')
        self.size_combo.addItem('100 x 50 mm', 'large')
        self.template_label = QLabel()
        self.template_combo = QComboBox()
        self.template_combo.addItem(tr('General Lab'), 'general')
        self.template_label.hide()
        self.template_combo.hide()
        self.code_combo = QComboBox()
        self.code_combo.currentIndexChanged.connect(self._refresh_preview)
        self.code_combo.addItem(tr('Barcode + Patient Name'), 'barcode_name')
        self.code_combo.addItem(tr('Barcode Only'), 'barcode_only')
        self.payload_combo = QComboBox()
        self.payload_combo.currentIndexChanged.connect(self._on_payload_changed)
        self.payload_combo.addItem(tr('Order ID only'), 'order_only')
        self.payload_combo.addItem(tr('Order ID + specimen code'), 'order_specimen')
        self.payload_combo.addItem(tr('Accession ID only'), 'accession_only')
        self.payload_combo.addItem(tr('Sample ID only'), 'sample_only')
        self.payload_combo.addItem(tr('Order ID + accession ID'), 'order_accession')
        self.show_order_number_text = QCheckBox(tr("Show Order Number Text"))
        self.show_order_number_text.stateChanged.connect(self._refresh_preview)
        self.show_datetime = QCheckBox(tr("Show Date/Time"))
        self.show_datetime.stateChanged.connect(self._refresh_preview)
        self.copies_label = QLabel()
        self.copies_input = QSpinBox()
        self.copies_input.setRange(1, 99)
        self.copies_input.setValue(1)
        self.copies_input.valueChanged.connect(self._refresh_preview)
        controls.addWidget(self.show_order_number_text, 0, 0, 1, 2)
        controls.addWidget(self.show_datetime, 0, 2, 1, 2)
        controls.addWidget(self.copies_label, 1, 0)
        controls.addWidget(self.copies_input, 1, 1)
        root.addLayout(controls)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(300)
        root.addWidget(self.preview)

        buttons = QHBoxLayout()
        self.close_button = QPushButton(tr("Close"))
        self.close_button.clicked.connect(self.reject)
        self.print_niimbot_button = QPushButton(tr("Print to NIIMBOT"))
        self.print_niimbot_button.clicked.connect(self.print_to_niimbot)
        self.print_button = QPushButton(tr("Print Labels"))
        self.print_button.clicked.connect(self.print_labels)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.print_niimbot_button)
        buttons.addWidget(self.print_button)
        root.addLayout(buttons)

        self._load_preview()

    def _load_preview(self) -> None:
        if not self.label_rows and self.order_id is not None:
            self.label_rows = self.database.get_order_label_entries(self.order_id)
        if not self.label_rows:
            self.info.setText(tr("No printable labels were found for this order."))
            self.print_button.setEnabled(False)
            self.print_niimbot_button.setEnabled(False)
            return
        self.info.setText(tr("Preview the specimen labels for the selected order before printing."))
        self.copies_label.setText(tr("Copies"))
        self.show_order_number_text.setText(tr("Show Order Number Text"))
        self.show_datetime.setText(tr("Show Date/Time"))
        self.client_id = self._resolve_client_id()
        self._load_saved_preferences()

    def _resolve_client_id(self) -> int | None:
        if not self.label_rows:
            return None
        value = self.label_rows[0].get('client_id')
        if value in (None, ''):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _load_saved_preferences(self) -> None:
        preferences = self.database.get_label_print_preferences(self.client_id)
        self._loading_preferences = True
        size_index = self.size_combo.findData(preferences.get('size') or 'small_tall')
        if size_index >= 0:
            self.size_combo.setCurrentIndex(size_index)
        self.template_combo.setCurrentIndex(0)
        payload_index = self.payload_combo.findData(preferences.get('payload') or 'order_only')
        if payload_index >= 0:
            self.payload_combo.setCurrentIndex(payload_index)
        self.show_barcode = str(preferences.get('show_barcode') or '1') == '1'
        self.show_patient_name = str(preferences.get('show_patient_name') or '1') == '1'
        self.show_order_number_text.setChecked(str(preferences.get('show_order_number_text') or '0') == '1')
        self.show_datetime.setChecked(str(preferences.get('show_datetime') or '0') == '1')
        try:
            self.copies_input.setValue(max(1, int(str(preferences.get('copies') or '1'))))
        except ValueError:
            self.copies_input.setValue(1)
        self._loading_preferences = False
        self._refresh_preview()

    def _save_label_preferences(self) -> None:
        if not hasattr(self, "show_order_number_text") or not hasattr(self, "show_datetime"):
            return
        self.database.save_label_print_preferences(
            str(self.template_combo.currentData() or 'general'),
            str(self.payload_combo.currentData() or 'order_only'),
            self.client_id,
            show_barcode=self.show_barcode,
            show_patient_name=self.show_patient_name,
            show_order_number_text=self.show_order_number_text.isChecked(),
            show_datetime=self.show_datetime.isChecked(),
        )

    def _on_template_changed(self) -> None:
        if not hasattr(self, "payload_combo"):
            return
        self._apply_template_defaults()
        if not self._loading_preferences:
            self._save_label_preferences()

    def _on_payload_changed(self) -> None:
        self._refresh_preview()
        if not self._loading_preferences:
            self._save_label_preferences()

    def _apply_template_defaults(self) -> None:
        if not hasattr(self, "payload_combo"):
            return
        payload_defaults = {
            'general': 'order_only',
            'chemistry': 'order_specimen',
            'hematology': 'order_specimen',
            'microbiology': 'order_accession',
            'analyzer': 'order_only',
        }
        payload_key = payload_defaults.get(self.template_combo.currentData(), 'order_only')
        payload_index = self.payload_combo.findData(payload_key)
        if payload_index >= 0 and payload_index != self.payload_combo.currentIndex():
            self.payload_combo.setCurrentIndex(payload_index)
            return
        if not self._loading_preferences:
            self._refresh_preview()

    def _refresh_preview(self) -> None:
        if not self.label_rows:
            return
        copies = self._copies_count()
        base_row = self._base_label_row(self.label_rows)
        if base_row is None:
            return
        expanded_rows: list[dict[str, object]] = []
        for copy_number in range(1, copies + 1):
            item = dict(base_row)
            item['copy_number'] = copy_number
            item['copies_total'] = copies
            expanded_rows.append(item)
        self.preview.setHtml(
            self._build_label_html(
                expanded_rows,
                self.size_combo.currentData(),
                self.template_combo.currentData(),
                self.payload_combo.currentData(),
                show_barcode=self.show_barcode,
                show_patient_name=self.show_patient_name,
                show_order_number_text=self.show_order_number_text.isChecked(),
                show_datetime=self.show_datetime.isChecked(),
            )
        )

    def _copies_count(self) -> int:
        return max(1, int(self.copies_input.value()))

    def print_labels(self) -> None:
        printer = QPrinter(QPrinter.HighResolution)
        preview = QPrintPreviewDialog(printer, self)
        document = QTextDocument()
        document.setHtml(self.preview.toHtml())
        print_method = getattr(document, "print", None) or getattr(document, "print_", None)
        if print_method is None:
            QMessageBox.critical(self, tr("Print Failed"), tr("This Qt build does not support document printing."))
            return
        preview.paintRequested.connect(print_method)
        preview.exec()

    def print_to_niimbot(self) -> None:
        if not self.label_rows:
            QMessageBox.warning(self, tr("Missing Selection"), tr("No printable labels were found for this order."))
            return
        base_row = self._base_label_row(self.label_rows)
        if base_row is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("No printable labels were found for this order."))
            return
        copies = self._copies_count()
        width_mm, height_mm = self._niimbot_label_size(self.size_combo.currentData())
        client = NIIMBOTClient()
        try:
            printers = client.list_printers()
            printer = next((item for item in printers if item.id and item.status.lower() != "offline"), None)
            if printer is None:
                raise NIIMBOTClientError(tr("No NIIMBOT printer was reported by the local helper."))
            token = self._build_token(base_row, "order_only")
            safe_token = "".join(character if character.isalnum() else "" for character in token.upper()) or token.upper()
            patient_name = str(base_row.get("patient_name") or "").strip()
            client.print_label(
                printer_id=printer.id,
                width_mm=width_mm,
                height_mm=height_mm,
                barcode_value=safe_token,
                human_text=safe_token,
                text_lines=self._label_text_lines(base_row),
                show_barcode=self.show_barcode,
                copies=copies,
            )
        except NIIMBOTClientError as exc:
            QMessageBox.warning(self, tr("NIIMBOT Print Failed"), str(exc))
            return
        QMessageBox.information(
            self,
            tr("Printed"),
            tr("Sent {count} NIIMBOT label(s) to the printer.", count=str(copies)),
        )

    def _base_label_row(self, rows: list[dict[str, object]]) -> dict[str, object] | None:
        if not rows:
            return None
        first_row = dict(rows[0])
        first_row['test_name'] = ''
        first_row['specimen_type'] = ''
        first_row['group_label'] = ''
        return first_row

    def _label_text_lines(self, row: dict[str, object]) -> list[str]:
        lines: list[str] = []
        if self.show_order_number_text.isChecked():
            order_number = str(row.get("order_number") or "").strip()
            if order_number:
                lines.append(order_number)
        if self.show_patient_name:
            patient_name = str(row.get("patient_name") or "").strip()
            if patient_name:
                lines.append(patient_name)
        if self.show_datetime.isChecked():
            created_at = str(row.get("created_at") or "").strip()
            if created_at:
                lines.append(created_at)
        return lines

    @classmethod
    def _build_label_html(
        cls,
        rows: list[dict[str, object]],
        size_key: str | None,
        template_key: str | None,
        payload_key: str | None,
        *,
        show_barcode: bool,
        show_patient_name: bool,
        show_order_number_text: bool,
        show_datetime: bool,
    ) -> str:
        profiles = {
            'vial_small': {'width': '40mm', 'padding': '5px', 'name': '10px', 'title': '12px', 'meta': '8px'},
            'tube_small': {'width': '50mm', 'padding': '5px', 'name': '10px', 'title': '12px', 'meta': '8px'},
            'small': {'width': '50mm', 'padding': '6px', 'name': '11px', 'title': '13px', 'meta': '9px'},
            'small_tall': {'width': '50mm', 'padding': '8px', 'name': '12px', 'title': '14px', 'meta': '10px'},
            'medium': {'width': '62mm', 'padding': '8px', 'name': '13px', 'title': '16px', 'meta': '10px'},
            'large': {'width': '100mm', 'padding': '12px', 'name': '16px', 'title': '20px', 'meta': '12px'},
        }
        templates = {
            'general': {'accent': '#222', 'subtitle': ''},
            'chemistry': {'accent': '#1f6f8b', 'subtitle': 'CHEM'},
            'hematology': {'accent': '#8b1f4a', 'subtitle': 'HEMA'},
            'microbiology': {'accent': '#2f6b2f', 'subtitle': 'MICRO'},
            'analyzer': {'accent': '#444', 'subtitle': 'ANALYZER'},
        }
        profile = profiles.get(size_key or 'medium', profiles['medium'])
        template = templates.get(template_key or 'general', templates['general'])
        blocks: list[str] = []
        for row in rows:
            token = cls._build_token(row, payload_key)
            machine_block = ''
            if show_barcode:
                machine_block = cls._code39_html(token)
            copies_text = ''
            if int(row.get('copies_total', 1) or 1) > 1:
                copies_text = f'<div style="font-size:{profile["meta"]};color:#666;">{tr("Copy")} {row.get("copy_number", 1)}/{row.get("copies_total", 1)}</div>'
            group_text = str(row.get('group_label') or '')
            subtitle = template['subtitle']
            accession = str(row.get('accession_id') or '')
            sample = str(row.get('sample_id') or '')
            id_line = ''
            if accession or sample:
                id_line = f'<div style="font-size:{profile["meta"]};color:#444;margin-top:2px;">{accession} {sample}</div>'
            subtitle_line = f'<div style="font-size:{profile["meta"]};font-weight:700;color:{template["accent"]};margin-top:2px;">{subtitle}</div>' if subtitle else ''
            patient_line = f'<div style="font-size:{profile["name"]};margin-top:4px;">{row.get("patient_name", "")}</div>' if show_patient_name and row.get("patient_name") else ''
            order_text_line = f'<div style="font-size:{profile["meta"]};margin-top:4px;">{row.get("order_number", "")}</div>' if show_order_number_text and row.get("order_number") else ''
            datetime_line = f'<div style="font-size:{profile["meta"]};color:#666;margin-top:4px;">{row.get("created_at", "")}</div>' if show_datetime and row.get("created_at") else ''
            test_line = f'<div style="font-size:{profile["name"]};margin-top:8px;">{row.get("test_name", "")}</div>' if row.get("test_name") else ''
            specimen_line = f'<div style="font-size:{profile["meta"]};color:#444;margin-top:4px;">{row.get("specimen_type") or ""}</div>' if row.get("specimen_type") else ''
            group_line = f'<div style="font-size:{profile["meta"]};color:#444;margin-top:2px;">{group_text}</div>' if group_text else ''
            blocks.append(
                f'<div style="border:1px solid {template["accent"]};padding:{profile["padding"]};margin:10px auto;page-break-inside:avoid;width:{profile["width"]};">'
                f'{subtitle_line}'
                f'{patient_line}'
                f'{order_text_line}'
                f'{datetime_line}'
                f'{test_line}'
                f'{specimen_line}'
                f'{group_line}'
                f'{id_line}'
                f"{machine_block}{copies_text}"
                "</div>"
            )
        return '<html><body style="font-family:Segoe UI, Arial, sans-serif;">' + ''.join(blocks) + '</body></html>'

    def _render_niimbot_label_image(self, row: dict[str, object], size_key: str | None) -> QImage:
        width_mm, height_mm = self._niimbot_label_size(size_key)
        px_per_mm = 12
        width_px = width_mm * px_per_mm
        height_px = height_mm * px_per_mm
        image = QImage(width_px, height_px, QImage.Format_ARGB32)
        image.fill(QColor("#ffffff"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        margin = max(12, int(width_px * 0.03))
        barcode_top = margin + 10
        barcode_height = max(90, int(height_px * 0.42))
        token = self._build_token(row, "order_only")
        safe_token = ''.join(character if character.isalnum() else '' for character in token.upper()) or token.upper()
        current_top = barcode_top + 8
        if self.show_barcode:
            self._draw_code39(painter, safe_token, margin, barcode_top, width_px - (margin * 2), barcode_height)
            current_top = barcode_top + barcode_height + 8
        painter.setPen(QColor("#111111"))
        order_to_name_gap = max(16, int(height_px * 0.05))
        name_to_date_gap = max(12, int(height_px * 0.04))

        if self.show_order_number_text.isChecked():
            order_number = str(row.get("order_number") or "").strip()
            if order_number:
                order_font = QFont("Segoe UI", max(18, int(height_px * 0.11)))
                painter.setFont(order_font)
                painter.drawText(margin, current_top, width_px - (margin * 2), 42, Qt.AlignHCenter | Qt.AlignVCenter, order_number)
                current_top += 42 + order_to_name_gap

        if self.show_patient_name:
            patient_name = str(row.get("patient_name") or "").strip()
            if patient_name:
                patient_font = QFont("Segoe UI", max(16, int(height_px * 0.095)))
                painter.setFont(patient_font)
                patient_height = max(28, int(height_px * 0.14))
                painter.drawText(margin, current_top, width_px - (margin * 2), patient_height, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, patient_name)
                current_top += patient_height + name_to_date_gap

        if self.show_datetime.isChecked():
            created_at = str(row.get("created_at") or "").strip()
            if created_at:
                datetime_font = QFont("Segoe UI", max(12, int(height_px * 0.07)))
                painter.setFont(datetime_font)
                painter.drawText(margin, current_top, width_px - (margin * 2), max(24, int(height_px * 0.09)), Qt.AlignLeft | Qt.AlignTop, created_at)

        painter.end()
        return image

    @classmethod
    def _draw_code39(cls, painter: QPainter, token: str, x: int, y: int, width: int, height: int) -> None:
        safe = ''.join(character if character in cls._CODE39_PATTERNS and character != '*' else '-' for character in token.upper())
        encoded = '*' + safe + '*'
        units: list[tuple[bool, int]] = []
        for character in encoded:
            pattern = cls._CODE39_PATTERNS.get(character, cls._CODE39_PATTERNS['-'])
            for index, width_code in enumerate(pattern):
                is_bar = index % 2 == 0
                unit_width = 3 if width_code == 'w' else 1
                units.append((is_bar, unit_width))
            units.append((False, 1))
        total_units = sum(unit for _is_bar, unit in units) or 1
        unit_px = max(1.0, width / total_units)
        cursor = float(x)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#111111"))
        for is_bar, unit_width in units:
            segment_width = unit_width * unit_px
            if is_bar:
                painter.drawRect(int(round(cursor)), y, max(1, int(round(segment_width))), height)
            cursor += segment_width

    @staticmethod
    def _niimbot_label_size(size_key: str | None) -> tuple[int, int]:
        size_map = {
            "vial_small": (40, 20),
            "tube_small": (50, 20),
            "small": (50, 25),
            "small_tall": (50, 30),
            "medium": (62, 30),
            "large": (100, 50),
        }
        return size_map.get(size_key or "small_tall", (50, 30))

    @staticmethod
    def _build_token(row: dict[str, object], payload_key: str | None) -> str:
        order_number = str(row.get('order_number') or '').upper().replace(' ', '')
        accession_id = str(row.get('accession_id') or '').upper().replace(' ', '')
        sample_id = str(row.get('sample_id') or '').upper().replace(' ', '')
        specimen_code = str(row.get('specimen_code') or 'SPC').upper().replace(' ', '')
        payload = payload_key or 'order_only'
        if payload == 'accession_only':
            return (accession_id or order_number or specimen_code)[:36]
        if payload == 'sample_only':
            return (sample_id or order_number or specimen_code)[:36]
        if payload == 'order_accession':
            return f'{order_number}-{accession_id or specimen_code}'[:36]
        if payload == 'order_specimen':
            return f'{order_number}-{specimen_code}'[:36]
        return (order_number or accession_id or sample_id or specimen_code)[:36]

    @classmethod
    def _code39_html(cls, token: str) -> str:
        safe = ''.join(character if character in cls._CODE39_PATTERNS and character != '*' else '-' for character in token.upper())
        encoded = '*' + safe + '*'
        bars: list[str] = []
        for character in encoded:
            pattern = cls._CODE39_PATTERNS.get(character, cls._CODE39_PATTERNS['-'])
            for index, width_code in enumerate(pattern):
                width = '3px' if width_code == 'w' else '1px'
                color = '#111' if index % 2 == 0 else '#fff'
                bars.append(f'<span style="display:inline-block;width:{width};height:42px;background:{color};"></span>')
            bars.append('<span style="display:inline-block;width:1px;height:42px;background:#fff;"></span>')
        return '<div style="margin-top:8px;line-height:0;">' + ''.join(bars) + f'</div><div style="font-size:10px;font-family:Consolas,monospace;margin-top:4px;">{safe}</div>'


class OrdersPage(DataAwarePage):
    def __init__(self, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__()
        self.database = database
        self.deployment_service = deployment_service
        self.patient_service = PatientService(database, deployment_service)
        self.order_service = OrderService(database, deployment_service)
        self.selected_items: list[dict[str, object]] = []
        self.recent_order_records: list[OrderSummaryRecord] = []
        self.edit_order_id: int | str | None = None

        self.setObjectName("ordersPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self.top_controls = self._build_top_controls()
        root.addWidget(self.top_controls)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.order_form_panel = self._build_order_form()
        self.order_form_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.recent_orders_panel = self._build_recent_orders()
        self.recent_orders_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cards.addWidget(self.order_form_panel, 5)
        cards.addWidget(self.recent_orders_panel, 4)
        root.addLayout(cards, 1)
        self._doctor_choices: list[tuple[int | str, str]] = []

        self.retranslate_ui()
        self.refresh_page_data()
        self.populate_next_order_number()

    def _build_card(self, object_name: str, title: str) -> tuple[QFrame, QVBoxLayout, QLabel]:
        card = QFrame()
        card.setObjectName(object_name)
        card.setProperty("class", "orderCard")
        card.setFrameShape(QFrame.NoFrame)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("orderCardTitle")
        layout.addWidget(title_label)
        return card, layout, title_label

    def _build_field_block(self, label_widget: QLabel, field: QWidget) -> QWidget:
        block = QWidget()
        block.setProperty("class", "fieldBlock")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        layout.addWidget(label_widget)
        layout.addWidget(field)
        return block

    def _build_top_controls(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("orderTopControls")
        bar.setProperty("class", "orderCard")
        layout = QGridLayout(bar)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(6)

        self.form_labels: dict[str, QLabel] = {}
        self.order_number = QLineEdit()
        self.order_number.setReadOnly(True)
        self.status = QComboBox()
        self.status.setMinimumWidth(150)
        self.scan_input = QLineEdit()
        self.scan_input.returnPressed.connect(self.open_scanned_order)

        for key, field in (
            ("order_number", self.order_number),
            ("status", self.status),
            ("scan", self.scan_input),
        ):
            label = QLabel()
            self.form_labels[key] = label
            layout.addWidget(self._build_field_block(label, field), 0, len(self.form_labels) - 1)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 2)
        return bar

    def _build_order_form(self) -> QWidget:
        self.form_group, layout, self.current_order_title = self._build_card("orderCurrentCard", "Orden actual")
        self.form_group.setObjectName('orderFormShell')

        self.form = QFormLayout()
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(8)
        self.form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.patient_combo = QComboBox()
        self.patient_combo.setMinimumWidth(210)
        self.add_patient_button = QPushButton()
        self.add_patient_button.setProperty("class", "secondaryButton")
        self.add_patient_button.clicked.connect(self.open_patient_dialog)
        patient_row = QWidget()
        patient_row_layout = QHBoxLayout(patient_row)
        patient_row_layout.setContentsMargins(0, 0, 0, 0)
        patient_row_layout.setSpacing(12)
        patient_row_layout.addWidget(self.patient_combo, 1)
        patient_row_layout.addWidget(self.add_patient_button, 0)

        self.doctor_input = QLineEdit()
        self.doctor_input.setMinimumWidth(210)
        self.client_combo = QComboBox()
        self.client_combo.setMinimumWidth(210)
        self.test_combo = QComboBox()
        self.panel_combo = QComboBox()
        self.test_combo.setMinimumWidth(210)
        self.panel_combo.setMinimumWidth(210)
        self._configure_searchable_combo(self.test_combo)
        self._configure_searchable_combo(self.panel_combo)
        self.add_test_button = QPushButton()
        self.add_test_button.setProperty("class", "secondaryButton")
        self.add_test_button.clicked.connect(self.add_selected_test)
        self.add_panel_button = QPushButton()
        self.add_panel_button.setProperty("class", "secondaryButton")
        self.add_panel_button.clicked.connect(self.add_selected_panel)
        self.test_row = QWidget()
        test_row_layout = QHBoxLayout(self.test_row)
        test_row_layout.setContentsMargins(0, 0, 0, 0)
        test_row_layout.setSpacing(12)
        test_row_layout.addWidget(self.test_combo, 1)
        test_row_layout.addWidget(self.add_test_button, 0)
        panel_row = QWidget()
        panel_row_layout = QHBoxLayout(panel_row)
        panel_row_layout.setContentsMargins(0, 0, 0, 0)
        panel_row_layout.setSpacing(12)
        panel_row_layout.addWidget(self.panel_combo, 1)
        panel_row_layout.addWidget(self.add_panel_button, 0)
        self.remove_button = QPushButton()
        self.remove_button.setProperty("class", "secondaryButton")
        self.remove_button.clicked.connect(self.remove_selected_test)

        self._add_form_row("patient", patient_row)
        self._add_form_row("doctor", self.doctor_input)
        self._add_form_row("client", self.client_combo)
        self._add_form_row("test", self.test_row)
        self._add_form_row("panel", panel_row)
        layout.addLayout(self.form)

        self.selected_group = QWidget()
        self.selected_group.setObjectName('orderSelectedShell')
        selected_layout = QVBoxLayout(self.selected_group)
        selected_layout.setContentsMargins(0, 0, 0, 0)
        selected_layout.setSpacing(0)
        self.selected_stack = QStackedWidget()
        self.selected_stack.setObjectName("selectedPanelsStack")
        self.empty_panels_state = self._build_empty_panels_state()
        self.selected_table = QTableWidget(0, 2)
        self.selected_table.setObjectName("selectedPanelsTable")
        self.selected_panels: list[dict[str, object]] = []
        self.selected_table.itemChanged.connect(self._handle_selected_table_item_changed)
        self.selected_table.horizontalHeader().setStretchLastSection(True)
        self.selected_table.setColumnWidth(0, 240)
        self.selected_table.setColumnWidth(1, 108)
        self.selected_table.setMinimumHeight(170)
        self.selected_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.selected_stack.addWidget(self.empty_panels_state)
        self.selected_stack.addWidget(self.selected_table)
        selected_layout.addWidget(self.selected_stack)
        layout.addWidget(self.selected_group, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.save_button = QPushButton()
        self.save_button.setProperty("class", "primaryButton")
        self.save_button.clicked.connect(self.save_order)
        actions.addStretch(1)
        actions.addWidget(self.remove_button)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)

        return self.form_group

    def _build_recent_orders(self) -> QWidget:
        self.recent_group, layout, self.recent_orders_title = self._build_card("recentOrdersGroup", "Órdenes recientes")
        self.recent_group.setObjectName("recentOrdersGroup")
        self.helper = QLabel()
        self.helper.setObjectName("ordersHelper")
        self.helper.setWordWrap(True)
        self.scan_button = QPushButton()
        self.scan_button.setProperty("class", "secondaryButton")
        self.scan_button.clicked.connect(self.open_scanned_order)
        self.orders_table = QTableWidget(0, len(ORDER_LIST_COLUMNS))
        self.orders_table.setObjectName("recentOrdersTable")
        self.orders_table.horizontalHeader().setStretchLastSection(True)
        self.orders_table.setMinimumHeight(230)
        self.orders_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.orders_table.setSelectionMode(QTableWidget.SingleSelection)
        self.orders_table.cellDoubleClicked.connect(self.handle_recent_order_double_click)
        layout.addWidget(self.helper)
        layout.addWidget(self.orders_table)

        actions = QGridLayout()
        actions.setHorizontalSpacing(8)
        actions.setVerticalSpacing(8)
        self.edit_order_button = QPushButton()
        self.edit_order_button.setProperty("class", "secondaryButton")
        self.edit_order_button.clicked.connect(self.open_selected_order_for_edit)
        self.label_button = QPushButton()
        self.label_button.setProperty("class", "secondaryButton")
        self.label_button.clicked.connect(self.open_order_labels_dialog)
        self.result_button = QPushButton()
        self.result_button.setProperty("class", "primaryButton")
        self.result_button.clicked.connect(self.open_order_results_dialog)
        self.order_template_button = QPushButton()
        self.order_template_button.setProperty("class", "secondaryButton")
        self.order_template_button.clicked.connect(self.save_order_import_template)
        self.import_orders_button = QPushButton()
        self.import_orders_button.setProperty("class", "secondaryButton")
        self.import_orders_button.clicked.connect(self.import_orders_from_excel)
        actions.addWidget(self.result_button, 0, 0)
        actions.addWidget(self.edit_order_button, 1, 0)
        actions.addWidget(self.label_button, 2, 0)
        actions.addWidget(self.order_template_button, 3, 0)
        actions.addWidget(self.import_orders_button, 4, 0)
        actions.setColumnStretch(0, 1)
        layout.addLayout(actions)
        return self.recent_group

    def _add_form_row(self, key: str, field: QWidget) -> None:
        label = QLabel()
        self.form_labels[key] = label
        self.form.addRow(label, field)

    def _build_empty_panels_state(self) -> QWidget:
        empty = QWidget()
        empty.setObjectName("emptyPanelsState")
        layout = QVBoxLayout(empty)
        layout.setContentsMargins(18, 22, 18, 22)
        layout.setSpacing(6)
        layout.addStretch(1)
        icon = QLabel("+")
        icon.setObjectName("emptyPanelsIcon")
        icon.setAlignment(Qt.AlignCenter)
        title = QLabel("No hay paneles agregados")
        title.setObjectName("emptyPanelsTitle")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel("Agregue un panel para comenzar")
        subtitle.setObjectName("emptyPanelsSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon, 0, Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)
        return empty

    def retranslate_ui(self) -> None:

        if self.order_service.uses_server_backend():
            self.helper.setText(tr("Scan or select a shared order to edit it from the server. Double-click a recent order to load it into the form."))
        else:
            self.helper.setText(tr("Enter or scan an order barcode, or double-click an order to enter results."))
        self.current_order_title.setText("Orden actual")
        self.recent_orders_title.setText("\u00d3rdenes recientes")
        self.form_labels["scan"].setText("Escanear Código")
        self.scan_input.setPlaceholderText(tr("Enter or scan an order barcode"))
        self.scan_button.setText("Abrir Código")
        self.add_patient_button.setText(tr("New Patient"))
        self.add_test_button.setText(tr("Add Test"))
        self.add_panel_button.setText(tr("Add Panel"))
        self.remove_button.setText("Quitar Panel")
        self.selected_table.setHorizontalHeaderLabels([tr("Panel"), tr("Outsourced")])
        self.edit_order_button.setText("Editar Orden Seleccionada")
        self.label_button.setText("Imprimir Etiquetas")
        self.result_button.setText("Agregar Resultado")
        self.order_template_button.setText(tr("Order Template"))
        self.import_orders_button.setText(tr("Import Orders"))
        self.form_labels["order_number"].setText("Número de Orden")
        self.form_labels["status"].setText("Estado")
        self.form_labels["patient"].setText(tr("Patient"))
        self.form_labels["doctor"].setText(tr("Doctor"))
        self.form_labels["client"].setText(tr("Client"))
        self.form_labels["test"].setText(tr("Individual Test"))
        self.form_labels["panel"].setText(tr("Panel"))
        self._set_test_row_visible(False)
        current_status = self.status.currentData()
        self.status.clear()
        if self.order_service.uses_server_backend():
            self.status.addItem(tr("Registered"), "registered")
            self.status.addItem(tr("Collected"), "collected")
            self.status.addItem(tr("In Lab"), "in_lab")
            self.status.addItem(tr("Completed"), "completed")
            self.status.addItem(tr("Reported"), "reported")
            self.status.addItem(tr("Amended"), "amended")
        else:
            self.status.addItem("Borrador", "draft")
            self.status.addItem(tr("In Progress"), "in_progress")
        status_index = self.status.findData(current_status)
        self.status.setCurrentIndex(status_index if status_index >= 0 else 0)
        self.selected_table.setHorizontalHeaderLabels([tr("Panel"), tr("Outsourced")])
        self.orders_table.setHorizontalHeaderLabels(["Número", "Paciente", "Estado", "Fecha"])
        self._apply_orders_table_column_visibility()
        self.refresh_choices()
        self.refresh_recent_orders()
        self._refresh_selected_table()
        self._update_form_mode()

    def refresh_on_show(self) -> None:
        self.refresh_page_data()

    def refresh_page_data(self) -> None:
        self.refresh_choices()
        self._apply_orders_table_column_visibility()
        self.refresh_recent_orders()

    def refresh_choices(self) -> None:
        self.set_combo_items(
            self.patient_combo,
            [(label, patient_id) for patient_id, label in self.patient_service.list_patient_choices()],
            placeholder=tr("Select patient"),
            selected_data=self.patient_combo.currentData(),
        )
        self._doctor_choices = [(doctor_id, label) for doctor_id, label in self.order_service.list_doctor_choices()]
        selected_client_id = self.client_combo.currentData()
        self.set_combo_items(
            self.client_combo,
            [(label, client_id) for client_id, label in self.order_service.list_client_choices()],
            placeholder=tr("Select client"),
            selected_data=selected_client_id,
        )
        self._set_searchable_combo_items(
            self.test_combo,
            [(label, test_id) for test_id, label in self.order_service.list_test_choices()],
            placeholder=tr("Select test"),
            selected_data=self.test_combo.currentData(),
        )
        self._set_searchable_combo_items(
            self.panel_combo,
            [(label, panel_id) for panel_id, label in self.order_service.list_panel_choices()],
            placeholder=tr("Select panel"),
            selected_data=self.panel_combo.currentData(),
        )

    def _configure_searchable_combo(self, combo: QComboBox) -> None:
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.completer().setCompletionMode(QCompleter.PopupCompletion)
        combo.completer().setFilterMode(Qt.MatchContains)
        combo.completer().setCaseSensitivity(Qt.CaseInsensitive)
        combo.completer().activated.connect(lambda text, target=combo: self._sync_searchable_combo_text(target, text))
        combo.lineEdit().editingFinished.connect(lambda target=combo: self._sync_searchable_combo_text(target, target.currentText()))

    def _set_searchable_combo_items(
        self,
        combo: QComboBox,
        items: list[tuple[str, int | str]],
        *,
        placeholder: str,
        selected_data: int | str | None,
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        for label, data in items:
            combo.addItem(label, data)
        combo.lineEdit().setPlaceholderText(placeholder)
        selected_index = combo.findData(selected_data) if selected_data is not None else -1
        combo.setCurrentIndex(selected_index if selected_index >= 0 else -1)
        if selected_index < 0:
            combo.lineEdit().clear()
        combo.blockSignals(False)

    def _sync_searchable_combo_text(self, combo: QComboBox, text: str) -> None:
        match_index = combo.findText(text, Qt.MatchFixedString)
        combo.setCurrentIndex(match_index if match_index >= 0 else -1)

    def refresh_recent_orders(self) -> None:
        self.recent_order_records = self.order_service.list_recent_orders()
        rows = [
            (
                record.order_number,
                record.patient_name,
                self._display_status(record.status),
                self._format_recent_order_date(record.created_at),
            )
            for record in self.recent_order_records
        ]
        self.set_table_rows(self.orders_table, rows)
        for row_index in range(self.orders_table.rowCount()):
            status_item = self.orders_table.item(row_index, 2)
            if status_item is not None:
                status_item.setTextAlignment(Qt.AlignCenter)
            date_item = self.orders_table.item(row_index, 3)
            if date_item is not None:
                date_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.orders_table.setColumnWidth(0, 92)
        self.orders_table.setColumnWidth(1, 170)
        self.orders_table.setColumnWidth(2, 96)
        self.orders_table.setColumnWidth(3, 88)
        self._apply_orders_table_column_visibility()

    @staticmethod
    def _display_status(status: str | None) -> str:
        labels = {
            "draft": "Borrador",
            "in_progress": "En progreso",
            "registered": "Registrada",
            "collected": "Recolectada",
            "in_lab": "En laboratorio",
            "completed": "Completada",
            "reported": "Reportada",
            "amended": "Corregida",
        }
        return labels.get(str(status or "").strip(), str(status or ""))

    def _visible_orders_list_columns(self) -> list[str]:
        ui_state = self.database.get_ui_state()
        stored = ui_state.get("orders_list_visible_columns")
        default_columns = [key for key, _label in ORDER_LIST_COLUMNS]
        visible = [
            key for key in stored
            if isinstance(key, str) and key in default_columns
        ] if isinstance(stored, list) else default_columns
        return visible or [default_columns[0]]

    def _apply_orders_table_column_visibility(self) -> None:
        visible = set(self._visible_orders_list_columns())
        for column_index, (key, _label) in enumerate(ORDER_LIST_COLUMNS):
            self.orders_table.setColumnHidden(column_index, key not in visible)

    @staticmethod
    def _format_recent_order_date(raw_value: str | None) -> str:
        value = str(raw_value or "").strip()
        if not value:
            return ""
        date_part = value.replace("T", " ").split(" ", 1)[0]
        chunks = date_part.split("-")
        if len(chunks) == 3:
            year, month, day = chunks
            return f"{day}-{month}-{year}"
        return date_part

    def open_patient_dialog(self) -> None:
        dialog = SharedPatientDialog(self.patient_service, self)
        if dialog.exec() == QDialog.Accepted and dialog.patient_id is not None:
            self.refresh_page_data()
            index = self.patient_combo.findData(dialog.patient_id)
            if index >= 0:
                self.patient_combo.setCurrentIndex(index)
            self.notify_data_changed()

    def open_doctor_dialog(self) -> None:
        if self.order_service.uses_server_backend():
            QMessageBox.information(
                self,
                tr("Not Available Yet"),
                tr("Doctor maintenance is not available in server mode yet. Use the server admin tools for shared providers."),
            )
            return
        dialog = DoctorDialog(self.database, self)
        if dialog.exec() == QDialog.Accepted and dialog.doctor_id is not None:
            self.refresh_page_data()
            doctor = self.database.get_doctor(dialog.doctor_id)
            self.doctor_input.setText(doctor.full_name if doctor is not None else dialog.full_name.text().strip())
            self.notify_data_changed()

    def edit_selected_doctor(self) -> None:
        if self.order_service.uses_server_backend():
            QMessageBox.information(
                self,
                tr("Not Available Yet"),
                tr("Doctor maintenance is not available in server mode yet. Use the server admin tools for shared providers."),
            )
            return
        doctor_id = self._resolve_doctor_id_from_input(create_if_missing=False)
        if doctor_id is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a doctor first."))
            return
        dialog = DoctorDialog(self.database, self, doctor_id=doctor_id)
        if dialog.exec() == QDialog.Accepted and dialog.doctor_id is not None:
            self.refresh_page_data()
            doctor = self.database.get_doctor(dialog.doctor_id)
            self.doctor_input.setText(doctor.full_name if doctor is not None else dialog.full_name.text().strip())
            self.notify_data_changed()

    def open_client_dialog(self) -> None:
        if self.order_service.uses_server_backend():
            QMessageBox.information(
                self,
                tr("Not Available Yet"),
                tr("Client maintenance is not available in server mode yet. Use the server admin tools for shared providers."),
            )
            return
        dialog = ClientDialog(self.database, self)
        if dialog.exec() == QDialog.Accepted and dialog.client_id is not None:
            self.refresh_page_data()
            index = self.client_combo.findData(dialog.client_id)
            if index >= 0:
                self.client_combo.setCurrentIndex(index)
            self.notify_data_changed()

    def edit_selected_client(self) -> None:
        if self.order_service.uses_server_backend():
            QMessageBox.information(
                self,
                tr("Not Available Yet"),
                tr("Client maintenance is not available in server mode yet. Use the server admin tools for shared providers."),
            )
            return
        client_id = self.client_combo.currentData()
        if client_id is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a client first."))
            return
        dialog = ClientDialog(self.database, self, client_id=client_id)
        if dialog.exec() == QDialog.Accepted and dialog.client_id is not None:
            self.refresh_page_data()
            index = self.client_combo.findData(dialog.client_id)
            if index >= 0:
                self.client_combo.setCurrentIndex(index)
            self.notify_data_changed()

    def open_scanned_order(self) -> None:
        order_number = self.scan_input.text().strip()
        if not order_number:
            QMessageBox.warning(self, tr("Missing Data"), tr("Enter or scan an order barcode."))
            return
        if self.order_service.uses_server_backend():
            try:
                record = self.order_service.get_order_detail_by_number(order_number)
            except RuntimeError as exc:
                QMessageBox.warning(self, tr("Missing Selection"), str(exc))
                return
            self._load_order_record(record)
            self.scan_input.clear()
            QMessageBox.information(self, tr("Order"), tr("Shared order loaded for editing."))
            return
        lookup = self.database.find_order_by_number(order_number)
        if lookup is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Barcode order not found."))
            return
        record = self.database.get_order_edit_record(lookup.id)
        if record is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Barcode order not found."))
            return
        self._load_order_record(record)
        self.scan_input.clear()
        if lookup.is_preallocated:
            QMessageBox.information(self, tr("Saved"), tr("Barcode order loaded. Assign the patient and tests, then save."))
            return
        self.refresh_recent_orders()
        self._select_recent_order(lookup.id)
        QMessageBox.information(self, tr("Order"), tr("Order loaded for editing."))

    def generate_preallocated_batch(self) -> None:
        try:
            count = int((self.batch_count_input.text() or '0').strip())
        except ValueError:
            QMessageBox.warning(self, tr("Invalid Data"), tr("Batch size must be a whole number."))
            return
        if count <= 0:
            QMessageBox.warning(self, tr("Invalid Data"), tr("Batch size must be a whole number."))
            return
        batch_prefix = (self.batch_prefix_input.text() or '').strip().upper()
        if batch_prefix and (len(batch_prefix) != 1 or not batch_prefix.isalpha()):
            QMessageBox.warning(self, tr("Invalid Data"), tr("Batch letter must be a single letter."))
            return
        label_rows = self.database.create_preallocated_order_batch(count, self.client_combo.currentData(), batch_prefix=batch_prefix)
        self.populate_next_order_number()
        dialog = OrderLabelsDialog(self.database, label_rows=label_rows, parent=self)
        dialog.exec()

    def open_order_labels_dialog(self) -> None:
        order_id = self._selected_recent_order_id()
        if order_id is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a recent order first."))
            return
        dialog = OrderLabelsDialog(self.database, order_id=order_id, parent=self)
        dialog.exec()

    def open_order_results_dialog(self) -> None:
        order_id = self._selected_recent_order_id()
        if order_id is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a recent order first."))
            return
        dialog = OrderResultsDialog(self.database, order_id, self.deployment_service, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_recent_orders()
            self.notify_data_changed()

    def save_order_import_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Save Order Template"),
            "order_import_template.xlsx",
            tr("Excel Workbook (*.xlsx)"),
        )
        if not path:
            return
        try:
            target = write_order_import_template(
                path,
                clients=self.database.list_client_choices(active_only=True),
                panels=self.database.list_panels(status_filter="active"),
            )
        except OSError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        QMessageBox.information(self, tr("Saved"), tr("Order template saved: {path}", path=str(target)))

    def import_orders_from_excel(self) -> None:
        if self.order_service.uses_server_backend():
            QMessageBox.information(self, tr("Not Available Yet"), tr("Order Excel import is not available yet in server mode."))
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("Import Orders"), "", tr("Excel Workbook (*.xlsx)"))
        if not path:
            return
        try:
            rows = read_order_workbook_rows(path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, tr("Import Failed"), str(exc))
            return
        plan, errors = self._build_order_import_plan(rows)
        if errors:
            QMessageBox.critical(self, tr("Import Failed"), "\n".join(errors[:20]))
            return
        if not plan:
            QMessageBox.information(self, tr("No Matches"), tr("No valid orders were found in the workbook."))
            return
        preview_lines = [
            f"{item['patient_name']} - {len(item['order_items'])} tests"
            for item in plan[:12]
        ]
        if len(plan) > 12:
            preview_lines.append(f"... +{len(plan) - 12} more")
        confirm = QMessageBox.question(
            self,
            tr("Preview Order Import"),
            tr("Create {count} orders?", count=str(len(plan))) + "\n\n" + "\n".join(preview_lines),
        )
        if confirm != QMessageBox.Yes:
            return
        created = 0
        try:
            for item in plan:
                self.database.create_order(
                    order_number=str(item.get("order_number") or "") or None,
                    accession_id=str(item.get("accession_id") or "") or None,
                    sample_id=str(item.get("sample_id") or "") or None,
                    patient_id=int(item["patient_id"]),
                    doctor_id=item.get("doctor_id"),
                    client_id=item.get("client_id"),
                    order_items=list(item["order_items"]),
                    status=str(item.get("status") or "draft"),
                    notes=str(item.get("notes") or ""),
                )
                created += 1
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        self.refresh_page_data()
        self.notify_data_changed()
        QMessageBox.information(self, tr("Saved"), tr("Created {count} orders.", count=str(created)))

    def _build_order_import_plan(self, rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[str]]:
        plan: list[dict[str, object]] = []
        errors: list[str] = []
        for index, row in enumerate(rows, start=1):
            row_label = self._order_import_row_label(row, index)
            first_name = str(row.get("first_name") or "").strip()
            last_name = str(row.get("last_name") or "").strip()
            if not first_name:
                errors.append(f"{row_label}: first_name is required.")
                continue
            order_items, item_errors = self._order_import_items(row)
            if item_errors:
                errors.extend(f"{row_label}: {message}" for message in item_errors)
                continue
            if not order_items:
                errors.append(f"{row_label}: add at least one panel_codes value.")
                continue
            patient_id = self._resolve_import_patient(row)
            doctor_id = self._resolve_import_doctor(str(row.get("doctor") or ""))
            client_id = self._resolve_import_client(str(row.get("client") or ""))
            status = str(row.get("status") or "draft").strip() or "draft"
            if status not in {"draft", "in_progress"}:
                errors.append(f"{row_label}: status must be draft or in_progress.")
                continue
            plan.append(
                {
                    "order_number": str(row.get("order_number") or "").strip(),
                    "accession_id": str(row.get("accession_id") or "").strip(),
                    "sample_id": str(row.get("sample_id") or "").strip(),
                    "patient_id": patient_id,
                    "patient_name": " ".join(part for part in [first_name, last_name] if part),
                    "doctor_id": doctor_id,
                    "client_id": client_id,
                    "order_items": order_items,
                    "status": status,
                    "notes": str(row.get("notes") or "").strip(),
                }
            )
        return plan, errors

    def _order_import_items(self, row: dict[str, str]) -> tuple[list[dict[str, object]], list[str]]:
        items: list[dict[str, object]] = []
        errors: list[str] = []
        test_labels = {int(test_id): label for test_id, label in self.database.list_test_choices()}
        for code in self._split_import_codes(str(row.get("test_codes") or "")):
            test_id = self.database.get_test_id_by_code(code)
            if test_id is None:
                errors.append(f"unknown test code {code}")
                continue
            items.append({"item_type": "test", "test_id": test_id, "label": test_labels.get(test_id, code), "source": tr("Test"), "is_outsourced": 0})
        for code in self._split_import_codes(str(row.get("panel_codes") or "")):
            panel_id = self.database.get_panel_id_by_code(code)
            if panel_id is None:
                errors.append(f"unknown panel code {code}")
                continue
            for panel_item in self.order_service.get_panel_order_items(panel_id):
                if getattr(panel_item, "item_type", "") != "test" or panel_item.test_id is None:
                    continue
                items.append(
                    {
                        "item_type": "test",
                        "test_id": int(panel_item.test_id),
                        "label": panel_item.label,
                        "source": code,
                        "is_outsourced": 0,
                    }
                )
        return items, errors

    def _resolve_import_patient(self, row: dict[str, str]) -> int:
        patient_code = str(row.get("patient_code") or "").strip()
        first_name = str(row.get("first_name") or "").strip()
        last_name = str(row.get("last_name") or "").strip()
        middle_name = str(row.get("middle_name") or "").strip()
        date_of_birth = str(row.get("date_of_birth") or "").strip()
        with self.database.connect() as connection:
            if patient_code:
                existing = connection.execute("SELECT id FROM patients WHERE patient_code = ? AND is_active = 1", (patient_code,)).fetchone()
                if existing is not None:
                    return int(existing["id"])
            existing = connection.execute(
                """
                SELECT id FROM patients
                WHERE lower(first_name) = lower(?)
                  AND lower(last_name) = lower(?)
                  AND lower(COALESCE(middle_name, '')) = lower(?)
                  AND COALESCE(date_of_birth, '') = ?
                  AND is_active = 1
                """,
                (first_name, last_name, middle_name, date_of_birth),
            ).fetchone()
            if existing is not None:
                return int(existing["id"])
        return self.database.create_patient(
            {
                "patient_code": patient_code,
                "first_name": first_name,
                "last_name": last_name,
                "middle_name": middle_name,
                "sex": str(row.get("sex") or "").strip(),
                "date_of_birth": date_of_birth,
                "age_value": self._parse_optional_int(str(row.get("age_value") or "")),
                "age_unit": str(row.get("age_unit") or "").strip(),
                "phone": str(row.get("phone") or "").strip(),
                "email": str(row.get("email") or "").strip(),
                "address": str(row.get("address") or "").strip(),
                "national_id": str(row.get("national_id") or "").strip(),
            }
        )

    def _resolve_import_doctor(self, doctor_name: str) -> int | None:
        normalized = doctor_name.strip()
        if not normalized:
            return None
        for doctor_id, label in self._doctor_choices:
            if str(label).strip().casefold() == normalized.casefold():
                return int(doctor_id)
        return self.database.create_doctor({"full_name": normalized, "license_number": "", "phone": "", "email": ""})

    def _resolve_import_client(self, client_name: str) -> int | None:
        normalized = client_name.strip()
        if not normalized:
            return None
        for client_id, label in self.order_service.list_client_choices():
            if str(label).strip().casefold() == normalized.casefold():
                return int(client_id)
        return None

    @staticmethod
    def _split_import_codes(value: str) -> list[str]:
        normalized = value.replace("\n", ",").replace(";", ",").replace("|", ",")
        return [chunk.strip() for chunk in normalized.split(",") if chunk.strip()]

    @staticmethod
    def _parse_optional_int(value: str) -> int | None:
        text = value.strip()
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            return None

    @staticmethod
    def _order_import_row_label(row: dict[str, str], default_row_number: int) -> str:
        sheet = str(row.get("__sheet_name__") or "").strip()
        row_number = str(row.get("__row_number__") or default_row_number).strip()
        return f"{sheet} row {row_number}" if sheet else f"Row {row_number}"

    def handle_recent_order_double_click(self, _row: int, _col: int) -> None:
        if self.order_service.uses_server_backend():
            self.open_selected_order_for_edit()
            return
        self.open_order_results_dialog()

    def open_selected_order_for_edit(self) -> None:
        order_id = self._selected_recent_order_id()
        if order_id is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a recent order first."))
            return
        if self.order_service.uses_server_backend():
            try:
                record = self.order_service.get_order_detail(order_id)
            except RuntimeError as exc:
                QMessageBox.warning(self, tr("Missing Selection"), str(exc))
                return
            self._load_order_record(record)
            QMessageBox.information(self, tr("Order"), tr("Shared order loaded for editing."))
            return
        record = self.database.get_order_edit_record(int(order_id))
        if record is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Order not found."))
            return
        self._load_order_record(record)
        QMessageBox.information(self, tr("Order"), tr("Order loaded for editing."))

    def _selected_recent_order_id(self) -> int | str | None:
        row = self.orders_table.currentRow()
        if row < 0 or row >= len(self.recent_order_records):
            return None
        return self.recent_order_records[row].id

    def _select_recent_order(self, order_id: int | str) -> None:
        for row_index, record in enumerate(self.recent_order_records):
            if record.id == order_id:
                self.orders_table.setCurrentCell(row_index, 0)
                self.orders_table.selectRow(row_index)
                return

    def _set_combo_value(self, combo: QComboBox, value: int | str | None) -> None:
        if value is None:
            combo.setCurrentIndex(0)
            return
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _doctor_label_from_id(self, doctor_id: int | str | None) -> str:
        if doctor_id is None:
            return ""
        for choice_id, label in self._doctor_choices:
            if str(choice_id) == str(doctor_id):
                return label
        if not self.order_service.uses_server_backend():
            doctor = self.database.get_doctor(int(doctor_id))
            if doctor is not None:
                return doctor.full_name
        return ""

    def _resolve_doctor_id_from_input(self, *, create_if_missing: bool) -> int | str | None:
        doctor_name = self.doctor_input.text().strip()
        if not doctor_name:
            return None
        for doctor_id, label in self._doctor_choices:
            if label.strip().casefold() == doctor_name.casefold():
                return doctor_id
        if self.order_service.uses_server_backend():
            raise RuntimeError("Enter an existing doctor name exactly as configured on the server.")
        if not create_if_missing:
            return None
        doctor_id = self.database.create_doctor(
            {
                "full_name": doctor_name,
                "license_number": "",
                "phone": "",
                "email": "",
            }
        )
        self.refresh_choices()
        self.doctor_input.setText(doctor_name)
        return doctor_id

    def _update_form_mode(self) -> None:
        if self.edit_order_id is None:
            self.save_button.setText(tr("Save Order"))
        else:
            self.save_button.setText(tr("Update Order"))

    def _load_order_record(self, record) -> None:
        self.edit_order_id = record.id
        self.order_number.setText(record.order_number)
        self._set_combo_value(self.patient_combo, record.patient_id if not record.is_preallocated else None)
        self.doctor_input.setText(self._doctor_label_from_id(record.doctor_id))
        self._set_combo_value(self.client_combo, record.client_id)
        status_value = record.status if not record.is_preallocated else 'draft'
        status_index = self.status.findData(status_value)
        self.status.setCurrentIndex(status_index if status_index >= 0 else 0)
        self.selected_items = [dict(item) for item in record.items]
        self._load_selected_panels_from_items()
        self._refresh_selected_table()
        self._update_form_mode()

    def add_selected_test(self) -> None:
        test_id = self.test_combo.currentData()
        label = self.test_combo.currentText()
        if test_id is None:
            QMessageBox.warning(self, tr("Missing Data"), tr("Select a test first."))
            return
        self._add_test_item(test_id, label, tr("Test"))
        self.test_combo.setCurrentIndex(0)

    def add_selected_panel(self) -> None:
        panel_id = self.panel_combo.currentData()
        panel_label = self.panel_combo.currentText()
        if panel_id is None:
            QMessageBox.warning(self, tr("Missing Data"), tr("Select a panel first."))
            return
        if any(panel.get("panel_id") == panel_id for panel in self.selected_panels):
            QMessageBox.information(self, tr("Panel Already Added"), tr("This panel is already on the order."))
            return
        panel_items = self.order_service.get_panel_order_items(panel_id)
        if not panel_items:
            QMessageBox.warning(self, tr("Empty Panel"), tr("This panel does not have any tests."))
            return
        panel_tests: list[dict[str, object]] = []
        for item in panel_items:
            item_type = str(item.get("item_type") or "test")
            if item_type != "test":
                continue
            test_id = item.get("test_id")
            if test_id is None:
                continue
            panel_tests.append(
                {
                    "item_type": "test",
                    "test_id": test_id,
                    "label": str(item.get("label") or ""),
                    "source": panel_label,
                    "is_outsourced": 0,
                }
            )
        if not panel_tests:
            QMessageBox.warning(self, tr("Empty Panel"), tr("This panel does not have any tests."))
            return
        self.selected_panels.append({"panel_id": panel_id, "label": panel_label, "items": panel_tests, "is_outsourced": 0})
        self._rebuild_selected_items_from_panels()
        self._refresh_selected_table()
        self.panel_combo.setCurrentIndex(-1)
        self.panel_combo.lineEdit().clear()

    def remove_selected_test(self) -> None:
        row = self.selected_table.currentRow()
        if row < 0 or row >= len(self.selected_panels):
            return
        self.selected_panels.pop(row)
        self._rebuild_selected_items_from_panels()
        self._refresh_selected_table()

    def save_order(self) -> None:
        patient_id = self.patient_combo.currentData()
        if patient_id is None:
            QMessageBox.warning(self, tr("Missing Data"), tr("Select a patient for the order."))
            return
        if not self.selected_items:
            QMessageBox.warning(self, tr("Missing Data"), tr("Add at least one test or panel."))
            return

        if self.order_service.uses_server_backend():
            unsupported_items = [item for item in self.selected_items if item.get("item_type") != "test"]
            if unsupported_items:
                QMessageBox.information(
                    self,
                    tr("Not Available Yet"),
                    tr("Server mode currently supports direct test orders only."),
                )
                return
            try:
                doctor_id = self._resolve_doctor_id_from_input(create_if_missing=False)
            except RuntimeError as exc:
                QMessageBox.warning(self, tr("Missing Data"), str(exc))
                return
            try:
                if self.edit_order_id is not None:
                    updated = self.order_service.update_simple_order(
                        self.edit_order_id,
                        patient_id=patient_id,
                        test_ids=[item.get("test_id") for item in self.selected_items],
                        items=self.selected_items,
                        accession_id=None,
                        sample_id=None,
                        status=str(self.status.currentData() or "pending"),
                        notes="",
                        doctor_id=doctor_id,
                        client_id=self.client_combo.currentData(),
                    )
                    message = tr("Order updated: {order_number}").format(order_number=updated.order_number)
                else:
                    created = self.order_service.create_simple_order(
                        patient_id=patient_id,
                        test_ids=[item.get("test_id") for item in self.selected_items],
                        items=self.selected_items,
                        accession_id=None,
                        sample_id=None,
                        status=str(self.status.currentData() or "pending"),
                        notes="",
                        doctor_id=doctor_id,
                        client_id=self.client_combo.currentData(),
                    )
                    message = tr("Order created: {order_number}").format(order_number=created.get("order_number") or "")
            except RuntimeError as exc:
                QMessageBox.critical(self, tr("Save Failed"), str(exc))
                return

            self.clear_order_form()
            self.refresh_recent_orders()
            self.notify_data_changed()
            QMessageBox.information(self, tr("Saved"), message)
            return

        try:
            doctor_id = self._resolve_doctor_id_from_input(create_if_missing=True)
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return

        try:
            if self.edit_order_id is not None:
                record = self.database.get_order_edit_record(int(self.edit_order_id))
                if record is not None and int(record.is_preallocated) == 1:
                    self.database.assign_preallocated_order(
                        order_id=int(self.edit_order_id),
                        accession_id=None,
                        sample_id=None,
                        patient_id=patient_id,
                        doctor_id=doctor_id,
                        client_id=self.client_combo.currentData(),
                        order_items=self.selected_items,
                        status=self.status.currentData(),
                        notes="",
                    )
                    message = tr("Order assigned.")
                else:
                    self.database.update_order(
                        order_id=int(self.edit_order_id),
                        accession_id=None,
                        sample_id=None,
                        patient_id=patient_id,
                        doctor_id=doctor_id,
                        client_id=self.client_combo.currentData(),
                        order_items=self.selected_items,
                        status=self.status.currentData(),
                        notes="",
                    )
                    message = tr("Order updated.")
            else:
                self.database.create_order(
                    order_number=None,
                    accession_id=None,
                    sample_id=None,
                    patient_id=patient_id,
                    doctor_id=doctor_id,
                    client_id=self.client_combo.currentData(),
                    order_items=self.selected_items,
                    status=self.status.currentData(),
                    notes="",
                )
                message = tr("Order created.")
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return

        self.clear_order_form()
        self.refresh_recent_orders()
        self.notify_data_changed()
        QMessageBox.information(self, tr("Saved"), message)

    def clear_order_form(self) -> None:
        self.edit_order_id = None
        self.populate_next_order_number()
        self.status.setCurrentIndex(0)
        self.patient_combo.setCurrentIndex(0)
        self.doctor_input.clear()
        self.client_combo.setCurrentIndex(0)
        self.test_combo.setCurrentIndex(0)
        self.panel_combo.setCurrentIndex(0)
        self.selected_panels = []
        self.selected_items = []
        self._refresh_selected_table()
        self._update_form_mode()

    def _add_test_item(self, test_id: int, label: str, source: str) -> None:
        if any(item.get("item_type") == "test" and item.get("test_id") == test_id for item in self.selected_items):
            return
        self.selected_items.append({"item_type": "test", "test_id": test_id, "label": label, "source": source, "is_outsourced": 0})
        self._refresh_selected_table()

    def _add_heading_item(self, label: str, source: str) -> None:
        heading = label.strip()
        if not heading:
            return
        self.selected_items.append({"item_type": "heading", "label": heading, "source": source, "is_outsourced": 0})
        self._refresh_selected_table()

    def _add_comment_item(self, label: str, source: str) -> None:
        comment_label = label.strip()
        if not comment_label:
            return
        self.selected_items.append({"item_type": "comment", "label": comment_label, "source": source, "is_outsourced": 0})
        self._refresh_selected_table()

    def _refresh_selected_table(self, labels_override: dict[int, str] | None = None) -> None:
        _ = labels_override
        self.selected_table.blockSignals(True)
        self.selected_table.setRowCount(len(self.selected_panels))
        for row_index, panel in enumerate(self.selected_panels):
            self.selected_table.setItem(row_index, 0, QTableWidgetItem(str(panel.get("label") or "")))
            outsourced_item = QTableWidgetItem()
            outsourced_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            outsourced_item.setCheckState(Qt.Checked if panel.get("is_outsourced") else Qt.Unchecked)
            self.selected_table.setItem(row_index, 1, outsourced_item)
        self.selected_table.blockSignals(False)
        self.selected_stack.setCurrentIndex(1 if self.selected_panels else 0)

    def populate_next_order_number(self) -> None:
        self.order_number.setText(self.order_service.next_order_number())
        self.order_number.setPlaceholderText(tr("Assigned automatically when saved."))

    def _set_test_row_visible(self, visible: bool) -> None:
        self.test_row.setVisible(visible)
        self.form_labels["test"].setVisible(visible)
        set_row_visible = getattr(self.form, "setRowVisible", None)
        if callable(set_row_visible):
            set_row_visible(self.form_labels["test"], visible)

    def _rebuild_selected_items_from_panels(self) -> None:
        items: list[dict[str, object]] = []
        seen_test_ids: set[object] = set()
        for panel in self.selected_panels:
            is_outsourced = 1 if panel.get("is_outsourced") else 0
            for item in panel.get("items") or []:
                if not isinstance(item, dict):
                    continue
                test_id = item.get("test_id")
                if test_id is None or test_id in seen_test_ids:
                    continue
                seen_test_ids.add(test_id)
                item_payload = dict(item)
                item_payload["is_outsourced"] = is_outsourced
                items.append(item_payload)
        self.selected_items = items

    def _load_selected_panels_from_items(self) -> None:
        grouped_panels: dict[str, dict[str, object]] = {}
        for item in self.selected_items:
            if str(item.get("item_type") or "test") != "test":
                continue
            source = str(item.get("source") or "").strip()
            if not source or source == tr("Test"):
                continue
            panel = grouped_panels.setdefault(
                source,
                {
                    "panel_id": None,
                    "label": source,
                    "items": [],
                    "is_outsourced": 0,
                },
            )
            panel["items"].append(dict(item))
            if item.get("is_outsourced"):
                panel["is_outsourced"] = 1
        self.selected_panels = [
            {
                "panel_id": panel.get("panel_id"),
                "label": panel.get("label"),
                "items": list(panel.get("items") or []),
                "is_outsourced": 1 if panel.get("is_outsourced") else 0,
            }
            for panel in grouped_panels.values()
        ]
        self._rebuild_selected_items_from_panels()

    def _handle_selected_table_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 1:
            return
        row = item.row()
        if row < 0 or row >= len(self.selected_panels):
            return
        self.selected_panels[row]["is_outsourced"] = 1 if item.checkState() == Qt.Checked else 0
        self._rebuild_selected_items_from_panels()













