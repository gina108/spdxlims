from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spdxlims.addons import AddonError, AddonManager, StoreAddon
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage


class AddonsPage(DataAwarePage):
    def __init__(self, addon_manager: AddonManager) -> None:
        super().__init__()
        self.addon_manager = addon_manager
        self.runtime_errors: dict[str, str] = {}

        root = QVBoxLayout(self)

        summary_group = QGroupBox()
        summary_layout = QVBoxLayout(summary_group)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_label)

        list_group = QGroupBox()
        list_layout = QVBoxLayout(list_group)
        self.list_help = QLabel()
        self.list_help.setWordWrap(True)
        list_layout.addWidget(self.list_help)

        self.addon_list = QListWidget()
        self.addon_list.currentItemChanged.connect(self._refresh_details)
        list_layout.addWidget(self.addon_list)

        self.details_label = QLabel()
        self.details_label.setWordWrap(True)
        self.details_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        list_layout.addWidget(self.details_label)

        actions_row = QWidget()
        actions_layout = QHBoxLayout(actions_row)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        self.open_store_button = QPushButton()
        self.open_store_button.clicked.connect(self._open_store_listing)
        self.reload_button = QPushButton()
        self.reload_button.clicked.connect(self._reload_runtime)
        actions_layout.addWidget(self.open_store_button)
        actions_layout.addWidget(self.reload_button)
        actions_layout.addStretch(1)
        list_layout.addWidget(actions_row)

        root.addWidget(summary_group)
        root.addWidget(list_group)
        root.addStretch(1)

        self.retranslate_ui()
        self.load_addons()

    def retranslate_ui(self) -> None:
        self.summary_label.setText(
            tr(
                "Sell optional workflows through the Microsoft Store. Addons become available in the app after the customer purchases and installs the matching Store package."
            )
        )
        self.list_help.setText(
            tr(
                "This page shows each Store addon, whether the optional package is installed on this device, and whether the app could load it."
            )
        )
        self.open_store_button.setText(tr("Open in Microsoft Store"))
        self.reload_button.setText(tr("Refresh Addons"))

    def refresh_on_show(self) -> None:
        # Opening the page is the user asking for current state, so this is the
        # one place that pays to re-query Windows for installed addons.
        self.addon_manager.invalidate_installed_cache()
        self.load_addons()

    def set_runtime_errors(self, errors: dict[str, str]) -> None:
        self.runtime_errors = dict(errors)
        self.load_addons()

    def load_addons(self) -> None:
        current_addon_id = self._selected_addon_id()
        addons = self.addon_manager.list_addons()
        self.addon_list.blockSignals(True)
        self.addon_list.clear()
        target_row = 0
        for index, addon in enumerate(addons):
            item = QListWidgetItem(
                f"{addon.manifest.name} ({addon.manifest.version}) - {addon.status_text}"
            )
            item.setData(Qt.UserRole, addon.manifest.addon_id)
            self.addon_list.addItem(item)
            if addon.manifest.addon_id == current_addon_id:
                target_row = index
        self.addon_list.blockSignals(False)
        if self.addon_list.count():
            self.addon_list.setCurrentRow(target_row)
        else:
            self.details_label.setText(tr("No Microsoft Store addons are configured yet."))
            self._refresh_action_state(None)

    def _reload_runtime(self) -> None:
        self.addon_manager.invalidate_installed_cache()
        reload_addons = getattr(self.window(), "reload_addons", None)
        if callable(reload_addons):
            reload_addons()
        self.load_addons()

    def _open_store_listing(self) -> None:
        addon = self._selected_addon()
        if addon is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select an addon first."))
            return
        try:
            store_url = self.addon_manager.get_store_url(addon.manifest.addon_id)
        except AddonError as exc:
            QMessageBox.warning(self, tr("Addon Error"), str(exc))
            return
        if not QDesktopServices.openUrl(QUrl(store_url)):
            QMessageBox.warning(
                self,
                tr("Open Store Failed"),
                tr("The Microsoft Store listing could not be opened from this device."),
            )

    def _selected_addon_id(self) -> str:
        item = self.addon_list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "").strip()

    def _selected_addon(self) -> StoreAddon | None:
        addon_id = self._selected_addon_id()
        for addon in self.addon_manager.list_addons():
            if addon.manifest.addon_id == addon_id:
                return addon
        return None

    def _refresh_details(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None = None,
    ) -> None:
        addon_id = str(current.data(Qt.UserRole) or "").strip() if current is not None else ""
        selected = None
        for addon in self.addon_manager.list_addons():
            if addon.manifest.addon_id == addon_id:
                selected = addon
                break
        if selected is None:
            self.details_label.setText(tr("Select an addon to review its details."))
            self._refresh_action_state(None)
            return
        runtime_error = self.runtime_errors.get(selected.manifest.addon_id)
        lines = [
            f"{tr('ID')}: {selected.manifest.addon_id}",
            f"{tr('Workspaces')}: {', '.join(entry.workspace for entry in selected.manifest.nav_entries)}",
            f"{tr('Navigation Labels')}: {', '.join(entry.nav_label for entry in selected.manifest.nav_entries)}",
            f"{tr('Store Product ID')}: {selected.manifest.store_product_id}",
            f"{tr('Delivery')}: {tr('Optional Package')}",
            f"{tr('Package Identity')}: {selected.manifest.optional_package_name or selected.manifest.optional_package_family_name}",
            f"{tr('Owned')}: {tr('Yes') if selected.is_owned else tr('No')}",
            f"{tr('Installed')}: {tr('Yes') if selected.is_installed else tr('No')}",
            selected.message,
        ]
        if selected.manifest.description:
            lines.insert(3, selected.manifest.description)
        if runtime_error:
            lines.append(f"{tr('Runtime Error')}: {runtime_error}")
        self.details_label.setText("\n".join(lines))
        self._refresh_action_state(selected)

    def _refresh_action_state(self, addon: StoreAddon | None) -> None:
        self.open_store_button.setEnabled(bool(addon and addon.can_open_store))
        self.reload_button.setEnabled(True)
