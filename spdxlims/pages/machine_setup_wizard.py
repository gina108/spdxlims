from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database
from spdxlims.instrument_broadcast import get_engine_url

_ENGINE_URL = get_engine_url()

_PROTOCOL_LABELS: dict[str, str] = {
    "hl7_v2": "HL7 v2 (común en equipos modernos de red)",
    "astm": "ASTM E1394 (común en equipos seriales)",
    "csv": "CSV (archivo de texto separado por comas)",
    "line_text": "Texto de línea",
    "framed_text": "Texto enmarcado",
    "binary": "Binario propietario",
    "unknown": "Protocolo no identificado",
}

_STEP_TITLES = [
    "Bienvenida",
    "Tipo de conexión",
    "Prueba de conexión",
    "Asignar análisis",
    "Guardar equipo",
]


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "equipo"


def _engine_get(path: str, timeout: float = 3.0) -> Any:
    try:
        with urllib.request.urlopen(_ENGINE_URL + path, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _engine_post(path: str, payload: dict[str, Any], timeout: float = 5.0) -> Any:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _ENGINE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


class _SectionLabel(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setStyleSheet("color: #555; font-size: 13px; padding: 4px 0 10px 0;")


class MachineSetupWizard(QDialog):
    PAGE_WELCOME = 0
    PAGE_CONNECTION = 1
    PAGE_CAPTURE = 2
    PAGE_MAPPING = 3
    PAGE_FINISH = 4

    def __init__(self, database: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.setWindowTitle("Asistente para agregar equipo nuevo")
        self.setMinimumSize(660, 560)
        self.setModal(True)

        self._probe_profile_id: str = ""
        self._session_id: str = ""
        self._detected_protocol: str = ""
        self._detected_codes: list[dict[str, str]] = []
        self._poll_attempts = 0
        self._poll_max = 20
        self._connection_type = "serial"
        self._serial_port = ""
        self._network_address = ""
        self._watch_dir = "incoming"
        self._saved = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)

        self._title_label = QLabel()
        self._title_label.setStyleSheet(
            "font-size: 17px; font-weight: bold; color: #222; padding-bottom: 2px;"
        )
        self._step_label = QLabel()
        self._step_label.setStyleSheet("color: #999; font-size: 11px; padding-bottom: 10px;")

        root.addWidget(self._title_label)
        root.addWidget(self._step_label)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        btn_row = QHBoxLayout()
        self._cancel_btn = QPushButton("Cancelar")
        self._back_btn = QPushButton("← Anterior")
        self._next_btn = QPushButton("Siguiente →")
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._back_btn.clicked.connect(self._go_back)
        self._next_btn.clicked.connect(self._go_next)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._back_btn)
        btn_row.addWidget(self._next_btn)
        root.addLayout(btn_row)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(3000)
        self._poll_timer.timeout.connect(self._poll_capture)

        self._build_all_pages()
        self._go_to_page(self.PAGE_WELCOME)

    # ------------------------------------------------------------------
    # Page builders
    # ------------------------------------------------------------------

    def _build_all_pages(self) -> None:
        self._stack.addWidget(self._build_welcome_page())
        self._stack.addWidget(self._build_connection_page())
        self._stack.addWidget(self._build_capture_page())
        self._stack.addWidget(self._build_mapping_page())
        self._stack.addWidget(self._build_finish_page())

    def _build_welcome_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        intro = QLabel(
            "Este asistente le guiará para conectar su analizador al LIMS en unos pocos pasos.\n\n"
            "No necesita saber qué protocolo usa su equipo — el sistema lo detectará "
            "automáticamente cuando reciba los primeros datos.\n\n"
            "Antes de comenzar, asegúrese de que:\n"
            "  • El motor de conectividad esté en funcionamiento (página Conectividad)\n"
            "  • El equipo esté encendido y conectado a esta computadora"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("font-size: 13px; line-height: 1.6;")

        self._engine_status_label = QLabel()
        self._engine_status_label.setWordWrap(True)
        self._engine_status_label.setStyleSheet("font-size: 12px; padding: 8px; border-radius: 4px;")

        layout.addWidget(intro)
        layout.addSpacing(8)
        layout.addWidget(self._engine_status_label)
        layout.addStretch(1)
        return page

    def _build_connection_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        layout.addWidget(_SectionLabel(
            "¿Cómo está conectado su equipo a esta computadora?"
        ))

        self._radio_serial = QRadioButton("Cable serial o adaptador USB-Serial  (más común en equipos de laboratorio)")
        self._radio_network = QRadioButton("Cable de red o WiFi  (el equipo tiene dirección IP)")
        self._radio_filedrop = QRadioButton("Carpeta compartida  (el equipo escribe archivos en una carpeta)")
        self._radio_serial.setChecked(True)
        self._radio_serial.toggled.connect(self._update_connection_fields)
        self._radio_network.toggled.connect(self._update_connection_fields)
        self._radio_filedrop.toggled.connect(self._update_connection_fields)

        layout.addWidget(self._radio_serial)
        layout.addWidget(self._radio_network)
        layout.addWidget(self._radio_filedrop)
        layout.addSpacing(6)

        # Serial fields
        self._serial_group = QGroupBox("Configuración serial")
        serial_form = QFormLayout(self._serial_group)
        self._serial_port_combo = QComboBox()
        self._serial_port_combo.setEditable(True)
        self._serial_port_combo.setPlaceholderText("Ej. COM3")
        self._scan_serial_btn = QPushButton("Buscar puertos")
        self._scan_serial_btn.clicked.connect(self._scan_serial_ports)
        serial_btn_row = QHBoxLayout()
        serial_btn_row.addWidget(self._serial_port_combo, 1)
        serial_btn_row.addWidget(self._scan_serial_btn)
        serial_form.addRow("Puerto serial:", serial_btn_row)
        self._serial_hint = QLabel("Si no sabe cuál es el puerto, haga clic en 'Buscar puertos'.")
        self._serial_hint.setWordWrap(True)
        self._serial_hint.setStyleSheet("color: #777; font-size: 11px;")
        serial_form.addRow(self._serial_hint)
        layout.addWidget(self._serial_group)

        # Network fields
        self._network_group = QGroupBox("Configuración de red")
        net_form = QFormLayout(self._network_group)
        self._network_ip = QLineEdit()
        self._network_ip.setPlaceholderText("Ej. 192.168.1.50")
        self._network_port = QLineEdit()
        self._network_port.setPlaceholderText("Ej. 5000  (consulte el manual del equipo)")
        self._network_mode = QComboBox()
        self._network_mode.addItem("El equipo se conecta a este servidor (TCP Server)", "tcp_server")
        self._network_mode.addItem("Este servidor se conecta al equipo (TCP Client)", "tcp_client")
        net_form.addRow("IP del equipo:", self._network_ip)
        net_form.addRow("Puerto:", self._network_port)
        net_form.addRow("Modo:", self._network_mode)
        layout.addWidget(self._network_group)

        # File drop fields
        self._filedrop_group = QGroupBox("Carpeta de archivos")
        fd_form = QFormLayout(self._filedrop_group)
        self._filedrop_dir = QLineEdit("incoming")
        self._browse_dir_btn = QPushButton("Buscar carpeta...")
        self._browse_dir_btn.clicked.connect(self._browse_watch_dir)
        fd_btn_row = QHBoxLayout()
        fd_btn_row.addWidget(self._filedrop_dir, 1)
        fd_btn_row.addWidget(self._browse_dir_btn)
        fd_form.addRow("Carpeta:", fd_btn_row)
        layout.addWidget(self._filedrop_group)

        layout.addStretch(1)
        self._update_connection_fields()
        return page

    def _build_capture_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        self._capture_instruction = QLabel()
        self._capture_instruction.setWordWrap(True)
        self._capture_instruction.setStyleSheet("font-size: 13px;")

        self._capture_progress = QProgressBar()
        self._capture_progress.setRange(0, self._poll_max)
        self._capture_progress.setValue(0)
        self._capture_progress.setTextVisible(False)

        self._capture_status = QLabel("Iniciando...")
        self._capture_status.setWordWrap(True)
        self._capture_status.setStyleSheet("font-size: 13px; padding: 6px 0;")

        self._capture_result_group = QGroupBox("Resultado de la detección")
        result_layout = QVBoxLayout(self._capture_result_group)
        self._capture_protocol_label = QLabel()
        self._capture_protocol_label.setWordWrap(True)
        self._capture_protocol_label.setStyleSheet("font-size: 13px;")
        self._capture_codes_label = QLabel()
        self._capture_codes_label.setWordWrap(True)
        self._capture_codes_label.setStyleSheet("color: #555; font-size: 12px;")
        result_layout.addWidget(self._capture_protocol_label)
        result_layout.addWidget(self._capture_codes_label)
        self._capture_result_group.hide()

        self._skip_capture_btn = QPushButton("Continuar sin detección automática")
        self._skip_capture_btn.setStyleSheet("color: #777;")
        self._skip_capture_btn.clicked.connect(self._skip_capture)
        self._skip_capture_btn.hide()

        layout.addWidget(self._capture_instruction)
        layout.addSpacing(8)
        layout.addWidget(self._capture_progress)
        layout.addWidget(self._capture_status)
        layout.addWidget(self._capture_result_group)
        layout.addWidget(self._skip_capture_btn)
        layout.addStretch(1)
        return page

    def _build_mapping_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(_SectionLabel(
            "Asigne cada código de su equipo al análisis correspondiente en el LIMS.\n"
            "Puede dejar en blanco los que no use y agregar más después desde la página de Equipos."
        ))

        self._mapping_rows: list[dict[str, Any]] = []
        self._test_choices: list[tuple[int, str]] = []

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self._mapping_container = QWidget()
        self._mapping_layout = QVBoxLayout(self._mapping_container)
        self._mapping_layout.setSpacing(4)
        self._mapping_layout.addStretch(1)
        scroll.setWidget(self._mapping_container)
        layout.addWidget(scroll, 1)

        add_row_btn = QPushButton("+ Agregar código manualmente")
        add_row_btn.setStyleSheet("color: #555;")
        add_row_btn.clicked.connect(lambda: self._add_mapping_row("", "", ""))
        layout.addWidget(add_row_btn)
        return page

    def _build_finish_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        layout.addWidget(_SectionLabel(
            "Ya casi terminamos. Ingrese el nombre del equipo y guarde la configuración."
        ))

        form = QFormLayout()
        self._machine_name = QLineEdit()
        self._machine_name.setPlaceholderText("Ej. Mindray BC-30s, Uroanálisis COM3")
        form.addRow("Nombre del equipo:", self._machine_name)
        layout.addLayout(form)

        self._bidir_check = QCheckBox(
            "Este equipo puede recibir una lista de trabajo desde el LIMS\n"
            "(consulte el manual de su equipo si no está seguro)"
        )
        layout.addWidget(self._bidir_check)
        layout.addSpacing(8)

        self._save_btn = QPushButton("Guardar equipo")
        self._save_btn.setStyleSheet("font-weight: bold; padding: 6px 18px;")
        self._save_btn.clicked.connect(self._save_equipment)
        layout.addWidget(self._save_btn)

        self._save_status = QLabel()
        self._save_status.setWordWrap(True)
        self._save_status.setStyleSheet("font-size: 12px; padding: 6px 0;")
        layout.addWidget(self._save_status)

        self._export_btn = QPushButton("Descargar archivo de configuración...")
        self._export_btn.setEnabled(False)
        self._export_btn.setToolTip(
            "Guarda un archivo que puede importar en otro laboratorio con el mismo equipo"
        )
        self._export_btn.clicked.connect(self._export_bundle)
        layout.addWidget(self._export_btn)

        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _go_to_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._title_label.setText(_STEP_TITLES[index])
        total = len(_STEP_TITLES)
        self._step_label.setText(f"Paso {index + 1} de {total}")
        self._back_btn.setEnabled(index > 0)
        self._next_btn.setVisible(index < self.PAGE_FINISH)
        if index == self.PAGE_FINISH:
            self._next_btn.hide()
            self._cancel_btn.setText("Cerrar")
        else:
            self._next_btn.show()
            self._cancel_btn.setText("Cancelar")
        self._on_page_entered(index)

    def _go_next(self) -> None:
        current = self._stack.currentIndex()
        if not self._validate_page(current):
            return
        if current == self.PAGE_CONNECTION:
            self._collect_connection_settings()
            self._start_capture_probe()
        self._go_to_page(current + 1)

    def _go_back(self) -> None:
        current = self._stack.currentIndex()
        if current == self.PAGE_CAPTURE:
            self._stop_probe()
        self._go_to_page(current - 1)

    def _on_cancel(self) -> None:
        self._stop_probe()
        self.reject() if not self._saved else self.accept()

    def _on_page_entered(self, index: int) -> None:
        if index == self.PAGE_WELCOME:
            self._check_engine_status()
        elif index == self.PAGE_MAPPING:
            self._populate_mapping_page()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_page(self, index: int) -> bool:
        if index == self.PAGE_CONNECTION:
            if self._radio_network.isChecked():
                if not self._network_ip.text().strip():
                    QMessageBox.warning(self, "Datos incompletos", "Ingrese la dirección IP del equipo.")
                    return False
                if not self._network_port.text().strip():
                    QMessageBox.warning(self, "Datos incompletos", "Ingrese el puerto de conexión.")
                    return False
        return True

    # ------------------------------------------------------------------
    # Engine status check
    # ------------------------------------------------------------------

    def _check_engine_status(self) -> None:
        result = _engine_get("/api/v1/health")
        if result and isinstance(result, dict) and result.get("status") == "ok":
            self._engine_status_label.setText(
                "✓  El motor de conectividad está en funcionamiento."
            )
            self._engine_status_label.setStyleSheet(
                "font-size: 12px; padding: 8px; border-radius: 4px; "
                "background: #eafaf1; color: #1a7a44;"
            )
        else:
            self._engine_status_label.setText(
                "⚠  El motor de conectividad no está en funcionamiento.\n"
                "Puede continuar, pero la detección automática del protocolo no estará disponible.\n"
                "Inicie el motor desde la página Conectividad antes de continuar para mejores resultados."
            )
            self._engine_status_label.setStyleSheet(
                "font-size: 12px; padding: 8px; border-radius: 4px; "
                "background: #fff8e1; color: #7a5c00;"
            )

    # ------------------------------------------------------------------
    # Connection page helpers
    # ------------------------------------------------------------------

    def _update_connection_fields(self) -> None:
        is_serial = self._radio_serial.isChecked()
        is_network = self._radio_network.isChecked()
        is_filedrop = self._radio_filedrop.isChecked()
        self._serial_group.setVisible(is_serial)
        self._network_group.setVisible(is_network)
        self._filedrop_group.setVisible(is_filedrop)

    def _scan_serial_ports(self) -> None:
        self._scan_serial_btn.setEnabled(False)
        self._scan_serial_btn.setText("Buscando...")
        try:
            result = _engine_get("/api/v1/ports/scan?mode=quick", timeout=15)
        finally:
            self._scan_serial_btn.setEnabled(True)
            self._scan_serial_btn.setText("Buscar puertos")
        if not isinstance(result, dict):
            QMessageBox.warning(
                self, "Motor no disponible",
                "No se pudo conectar con el motor de conectividad.\n"
                "Asegúrese de que el motor esté en funcionamiento e intente de nuevo.\n\n"
                "También puede escribir el nombre del puerto directamente (Ej. COM3)."
            )
            return
        ports = result.get("ports") or []
        current = self._serial_port_combo.currentText()
        self._serial_port_combo.blockSignals(True)
        self._serial_port_combo.clear()
        found = 0
        for port in ports:
            if not isinstance(port, dict):
                continue
            name = str(port.get("port_name") or port.get("port_path") or "")
            product = str(port.get("product") or "")
            label = f"{name}  —  {product}" if product else name
            if name:
                self._serial_port_combo.addItem(label, name)
                found += 1
        self._serial_port_combo.blockSignals(False)
        if found == 0:
            self._serial_hint.setText(
                "No se encontraron puertos seriales. Verifique que el cable esté conectado "
                "e intente de nuevo, o escriba el nombre del puerto manualmente (Ej. COM3)."
            )
        else:
            self._serial_hint.setText(f"Se encontraron {found} puerto(s). Seleccione el de su equipo.")
            if current:
                idx = self._serial_port_combo.findText(current, Qt.MatchContains)
                if idx >= 0:
                    self._serial_port_combo.setCurrentIndex(idx)

    def _browse_watch_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de archivos")
        if folder:
            self._filedrop_dir.setText(folder)

    def _collect_connection_settings(self) -> None:
        if self._radio_serial.isChecked():
            self._connection_type = "serial"
            data = self._serial_port_combo.currentData()
            self._serial_port = data if isinstance(data, str) else self._serial_port_combo.currentText().split("—")[0].strip()
        elif self._radio_network.isChecked():
            mode = str(self._network_mode.currentData() or "tcp_server")
            self._connection_type = mode
            ip = self._network_ip.text().strip()
            port = self._network_port.text().strip()
            self._network_address = f"{ip}:{port}" if port else ip
        else:
            self._connection_type = "file_drop"
            self._watch_dir = self._filedrop_dir.text().strip() or "incoming"

    # ------------------------------------------------------------------
    # Capture / auto-detection
    # ------------------------------------------------------------------

    def _start_capture_probe(self) -> None:
        self._poll_attempts = 0
        self._detected_codes = []
        self._detected_protocol = ""
        self._capture_progress.setValue(0)
        self._capture_result_group.hide()
        self._skip_capture_btn.hide()

        if self._connection_type == "serial":
            port = self._serial_port or "COM1"
            desc = f"puerto serial {port}"
            self._capture_instruction.setText(
                f"Conectando al equipo en el {desc}.\n\n"
                "Asegúrese de que el equipo esté encendido. Si el equipo no envía datos "
                "automáticamente, intente correr una muestra de prueba."
            )
        elif self._connection_type in ("tcp_server", "tcp_client"):
            desc = f"red ({self._network_address})"
            self._capture_instruction.setText(
                f"Conectando al equipo en {desc}.\n\n"
                "Asegúrese de que el equipo esté encendido y en la misma red. "
                "Si el equipo no envía datos automáticamente, intente correr una muestra de prueba."
            )
        else:
            self._capture_instruction.setText(
                f"Monitoreando la carpeta: {self._watch_dir}\n\n"
                "Coloque un archivo de resultados en esa carpeta para que el sistema lo procese."
            )

        self._capture_status.setText("Creando perfil de prueba en el motor...")

        import time as _time
        ts = str(int(_time.time()))
        self._probe_profile_id = f"wizard-probe-{ts}"

        profile_payload = self._build_probe_profile()
        result = _engine_post("/api/v1/profiles", profile_payload)
        if result is None:
            self._capture_status.setText(
                "No se pudo conectar con el motor de conectividad.\n"
                "La detección automática no está disponible ahora mismo.\n"
                "Puede continuar e ingresar los códigos manualmente."
            )
            self._skip_capture_btn.show()
            return

        start_result = _engine_post("/api/v1/capture/start", {"profile_id": self._probe_profile_id})
        if isinstance(start_result, dict):
            self._session_id = str(start_result.get("session_id") or "")

        self._capture_status.setText("Esperando datos del equipo...")
        self._poll_timer.start()

    def _build_probe_profile(self) -> dict[str, Any]:
        transport: dict[str, Any] = {}
        if self._connection_type == "serial":
            transport = {
                "type": "serial",
                "session_mode": "astm",
                "serial_port": self._serial_port or "COM1",
                "baud_rate": 9600,
                "data_bits": 8,
                "parity": "N",
                "stop_bits": 1,
            }
        elif self._connection_type == "tcp_server":
            parts = self._network_address.split(":")
            port = parts[-1] if len(parts) > 1 else "5000"
            transport = {"type": "tcp_server", "listen_address": f"0.0.0.0:{port}"}
        elif self._connection_type == "tcp_client":
            transport = {"type": "tcp_client", "remote_address": self._network_address}
        else:
            watch = self._watch_dir or "incoming"
            transport = {"type": "file_drop", "watch_directories": [watch]}
        return {
            "id": self._probe_profile_id,
            "name": f"Sonda de asistente ({self._probe_profile_id})",
            "transport": transport,
            "parsing": {"strategy": "astm"},
            "mapping": {},
            "learning_mode": {"enabled": True},
        }

    def _poll_capture(self) -> None:
        self._poll_attempts += 1
        self._capture_progress.setValue(self._poll_attempts)

        captures = _engine_get(f"/api/v1/captures?profile_id={self._probe_profile_id}&limit=5")
        if isinstance(captures, list) and captures:
            self._poll_timer.stop()
            self._process_captures(captures)
            return

        remaining = self._poll_max - self._poll_attempts
        if remaining > 0:
            self._capture_status.setText(
                f"Esperando datos del equipo... ({remaining * 3} segundos restantes)\n"
                "Si el equipo no envía datos, intente correr una muestra de prueba."
            )
        else:
            self._poll_timer.stop()
            self._capture_status.setText(
                "No se recibieron datos del equipo en 60 segundos.\n\n"
                "Posibles causas:\n"
                "  • El cable no está bien conectado\n"
                "  • El equipo no está encendido\n"
                "  • El puerto o dirección IP no son correctos\n\n"
                "Puede continuar e ingresar los códigos de análisis manualmente."
            )
            self._skip_capture_btn.show()

    def _process_captures(self, captures: list[dict[str, Any]]) -> None:
        codes: dict[str, dict[str, str]] = {}
        protocol = ""
        for cap in captures:
            if not isinstance(cap, dict):
                continue
            cls = cap.get("classification") or {}
            if isinstance(cls, dict) and not protocol:
                protocol = str(cls.get("selected") or "")
            parsed_raw = cap.get("parsed_json") or ""
            if not parsed_raw:
                continue
            try:
                parsed = json.loads(parsed_raw) if isinstance(parsed_raw, str) else parsed_raw
            except (json.JSONDecodeError, TypeError):
                continue
            message = parsed.get("message") or {}
            if not isinstance(message, dict):
                continue
            for obs in message.get("observations") or []:
                if not isinstance(obs, dict):
                    continue
                code = str(obs.get("instrument_test_code") or "").strip()
                name = str(obs.get("instrument_test_name") or "").strip()
                unit = str(obs.get("units_raw") or obs.get("units_normalized") or "").strip()
                if code:
                    codes[code] = {"code": code, "name": name, "unit": unit}

        self._detected_protocol = protocol
        self._detected_codes = list(codes.values())

        proto_label = _PROTOCOL_LABELS.get(protocol, protocol or "Desconocido")
        self._capture_protocol_label.setText(
            f"<b>Protocolo detectado:</b> {proto_label}"
        )
        if self._detected_codes:
            code_list = ", ".join(c["code"] for c in self._detected_codes[:12])
            suffix = f" (+{len(self._detected_codes) - 12} más)" if len(self._detected_codes) > 12 else ""
            self._capture_codes_label.setText(
                f"<b>Códigos encontrados ({len(self._detected_codes)}):</b> {code_list}{suffix}"
            )
        else:
            self._capture_codes_label.setText(
                "Se recibieron datos pero no se encontraron códigos de análisis en este ciclo."
            )
        self._capture_result_group.show()
        self._capture_status.setText(
            "¡Conexión exitosa! Haga clic en 'Siguiente' para asignar los análisis."
        )
        self._capture_status.setStyleSheet(
            "font-size: 13px; padding: 6px 0; color: #1a7a44; font-weight: bold;"
        )

    def _skip_capture(self) -> None:
        self._poll_timer.stop()
        self._go_to_page(self.PAGE_MAPPING)

    def _stop_probe(self) -> None:
        self._poll_timer.stop()
        if self._session_id:
            _engine_post("/api/v1/capture/stop", {"session_id": self._session_id})
            self._session_id = ""

    # ------------------------------------------------------------------
    # Mapping page
    # ------------------------------------------------------------------

    def _populate_mapping_page(self) -> None:
        self._test_choices = self.database.list_test_choices()
        for row_widget in list(self._mapping_rows):
            self._mapping_layout.removeWidget(row_widget["widget"])
            row_widget["widget"].deleteLater()
        self._mapping_rows.clear()

        if self._detected_codes:
            for entry in self._detected_codes:
                self._add_mapping_row(entry["code"], entry["name"], entry.get("unit", ""))
        else:
            for _ in range(3):
                self._add_mapping_row("", "", "")

    def _add_mapping_row(self, code: str, name: str, unit: str) -> None:
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        code_edit = QLineEdit(code)
        code_edit.setPlaceholderText("Código")
        code_edit.setFixedWidth(90)
        code_edit.setReadOnly(bool(code))

        name_edit = QLineEdit(name)
        name_edit.setPlaceholderText("Nombre (opcional)")
        name_edit.setFixedWidth(130)

        test_combo = QComboBox()
        test_combo.setEditable(True)
        test_combo.setInsertPolicy(QComboBox.NoInsert)
        test_combo.addItem("— No asignar —", None)
        for test_id, label in self._test_choices:
            test_combo.addItem(label, test_id)
        test_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        unit_edit = QLineEdit(unit)
        unit_edit.setPlaceholderText("Unidad")
        unit_edit.setFixedWidth(80)

        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(26, 26)
        remove_btn.setStyleSheet("color: #cc4444; border: none;")

        row_layout.addWidget(code_edit)
        row_layout.addWidget(name_edit)
        row_layout.addWidget(test_combo, 1)
        row_layout.addWidget(unit_edit)
        row_layout.addWidget(remove_btn)

        row_data: dict[str, Any] = {
            "widget": row_widget,
            "code": code_edit,
            "name": name_edit,
            "test": test_combo,
            "unit": unit_edit,
        }
        self._mapping_rows.append(row_data)
        remove_btn.clicked.connect(lambda: self._remove_mapping_row(row_data))

        stretch_item = self._mapping_layout.takeAt(self._mapping_layout.count() - 1)
        self._mapping_layout.addWidget(row_widget)
        if stretch_item:
            self._mapping_layout.addItem(stretch_item)

    def _remove_mapping_row(self, row_data: dict[str, Any]) -> None:
        if row_data in self._mapping_rows:
            self._mapping_rows.remove(row_data)
        row_data["widget"].hide()
        self._mapping_layout.removeWidget(row_data["widget"])
        row_data["widget"].deleteLater()

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save_equipment(self) -> None:
        name = self._machine_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Nombre requerido", "Ingrese un nombre para el equipo.")
            return

        self._save_btn.setEnabled(False)
        self._save_btn.setText("Guardando...")
        try:
            self._do_save(name)
        finally:
            self._save_btn.setEnabled(True)
            self._save_btn.setText("Guardar equipo")

    def _do_save(self, name: str) -> None:
        profile_id = _slugify(name)

        equipment_payload = {
            "name": name,
            "equipment_type": "Analyzer",
            "manufacturer": "",
            "model": "",
            "serial_number": "",
            "location": self._connection_label(),
            "status": "active",
            "last_maintenance_date": "",
            "next_maintenance_date": "",
            "notes": self._build_notes(profile_id),
        }
        equipment_id = self.database.create_equipment(equipment_payload)

        mappings_saved = 0
        for row in self._mapping_rows:
            code = row["code"].text().strip()
            test_id = row["test"].currentData()
            if not code or test_id is None:
                continue
            try:
                self.database.save_instrument_result_mapping(
                    instrument_profile=profile_id,
                    device_id="" if self._connection_type == "tcp_server" else self._connection_label(),
                    raw_code=code,
                    raw_name=row["name"].text().strip(),
                    test_id=int(test_id),
                    unit_override=row["unit"].text().strip() or None,
                )
                mappings_saved += 1
            except Exception:
                pass

        if self._bidir_check.isChecked():
            # Use "astm" for serial/TCP ASTM analyzers; they get orders via the Go
            # engine's pending-orders store (Q record query response), not HL7 ORM.
            bidir_protocol = "astm" if self._connection_type in ("serial", "tcp_server", "tcp_client") else "hl7_orm"
            self.database.save_instrument_order_match(
                profile_id=profile_id,
                instrument_field="sample_id",
                order_field="order_number",
                auto_import=True,
                broadcast_enabled=True,
                broadcast_protocol=bidir_protocol,
                broadcast_encoding="ascii",
            )

        final_profile = self._build_final_profile(profile_id, name)
        _engine_post("/api/v1/profiles", final_profile)
        self._stop_probe()

        self._saved = True
        self._export_btn.setEnabled(True)
        self._save_btn.setEnabled(False)
        self._cancel_btn.setText("Cerrar")

        parts = [f"Equipo '{name}' guardado correctamente."]
        if mappings_saved:
            parts.append(f"{mappings_saved} asignación(es) de análisis guardadas.")
        if self._bidir_check.isChecked():
            parts.append("Configuración bidireccional habilitada.")
        self._save_status.setText("  ".join(parts))
        self._save_status.setStyleSheet(
            "font-size: 12px; padding: 6px 0; color: #1a7a44; font-weight: bold;"
        )

    def _connection_label(self) -> str:
        if self._connection_type == "serial":
            return self._serial_port or "serial"
        elif self._connection_type in ("tcp_server", "tcp_client"):
            return self._network_address
        else:
            return self._watch_dir or "incoming"

    def _build_notes(self, profile_id: str) -> str:
        lines = [f"Perfil de conectividad: {profile_id}"]
        if self._connection_type == "serial":
            lines.append(f"Conexión: puerto serial {self._serial_port or 'desconocido'}")
        elif self._connection_type in ("tcp_server", "tcp_client"):
            mode = "servidor TCP" if self._connection_type == "tcp_server" else "cliente TCP"
            lines.append(f"Conexión: {mode} — {self._network_address}")
        else:
            lines.append(f"Conexión: carpeta de archivos — {self._watch_dir}")
        if self._detected_protocol:
            proto = _PROTOCOL_LABELS.get(self._detected_protocol, self._detected_protocol)
            lines.append(f"Protocolo detectado: {proto}")
        return "\n".join(lines)

    def _build_final_profile(self, profile_id: str, name: str) -> dict[str, Any]:
        # ASTM session handling is needed when: serial, detected-as-astm, or bidirectional
        # ASTM over TCP (bidir implies the analyzer uses ASTM Q records regardless of
        # whether the probe step detected it).
        is_astm = (
            self._connection_type == "serial"
            or self._detected_protocol == "astm"
            or (
                self._bidir_check.isChecked()
                and self._connection_type in ("tcp_server", "tcp_client")
            )
        )

        transport: dict[str, Any]
        if self._connection_type == "serial":
            transport = {
                "type": "serial",
                "session_mode": "astm",
                "serial_port": self._serial_port or "COM1",
                "baud_rate": 9600,
                "data_bits": 8,
                "parity": "N",
                "stop_bits": 1,
            }
        elif self._connection_type == "tcp_server":
            parts = self._network_address.split(":")
            port = parts[-1] if len(parts) > 1 else "5000"
            transport = {"type": "tcp_server", "listen_address": f"0.0.0.0:{port}"}
            if is_astm:
                transport["session_mode"] = "astm"
        elif self._connection_type == "tcp_client":
            transport = {"type": "tcp_client", "remote_address": self._network_address}
            if is_astm:
                transport["session_mode"] = "astm"
        else:
            transport = {"type": "file_drop", "watch_directories": [self._watch_dir or "incoming"]}

        test_mappings = []
        for row in self._mapping_rows:
            code = row["code"].text().strip()
            if not code:
                continue
            test_mappings.append({
                "match_type": "exact",
                "pattern": code,
                "canonical_assay": row["name"].text().strip() or code,
                "lis_test_id": f"LIS-{code}",
                "normalized_units": row["unit"].text().strip() or "",
            })

        protocol_hint = self._detected_protocol or ("astm" if is_astm else "hl7_v2")
        return {
            "id": profile_id,
            "name": name,
            "protocol_hint": protocol_hint,
            "transport": transport,
            "parsing": {"strategy": "astm" if is_astm else "hl7_oru"},
            "mapping": {"test_mappings": test_mappings},
            "learning_mode": {"enabled": True},
        }

    # ------------------------------------------------------------------
    # Export bundle
    # ------------------------------------------------------------------

    def _export_bundle(self) -> None:
        result = _engine_get("/api/v1/migration-bundle/export", timeout=10)
        if not isinstance(result, dict):
            QMessageBox.warning(
                self, "Error al exportar",
                "No se pudo obtener el archivo de configuración del motor.\n"
                "Asegúrese de que el motor de conectividad esté en funcionamiento."
            )
            return
        machine_name = self._machine_name.text().strip()
        default_name = f"config-{_slugify(machine_name)}.json" if machine_name else "config-equipo.json"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar archivo de configuración",
            default_name,
            "JSON (*.json);;Todos los archivos (*)",
        )
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            QMessageBox.information(
                self, "Archivo guardado",
                f"Archivo de configuración guardado en:\n{path}\n\n"
                "Puede importar este archivo en otro laboratorio desde la consola de conectividad."
            )
        except OSError as exc:
            QMessageBox.critical(self, "Error al guardar", str(exc))
