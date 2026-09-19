from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from spdxlims.addons import AddonManager
from spdxlims.database import Database
from spdxlims.deployment import DeploymentService
from spdxlims.i18n import get_language, set_language, tr
from spdxlims.theme import turn_pixmap
from spdxlims.instance import app_instance
from spdxlims.pages.addons_page import AddonsPage
from spdxlims.pages.addon_placeholder_page import AddonPlaceholderPage
from spdxlims.pages.administrative_page import AdministrativePage
from spdxlims.pages.clients_page import ClientsPage
from spdxlims.pages.clinics_page import ClinicsPage
from spdxlims.pages.doctors_page import DoctorsPage
from spdxlims.pages.instrument_connectivity_page import InstrumentConnectivityPage
from spdxlims.pages.marketing_page import MarketingListPage
from spdxlims.pages.orders_browser_page import OrdersBrowserPage
from spdxlims.pages.orders_page import OrdersPage
from spdxlims.pages.panels_page import PanelsPage
from spdxlims.pages.patients_page import PatientsPage
from spdxlims.pages.portal_catalog_page import PortalCatalogPage
from spdxlims.pages.prices_page import PricesPage
from spdxlims.pages.results_page import InstrumentResultsPage, ResultsPage
from spdxlims.pages.reports_page import ReportsPage
from spdxlims.pages.settings_page import SettingsPage
from spdxlims.pages.statistics_page import StatisticsPage
from spdxlims.pages.tests_page import TestsPage


