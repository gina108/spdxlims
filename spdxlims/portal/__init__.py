"""Client web portal integration (laboratoriospdx-orders).

The LIS talks to the order-collection app ONLY through its shared-secret
``/lis/*`` API — there is no shared database. This package holds the HTTP
client, the on-disk settings/mapping store, and the import orchestration used
by the PORTAL page.
"""
from __future__ import annotations

from spdxlims.portal.client import PortalClient, PortalError
from spdxlims.portal.settings import PortalSettings, PortalStore

__all__ = [
    "PortalClient",
    "PortalError",
    "PortalSettings",
    "PortalStore",
]
