from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout

from spdxlims.database import Database
from spdxlims.deployment import DeploymentService
from spdxlims.i18n import tr
from spdxlims.pages.administrative_page import AdministrativePage
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.pages.prices_page import PricesPage


class AdminSuitePage(DataAwarePage):
    def __init__(self, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__()
        self.prices_page = PricesPage(database, deployment_service)
        self.admin_page = AdministrativePage(database)

        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.prices_page, "")
        self.tabs.addTab(self.admin_page, "")
        root.addWidget(self.tabs)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        retranslate_prices = getattr(self.prices_page, "retranslate_ui", None)
        if callable(retranslate_prices):
            retranslate_prices()
        retranslate_admin = getattr(self.admin_page, "retranslate_ui", None)
        if callable(retranslate_admin):
            retranslate_admin()
        self.tabs.setTabText(0, tr("Prices"))
        self.tabs.setTabText(1, tr("Administrative Operations"))

    def refresh_on_show(self) -> None:
        refresh_prices = getattr(self.prices_page, "refresh_on_show", None)
        if callable(refresh_prices):
            refresh_prices()
        refresh_admin = getattr(self.admin_page, "refresh_on_show", None)
        if callable(refresh_admin):
            refresh_admin()
