"""PORTAL page — pull pending client-portal orders into the LIS.

Talks to the order-collection app's shared-secret ``/lis/*`` API. Staff review
each pending order, map the portal's tests to LIS tests once (the choice is
remembered), and import it as a LIS patient + lab order.
"""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database
from spdxlims.deployment import DeploymentService
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.portal.client import PendingOrder, PortalClient, PortalError
from spdxlims.portal.import_service import PortalImportService
from spdxlims.portal.result_service import PortalResultService
from spdxlims.portal.settings import PortalSettings, PortalStore
from spdxlims.provider_service import ProviderService

_SEX_CHOICES = [("(sin especificar)", None), ("Femenino", "F"), ("Masculino", "M"), ("Otro", "O")]


class ImportOrderDialog(QDialog):
    """Confirm patient details and map portal tests -> LIS tests for one order."""

    def __init__(
        self,
        order: PendingOrder,
        import_service: PortalImportService,
        store: PortalStore,
        portal_test_labels: dict[int, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Importar pedido #{order.id}")
        self.setMinimumWidth(520)
        self._order = order
        self._service = import_service
        self._store = store
        self._panel_choices = import_service.list_panel_choices()
        saved_mapping = store.load_mapping()

        root = QVBoxLayout(self)

        # -- patient ------------------------------------------------------
        patient_box = QGroupBox("Paciente")
        form = QFormLayout(patient_box)
        first_name, last_name = import_service.split_name(order.patient_name)
        self.first_name = QLineEdit(first_name)
        self.last_name = QLineEdit(last_name)
        self.sex = QComboBox()
        for label, data in _SEX_CHOICES:
            self.sex.addItem(label, data)
        self._select_sex(import_service.gender_to_sex(order.patient_gender))
        self.phone = QLineEdit(order.patient_phone)
        form.addRow("Nombre", self.first_name)
        form.addRow("Apellidos", self.last_name)
        form.addRow("Sexo", self.sex)
        form.addRow("Teléfono", self.phone)
        root.addWidget(patient_box)

        # -- panel mapping ------------------------------------------------
        tests_box = QGroupBox("Exámenes del portal → paneles del LIS")
        tests_layout = QFormLayout(tests_box)
        self._test_combos: list[QComboBox] = []
        if not order.tests:
            tests_layout.addRow(QLabel("(el pedido no incluye exámenes)"))
        for portal_test_id in order.tests:
            combo = QComboBox()
            combo.addItem("— elegir panel —", "")
            for value, label in self._panel_choices:
                combo.addItem(label, value)
            preselect = saved_mapping.get(str(portal_test_id))
            if preselect is not None:
                index = combo.findData(preselect)
                if index >= 0:
                    combo.setCurrentIndex(index)
            combo.setProperty("portal_test_id", portal_test_id)
            self._test_combos.append(combo)
            label_text = portal_test_labels.get(portal_test_id, f"Examen #{portal_test_id}")
            tests_layout.addRow(label_text, combo)
        root.addWidget(tests_box)

        notes_box = QGroupBox("Notas")
        notes_layout = QVBoxLayout(notes_box)
        self.notes = QLineEdit(order.notes)
        notes_layout.addWidget(self.notes)
        root.addWidget(notes_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Importar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.result: ImportOutcome | None = None

    def _select_sex(self, sex: str | None) -> None:
        index = self.sex.findData(sex)
        self.sex.setCurrentIndex(index if index >= 0 else 0)

    def _on_accept(self) -> None:
        if not self.first_name.text().strip() or not self.last_name.text().strip():
            QMessageBox.warning(self, "Datos incompletos", "Nombre y apellidos son obligatorios.")
            return
        lis_panel_ids: list[str] = []
        mapping_additions: dict[str, str] = {}
        for combo in self._test_combos:
            value = combo.currentData()
            if not value:
                QMessageBox.warning(self, "Mapeo incompleto", "Asigna un panel del LIS a cada examen del portal.")
                return
            lis_panel_ids.append(str(value))
            mapping_additions[str(combo.property("portal_test_id"))] = str(value)
        if not lis_panel_ids:
            QMessageBox.warning(self, "Sin exámenes", "El pedido no tiene exámenes para importar.")
            return

        patient_payload = {
            "first_name": self.first_name.text().strip(),
            "last_name": self.last_name.text().strip(),
            "sex": self.sex.currentData(),
            "phone": self.phone.text().strip(),
        }
        if self._order.patient_age is not None:
            patient_payload["age_value"] = self._order.patient_age
            patient_payload["age_unit"] = "years"

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            outcome = self._service.import_order(
                self._order,
                patient_payload=patient_payload,
                lis_panel_ids=lis_panel_ids,
                notes=self.notes.text().strip(),
                lis_client_id=self._store.lis_client_id_for(self._order.clinic_id),
            )
        except Exception as exc:  # noqa: BLE001 - surface any import failure to the user
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Error al importar", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        self._store.update_mapping(mapping_additions)
        self.result = ImportOutcome(order_id=outcome.order_id, order_number=outcome.order_number)
        self.accept()


class ImportOutcome:
    __slots__ = ("order_id", "order_number")

    def __init__(self, order_id: str, order_number: str) -> None:
        self.order_id = order_id
        self.order_number = order_number


class ClinicsDialog(QDialog):
    """Create portal clinic logins and link each clinic to a LIS client."""

    def __init__(
        self,
        client: PortalClient | None,
        store: PortalStore,
        providers: ProviderService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Clínicas del portal")
        self.setMinimumSize(700, 480)
        self._client = client
        self._store = store
        self._providers = providers
        self._clinics: list[dict] = []
        self._client_choices: list[tuple[str, str]] = []

        root = QVBoxLayout(self)
        if client is None:
            root.addWidget(QLabel("Configura la conexión del portal para administrar clínicas."))
            close = QPushButton("Cerrar")
            close.clicked.connect(self.reject)
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(close)
            root.addLayout(row)
            return

        root.addWidget(
            QLabel(
                "Accesos de las clínicas al portal. Vincula cada clínica a un cliente del LIS para "
                "que sus pedidos importados queden registrados a nombre de ese cliente."
            )
        )

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

        create_box = QGroupBox("Crear acceso de clínica")
        form = QFormLayout(create_box)
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
        root.addWidget(create_box)

        close_row = QHBoxLayout()
        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.accept)
        close_row.addStretch(1)
        close_row.addWidget(close_button)
        root.addLayout(close_row)

        self._reload()

    def _reload(self) -> None:
        try:
            self._clinics = self._client.list_clinics()
            self._client_choices = [
                (str(record.id), record.name)
                for record in self._providers.list_clients(status_filter="active")
            ]
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudieron cargar las clínicas:\n{exc}")
            return
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
            saved = self._store.lis_client_id_for(clinic_id)
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
                self._store.record_clinic_link(clinic_id, dialog.client_id)
            self._reload()  # rebuild with the new client list and saved selection
            return
        self._store.record_clinic_link(clinic_id, data or "")

    def _create_clinic(self) -> None:
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
            self._client.create_clinic(
                name=name, email=email, password=password, phone=self.new_phone.text().strip() or None
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error al crear", str(exc))
            return
        for field in (self.new_name, self.new_email, self.new_password, self.new_phone):
            field.clear()
        QMessageBox.information(self, "Clínica creada", f"Se creó el acceso para {name}.")
        self._reload()

    def _reset_password(self) -> None:
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
            self._client.update_clinic(int(clinic["id"]), password=new_password)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(exc))
            return
        QMessageBox.information(self, "Listo", "La contraseña se actualizó.")

    def _toggle_active(self) -> None:
        clinic = self._selected_clinic()
        if clinic is None:
            return
        new_state = 0 if bool(clinic.get("is_active", 1)) else 1
        try:
            self._client.update_clinic(int(clinic["id"]), is_active=new_state)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", str(exc))
            return
        self._reload()


class PortalPage(DataAwarePage):
    # Emitted from the background poll worker with the fetch/import outcome so the
    # UI thread can update the table and labels (see _bg_poll / _apply_poll_result).
    _poll_result = Signal(object)

    def __init__(self, data_dir: Path, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__()
        self.store = PortalStore(data_dir)
        self.import_service = PortalImportService(database, deployment_service)
        self._results = PortalResultService(self.store)
        self._providers = ProviderService(database, deployment_service)
        self._pending: list[PendingOrder] = []
        self._portal_test_labels: dict[int, str] = {}

        root = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("PORTAL de clientes")
        title.setObjectName("SectionTitle")
        self.connection_label = QLabel()
        self.connection_label.setWordWrap(True)
        self.refresh_button = QPushButton("Actualizar")
        self.refresh_button.clicked.connect(self.refresh_on_show)
        self.open_button = QPushButton("Abrir en navegador")
        self.open_button.clicked.connect(self._open_in_browser)
        self.clinics_button = QPushButton("Clínicas")
        self.clinics_button.setToolTip("Crear accesos de clínicas y vincularlas a un cliente del LIS.")
        self.clinics_button.clicked.connect(self._open_clinics)
        header.addWidget(title)
        header.addWidget(self.connection_label, 1)
        header.addWidget(self.clinics_button)
        header.addWidget(self.open_button)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        root.addWidget(self._build_settings_box())

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Pedido", "Paciente", "Edad", "Sexo", "Exámenes", "Creado"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self._import_selected())
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.status_label = QLabel("")
        self.auto_import_check = QCheckBox("Importar automáticamente los pedidos ya mapeados")
        self.auto_import_check.setToolTip(
            "Importa sin intervención los pedidos cuyos exámenes ya están asociados a un panel del LIS.\n"
            "Los pedidos con exámenes sin mapear se dejan para revisión manual."
        )
        self.auto_import_check.toggled.connect(self._on_auto_import_toggled)
        self.import_button = QPushButton("Importar pedido seleccionado")
        self.import_button.clicked.connect(self._import_selected)
        actions.addWidget(self.status_label, 1)
        actions.addWidget(self.auto_import_check)
        actions.addWidget(self.import_button)
        root.addLayout(actions)

        # Background poll: runs whenever auto-import is enabled and the portal is
        # configured, even while this page is hidden. The network fetch + import
        # work happens on a worker thread (see _bg_poll) so it never freezes the
        # UI of whatever page the user is on. Each tick re-fetches pending orders
        # and imports any that are fully mapped.
        self._poll_busy = False
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._start_poll)
        self._poll_result.connect(self._apply_poll_result)

        self._load_settings_into_form()
        self._start_poll()

    # -- settings UI -------------------------------------------------------
    def _build_settings_box(self) -> QWidget:
        self.settings_box = QGroupBox("Conexión")
        self.settings_box.setCheckable(True)
        self.settings_box.setChecked(False)
        form = QFormLayout(self.settings_box)
        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("https://lab-orders.<subdominio>.workers.dev")
        self.secret_input = QLineEdit()
        self.secret_input.setEchoMode(QLineEdit.Password)
        self.interval_input = QSpinBox()
        self.interval_input.setRange(15, 3600)
        self.interval_input.setSuffix(" s")
        save_button = QPushButton("Guardar")
        save_button.clicked.connect(self._save_settings)
        test_button = QPushButton("Probar conexión")
        test_button.clicked.connect(self._test_connection)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(test_button)
        buttons.addWidget(save_button)
        form.addRow("URL base", self.base_url_input)
        form.addRow("Secreto compartido", self.secret_input)
        form.addRow("Intervalo de sondeo", self.interval_input)
        form.addRow(buttons)
        return self.settings_box

    def _load_settings_into_form(self) -> None:
        settings = self.store.load_settings()
        self.base_url_input.setText(settings.base_url)
        self.secret_input.setText(settings.shared_secret)
        self.interval_input.setValue(settings.poll_interval_seconds)
        self.auto_import_check.blockSignals(True)
        self.auto_import_check.setChecked(settings.auto_import)
        self.auto_import_check.blockSignals(False)
        if not settings.is_configured():
            self.settings_box.setChecked(True)
        self._sync_poll_timer()

    def _current_settings(self) -> PortalSettings:
        return PortalSettings(
            base_url=self.base_url_input.text().strip(),
            shared_secret=self.secret_input.text().strip(),
            poll_interval_seconds=int(self.interval_input.value()),
            auto_import=self.auto_import_check.isChecked(),
        )

    def _sync_poll_timer(self) -> None:
        """Keep the background poll running whenever auto-import is on and the
        portal is configured. The poll's network I/O runs on a worker thread (see
        _bg_poll), so it is safe to keep ticking while the user works on another
        page — newly placed portal orders import without switching back here."""
        settings = self.store.load_settings()
        if settings.auto_import and settings.is_configured():
            self._poll_timer.start(max(15, settings.poll_interval_seconds) * 1000)
        else:
            self._poll_timer.stop()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self._sync_poll_timer()

    def _on_auto_import_toggled(self, checked: bool) -> None:
        # Persist alongside the connection settings (don't lose URL/secret).
        self.store.save_settings(self._current_settings())
        self._sync_poll_timer()
        if checked:
            # Import anything already mapped right away instead of waiting a tick.
            self.refresh_on_show()

    def _save_settings(self) -> None:
        self.store.save_settings(self._current_settings())
        QMessageBox.information(self, "Guardado", "La configuración del portal se guardó.")
        self._sync_poll_timer()
        self.refresh_on_show()

    def _client(self) -> PortalClient | None:
        settings = self.store.load_settings()
        if not settings.is_configured():
            return None
        return PortalClient(settings.base_url, settings.shared_secret)

    def _open_in_browser(self) -> None:
        settings = self.store.load_settings()
        if not settings.base_url.strip():
            QMessageBox.information(self, "Sin URL", "Configura primero la URL base del portal.")
            return
        QDesktopServices.openUrl(QUrl(settings.base_url.strip()))

    def _open_clinics(self) -> None:
        dialog = ClinicsDialog(self._client(), self.store, self._providers, self)
        dialog.exec()

    # -- network actions ---------------------------------------------------
    def _test_connection(self) -> None:
        settings = self._current_settings()
        if not settings.is_configured():
            QMessageBox.warning(self, "Falta configuración", "Captura la URL base y el secreto compartido.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            health = PortalClient(settings.base_url, settings.shared_secret).health()
        except PortalError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Sin conexión", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(
            self,
            "Conexión correcta",
            f"Pedidos pendientes: {health.get('pending_count', 0)}\n"
            f"Última importación: {health.get('last_import_at') or 'nunca'}",
        )

    def refresh_on_show(self) -> None:
        client = self._client()
        if client is None:
            self.connection_label.setText("● sin configurar")
            self.connection_label.setStyleSheet("color: #7f8a98;")
            self.table.setRowCount(0)
            self.status_label.setText("Configura la conexión para ver pedidos pendientes.")
            self.import_button.setEnabled(False)
            return
        self._start_poll()

    def _start_poll(self) -> None:
        """Kick off a background poll if one isn't already in flight and the portal
        is configured. Safe to call from the UI thread (timer tick, page show,
        buttons). The actual fetch + auto-import happens off the UI thread."""
        if self._poll_busy:
            return
        settings = self.store.load_settings()
        if not settings.is_configured():
            return
        client = PortalClient(settings.base_url, settings.shared_secret)
        self._poll_busy = True
        threading.Thread(
            target=self._bg_poll, args=(client, settings.auto_import), daemon=True
        ).start()

    def _bg_poll(self, client: PortalClient, auto_import: bool) -> None:
        """Worker thread: fetch pending orders, auto-import the ready ones, and
        re-send any finalized reports. Never touches widgets directly — results
        are handed back to the UI thread via the _poll_result signal."""
        result: dict = {"ok": False}
        try:
            labels = self._load_portal_test_labels(client)
            pending = client.pending_orders()
            health = client.health()
        except Exception as exc:  # noqa: BLE001 - report any failure to the UI thread
            result["error"] = str(exc)
            self._poll_result.emit(result)
            return

        imported = 0
        failures = 0
        if auto_import:
            imported, failures = self._import_ready_orders(client, pending)
            if imported:
                try:
                    pending = client.pending_orders()
                except PortalError:
                    pass

        try:
            published = self._results.retry_pending()
        except Exception:  # noqa: BLE001 - retry again on the next poll
            published = 0

        result.update(
            ok=True,
            labels=labels,
            pending=pending,
            health=health,
            imported=imported,
            failures=failures,
            published=published,
        )
        self._poll_result.emit(result)

    def _import_ready_orders(
        self, client: PortalClient, pending: list[PendingOrder]
    ) -> tuple[int, int]:
        """Import, without prompting, every pending order whose portal tests are
        all already mapped to a LIS panel. Orders with any unmapped test (or no
        patient name) are left untouched for manual review in the dialog. Runs on
        the worker thread; the Database opens a fresh connection per call so this
        is safe off the UI thread."""
        mapping = self.store.load_mapping()
        ready = [
            order
            for order in pending
            if order.tests
            and order.patient_name.strip()
            and all(str(test_id) in mapping for test_id in order.tests)
        ]
        imported = 0
        failures = 0
        for order in ready:
            lis_panel_ids = [mapping[str(test_id)] for test_id in order.tests]
            try:
                outcome = self.import_service.import_order(
                    order,
                    patient_payload=self.import_service.build_patient_payload(order),
                    lis_panel_ids=lis_panel_ids,
                    notes=order.notes,
                    lis_client_id=self.store.lis_client_id_for(order.clinic_id),
                )
            except Exception:  # noqa: BLE001 - skip a bad order, keep going
                failures += 1
                continue
            # Remember the portal<->LIS link so the finalized report can be
            # published back to the portal later.
            self.store.record_import_link(outcome.order_id, order.id)
            try:
                client.mark_imported([order.id], {order.id: outcome.order_id})
            except PortalError:
                failures += 1  # created in LIS but not marked; will retry next poll
            imported += 1
        return imported, failures

    def _apply_poll_result(self, result: dict) -> None:
        """UI thread: apply a background poll's outcome to the table and labels."""
        self._poll_busy = False
        if not result.get("ok"):
            self.connection_label.setText("● sin conexión")
            self.connection_label.setStyleSheet("color: #e05260;")
            error = result.get("error")
            if error:
                self.status_label.setText(str(error))
            self.import_button.setEnabled(False)
            return

        self._portal_test_labels = result["labels"]
        self._pending = result["pending"]
        health = result["health"]
        self.connection_label.setText("● conectado")
        self.connection_label.setStyleSheet("color: #3ddc84;")
        self.import_button.setEnabled(True)
        self._populate_table()

        status = (
            f"Pendientes: {health.get('pending_count', 0)}   "
            f"Última importación: {health.get('last_import_at') or 'nunca'}"
        )
        imported = result.get("imported", 0)
        failures = result.get("failures", 0)
        if imported or failures:
            suffix = f"   Con problemas: {failures} (revisa manualmente)." if failures else ""
            status = f"Importados automáticamente: {imported}.{suffix}   " + status
        published = result.get("published", 0)
        if published:
            status += f"   Resultados enviados al portal: {published}."
        self.status_label.setText(status)

        if imported:
            # Refresh the page the user is actually on so the new order shows up.
            self.notify_data_changed()

    def _load_portal_test_labels(self, client: PortalClient) -> dict[int, str]:
        labels: dict[int, str] = {}
        for item in client.tests():
            try:
                test_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            name = str(item.get("name") or f"Examen #{test_id}")
            category = str(item.get("category") or "").strip()
            labels[test_id] = f"{name} ({category})" if category else name
        return labels

    def _populate_table(self) -> None:
        self.table.setRowCount(len(self._pending))
        for row, order in enumerate(self._pending):
            test_names = ", ".join(
                self._portal_test_labels.get(t, f"#{t}").split(" (")[0] for t in order.tests
            )
            values = [
                str(order.id),
                order.patient_name,
                "" if order.patient_age is None else str(order.patient_age),
                order.patient_gender,
                test_names,
                order.created_at,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.UserRole, row)
                self.table.setItem(row, col, item)

    def _import_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._pending):
            QMessageBox.information(self, "Selecciona un pedido", "Elige un pedido pendiente de la lista.")
            return
        order = self._pending[row]
        dialog = ImportOrderDialog(order, self.import_service, self.store, self._portal_test_labels, self)
        if dialog.exec() != QDialog.Accepted or dialog.result is None:
            return

        # Remember the portal<->LIS link so the finalized report can be published
        # back to the portal later.
        self.store.record_import_link(dialog.result.order_id, order.id)
        client = self._client()
        try:
            if client is not None:
                client.mark_imported([order.id], {order.id: dialog.result.order_id})
        except PortalError as exc:
            QMessageBox.warning(
                self,
                "Importado, pero…",
                f"La orden {dialog.result.order_number} se creó en el LIS, pero no se pudo marcar como "
                f"importada en el portal:\n{exc}\nSe volverá a mostrar al actualizar.",
            )
        self.notify_data_changed()
        QMessageBox.information(
            self,
            "Pedido importado",
            f"Se creó la orden {dialog.result.order_number} en el LIS.",
        )
        self.refresh_on_show()
