from __future__ import annotations

from spdxlims.database import Database
from spdxlims.deployment import DeploymentService
from spdxlims.pages.catalog_page import CatalogPage


class PanelsPage(CatalogPage):
    def __init__(self, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__(database, mode="panels", deployment_service=deployment_service)
