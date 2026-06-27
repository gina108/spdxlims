"""Clínicas del portal — manage portal clinic logins and link each to a LIS client.

Previously a pop-up (ClinicsDialog) launched from the PORTAL page; now a first
class drawer page in the "invoices" workspace. Talks to the order-collection
app's shared-secret ``/lis/*`` API via PortalClient, and remembers the
clinic<->LIS-client link in the local PortalStore.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database
from spdxlims.deployment import DeploymentService
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.portal.client import PortalClient
from spdxlims.portal.settings import PortalStore
from spdxlims.provider_service import ProviderService


class CredentialsDialog(QDialog):
    """Show a clinic's portal login in a copy-paste friendly box.

    The portal stores only a password hash and never returns it, so the moment a
    password is set (clinic created or reset) is the only chance to capture it.
    Presenting it as selectable text with a one-click copy avoids transcription
    errors when handing the login to the clinic.
    """

    def __init__(
        self,
        *,
        name: str,
        site_url: str,
        email: str,
        password: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Acceso de la clínica")
        self.setMinimumWidth(460)
        self._text = self._format(name, site_url, email, password)

        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                "Comparte estos datos con la clínica. La contraseña no se puede volver "
                "a consultar después; cópiala ahora."
            )
        )
        view = QPlainTextEdit(self._text)
        view.setReadOnly(True)
        view.setFixedHeight(120)
        root.addWidget(view)

        buttons = QHBoxLayout()
        self.copy_button = QPushButton("Copiar")
        self.copy_button.clicked.connect(self._copy)
        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

    @staticmethod
    def _format(name: str, site_url: str, email: str, password: str) -> str:
        lines = [f"Acceso al portal de laboratorio — {name}".rstrip(" —")]
        if site_url:
            lines.append(f"Sitio: {site_url}")
        lines.append(f"Usuario (correo): {email}")
        lines.append(f"Contraseña: {password}")
        return "\n".join(lines)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._text)
        self.copy_button.setText("Copiado ✓")


class ClinicsPage(DataAwarePage):
    """Create portal clinic logins and link each clinic to a LIS client."""

    def __init__(self, data_dir: Path, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__()
        self.store = PortalStore(data_dir)
        self._providers = ProviderService(database, deployment_service)
        self._clinics: list[dict] = []
        self._client_choices: list[tuple[str, str]] = []

        root = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("Clínicas del portal")
        title.setObjectName("SectionTitle")
        self.refresh_button = QPushButton("Actualizar")
        self.refresh_button.clicked.connect(self._reload)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        root.addWidget(
            QLabel(
                "Accesos de las clínicas al portal. Vincula cada clínica a un cliente del LIS para "
                "que sus pedidos importados queden registrados a nombre de ese cliente."
            )
        )

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Clínica", "Correo", "Estado", "Cliente del LIS"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 180)
        self.table.setColumnWidth(2, 80)
        root.addWidget(self.table, 1)

        row_actions = QHBoxLayout()
        self.toggle_button = QPushButton("Activar / Desactivar")
        self.toggle_button.clicked.connect(self._toggle_active)
        self.reset_button = QPushButton("Restablecer contraseña")
        self.reset_button.clicked.connect(self._reset_password)
        row_actions.addStretch(1)
        row_actions.addWidget(self.toggle_button)
        row_actions.addWidget(self.reset_button)
        root.addLayout(row_actions)

        self.create_box = QGroupBox("Crear acceso de clínica")
        form = QFormLayout(self.create_box)
        self.new_name = QLineEdit()
        self.new_email = QLineEdit()
        self.new_password = QLineEdit()
        self.new_phone = QLineEdit()
        form.addRow("Nombre", self.new_name)
        form.addRow("Correo", self.new_email)
        form.addRow("Contraseña", self.new_password)
        form.addRow("Teléfono (opcional)", self.new_phone)
        create_button = QPushButton("Crear clínica")
        create_button.clicked.connect(self._create_clinic)
        form.addRow(create_button)
        root.addWidget(self.create_box)

    def refresh_on_show(self) -> None:
        self._reload()

    def _client(self) -> PortalClient | None:
        settings = self.store.load_settings()
        if not settings.is_configured():
            return None
        return PortalClient(settings.base_url, settings.shared_secret)

    def _show_credentials(self, *, name: str, email: str, password: str) -> None:
        site_url = self.store.load_settings().base_url.strip()
        CredentialsDialog(
            name=name, site_url=site_url, email=email, password=password, parent=self
        ).exec()

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.table.setEnabled(enabled)
        self.toggle_button.setEnabled(enabled)
        self.reset_button.setEnabled(enabled)
        self.create_box.setEnabled(enabled)

    def _reload(self) -> None:
        client = self._client()
        if client is None:
            self.table.setRowCount(0)
            self._clinics = []
            self._set_controls_enabled(False)
            self.status_label.setText(
                "Configura la conexión del portal (en la página PORTAL) para administrar clínicas."
            )
            return
        try:
            self._clinics = client.list_clinics()
            self._client_choices = [
                (str(record.id), record.name)
                for record in self._providers.list_clients(status_filter="active")
            ]
        except Exception as exc:  # noqa: BLE001
            self._set_controls_enabled(False)
            self.status_label.setText(f"No se pudieron cargar las clínicas: {exc}")
            return
        self._set_controls_enabled(True)
        self.status_label.setText("")
        self.table.setRowCount(len(self._clinics))
        for row, clinic in enumerate(self._clinics):
            clinic_id = clinic.get("id")
            active = bool(clinic.get("is_active", 1))
            self.table.setItem(row, 0, QTableWidgetItem(str(clinic.get("name") or "")))
            self.table.setItem(row, 1, QTableWidgetItem(str(clinic.get("email") or "")))
            self.table.setItem(row, 2, QTableWidgetItem("Activa" if active else "Inactiva"))
            combo = QComboBox()
            # Fill the whole cell and drop the themed purple border/outline.
            combo.setStyleSheet(
                "QComboBox { border: none; outline: none; background: transparent; padding: 0 8px; }"
                "QComboBox:focus { border: none; outline: none; }"
                "QComboBox::drop-down { border: none; width: 22px; }"
            )
            combo.addItem("— sin vincular —", "")
            for value, label in self._client_choices:
                combo.addItem(label, value)
            combo.addItem("➕ Crear cliente nuevo…", "__new__")
            saved = self.store.lis_client_id_for(clinic_id)
            index = combo.findData(str(saved)) if saved is not None else 0
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.currentIndexChanged.connect(
                lambda _i, c=combo, cid=clinic_id: self._on_map_changed(c, cid)
            )
            self.table.setCellWidget(row, 3, combo)

    def _selected_clinic(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._clinics):
            QMessageBox.information(self, "Selecciona una clínica", "Elige una clínica de la lista.")
            return None
        return self._clinics[row]

    def _on_map_changed(self, combo: QComboBox, clinic_id: object) -> None:
        data = combo.currentData()
        if data == "__new__":
            from spdxlims.pages.clients_page import ServerClientDialog

            dialog = ServerClientDialog(self._providers, self)
            if dialog.exec() == QDialog.Accepted and dialog.client_id is not None:
                self.store.record_clinic_link(clinic_id, dialog.client_id)
            self._reload()  # rebuild with the new client list and saved selection
            return
        self.store.record_clinic_link(clinic_id, data or "")

    def _create_clinic(self) -> None:
        client = self._client()
        if client is None:
            return
        name = self.new_name.text().strip()
        email = self.new_email.text().strip()
        password = self.new_password.text()
        if not name or not email or not password:
            QMessageBox.warning(self, "Datos incompletos", "Nombre, correo y contraseña son obligatorios.")
            return
        if len(password) < 6:
            QMessageBox.warning(self, "Contraseña corta", "La contraseña debe tener al menos 6 caracteres.")
            return
        try:
            client.create_clinic(
                name=name, email=email, password=password, phone=self.new_phone.text().strip() or None
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error al crear", str(exc))
            return
        for field in (self.new_name, self.new_email, self.new_password, self.new_phone):
            field.clear()
        self._show_credentials(name=name, email=email, password=password)
        self._reload()

    def _reset_password(self) -> None:
        client = self._client()
        if client is None:
            return
        clinic = self._selected_clinic()
        if clinic is None:
            return
        new_password, ok = QInputDialog.getText(
            self,
            "Restablecer contraseña",
            f"Nueva contraseña para {clinic.get('name')}:",
            QLineEdit.Normal,
            "",
        )
        if not ok:
            return
        if len(new_password) < 6:
            QMessageBox.warning(self, "Contraseña corta", "La contraseña debe tener al menos 6 caracteres.")
            return
        try:
            client.update_clinic(int(clinic["id"]), password=new_password)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(exc))
            return
        self._show_credentials(
            name=str(clinic.get("name") or ""),
            email=str(clinic.get("email") or ""),
            password=new_password,
        )

    def _toggle_active(self) -> None:
        client = self._client()
        if client is None:
            return
        clinic = self._selected_clinic()
        if clinic is None:
            return
        new_state = 0 if bool(clinic.get("is_active", 1)) else 1
        try:
            client.update_clinic(int(clinic["id"]), is_active=new_state)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(exc))
            return
        self._reload()
