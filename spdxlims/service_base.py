from __future__ import annotations

from dataclasses import dataclass

from spdxlims.database import Database
from spdxlims.deployment import DeploymentService


@dataclass(slots=True)
class ServiceBase:
    database: Database
    deployment_service: DeploymentService

    def _is_local(self) -> bool:
        return self.deployment_service.load().mode != "server"

    def uses_server_backend(self) -> bool:
        return not self._is_local()
