"""Publish finalized report PDFs back to the client portal.

Only orders that were imported from the portal have a link (recorded at import
time in PortalStore); everything here is a no-op for ordinary LIS orders. Uploads
are resilient to connectivity: a PDF that can't be sent right now is stashed
locally and retried, so approving a report never depends on the portal being
reachable.
"""
from __future__ import annotations

from dataclasses import dataclass

from spdxlims.portal.client import PortalClient, PortalError
from spdxlims.portal.settings import PortalStore


@dataclass(slots=True)
class PortalResultService:
    store: PortalStore

    def _client(self) -> PortalClient | None:
        settings = self.store.load_settings()
        if not settings.is_configured():
            return None
        return PortalClient(settings.base_url, settings.shared_secret)

    def is_linked(self, lis_order_id: object) -> bool:
        """True if this LIS order originated from a portal order."""
        return self.store.portal_order_id_for(lis_order_id) is not None

    def publish(self, lis_order_id: object, pdf_bytes: bytes) -> str:
        """Upload the report for a portal-linked order.

        Returns 'not_linked' (ordinary order, nothing to do), 'uploaded'
        (delivered to the portal) or 'queued' (portal unreachable; stashed for a
        later retry_pending)."""
        portal_order_id = self.store.portal_order_id_for(lis_order_id)
        if portal_order_id is None:
            return "not_linked"
        client = self._client()
        if client is not None:
            try:
                client.upload_result(portal_order_id, pdf_bytes)
            except PortalError:
                pass
            else:
                self.store.clear_pending_result(lis_order_id)
                return "uploaded"
        self.store.stash_pending_result(lis_order_id, pdf_bytes)
        return "queued"

    def retry_pending(self) -> int:
        """Re-upload any stashed results. Returns how many were delivered."""
        client = self._client()
        if client is None:
            return 0
        uploaded = 0
        for lis_order_id, pdf_bytes in self.store.list_pending_results():
            portal_order_id = self.store.portal_order_id_for(lis_order_id)
            if portal_order_id is None:
                self.store.clear_pending_result(lis_order_id)  # orphaned stash
                continue
            try:
                client.upload_result(portal_order_id, pdf_bytes)
            except PortalError:
                continue
            self.store.clear_pending_result(lis_order_id)
            uploaded += 1
        return uploaded
