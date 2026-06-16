from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database
from spdxlims.i18n import tr


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
