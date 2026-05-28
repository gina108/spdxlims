from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QVBoxLayout

from spdxlims.addons import AddonError, AddonManager, StoreAddon
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage


class AddonPlaceholderPage(DataAwarePage):
    def __init__(self, addon_manager: AddonManager, addon: StoreAddon) -> None:
        super().__init__()
        self.addon_manager = addon_manager
        self.addon = addon

        root = QVBoxLayout(self)
        self.title_label = QLabel()
        self.title_label.setObjectName("SectionTitle")
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.open_store_button = QPushButton()
        self.open_store_button.clicked.connect(self._open_store)
        self.refresh_button = QPushButton()
        self.refresh_button.clicked.connect(self._refresh_runtime)
        root.addWidget(self.title_label)
        root.addWidget(self.status_label)
        root.addWidget(self.open_store_button)
        root.addWidget(self.refresh_button)
        root.addStretch(1)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self.title_label.setText(self.addon.manifest.name)
        self.status_label.setText(self.addon.message)
        self.open_store_button.setText(tr("Open in Microsoft Store"))
        self.refresh_button.setText(tr("Refresh Addon Status"))

    def _open_store(self) -> None:
        try:
            store_url = self.addon_manager.get_store_url(self.addon.manifest.addon_id)
        except AddonError as exc:
            QMessageBox.warning(self, tr("Addon Error"), str(exc))
            return
        if not QDesktopServices.openUrl(QUrl(store_url)):
            QMessageBox.warning(self, tr("Open Store Failed"), tr("The Microsoft Store listing could not be opened from this device."))

    def _refresh_runtime(self) -> None:
        reload_addons = getattr(self.window(), "reload_addons", None)
        if callable(reload_addons):
            reload_addons()
