from __future__ import annotations

import sqlite3
from datetime import datetime

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database
from spdxlims.i18n import tr


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
        self.date_of_birth.setPlaceholderText("AAAA-MM-DD")
        self.age_value = QLineEdit()
        self.age_value.setPlaceholderText("ej. 35")
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
        if not self.first_name.text().strip():
            QMessageBox.warning(self, tr("Missing Data"), tr("First name is required."))
            return
        age_value_text = self.age_value.text().strip()
        dob_text = self.date_of_birth.text().strip()
        if not dob_text and not age_value_text:
            QMessageBox.warning(self, tr("Missing Data"), tr("Enter either date of birth or age."))
            return
        if dob_text:
            try:
                datetime.strptime(dob_text, "%Y-%m-%d")
            except ValueError:
                QMessageBox.warning(self, tr("Invalid Date"), tr("Date of birth must be a valid date in YYYY-MM-DD format."))
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
                "date_of_birth": dob_text,
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
