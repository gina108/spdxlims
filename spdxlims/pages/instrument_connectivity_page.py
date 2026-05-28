from __future__ import annotations

import importlib
import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage


class InstrumentConnectivityPage(DataAwarePage):
    AUTO_START_PROFILE_IDS = ("cor50-lis", "mindray-bc30s", "urinalysis-com6")

    def __init__(self) -> None:
        super().__init__()
        self.engine_url = "http://127.0.0.1:9088"
        self.health_url = self.engine_url + "/api/v1/health"
        self.engine_process: QProcess | None = None
        self.web_view = None
        self._web_view_class = None
        self._web_engine_checked = False
        self._web_view_ready = False
        self._web_loaded = False
        self._auto_start_requested = False

        root = QVBoxLayout(self)

        self.summary_group = QGroupBox()
        summary_layout = QVBoxLayout(self.summary_group)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.status_label = QLabel()
        self.endpoint_label = QLabel(self.engine_url)

        action_row = QHBoxLayout()
        self.start_button = QPushButton()
        self.stop_button = QPushButton()
        self.refresh_button = QPushButton()
        self.browser_button = QPushButton()
        self.start_button.clicked.connect(self.start_engine)
        self.stop_button.clicked.connect(self.stop_engine)
        self.refresh_button.clicked.connect(self.refresh_status)
        self.browser_button.clicked.connect(self.open_in_browser)
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.stop_button)
        action_row.addWidget(self.refresh_button)
        action_row.addWidget(self.browser_button)
        action_row.addStretch(1)

        summary_layout.addWidget(self.summary_label)
        summary_layout.addWidget(self.status_label)
        summary_layout.addWidget(self.endpoint_label)
        summary_layout.addLayout(action_row)

        self.log_group = QGroupBox()
        log_layout = QVBoxLayout(self.log_group)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(140)
        log_layout.addWidget(self.log_output)

        self.viewer_group = QGroupBox()
        self.viewer_layout = QVBoxLayout(self.viewer_group)
        self.viewer_placeholder = QLabel()
        self.viewer_placeholder.setWordWrap(True)
        self.viewer_placeholder.setMinimumHeight(480)
        self.viewer_layout.addWidget(self.viewer_placeholder)

        root.addWidget(self.summary_group)
        root.addWidget(self.log_group)
        root.addWidget(self.viewer_group, 1)

        self.health_timer = QTimer(self)
        self.health_timer.setInterval(5000)
        self.health_timer.timeout.connect(self.refresh_status)
        self.health_timer.start()

        self.retranslate_ui()
        self.refresh_status()
        QTimer.singleShot(0, self._ensure_web_view)

    def auto_start(self) -> None:
        if self._auto_start_requested:
            return
        self._auto_start_requested = True
        self._sync_runtime_profiles()
        if self._fetch_health() is None:
            self.start_engine(silent=True, start_default_profiles=True)
            QTimer.singleShot(1500, self._ensure_default_profile_sessions)
            return
        self._ensure_default_profile_sessions()

    def retranslate_ui(self) -> None:
        self.summary_group.setTitle(tr("Instrument Connectivity"))
        self.log_group.setTitle(tr("Engine Log"))
        self.viewer_group.setTitle(tr("Instrument Connectivity Console"))
        self.summary_label.setText(
            tr(
                "Use this page to monitor the local instrument connectivity engine, launch it for workstation use, and access the embedded diagnostics console."
            )
        )
        self.start_button.setText(tr("Start Engine"))
        self.stop_button.setText(tr("Stop Engine"))
        self.refresh_button.setText(tr("Refresh Status"))
        self.browser_button.setText(tr("Open In Browser"))
        self.endpoint_label.setText(f"{tr('Endpoint')}: {self.engine_url}")
        if not self._web_view_ready:
            if self._get_web_view_class() is None:
                self.viewer_placeholder.setText(tr("Qt WebEngine is not available in this environment."))
            else:
                self.viewer_placeholder.setText(tr("Loading connectivity console..."))
        self._update_status_label(False, tr("Checking engine status..."))

    def refresh_on_show(self) -> None:
        self.refresh_status()

    def refresh_status(self) -> None:
        self._sync_runtime_profiles()
        status_payload = self._fetch_health()
        if status_payload is None:
            self._update_status_label(False, tr("Engine is offline. Start the local engine or install the Windows service."))
            if self.web_view is not None:
                self._web_loaded = False
            if not self._web_view_ready and self._get_web_view_class() is not None:
                self.viewer_placeholder.setText(tr("Loading connectivity console..."))
            return

        self._update_status_label(True, tr("Engine is online and responding on localhost."))
        if self.web_view is not None and not self._web_loaded:
            self.web_view.setUrl(QUrl(self.engine_url))
            self._web_loaded = True
        elif not self._web_view_ready and self._get_web_view_class() is not None:
            self.viewer_placeholder.setText(tr("Loading connectivity console..."))
        if isinstance(status_payload, dict):
            auth_note = tr("API token configured.") if status_payload.get("auth_configured") else tr("API token not configured.")
            self.log_output.append(f"[{status_payload.get('time', '')}] {auth_note}")

    def start_engine(self, *, silent: bool = False, start_default_profiles: bool = False) -> None:
        self._sync_runtime_profiles()
        if self.engine_process is not None and self.engine_process.state() != QProcess.NotRunning:
            if not silent:
                QMessageBox.information(self, tr("Instrument Connectivity"), tr("The local engine process is already running from this UI session."))
            if start_default_profiles:
                self._ensure_default_profile_sessions()
            return

        command = self._resolve_engine_command()
        if command is None:
            if not silent:
                QMessageBox.warning(
                    self,
                    tr("Instrument Connectivity"),
                    tr("No instrument engine executable was found. Build the addon package or keep the instrument-connectivity source tree available."),
                )
            else:
                self.log_output.append(tr("No instrument engine executable was found."))
            return

        program, args, workdir = command
        process = QProcess(self)
        process.setProgram(program)
        process.setArguments(args)
        process.setWorkingDirectory(str(workdir))
        environment = QProcessEnvironment.systemEnvironment()
        process.setProcessEnvironment(environment)
        process.readyReadStandardOutput.connect(self._append_stdout)
        process.readyReadStandardError.connect(self._append_stderr)
        process.finished.connect(self._process_finished)
        process.start()
        if not process.waitForStarted(5000):
            if not silent:
                QMessageBox.critical(self, tr("Instrument Connectivity"), tr("The instrument engine could not be started from the host UI."))
            else:
                self.log_output.append(tr("The instrument engine could not be started from the host UI."))
            return
        self.engine_process = process
        self.log_output.append(f"$ {program} {' '.join(args)}")
        self.refresh_status()
        if start_default_profiles:
            QTimer.singleShot(1500, self._ensure_default_profile_sessions)

    def stop_engine(self) -> None:
        if self.engine_process is None or self.engine_process.state() == QProcess.NotRunning:
            QMessageBox.information(self, tr("Instrument Connectivity"), tr("No locally started engine process is running in this UI session."))
            return
        self.engine_process.terminate()
        if not self.engine_process.waitForFinished(5000):
            self.engine_process.kill()
            self.engine_process.waitForFinished(3000)
        self.refresh_status()

    def open_in_browser(self) -> None:
        QDesktopServices.openUrl(QUrl(self.engine_url))

    def _fetch_health(self) -> dict[str, object] | None:
        try:
            with urllib.request.urlopen(self.health_url, timeout=1.5) as response:
                raw = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _fetch_runtime_status(self) -> dict[str, object] | None:
        return self._get_json("/api/v1/runtime/status")

    def _get_json(self, path: str) -> dict[str, object] | list[object] | None:
        try:
            with urllib.request.urlopen(self.engine_url + path, timeout=2.5) as response:
                raw = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            self.log_output.append(f"{tr('Could not parse engine response')}: {exc}")
            return None

    def _post_json(self, path: str, payload: dict[str, object]) -> dict[str, object] | None:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.engine_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self.log_output.append(f"{tr('Engine request failed')}: {exc.code} {detail}")
            return None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.log_output.append(f"{tr('Engine request failed')}: {exc}")
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.log_output.append(f"{tr('Could not parse engine response')}: {exc}")
            return None
        return parsed if isinstance(parsed, dict) else None

    def _ensure_default_profile_sessions(self) -> None:
        status = self._fetch_runtime_status()
        if not isinstance(status, dict):
            return
        devices = status.get("devices")
        active_profiles: set[str] = set()
        if isinstance(devices, list):
            for device in devices:
                if not isinstance(device, dict):
                    continue
                profile_id = str(device.get("profile_id") or "")
                state = str(device.get("session_state") or "")
                if profile_id and state not in {"", "error", "stopped"}:
                    active_profiles.add(profile_id)
        for profile_id in self.AUTO_START_PROFILE_IDS:
            if profile_id in active_profiles:
                continue
            result = self._post_json("/api/v1/capture/start", {"profile_id": profile_id})
            if result and result.get("session_id"):
                self.log_output.append(f"{tr('Started instrument profile')}: {profile_id} ({result['session_id']})")
        self.refresh_status()

    def _resolve_engine_command(self) -> tuple[str, list[str], Path] | None:
        root = Path(__file__).resolve().parents[2]
        runtime_dir = root / "data" / "instrument-engine"
        source_root = root / "instrument-connectivity"
        candidates = [
            root / "instrument-connectivity" / "dist" / "build" / "instrument-agent.exe",
            root / "instrument-connectivity" / "bin" / "instrument-agent.exe",
            root / "instrument-connectivity" / "dist" / "instrument-connectivity-windows" / "bin" / "instrument-agent.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                workdir = self._resolve_engine_workdir(candidate, source_root)
                return str(candidate), ["-data-dir", str(runtime_dir)], workdir
        if (source_root / "cmd" / "agent").exists():
            return "go", ["run", ".\\cmd\\agent", "-data-dir", str(runtime_dir)], source_root
        return None

    def _sync_runtime_profiles(self) -> None:
        root = Path(__file__).resolve().parents[2]
        runtime_profiles = root / "data" / "instrument-engine" / "profiles"
        source_profiles = root / "instrument-connectivity" / "profiles"
        if not source_profiles.exists():
            return
        runtime_profiles.mkdir(parents=True, exist_ok=True)
        for source in source_profiles.glob("*.yaml"):
            target = runtime_profiles / source.name
            try:
                if not target.exists() or source.read_bytes() != target.read_bytes():
                    shutil.copy2(source, target)
            except OSError as exc:
                self.log_output.append(f"{tr('Could not sync instrument profile')}: {source.name}: {exc}")

    def _resolve_engine_workdir(self, executable: Path, source_root: Path) -> Path:
        possible_roots = [
            executable.parent,
            executable.parent.parent,
            source_root,
        ]
        for candidate in possible_roots:
            if (candidate / "web" / "index.html").exists():
                return candidate
        return executable.parent

    def _get_web_view_class(self):
        if self._web_engine_checked:
            return self._web_view_class
        self._web_engine_checked = True
        try:
            module = importlib.import_module("PySide6.QtWebEngineWidgets")
        except ImportError:  # pragma: no cover
            self._web_view_class = None
            return None
        self._web_view_class = getattr(module, "QWebEngineView", None)
        return self._web_view_class

    def _ensure_web_view(self) -> None:
        web_view_class = self._get_web_view_class()
        if self._web_view_ready or web_view_class is None:
            return
        self.web_view = web_view_class()
        self.web_view.setMinimumHeight(480)
        self.web_view.loadStarted.connect(self._handle_web_load_started)
        self.web_view.loadFinished.connect(self._handle_web_load_finished)
        self.viewer_layout.removeWidget(self.viewer_placeholder)
        self.viewer_placeholder.hide()
        self.viewer_layout.addWidget(self.web_view)
        self._web_view_ready = True
        self.refresh_status()

    def _handle_web_load_started(self) -> None:
        self._web_loaded = False
        self.viewer_group.setTitle(tr("Instrument Connectivity Console Loading"))

    def _handle_web_load_finished(self, ok: bool) -> None:
        self._web_loaded = ok
        self.viewer_group.setTitle(tr("Instrument Connectivity Console"))

    def _append_stdout(self) -> None:
        if self.engine_process is None:
            return
        text = bytes(self.engine_process.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
        if text:
            self.log_output.append(text)

    def _append_stderr(self) -> None:
        if self.engine_process is None:
            return
        text = bytes(self.engine_process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if text:
            self.log_output.append(text)

    def _process_finished(self) -> None:
        self.log_output.append(tr("Instrument engine process exited."))
        self.refresh_status()

    def _update_status_label(self, online: bool, message: str) -> None:
        state = tr("Online") if online else tr("Offline")
        color = "#5ad08c" if online else "#ff7b7b"
        self.status_label.setText(f"<b>{tr('Status')}:</b> <span style='color:{color}'>{state}</span>  {message}")
