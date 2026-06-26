from __future__ import annotations

import importlib
import json
import threading
import urllib.error
import urllib.request

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QVBoxLayout,
)

from spdxlims.i18n import tr
from spdxlims.instrument_broadcast import get_engine_url
from spdxlims.pages.base_page import DataAwarePage


class InstrumentConnectivityPage(DataAwarePage):
    _health_result = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._health_result.connect(self._apply_health_result)
        self.engine_url = get_engine_url()
        self.web_view = None
        self._web_view_class = None
        self._web_engine_checked = False
        self._web_view_ready = False
        self._web_loaded = False

        root = QVBoxLayout(self)

        self.viewer_group = QGroupBox()
        self.viewer_layout = QVBoxLayout(self.viewer_group)
        self.viewer_placeholder = QLabel()
        self.viewer_placeholder.setWordWrap(True)
        self.viewer_placeholder.setMinimumHeight(400)
        self.viewer_layout.addWidget(self.viewer_placeholder)
        root.addWidget(self.viewer_group, 1)

        self.health_timer = QTimer(self)
        self.health_timer.setInterval(5000)
        self.health_timer.timeout.connect(self._check_health)
        self.health_timer.start()

        self.retranslate_ui()
        QTimer.singleShot(0, self._ensure_web_view)

    # ── UI strings ───────────────────────────────────────────────────────

    def retranslate_ui(self) -> None:
        self.viewer_group.setTitle(tr("Instrument Connectivity Console"))
        if not self._web_view_ready:
            if self._get_web_view_class() is None:
                self.viewer_placeholder.setText(tr("Qt WebEngine is not available in this environment."))
            else:
                self.viewer_placeholder.setText(tr("Loading connectivity console…"))

    # ── Health check (for web view auto-load) ────────────────────────────

    def refresh_on_show(self) -> None:
        self._check_health()

    def _check_health(self) -> None:
        threading.Thread(target=self._bg_check_health, daemon=True).start()

    def _bg_check_health(self) -> None:
        self._health_result.emit(self._fetch_health())

    def _apply_health_result(self, payload: dict | None) -> None:
        if payload is not None:
            if self.web_view is not None and not self._web_loaded:
                self.web_view.setUrl(QUrl(self.engine_url))
                self._web_loaded = True
        else:
            if self.web_view is not None:
                self._web_loaded = False

    def _fetch_health(self) -> dict | None:
        try:
            with urllib.request.urlopen(self.engine_url + "/api/v1/health", timeout=1.5) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return None

    # ── Web view ─────────────────────────────────────────────────────────

    def _get_web_view_class(self):
        if self._web_engine_checked:
            return self._web_view_class
        self._web_engine_checked = True
        try:
            module = importlib.import_module("PySide6.QtWebEngineWidgets")
        except ImportError:
            self._web_view_class = None
            return None
        self._web_view_class = getattr(module, "QWebEngineView", None)
        return self._web_view_class

    def _ensure_web_view(self) -> None:
        web_view_class = self._get_web_view_class()
        if self._web_view_ready or web_view_class is None:
            return
        self.web_view = web_view_class()
        self.web_view.setMinimumHeight(400)
        self.web_view.loadStarted.connect(self._handle_web_load_started)
        self.web_view.loadFinished.connect(self._handle_web_load_finished)
        self.viewer_layout.removeWidget(self.viewer_placeholder)
        self.viewer_placeholder.hide()
        self.viewer_layout.addWidget(self.web_view)
        self._web_view_ready = True
        self._check_health()

    def _handle_web_load_started(self) -> None:
        self._web_loaded = False
        self.viewer_group.setTitle(tr("Instrument Connectivity Console Loading"))

    def _handle_web_load_finished(self, ok: bool) -> None:
        self._web_loaded = ok
        self.viewer_group.setTitle(tr("Instrument Connectivity Console"))
