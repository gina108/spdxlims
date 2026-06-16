from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget

from spdxlims.i18n import tr
from spdxlims.patient_service import PatientService


class PatientDialog(QDialog):
    def __init__(self, patient_service: PatientService, parent: QWidget | None = None, patient_id: int | str | None = None) -> None:
        super().__init__(parent)
        self.patient_service = patient_service
        self.patient_id: int | str | None = patient_id
        self._editing = patient_id is not None
        self._is_active = True
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
        self.age_value.setPlaceholderText("ej. 35")
        self.age_unit = QComboBox()
        self.age_unit.addItem(tr("Years"), "years")
        self.age_unit.addItem(tr("Months"), "months")
        self.age_unit.addItem(tr("Days"), "days")
        self.phone = QLineEdit()
        self.phone_country_code = QLabel(f"+{self.patient_service.database.get_whatsapp_country_code()}")
        self.phone_country_code.setToolTip(tr("Default WhatsApp country code. Change it in Settings."))
        self.phone_row = QWidget()
        phone_layout = QHBoxLayout(self.phone_row)
        phone_layout.setContentsMargins(0, 0, 0, 0)
        phone_layout.setSpacing(8)
        phone_layout.addWidget(self.phone_country_code)
        phone_layout.addWidget(self.phone, 1)
        self.email = QLineEdit()
        self.address = QLineEdit()

        form.addRow(tr("First Name"), self.first_name)
        form.addRow(tr("Last Name"), self.last_name)
        form.addRow(tr("Middle Name"), self.middle_name)
        form.addRow(tr("Sex"), self.sex)
        form.addRow(tr("Date of Birth"), self.date_of_birth)
        form.addRow(tr("Age"), self.age_value)
        form.addRow(tr("Age Unit"), self.age_unit)
        form.addRow(tr("Phone"), self.phone_row)
        form.addRow(tr("Email"), self.email)
        form.addRow(tr("Address"), self.address)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        cancel = QPushButton(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        self.archive_button = QPushButton(tr("Archive Patient"))
        self.archive_button.clicked.connect(self.toggle_archive_patient)
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
        patient = self.patient_service.get_patient(self.patient_id)
        if patient is None:
            return
        self.first_name.setText(patient.get("first_name") or "")
        self.last_name.setText(patient.get("last_name") or "")
        self.middle_name.setText(patient.get("middle_name") or "")
        sex_index = self.sex.findData(patient.get("sex") or "")
        self.sex.setCurrentIndex(sex_index if sex_index >= 0 else 0)
        self.date_of_birth.setText(patient.get("date_of_birth") or "")
        self.age_value.setText(str(patient.get("age_value")) if patient.get("age_value") is not None else "")
        age_unit_index = self.age_unit.findData(patient.get("age_unit") or "")
        self.age_unit.setCurrentIndex(age_unit_index if age_unit_index >= 0 else 0)
        self.phone.setText(patient.get("phone") or "")
        self.email.setText(patient.get("email") or "")
        self.address.setText(patient.get("address") or "")
        self._is_active = bool(patient.get("is_active", 1))
        self.archive_button.setText(tr("Archive Patient") if self._is_active else tr("Unarchive Patient"))

    def toggle_archive_patient(self) -> None:
        if not self._editing or self.patient_id is None:
            return
        title = tr("Archive Patient") if self._is_active else tr("Unarchive Patient")
        prompt = tr("Archive this patient? The patient will be hidden from normal lists.") if self._is_active else tr("Restore this patient to active lists?")
        answer = QMessageBox.question(self, title, prompt)
        if answer != QMessageBox.Yes:
            return
        try:
            if self._is_active:
                self.patient_service.archive_patient(self.patient_id)
            else:
                self.patient_service.unarchive_patient(self.patient_id)
        except RuntimeError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        self.accept()

    def save_patient(self) -> None:
        if not self.first_name.text().strip():
            QMessageBox.warning(self, tr("Missing Data"), tr("First name is required."))
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
        try:
            if self._editing and self.patient_id is not None:
                self.patient_service.update_patient(self.patient_id, payload)
            else:
                self.patient_id = self.patient_service.create_patient(payload)
        except RuntimeError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        self.accept()