class MainWindow(QMainWindow):
    def __init__(
        self,
        database: Database,
        deployment_service: DeploymentService,
        addon_manager: AddonManager,
    ) -> None:
        super().__init__()
        self.database = database
        self.deployment_service = deployment_service
        self.addon_manager = addon_manager
        self._backend_fallback_process: subprocess.Popen | None = None
        self.current_workspace = "operations"
        self.visible_entries: list[tuple[str, str, str]] = []
        self.page_indices: dict[str, int] = {}
        self.page_scroll_areas: dict[str, QScrollArea] = {}
        self.workspace_buttons: dict[str, QPushButton] = {}
        self.stale_pages: set[str] = set()
        self.addon_page_keys: set[str] = set()
        self.page_builders: dict[str, callable] = {}
        self.current_page_key: str | None = None
        self.current_top_button = "operations"
        self.workspace_targets: dict[str, str | None] = {
            "operations": None,
            "data": None,
            "administrative": None,
            "equipment": None,
            "invoices": None,
            "pdf_tables": None,
        }

        splitter = QSplitter(Qt.Horizontal)
        self.splitter = splitter
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(0)

        sidebar = QWidget()
        sidebar.setObjectName("navSidebar")
        sidebar.setFixedWidth(268)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 22, 18, 18)
        sidebar_layout.setSpacing(16)

        self.logo_label = QLabel()
        self.logo_label.setObjectName("drawerLogo")
        self.logo_label.setAlignment(Qt.AlignCenter)
        self.logo_label.setFixedHeight(104)
        sidebar_layout.addWidget(self.logo_label)

        self.workspace_label = QLabel()
        self.workspace_label.setObjectName("workspaceLabel")
        self.workspace_label.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(self.workspace_label)

        selector_layout = QVBoxLayout()
        selector_layout.setSpacing(6)
        selector_top_row = QHBoxLayout()
        selector_top_row.setSpacing(6)
        selector_bottom_row = QHBoxLayout()
        selector_bottom_row.setSpacing(6)
        top_row_keys = ("operations", "data", "administrative")
        bottom_row_keys = ("equipment", "pdf_tables", "invoices")
        for workspace_key in top_row_keys + bottom_row_keys:
            button = QPushButton()
            button.setObjectName("workspaceSelector")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, key=workspace_key: self._activate_top_button(key))
            self.workspace_buttons[workspace_key] = button
            if workspace_key in top_row_keys:
                selector_top_row.addWidget(button)
            else:
                selector_bottom_row.addWidget(button)
        selector_layout.addLayout(selector_top_row)
        selector_layout.addLayout(selector_bottom_row)
        sidebar_layout.addLayout(selector_layout)

        self.nav = QListWidget()
        self.nav.setObjectName("navDrawer")
        self.nav.setSpacing(6)
        self.nav.setWordWrap(True)
        self.nav.setTextElideMode(Qt.ElideNone)
        sidebar_layout.addWidget(self.nav, 1)

        self.account_block = QFrame()
        self.account_block.setObjectName("accountBlock")
        account_layout = QVBoxLayout(self.account_block)
        account_layout.setContentsMargins(14, 12, 14, 12)
        account_layout.setSpacing(3)
        self.account_role_label = QLabel("OPS")
        self.account_role_label.setObjectName("accountRole")
        self.account_name_label = QLabel("Operaciones")
        self.account_name_label.setObjectName("accountName")
        account_layout.addWidget(self.account_role_label)
        account_layout.addWidget(self.account_name_label)
        sidebar_layout.addWidget(self.account_block)

        self.stack = QStackedWidget()
        self.stack.setContentsMargins(0, 0, 0, 0)

        page_specs = [
            ("patients", lambda: PatientsPage(database, deployment_service)),
            ("tests", lambda: TestsPage(database, deployment_service)),
            ("panels", lambda: PanelsPage(database, deployment_service)),
            ("instrument_connectivity", lambda: InstrumentConnectivityPage()),
            ("portal_catalog", lambda: PortalCatalogPage(addon_manager.data_dir, database, deployment_service)),
            ("portal_clinics", lambda: ClinicsPage(addon_manager.data_dir, database, deployment_service)),
            ("orders", lambda: OrdersPage(database, deployment_service)),
            ("orders_browser", lambda: OrdersBrowserPage(database, deployment_service)),
            ("instrument_results", lambda: InstrumentResultsPage(database, deployment_service)),
            ("results", lambda: ResultsPage(database, deployment_service, data_dir=addon_manager.data_dir)),
            ("doctors", lambda: DoctorsPage(database, deployment_service)),
            ("clients", lambda: ClientsPage(database, deployment_service)),
            ("statistics", lambda: StatisticsPage(database, deployment_service)),
            ("addons", lambda: AddonsPage(addon_manager)),
            ("settings", lambda: SettingsPage(database, deployment_service)),
            ("admin_prices", lambda: PricesPage(database, deployment_service)),
            ("admin_invoices", lambda: AdministrativePage(database, section_mode="collections", deployment_service=deployment_service)),
            ("admin_inventory", lambda: AdministrativePage(database, section_mode="inventory", deployment_service=deployment_service)),
            ("admin_reports", lambda: ReportsPage(database, deployment_service)),
            ("admin_marketing", lambda: MarketingListPage(database, deployment_service)),
        ]
        self.pages: dict[str, QWidget] = {}
        for page_key, builder in page_specs:
            self.page_builders[page_key] = builder
        self.nav_entries = [
            ("orders_ops", "orders", "New Order", ("operations",)),
            ("instrument_results", "instrument_results", "Instrument Results", ("operations",)),
            ("results", "results", "Results Review", ("operations",)),
            ("settings_ops", "settings", "Settings", ("operations",)),
            ("orders_data", "orders_browser", "Orders", ("data",)),
            ("tests", "tests", "Tests", ("data",)),
            ("panels", "panels", "Panels", ("data",)),
            ("doctors", "doctors", "Doctors", ("data",)),
            ("clients", "clients", "Clients", ("data",)),
            ("patients_data", "patients", "Patients", ("data",)),
            ("instrument_connectivity", "instrument_connectivity", "Instrument Connectivity", ("equipment",)),
            ("portal_catalog", "portal_catalog", "Catálogo del portal", ("invoices",)),
            ("portal_clinics", "portal_clinics", "Clínicas", ("invoices",)),
            ("statistics", "statistics", "Statistics", ("administrative",)),
        ]
        self.reload_addons(initial_load=True)

        self.nav.currentRowChanged.connect(self._change_page)
        self._rebuild_navigation(preferred_page_key="orders")

        splitter.addWidget(sidebar)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([268, 1400])

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(splitter)
        self.setCentralWidget(container)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._load_drawer_logo()
        # Pages retranslate themselves in their own __init__, so cascading into
        # them here would redo that work (and the data refreshes it triggers)
        # for every page already built.
        self.retranslate_ui(include_pages=False)
        self.refresh_deployment_status()
        QTimer.singleShot(200, self._try_auto_start_backend)
        QTimer.singleShot(300, self._try_auto_login)
        QTimer.singleShot(750, self._autostart_instrument_connectivity)
        QTimer.singleShot(900, self._autostart_portal_poll)

    def retranslate_ui(self, *, include_pages: bool = True) -> None:
        self.setWindowTitle(app_instance().display_name)
        self.workspace_label.setText(self._workspace_label_text())
        self.workspace_buttons["operations"].setText(self._workspace_button_text("operations"))
        self.workspace_buttons["data"].setText(self._workspace_button_text("data"))
        administrative_button = self.workspace_buttons.get("administrative")
        if administrative_button is not None:
            administrative_button.setText(self._workspace_button_text("administrative"))
        equipment_button = self.workspace_buttons.get("equipment")
        if equipment_button is not None:
            equipment_button.setText(self._workspace_button_text("equipment"))
        pdf_button = self.workspace_buttons.get("pdf_tables")
        if pdf_button is not None:
            pdf_button.setText(self._workspace_button_text("pdf_tables"))
        invoices_button = self.workspace_buttons.get("invoices")
        if invoices_button is not None:
            invoices_button.setText(self._workspace_button_text("invoices"))
        self._update_workspace_button_states()
        self._update_account_block()
        self._refresh_navigation_labels()
        if include_pages:
            for page in self.pages.values():
                retranslate = getattr(page, "retranslate_ui", None)
                if callable(retranslate):
                    retranslate()
        self.refresh_deployment_status()

    def apply_language(self, language_code: str) -> None:
        set_language(language_code)
        self.retranslate_ui()
        current_index = self.nav.currentRow()
        if current_index >= 0:
            self._change_page(current_index)

    def _change_page(self, index: int) -> None:
        if index < 0 or index >= len(self.visible_entries):
            return
        _entry_id, target_page_key, _label_key = self.visible_entries[index]
        self._show_page(target_page_key)

    def _show_page(self, target_page_key: str) -> None:
        loading_message: str | None = None
        if target_page_key == "instrument_connectivity" and target_page_key not in self.pages:
            loading_message = tr("Loading connectivity page...")
        if loading_message is not None:
            self.status.showMessage(loading_message)
            QApplication.setOverrideCursor(Qt.WaitCursor)
            QApplication.processEvents()
        try:
            self._ensure_page(target_page_key)
            self.current_page_key = target_page_key
            self.stack.setCurrentIndex(self.page_indices[target_page_key])
            page = self.pages[target_page_key]
            refresh = getattr(page, "refresh_on_show", None)
            if callable(refresh):
                refresh()
            self.stale_pages.discard(target_page_key)
            self._update_workspace_button_states()
        finally:
            if loading_message is not None:
                QApplication.restoreOverrideCursor()
                self.refresh_deployment_status()

    def refresh_all_pages(self, *, exclude: QWidget | None = None) -> None:
        for page_key, page in self.pages.items():
            if page is exclude:
                continue
            if page_key == self.current_page_key:
                refresh = getattr(page, "refresh_on_show", None)
                if callable(refresh):
                    refresh()
            else:
                self.stale_pages.add(page_key)

    def reload_addons(self, *, initial_load: bool = False) -> None:
        for page_key in list(self.addon_page_keys):
            scroll_area = self.page_scroll_areas.pop(page_key, None)
            if scroll_area is not None:
                self.stack.removeWidget(scroll_area)
                scroll_area.deleteLater()
            self.page_indices.pop(page_key, None)
            page = self.pages.pop(page_key, None)
            if page is not None:
                page.deleteLater()
            self.stale_pages.discard(page_key)
            self.page_builders.pop(page_key, None)
        self.addon_page_keys.clear()
        self.nav_entries = [
            entry for entry in self.nav_entries
            if not entry[0].startswith("addon:") and not entry[0].startswith("admin_")
        ]

        available_addons = {addon.manifest.addon_id: addon for addon in self.addon_manager.list_addons()}
        for addon_id, addon in available_addons.items():
            if addon_id == "administrative_tools":
                self.page_builders["admin_prices"] = lambda: PricesPage(self.database, self.deployment_service)
                self.page_builders["admin_invoices"] = lambda: AdministrativePage(self.database, section_mode="collections", deployment_service=self.deployment_service)
                self.page_builders["admin_inventory"] = lambda: AdministrativePage(self.database, section_mode="inventory", deployment_service=self.deployment_service)
                self.page_builders["admin_marketing"] = lambda: MarketingListPage(self.database, self.deployment_service)
                self.nav_entries.append(("admin_inventory", "admin_inventory", "Inventario", ("administrative",)))
                self.nav_entries.append(("admin_prices", "admin_prices", "Precios", ("administrative",)))
                self.nav_entries.append(("admin_invoices", "admin_invoices", "Cobranza de clientes", ("administrative",)))
                self.nav_entries.append(("admin_marketing", "admin_marketing", "Marketing List", ("administrative",)))
                continue
            page_key = f"addon:{addon_id}"
            if addon_id in {"equipment_manager", "pdf_table_extractor", "facturas"} or addon.is_installed:
                self.page_builders[page_key] = (
                    lambda current_addon_id=addon_id: self.addon_manager.build_page(
                        current_addon_id,
                        self.database,
                        self.deployment_service,
                    )
                )
            else:
                self.page_builders[page_key] = (
                    lambda current_addon=addon: AddonPlaceholderPage(self.addon_manager, current_addon)
                )
                self.addon_page_keys.add(page_key)
            for nav_entry in addon.manifest.nav_entries:
                workspace = nav_entry.workspace
                if addon.manifest.addon_id == "equipment_manager":
                    workspace = "equipment"
                elif addon.manifest.addon_id == "facturas":
                    workspace = "invoices"
                elif addon.manifest.addon_id == "pdf_table_extractor":
                    workspace = "pdf_tables"
                workspaces = (workspace,)
                self.nav_entries.append(
                    (
                        f"addon:{addon.manifest.addon_id}:{nav_entry.entry_id}",
                        page_key,
                        nav_entry.nav_label,
                        workspaces,
                    )
                )
        self.workspace_targets["administrative"] = self._find_nav_page_key("Statistics", "administrative")
        self.workspace_targets["equipment"] = self._find_nav_page_key("Equipment", "equipment")
        self.workspace_targets["invoices"] = self._find_nav_page_key("Portal", "invoices")
        self.workspace_targets["pdf_tables"] = self._find_nav_page_key("PDF Tables", "pdf_tables")

        addons_page = self.pages.get("addons")
        if isinstance(addons_page, AddonsPage):
            addons_page.set_runtime_errors({})
        if not initial_load:
            self._rebuild_navigation()

    def refresh_deployment_status(self) -> None:
        config = self.deployment_service.load()
        if config.mode == "server":
            session_label = self.deployment_service.session_label()
            if session_label:
                self.status.showMessage(tr("Server mode configured: {server_url} - {session}", server_url=config.server_url, session=session_label))
                self._update_workspace_button_states()
                return
            self.status.showMessage(tr("Server mode configured: {server_url} - login required", server_url=config.server_url))
            self._update_workspace_button_states()
            return
        self.status.showMessage(tr("Local mode enabled: the desktop app is still using the local SQLite database."))
        self._update_workspace_button_states()

    def _load_drawer_logo(self) -> None:
        logo_path = Path(__file__).resolve().parent.parent / "assets" / "SDXpurple.png"
        if not logo_path.exists():
            self.logo_label.clear()
            return
        pixmap = QPixmap(str(logo_path))
        if pixmap.isNull():
            self.logo_label.clear()
            return
        scaled = pixmap.scaled(190, 92, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        # The logo is a purple wordmark, so on an install wearing another accent
        # it is turned with the rest of the theme - a purple logo over blue
        # chrome is exactly the confusion the accent exists to prevent.
        self.logo_label.setPixmap(turn_pixmap(scaled))

    def _set_workspace(self, workspace_key: str, *, preferred_page_key: str | None = None) -> None:
        if workspace_key == self.current_workspace:
            if preferred_page_key is not None:
                self._rebuild_navigation(preferred_page_key=preferred_page_key)
            return
        self.current_workspace = workspace_key
        self.workspace_label.setText(self._workspace_label_text())
        self._update_account_block()
        self._update_workspace_button_states()
        self._rebuild_navigation(preferred_page_key=preferred_page_key)

    def _activate_top_button(self, button_key: str) -> None:
        if not self._can_open_workspace(button_key):
            self.status.showMessage(tr("Your current server role does not have access to that workspace."))
            return
        self.current_top_button = button_key
        self.workspace_label.setText(self._workspace_label_text())
        self._update_account_block()
        mapping = {
            "operations": ("operations", None),
            "data": ("data", None),
            "administrative": ("administrative", self.workspace_targets.get("administrative")),
            "equipment": ("equipment", self.workspace_targets.get("equipment")),
            "invoices": ("invoices", self.workspace_targets.get("invoices")),
            "pdf_tables": ("pdf_tables", self.workspace_targets.get("pdf_tables")),
        }
        workspace_key, preferred_page_key = mapping.get(button_key, ("operations", None))
        self._set_workspace(workspace_key, preferred_page_key=preferred_page_key)

    def _update_workspace_button_states(self) -> None:
        selected_page_key = self._current_page_key()
        for workspace_key, button in self.workspace_buttons.items():
            is_checked = False
            if workspace_key == "operations":
                is_checked = self.current_workspace == "operations"
            elif workspace_key == "data":
                is_checked = self.current_workspace == "data"
            elif workspace_key == "administrative":
                is_checked = self.current_workspace == "administrative"
            elif workspace_key == "equipment":
                is_checked = self.current_workspace == "equipment"
            elif workspace_key == "invoices":
                is_checked = self.current_workspace == "invoices"
            elif workspace_key == "pdf_tables":
                is_checked = self.current_workspace == "pdf_tables"
            button.setChecked(is_checked)
            button.setEnabled(self._can_open_workspace(workspace_key))

    def _can_open_workspace(self, workspace_key: str) -> bool:
        config = self.deployment_service.load()
        if config.mode != "server":
            return True
        if workspace_key in {"administrative", "invoices"}:
            return self.deployment_service.has_any_role("admin", "lab_manager")
        return True

    def _rebuild_navigation(self, *, preferred_page_key: str | None = None) -> None:
        current_page_key = self._current_page_key()
        if preferred_page_key is not None:
            current_page_key = preferred_page_key
        self.nav.blockSignals(True)
        self.nav.clear()
        self.visible_entries = []
        target_row: int | None = None
        for entry_id, target_page_key, label_key, workspaces in self.nav_entries:
            if self.current_workspace not in workspaces:
                continue
            item = QListWidgetItem(self._translate_nav_key(label_key), self.nav)
            item.setIcon(self._nav_icon(entry_id, target_page_key))
            item.setSizeHint(QSize(0, 58))
            item.setData(Qt.UserRole, entry_id)
            self.visible_entries.append((entry_id, target_page_key, label_key))
            if target_page_key == current_page_key:
                target_row = len(self.visible_entries) - 1
        self.nav.blockSignals(False)
        if not self.visible_entries:
            return
        self.nav.blockSignals(True)
        if target_row is None:
            self.nav.setCurrentRow(-1)
        else:
            self.nav.setCurrentRow(target_row)
        self.nav.blockSignals(False)
        if preferred_page_key is not None and target_row is None:
            self._show_page(preferred_page_key)
            return
        selected_row = target_row if target_row is not None else 0
        self._change_page(selected_row)

    def _refresh_navigation_labels(self) -> None:
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            if item is None or row >= len(self.visible_entries):
                continue
            _entry_id, _target_page_key, label_key = self.visible_entries[row]
            item.setText(self._translate_nav_key(label_key))

    def _translate_nav_key(self, key: str) -> str:
        labels = {
            "New Order": "Nueva Orden",
            "Instrument Results": "Resultados de Instrumentos",
            "Results Review": "Revisión de Resultados",
            "Settings": "Configuración",
        }
        if key in labels:
            return labels[key]
        label = tr(key)
        if get_language() == "es" and key == "Orders":
            return "Ordenes"
        return label

    def _nav_icon(self, entry_id: str, target_page_key: str) -> QIcon:
        icon_map = {
            "orders": "orders.svg",
            "instrument_results": "instrument_results.svg",
            "results": "results.svg",
            "settings": "settings.svg",
            "admin_prices": "admin_prices.svg",
            "admin_inventory": "admin_inventory.svg",
            "admin_reports": "admin_reports.svg",
            "admin_invoices": "admin_invoices.svg",
        }
        icon_dir = Path(__file__).resolve().parent.parent / "assets" / "icons"
        key = target_page_key if target_page_key in icon_map else entry_id
        svg_name = icon_map.get(key)
        if svg_name:
            icon_path = icon_dir / svg_name
            if icon_path.exists():
                return QIcon(str(icon_path))
        return self.style().standardIcon(QStyle.SP_FileIcon)

    def _current_page_key(self) -> str | None:
        return self.current_page_key

    def _workspace_label_text(self) -> str:
        if self.current_top_button == "operations":
            return tr("Operations Short").upper()
        if self.current_top_button == "data":
            return tr("Data Short").upper()
        if self.current_top_button == "equipment":
            return self._workspace_button_text("equipment")
        if self.current_top_button == "invoices":
            return self._workspace_button_text("invoices")
        if self.current_top_button == "pdf_tables":
            return self._workspace_button_text("pdf_tables")
        return tr("Administrative Short").upper()

    def _workspace_button_text(self, workspace_key: str) -> str:
        labels = {
            "operations": "Ops",
            "data": "Datos",
            "administrative": "Admin",
            "equipment": "Equipo",
            "invoices": "Portal",
            "pdf_tables": "PDF",
        }
        return labels[workspace_key]

    def _update_account_block(self) -> None:
        short = {
            "operations": "OPS",
            "data": "DATA",
            "administrative": "ADMIN",
            "equipment": "EQP",
            "invoices": "PRTL",
            "pdf_tables": "PDF",
        }
        full = {
            "operations": "Operaciones",
            "data": "Datos",
            "administrative": "Administrativo",
            "equipment": "Equipo",
            "invoices": "Portal",
            "pdf_tables": "PDF",
        }
        key = self.current_top_button
        self.account_role_label.setText(short.get(key, key.upper()))
        self.account_name_label.setText(full.get(key, key.title()))

    def _find_nav_page_key(self, label_key: str, workspace_key: str) -> str | None:
        for _entry_id, target_page_key, nav_label, workspaces in self.nav_entries:
            if workspace_key in workspaces and nav_label == label_key:
                return target_page_key
        return None

    def _make_scrollable(self, page_key: str, page: QWidget) -> QScrollArea:
        page_layout = page.layout()
        if page_layout is not None:
            page_layout.setContentsMargins(0, 0, 6, 6)
            page_layout.setSpacing(max(6, page_layout.spacing() - 2))
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setContentsMargins(0, 0, 0, 0)
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        scroll.setWidget(page)
        return scroll

    def _register_page(self, page_key: str, page: QWidget) -> None:
        self.pages[page_key] = page
        scroll_area = self._make_scrollable(page_key, page)
        self.page_scroll_areas[page_key] = scroll_area
        self.page_indices[page_key] = self.stack.addWidget(scroll_area)
        self.stale_pages.add(page_key)

    def _ensure_page(self, page_key: str) -> None:
        if page_key in self.pages:
            return
        builder = self.page_builders.get(page_key)
        if builder is None:
            return
        self._register_page(page_key, builder())

    def _try_auto_login(self) -> None:
        threading.Thread(target=self._bg_auto_login, daemon=True).start()

    def _bg_auto_login(self) -> None:
        ok = self.deployment_service.try_auto_login()
        if ok:
            QTimer.singleShot(0, self.refresh_deployment_status)

    def _is_backend_local(self) -> bool:
        config = self.deployment_service.load()
        if config.mode != "server":
            return False
        url = config.server_url.lower()
        return "127.0.0.1" in url or "localhost" in url

    def _try_auto_start_backend(self) -> None:
        if not self._is_backend_local():
            return
        threading.Thread(target=self._bg_auto_start_backend, daemon=True).start()

    def _bg_auto_start_backend(self) -> None:
        config = self.deployment_service.load()
        health = self.deployment_service.ping(config.server_url, timeout_seconds=1.5)
        if health.ok:
            return
        started_service = self._start_backend_windows_service()
        if not started_service:
            QTimer.singleShot(0, self._start_backend_fallback_process)
        for _ in range(12):
            time.sleep(1)
            health = self.deployment_service.ping(config.server_url, timeout_seconds=1.0)
            if health.ok:
                self._bg_auto_login()
                QTimer.singleShot(0, self.refresh_deployment_status)
                return

    def _start_backend_windows_service(self) -> bool:
        try:
            probe = subprocess.run(
                ["sc", "query", "SPDXLIMSBackend"],
                capture_output=True, timeout=5,
            )
            if probe.returncode != 0:
                return False
            subprocess.run(["sc", "start", "SPDXLIMSBackend"], capture_output=True, timeout=10)
            return True
        except Exception:
            return False

    def _start_backend_fallback_process(self) -> None:
        if self._backend_fallback_process is not None and self._backend_fallback_process.poll() is None:
            return
        backend_dir = self._find_backend_dir()
        if backend_dir is None:
            return
        import os
        env = os.environ.copy()
        env_file = backend_dir / ".env"
        if env_file.exists():
            for raw in env_file.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip()
        self._backend_fallback_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "0.0.0.0", "--port", "8001"],
            cwd=str(backend_dir),
            env=env,
        )

    def _find_backend_dir(self) -> Path | None:
        if getattr(sys, "frozen", False):
            root = Path(sys.executable).resolve().parent
        else:
            root = Path(__file__).resolve().parents[2]
        candidate = root / "backend"
        return candidate if (candidate / "app" / "main.py").exists() else None

    def closeEvent(self, event) -> None:
        # Stop every timer this window owns before anything is torn down. The
        # pages poll on timers - engine health, portal, auto-import - and a tick
        # that lands mid-teardown starts work against widgets that are going
        # away, which shows up as "python is not responding" on the way out.
        for timer in self.findChildren(QTimer):
            timer.stop()
        if self._backend_fallback_process is not None and self._backend_fallback_process.poll() is None:
            self._backend_fallback_process.terminate()
        super().closeEvent(event)

    def _autostart_instrument_connectivity(self) -> None:
        self._ensure_page("instrument_results")
        page = self.pages.get("instrument_results")
        auto_start = getattr(page, "auto_start", None)
        if callable(auto_start):
            auto_start()

    def _autostart_portal_poll(self) -> None:
        """Build the PORTAL page at launch so its background auto-import poll runs
        from startup, without the user having to open the page first. The poll only
        does network work when the portal is configured with auto-import enabled, so
        eagerly creating the page is cheap when the portal isn't set up."""
        if "addon:facturas" not in self.page_builders:
            return
        try:
            self._ensure_page("addon:facturas")
        except Exception:  # noqa: BLE001 - never let addon startup break the app
            pass

    def navigate_to_pdf_target(self, order_id: int, panel_label: str) -> None:
        self.current_top_button = "pdf_tables"
        self.workspace_label.setText(self._workspace_label_text())
        self._update_account_block()
        target_page_key = self.workspace_targets.get("pdf_tables")
        if target_page_key is None:
            self._update_workspace_button_states()
            return
        self._set_workspace("pdf_tables", preferred_page_key=target_page_key)
        self._show_page(target_page_key)
        page = self.pages.get(target_page_key)
        set_target_selection = getattr(page, "set_target_selection", None)
        if callable(set_target_selection):
            set_target_selection(int(order_id), str(panel_label))


