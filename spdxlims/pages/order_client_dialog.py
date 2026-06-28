from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spdxlims.auto_invoicing import FREQUENCY_OPTIONS
from spdxlims.database import Database
from spdxlims.i18n import tr
from spdxlims.sat_catalogs import REGIMEN_FISCAL_OPTIONS, USO_CFDI_OPTIONS


class ClientDialog(QDialog):
    def __init__(self, database: Database, parent: QWidget | None = None, client_id: int | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.client_id: int | None = client_id
        self._editing = client_id is not None
        self.setWindowTitle(tr("Edit Client") if self._editing else tr("New Client"))
        self.setModal(True)
        self.resize(480, 520)

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

        self.auto_invoice_enabled = QCheckBox(tr("Automatically create invoices"))
        self.auto_invoice_frequency = QComboBox()
        for code, label in FREQUENCY_OPTIONS:
            self.auto_invoice_frequency.addItem(tr(label), code)
        self.auto_invoice_enabled.toggled.connect(self.auto_invoice_frequency.setEnabled)
        self.auto_invoice_frequency.setEnabled(False)

        branding = self.database.get_report_branding_options()
        self.header_image_combo = QComboBox()
        self._populate_branding_combo(self.header_image_combo, branding.get("headers", []))
        self.footer_image_combo = QComboBox()
        self._populate_branding_combo(self.footer_image_combo, branding.get("footers", []))

        form.addRow(tr("Client"), self.name)
        form.addRow(tr("Phone"), self.phone)
        form.addRow(tr("Email"), self.email)
        form.addRow(tr("Tax ID (RFC)"), self.tax_id)
        form.addRow(tr("Fiscal Regime"), self.fiscal_regime)
        form.addRow(tr("Postal Code"), self.postal_code)
        form.addRow(tr("CFDI Use"), self.cfdi_use)
        form.addRow("", self.auto_invoice_enabled)
        form.addRow(tr("Invoice Frequency"), self.auto_invoice_frequency)
        form.addRow(tr("Report Header Image"), self.header_image_combo)
        form.addRow(tr("Report Footer Image"), self.footer_image_combo)
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

    def _populate_branding_combo(self, combo: QComboBox, paths: list[str]) -> None:
        """Fill a combo with the report images uploaded in Settings.

        The first entry ("Use lab default") maps to an empty path, meaning the
        report falls back to the lab-wide header/footer for this client.
        """
        combo.clear()
        combo.addItem(tr("Use lab default"), "")
        for raw_path in paths:
            value = str(raw_path or "").strip()
            if not value or combo.findData(value) >= 0:
                continue
            combo.addItem(self._branding_label(value), value)

    @staticmethod
    def _branding_label(raw_path: str) -> str:
        return Path(raw_path).name or raw_path

    def _select_branding_path(self, combo: QComboBox, raw_path: str | None) -> None:
        value = str(raw_path or "").strip()
        if not value:
            combo.setCurrentIndex(0)
            return
        index = combo.findData(value)
        if index < 0:
            # The image is still assigned to the client but was removed from the
            # Settings library; keep it selectable so saving does not drop it.
            combo.addItem(self._branding_label(value), value)
            index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

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
        self.auto_invoice_enabled.setChecked(bool(client.auto_invoice_enabled))
        frequency_index = self.auto_invoice_frequency.findData(client.auto_invoice_frequency or '')
        self.auto_invoice_frequency.setCurrentIndex(frequency_index if frequency_index >= 0 else 0)
        self._select_branding_path(self.header_image_combo, client.header_image_path)
        self._select_branding_path(self.footer_image_combo, client.footer_signature_image_path)
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
                "auto_invoice_enabled": self.auto_invoice_enabled.isChecked(),
                "auto_invoice_frequency": self.auto_invoice_frequency.currentData() if self.auto_invoice_enabled.isChecked() else None,
                "header_image_path": self.header_image_combo.currentData(),
                "footer_signature_image_path": self.footer_image_combo.currentData(),
            }
            if self._editing and self.client_id is not None:
                self.database.update_client(self.client_id, payload)
            else:
                self.client_id = self.database.create_client(payload)
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        self.accept()
