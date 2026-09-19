from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spdxlims.engine_client import EngineClient, EngineUnavailable
from spdxlims.engine_identity import owns_hardware
from spdxlims.i18n import tr
from spdxlims.instrument_broadcast import get_engine_url

_COLOR_GREEN = "#5ad08c"
_COLOR_ORANGE = "#f5a623"
_COLOR_RED = "#ff7b7b"
_COLOR_GRAY = "#888888"

_STATE_COLOR: dict[str, str] = {
    "active": _COLOR_GREEN,
    "connected": _COLOR_GREEN,
    "listening": _COLOR_ORANGE,
    "idle": _COLOR_GREEN,
    "retrying": _COLOR_ORANGE,
    "disconnected": _COLOR_RED,
    "error": _COLOR_RED,
    "stopped": _COLOR_GRAY,
}

_PROFILE_NAMES: dict[str, str] = {
    "cor50-lis": "COR 50",
    "mindray-bc30s": "Mindray BC-30s",
    "urinalysis-com6": "Urinalysis",
    "cm250": "CM250",
}

_CIRCLE = "●"
_CIRCLE_STYLE = "font-size: 22px; line-height: 1;"


class InstrumentStatusPanel(QGroupBox):
    AUTO_START_PROFILE_IDS = ("cor50-lis", "mindray-bc30s", "urinalysis-com6", "cm250")
    _health_result = Signal(object)
    _auto_start_done = Signal(object)
    _runtime_result = Signal(object)
    log_message = Signal(str)

    def __init__(self, deployment_service=None) -> None:
        super().__init__()
        self._health_result.connect(self._apply_health_result)
        self._auto_start_done.connect(self._finish_auto_start)
        self._runtime_result.connect(self._apply_runtime_status)
        # Needed so a workstation can read the engine through the backend; the
        # engine itself binds loopback and is unreachable from another machine.
        self.deployment_service = deployment_service
        self.engine_url = get_engine_url()
        self.health_url = self.engine_url + "/api/v1/health"
        self.engine_process: QProcess | None = None
        self._auto_start_requested = False

        self.setMinimumWidth(240)
        self.setMaximumWidth(290)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Engine row
        self._engine_circle = QLabel(_CIRCLE)
        self._engine_circle.setStyleSheet(f"color: {_COLOR_GRAY}; {_CIRCLE_STYLE}")
        self._engine_name = QLabel()
        self._engine_name.setStyleSheet("font-weight: bold;")
        self._engine_state = QLabel()
        self._engine_state.setStyleSheet(f"color: {_COLOR_GRAY}; font-size: 11px;")
        self._engine_state.setWordWrap(True)

        engine_top = QHBoxLayout()
        engine_top.addWidget(self._engine_circle)
        engine_top.addWidget(self._engine_name, 1)
        engine_widget = QWidget()
        engine_box = QVBoxLayout(engine_widget)
        engine_box.setContentsMargins(0, 0, 0, 0)
        engine_box.setSpacing(2)
        engine_box.addLayout(engine_top)
        engine_box.addWidget(self._engine_state)
        layout.addWidget(engine_widget)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # Per-instrument rows
        self._instrument_rows: dict[str, dict] = {}
        for profile_id in self.AUTO_START_PROFILE_IDS:
            display_name = _PROFILE_NAMES.get(profile_id, profile_id)

            circle = QLabel(_CIRCLE)
            circle.setStyleSheet(f"color: {_COLOR_GRAY}; {_CIRCLE_STYLE}")

            name_lbl = QLabel(display_name)
            name_lbl.setStyleSheet("font-weight: bold;")

            state_lbl = QLabel("—")
            state_lbl.setStyleSheet(f"color: {_COLOR_GRAY}; font-size: 11px;")

            reconnect_btn = QPushButton(tr("Reconnect"))
            reconnect_btn.setVisible(False)
            reconnect_btn.clicked.connect(
                lambda _checked=False, pid=profile_id: self._reconnect_profile(pid)
            )

            top_row = QHBoxLayout()
            top_row.addWidget(circle)
            top_row.addWidget(name_lbl, 1)

            row_widget = QWidget()
            row_box = QVBoxLayout(row_widget)
            row_box.setContentsMargins(0, 0, 0, 0)
            row_box.setSpacing(2)
            row_box.addLayout(top_row)
            row_box.addWidget(state_lbl)
            row_box.addWidget(reconnect_btn)
            layout.addWidget(row_widget)

            self._instrument_rows[profile_id] = {
                "circle": circle,
                "state_lbl": state_lbl,
                "reconnect_btn": reconnect_btn,
            }

        layout.addStretch(1)

        # Engine controls
        controls_line = QFrame()
        controls_line.setFrameShape(QFrame.Shape.HLine)
        controls_line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(controls_line)

        self.start_button = QPushButton()
        self.stop_button = QPushButton()
        self.refresh_button = QPushButton()
        self.browser_button = QPushButton()
        self.start_button.clicked.connect(self.start_engine)
        self.stop_button.clicked.connect(self.stop_engine)
        self.refresh_button.clicked.connect(self.refresh_status)
        self.browser_button.clicked.connect(self.open_in_browser)
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.browser_button)

        self.endpoint_label = QLabel()
        self.endpoint_label.setStyleSheet(f"color: {_COLOR_GRAY}; font-size: 10px;")
        self.endpoint_label.setWordWrap(True)
        layout.addWidget(self.endpoint_label)

        self.health_timer = QTimer(self)
        self.health_timer.setInterval(5000)
        self.health_timer.timeout.connect(self.refresh_status)
        self.health_timer.start()

        self.retranslate_ui()
        self.refresh_status()

    # ── UI strings ───────────────────────────────────────────────────────

    def retranslate_ui(self) -> None:
        self.setTitle(tr("Connectivity Status"))
        self._engine_name.setText(tr("Engine"))
        self._engine_state.setText(tr("Checking…"))
        self.start_button.setText(tr("Start Engine"))
        self.stop_button.setText(tr("Stop Engine"))
        self.refresh_button.setText(tr("Refresh Status"))
        self.browser_button.setText(tr("Open In Browser"))
        self.endpoint_label.setText(self.engine_url)

    # ── Auto-start ───────────────────────────────────────────────────────

    def auto_start(self) -> None:
        if self._auto_start_requested:
            return
        self._auto_start_requested = True
        self._sync_runtime_profiles()
        threading.Thread(target=self._bg_auto_start, daemon=True).start()

    def _bg_auto_start(self) -> None:
        health = self._fetch_health()
        self._auto_start_done.emit(health)

    def _finish_auto_start(self, health: dict | None) -> None:
        self._kill_stale_dev_agents()
        if health is None:
            if not self._engine_service_installed():
                self.start_engine(silent=True, start_default_profiles=True)
            QTimer.singleShot(1500, self._ensure_default_profile_sessions)
        else:
            self._ensure_default_profile_sessions()

    def _engine_service_installed(self) -> bool:
        try:
            result = subprocess.run(
                ["sc", "query", "InstrumentConnectivityEngine"],
                capture_output=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return result.returncode == 0
        except Exception:
            return False

    # ── Hardware ownership ───────────────────────────────────────────────

    def _owns_hardware(self) -> bool:
        """True when this checkout is the one allowed to open the analyzers."""
        return owns_hardware(self._runtime_dir())

    def _kill_stale_dev_agents(self) -> None:
        # Kill any agent.exe processes left behind by `go run` in temp build dirs.
        # These outlive the terminal they were launched from and aren't visible by
        # name in Task Manager, but they hold ports and database connections.
        try:
            ps_cmd = (
                "Get-CimInstance Win32_Process "
                "| Where-Object { $_.Name -eq 'agent.exe' -and $_.ExecutablePath -like '*Temp*go-build*' } "
                "| ForEach-Object { $id = $_.ProcessId; Stop-Process -Id $id -Force -ErrorAction SilentlyContinue; $id }"
            )
            result = subprocess.run(
                ["powershell", "-NonInteractive", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            killed = [p.strip() for p in result.stdout.splitlines() if p.strip()]
            if killed:
                self.log_message.emit(f"Stopped stale Go dev agent(s): PID {', '.join(killed)}")
        except Exception:
            pass

    # ── Status refresh ───────────────────────────────────────────────────

    def refresh_status(self) -> None:
        self._sync_runtime_profiles()
        threading.Thread(target=self._bg_check_health, daemon=True).start()

    def _bg_check_health(self) -> None:
        self._health_result.emit(self._fetch_health())

    def _apply_health_result(self, payload: dict | None) -> None:
        online = payload is not None
        if online:
            self._engine_circle.setStyleSheet(f"color: {_COLOR_GREEN}; {_CIRCLE_STYLE}")
            self._engine_state.setText(tr("Online"))
            if isinstance(payload, dict):
                auth_note = tr("API token configured.") if payload.get("auth_configured") else tr("No API token.")
                self.log_message.emit(f"[{payload.get('time', '')}] {auth_note}")
            threading.Thread(target=self._bg_fetch_runtime, daemon=True).start()
        else:
            self._engine_circle.setStyleSheet(f"color: {_COLOR_RED}; {_CIRCLE_STYLE}")
            self._engine_state.setText(tr("Offline"))
            self._reset_instrument_indicators()

    def _bg_fetch_runtime(self) -> None:
        data = self._get_json("/api/v1/runtime/status")
        devices = data.get("devices") if isinstance(data, dict) else None
        self._runtime_result.emit(devices)

    @staticmethod
    def _states_by_profile(devices: list) -> dict[str, str]:
        """The live state per profile, ignoring rows that are not a live link.

        The engine keeps a device row for every source it has ever read and
        never expires them: re-parsing a stored capture adds a row of its own,
        with transport "replay", and its timestamp is the newest one there is.
        Taking the newest row therefore showed the COR 50 as connected while the
        analyzer was switched off, because a replay had touched it last.

        A row counts only when its transport is the one the session is actually
        configured with, and the newest of those wins. For a TCP listener that is
        either the live client connection or the listener row, which is where the
        engine records the disconnect when the client goes away.
        """
        best: dict[str, tuple[str, str]] = {}  # profile_id -> (state, updated_at)
        for device in devices:
            if not isinstance(device, dict):
                continue
            settings = device.get("selected_settings")
            configured = str((settings or {}).get("type") or "") if isinstance(settings, dict) else ""
            if configured and str(device.get("transport_type") or "") != configured:
                continue
            pid = str(device.get("profile_id") or "")
            state = str(device.get("session_state") or "unknown")
            updated_at = str(device.get("updated_at") or "")
            if pid not in best or updated_at > best[pid][1]:
                best[pid] = (state, updated_at)
        return {pid: state for pid, (state, _) in best.items()}

    def _apply_runtime_status(self, devices: list | None) -> None:
        if not isinstance(devices, list):
            return
        best = self._states_by_profile(devices)
        for profile_id, row in self._instrument_rows.items():
            state = best.get(profile_id, "unknown")
            color = _STATE_COLOR.get(state, _COLOR_GRAY)
            row["circle"].setStyleSheet(f"color: {color}; {_CIRCLE_STYLE}")
            row["state_lbl"].setText(state.replace("_", " ").capitalize())
            row["reconnect_btn"].setVisible(state in ("disconnected", "error", "stopped", "unknown"))

    def _reset_instrument_indicators(self) -> None:
        for row in self._instrument_rows.values():
            row["circle"].setStyleSheet(f"color: {_COLOR_GRAY}; {_CIRCLE_STYLE}")
            row["state_lbl"].setText(tr("Engine offline"))
            row["reconnect_btn"].setVisible(False)

    # ── Reconnect ────────────────────────────────────────────────────────

    def _reconnect_profile(self, profile_id: str) -> None:
        name = _PROFILE_NAMES.get(profile_id, profile_id)
        if not self._owns_hardware():
            QMessageBox.information(
                self,
                tr("Instrument Connectivity"),
                tr("The instrument engine service owns the analyzers. Reconnect {name} from the production install instead.", name=name),
            )
            return
        result = self._post_json("/api/v1/capture/start", {"profile_id": profile_id})
        if result and result.get("session_id"):
            self.log_message.emit(f"{tr('Started')} {name} ({result['session_id']})")
        else:
            self.log_message.emit(f"{tr('Could not start')} {name}")
        threading.Thread(target=self._bg_fetch_runtime, daemon=True).start()

    # ── Engine start / stop ──────────────────────────────────────────────

    def start_engine(self, *, silent: bool = False, start_default_profiles: bool = False) -> None:
        self._sync_runtime_profiles()
        if not self._owns_hardware():
            # Never race the service for its port. If the service is merely
            # stopped, an engine started here would bind 9088 and then block the
            # real service from coming back.
            msg = tr("The instrument engine service owns the analyzers. Start it from the production install.")
            if not silent:
                QMessageBox.information(self, tr("Instrument Connectivity"), msg)
            else:
                self.log_message.emit(msg)
            return
        if self.engine_process is not None and self.engine_process.state() != QProcess.NotRunning:
            if not silent:
                QMessageBox.information(self, tr("Instrument Connectivity"), tr("The local engine process is already running from this UI session."))
            if start_default_profiles:
                self._ensure_default_profile_sessions()
            return
        if self._fetch_health() is not None:
            if not silent:
                QMessageBox.information(self, tr("Instrument Connectivity"), tr("The instrument engine is already running."))
            if start_default_profiles:
                self._ensure_default_profile_sessions()
            return
        command = self._resolve_engine_command()
        if command is None:
            msg = tr("No instrument engine executable was found. Build the addon package or keep the instrument-connectivity source tree available.")
            if not silent:
                QMessageBox.warning(self, tr("Instrument Connectivity"), msg)
            else:
                self.log_message.emit(msg)
            return
        program, args, workdir = command
        process = QProcess(self)
        process.setProgram(program)
        process.setArguments(args)
        process.setWorkingDirectory(str(workdir))
        process.setProcessEnvironment(QProcessEnvironment.systemEnvironment())
        process.errorOccurred.connect(self._process_error)
        process.finished.connect(self._process_finished)
        process.start()
        if not process.waitForStarted(5000):
            msg = tr("The instrument engine could not be started from the host UI.")
            self.log_message.emit(f"{msg}: {process.errorString()}")
            if not silent:
                QMessageBox.critical(self, tr("Instrument Connectivity"), msg)
            process.deleteLater()
            return
        self.engine_process = process
        self.log_message.emit(f"$ {program} {' '.join(args)}")
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

    def _process_error(self, error) -> None:
        if self.engine_process is None:
            return
        self.log_message.emit(f"{tr('Engine process error')}: {error.name} {self.engine_process.errorString()}")

    def _process_finished(self) -> None:
        self.log_message.emit(tr("Instrument engine process exited."))
        self.refresh_status()

    # ── HTTP helpers ─────────────────────────────────────────────────────

    def _engine_client(self) -> EngineClient:
        return EngineClient(self.deployment_service, self.engine_url)

    def _fetch_health(self) -> dict | None:
        # On a workstation this is relayed by the backend: the engine binds
        # loopback, so a direct call could only ever report "disconnected".
        return self._engine_client().health()

    def _get_json(self, path: str) -> dict | list | None:
        client = self._engine_client()
        try:
            if path == "/api/v1/runtime/status":
                return client.runtime_status()
            return client._direct(path)
        except EngineUnavailable:
            return None

    def _post_json(self, path: str, payload: dict) -> dict | None:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.engine_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=4) as response:
                parsed = json.loads(response.read().decode("utf-8"))
                return parsed if isinstance(parsed, dict) else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self.log_message.emit(f"{tr('Engine request failed')}: {exc.code} {detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.log_message.emit(f"{tr('Engine request failed')}: {exc}")
        except json.JSONDecodeError as exc:
            self.log_message.emit(f"{tr('Could not parse engine response')}: {exc}")
        return None

    # ── Default profile sessions ─────────────────────────────────────────

    def _ensure_default_profile_sessions(self) -> None:
        status = self._get_json("/api/v1/runtime/status")
        if not isinstance(status, dict):
            return
        devices = status.get("devices")
        active_profiles: set[str] = set()
        if isinstance(devices, list):
            for device in devices:
                if not isinstance(device, dict):
                    continue
                pid = str(device.get("profile_id") or "")
                state = str(device.get("session_state") or "")
                if pid and state not in ("", "error", "stopped"):
                    active_profiles.add(pid)
        if not self._owns_hardware():
            self.log_message.emit(
                tr("The instrument engine service owns the analyzers. This checkout will not open them.")
            )
            self.refresh_status()
            return
        for profile_id in self.AUTO_START_PROFILE_IDS:
            if profile_id in active_profiles:
                continue
            result = self._post_json("/api/v1/capture/start", {"profile_id": profile_id})
            if result and result.get("session_id"):
                self.log_message.emit(f"{tr('Started instrument profile')}: {profile_id} ({result['session_id']})")
        self.refresh_status()

    # ── Engine process resolution ────────────────────────────────────────

    def _engine_listen_addr(self) -> str | None:
        cfg_path = self._runtime_dir() / "engine.json"
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            addr = (data.get("listen_addr") or "").strip()
            return addr or None
        except (OSError, json.JSONDecodeError):
            return None

    def _resolve_engine_command(self) -> tuple[str, list[str], Path] | None:
        root = self._app_root()
        runtime_dir = self._runtime_dir()
        source_root = root / "instrument-connectivity"
        go_executable = self._go_executable()
        listen_addr = self._engine_listen_addr()
        listen_args = ["-listen", listen_addr] if listen_addr else []
        # Session resume is driven by engine.db, not by the `enabled:` field in
        # the profile YAML, so an engine started here without this flag reopens
        # whatever was live when its DB was last written - taking the analyzers
        # away from the service that owns them.
        resume_args = [] if self._owns_hardware() else ["-no-auto-resume"]
        extra_args = listen_args + resume_args
        binary_in_runtime = runtime_dir / "instrument-agent.exe"
        all_candidates = ([binary_in_runtime] if binary_in_runtime.exists() else []) + self._engine_binary_candidates(root)
        for candidate in all_candidates:
            if candidate.exists():
                workdir = self._resolve_engine_workdir(candidate, source_root)
                return str(candidate), ["-data-dir", str(runtime_dir)] + extra_args, workdir
        if (source_root / "cmd" / "agent").exists() and go_executable:
            return go_executable, ["run", ".\\cmd\\agent", "-data-dir", str(runtime_dir)] + extra_args, source_root
        return None

    def _go_executable(self) -> str | None:
        path_go = shutil.which("go")
        if path_go:
            return path_go
        common = Path("C:/Program Files/Go/bin/go.exe")
        if common.exists():
            return str(common)
        return None

    def _sync_runtime_profiles(self) -> None:
        runtime_profiles = self._runtime_dir() / "profiles"
        source_profiles = self._profile_source_dir()
        if not source_profiles.exists():
            return
        runtime_profiles.mkdir(parents=True, exist_ok=True)
        for source in source_profiles.glob("*.yaml"):
            target = runtime_profiles / source.name
            try:
                if source.resolve() == target.resolve():
                    continue
                if not target.exists() or source.read_bytes() != target.read_bytes():
                    shutil.copy2(source, target)
            except OSError as exc:
                self.log_message.emit(f"{tr('Could not sync instrument profile')}: {source.name}: {exc}")

    def _resolve_engine_workdir(self, executable: Path, source_root: Path) -> Path:
        for candidate in [executable.parent, executable.parent.parent, source_root]:
            if (candidate / "web" / "index.html").exists():
                return candidate
        return executable.parent

    def _app_root(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parents[2]

    def _engine_binary_candidates(self, root: Path) -> list[Path]:
        env_path = os.environ.get("INSTRUMENT_ENGINE_EXE", "").strip()
        roots = [
            root,
            root / "instrument-connectivity",
            root / "instrument-connectivity" / "dist" / "instrument-connectivity-windows",
            root / "instrument-connectivity-windows",
            root.parent / "instrument-connectivity-windows",
            Path(getattr(sys, "_MEIPASS", root)),
        ]
        candidates: list[Path] = []
        if env_path:
            candidates.append(Path(env_path))
        for base in roots:
            candidates.extend([
                base / "bin" / "instrument-agent.exe",
                base / "instrument-agent.exe",
                base / "dist" / "build" / "instrument-agent.exe",
                base / "dist" / "instrument-connectivity-windows" / "bin" / "instrument-agent.exe",
            ])
        seen: set[Path] = set()
        deduped: list[Path] = []
        for c in candidates:
            r = c.expanduser()
            if r not in seen:
                deduped.append(r)
                seen.add(r)
        return deduped

    def _runtime_dir(self) -> Path:
        env_path = os.environ.get("INSTRUMENT_ENGINE_DATA_DIR", "").strip()
        if env_path:
            return Path(env_path).expanduser()
        root = self._app_root()
        package_runtime = root / "runtime-data"
        if package_runtime.exists():
            return package_runtime
        sibling_runtime = root.parent / "instrument-connectivity-windows" / "runtime-data"
        if sibling_runtime.exists():
            return sibling_runtime
        return root / "data" / "instrument-engine"

    def _profile_source_dir(self) -> Path:
        root = self._app_root()
        candidates = [
            root / "instrument-connectivity" / "profiles",
            root / "profiles",
            root / "instrument-connectivity-windows" / "profiles",
            root.parent / "instrument-connectivity-windows" / "profiles",
            Path(getattr(sys, "_MEIPASS", root)) / "profiles",
            self._runtime_dir() / "profiles",
        ]
        for candidate in candidates:
            if candidate.exists() and any(candidate.glob("*.yaml")):
                return candidate
        return candidates[0]
