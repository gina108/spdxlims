from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PySide6.QtWidgets import QWidget

from spdxlims.database import Database
from spdxlims.deployment import DeploymentService


class AddonError(RuntimeError):
    """Raised when an addon action cannot be completed."""


@dataclass(slots=True)
class AddonNavEntry:
    entry_id: str
    nav_label: str
    workspace: str


@dataclass(slots=True)
class AddonManifest:
    addon_id: str
    name: str
    version: str
    description: str
    nav_entries: list[AddonNavEntry]
    store_product_id: str
    store_offer_token: str
    optional_package_family_name: str
    optional_package_name: str


@dataclass(slots=True)
class StoreAddon:
    manifest: AddonManifest
    is_owned: bool
    is_installed: bool
    can_open_store: bool
    status_text: str
    message: str = ""


@dataclass(slots=True)
class LoadedAddonPage:
    manifest: AddonManifest
    page: QWidget


class AddonManager:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.state_path = data_dir / "addons" / "store_dev_state.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._catalog = self._build_catalog()
        self._page_factories = self._build_page_factories()

    def list_addons(self) -> list[StoreAddon]:
        dev_state = self._load_dev_state()
        addons: list[StoreAddon] = []
        for manifest in self._catalog:
            override = dev_state.get(manifest.addon_id, {})
            installed = self._resolve_installed_state(manifest, override)
            owned = self._resolve_owned_state(installed, override)
            status_text = self._status_text(owned=owned, installed=installed)
            message = self._status_message(manifest, owned=owned, installed=installed)
            addons.append(
                StoreAddon(
                    manifest=manifest,
                    is_owned=owned,
                    is_installed=installed,
                    can_open_store=bool(manifest.store_product_id),
                    status_text=status_text,
                    message=message,
                )
            )
        return addons

    def get_store_url(self, addon_id: str) -> str:
        manifest = self._get_manifest(addon_id)
        if not manifest.store_product_id:
            raise AddonError("This addon does not have a Microsoft Store product ID yet.")
        return f"ms-windows-store://pdp/?ProductId={manifest.store_product_id}"

    def load_pages(
        self,
        database: Database,
        deployment_service: DeploymentService,
    ) -> tuple[list[LoadedAddonPage], dict[str, str]]:
        pages: list[LoadedAddonPage] = []
        errors: dict[str, str] = {}
        available = {addon.manifest.addon_id: addon for addon in self.list_addons()}
        for addon_id, factory in self._page_factories.items():
            addon = available.get(addon_id)
            if addon is None:
                continue
            if not addon.is_installed:
                continue
            try:
                page = factory(database, deployment_service)
            except Exception as exc:  # noqa: BLE001
                errors[addon_id] = str(exc)
                continue
            pages.append(LoadedAddonPage(manifest=addon.manifest, page=page))
        return pages, errors

    def build_page(
        self,
        addon_id: str,
        database: Database,
        deployment_service: DeploymentService,
    ) -> QWidget:
        factory = self._page_factories.get(addon_id)
        if factory is None:
            raise AddonError(f"Addon '{addon_id}' does not expose an in-app page.")
        return factory(database, deployment_service)

    def _build_catalog(self) -> list[AddonManifest]:
        return [
            AddonManifest(
                addon_id="administrative_tools",
                name="Admin Suite",
                version="1.0.0",
                description="Administrative tools for prices, receipt printing, billing, invoicing, inventory, suppliers, stock movements, and Excel exports.",
                nav_entries=[
                    AddonNavEntry(
                        entry_id="admin",
                        nav_label="Admin",
                        workspace="administrative",
                    ),
                ],
                store_product_id="ADMIN_TOOLS_STORE_ID",
                store_offer_token="administrative_tools",
                optional_package_family_name="SPDXLIMS.AdministrativeTools_0000000000000",
                optional_package_name="SPDXLIMS.AdministrativeTools",
            ),
            AddonManifest(
                addon_id="equipment_manager",
                name="Equipment Manager",
                version="1.0.0",
                description="Instrument and equipment registration with maintenance tracking.",
                nav_entries=[
                    AddonNavEntry(
                        entry_id="equipment",
                        nav_label="Equipment",
                        workspace="administrative",
                    )
                ],
                store_product_id="EQUIPMENT_MANAGER_STORE_ID",
                store_offer_token="equipment_manager",
                optional_package_family_name="SPDXLIMS.EquipmentManager_0000000000000",
                optional_package_name="SPDXLIMS.EquipmentManager",
            ),
            AddonManifest(
                addon_id="pdf_table_extractor",
                name="PDF Table Extractor",
                version="1.0.0",
                description="Integrated PDF table extraction workflow adapted for LIMS use.",
                nav_entries=[
                    AddonNavEntry(
                        entry_id="pdf_table_extractor",
                        nav_label="PDF Tables",
                        workspace="data",
                    )
                ],
                store_product_id="PDF_TABLE_EXTRACTOR_STORE_ID",
                store_offer_token="pdf_table_extractor",
                optional_package_family_name="SPDXLIMS.PdfTableExtractor_0000000000000",
                optional_package_name="SPDXLIMS.PdfTableExtractor",
            ),
            AddonManifest(
                addon_id="facturas",
                name="Portal",
                version="1.0.0",
                description="Client web portal integration: pull clinic orders and publish result PDFs.",
                nav_entries=[
                    AddonNavEntry(
                        entry_id="facturas",
                        nav_label="Portal",
                        workspace="administrative",
                    )
                ],
                store_product_id="FACTURAS_STORE_ID",
                store_offer_token="facturas",
                optional_package_family_name="SPDXLIMS.Facturas_0000000000000",
                optional_package_name="SPDXLIMS.Facturas",
            ),
        ]

    def _build_page_factories(
        self,
    ) -> dict[str, Callable[[Database, DeploymentService], QWidget]]:
        from spdxlims.pages.admin_suite_page import AdminSuitePage
        from spdxlims.pages.equipment_page import EquipmentPage
        from spdxlims.pages.pdf_table_extractor_page import PdfTableExtractorPage
        from spdxlims.pages.portal_page import PortalPage

        return {
            "administrative_tools": lambda database, deployment: AdminSuitePage(database, deployment),
            "equipment_manager": lambda database, _deployment: EquipmentPage(database),
            "pdf_table_extractor": lambda _database, _deployment: PdfTableExtractorPage(
                self.data_dir / "addons" / "pdf_table_extractor"
            ),
            "facturas": lambda database, deployment: PortalPage(self.data_dir, database, deployment),
        }

    def _get_manifest(self, addon_id: str) -> AddonManifest:
        normalized = addon_id.strip().lower()
        for manifest in self._catalog:
            if manifest.addon_id == normalized:
                return manifest
        raise AddonError(f"Unknown addon '{addon_id}'.")

    def _resolve_installed_state(self, manifest: AddonManifest, override: dict[str, Any]) -> bool:
        if "installed" in override:
            return bool(override.get("installed"))
        return self._detect_optional_package(manifest)

    def _resolve_owned_state(self, installed: bool, override: dict[str, Any]) -> bool:
        if "owned" in override:
            return bool(override.get("owned"))
        return installed

    def _detect_optional_package(self, manifest: AddonManifest) -> bool:
        package_name = manifest.optional_package_name.strip()
        package_family_name = manifest.optional_package_family_name.strip()
        if not package_name and not package_family_name:
            return False
        script = [
            "$ErrorActionPreference='Stop'",
            "$packages = Get-AppxPackage -PackageTypeFilter Optional",
        ]
        if package_family_name and package_name:
            script.append(
                "$match = $packages | Where-Object { $_.PackageFamilyName -eq "
                f"'{package_family_name}' -or $_.Name -eq '{package_name}' }}"
            )
        elif package_family_name:
            script.append(
                "$match = $packages | Where-Object { $_.PackageFamilyName -eq "
                f"'{package_family_name}' }}"
            )
        else:
            script.append(
                "$match = $packages | Where-Object { $_.Name -eq "
                f"'{package_name}' }}"
            )
        script.append("if ($match) { 'installed' }")
        command = "; ".join(script)
        creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                creationflags=creation_flags,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return "installed" in result.stdout.lower()

    def _load_dev_state(self) -> dict[str, dict[str, Any]]:
        if not self.state_path.exists():
            return {}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        normalized: dict[str, dict[str, Any]] = {}
        for key, value in payload.items():
            if isinstance(key, str) and isinstance(value, dict):
                normalized[key.strip().lower()] = value
        return normalized

    @staticmethod
    def _status_text(*, owned: bool, installed: bool) -> str:
        if installed and owned:
            return "Installed"
        if owned:
            return "Owned"
        return "Store Purchase Required"

    @staticmethod
    def _status_message(manifest: AddonManifest, *, owned: bool, installed: bool) -> str:
        if installed:
            return f"{manifest.name} is installed and available in the app."
        if owned:
            return (
                f"{manifest.name} appears to be owned, but its optional package is not installed on this device yet."
            )
        return (
            f"{manifest.name} is sold through the Microsoft Store and becomes available after purchase and installation."
        )
