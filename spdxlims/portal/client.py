"""HTTP client for the order-collection app's ``/lis/*`` API.

This is the *only* surface the LIS uses to talk to the client portal. It
authenticates with the shared secret in an ``Authorization`` header and never
touches the clinic JWT auth path. Built on ``urllib`` (stdlib) to match
``spdxlims.server_client`` and avoid adding an httpx dependency to the desktop
app.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib import error, request


class PortalError(RuntimeError):
    """Raised when the portal API returns an error (4xx/5xx) or is unreachable."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class PendingOrder:
    id: int
    clinic_id: int | None
    patient_id: int | None
    tests: list[int]
    notes: str
    created_at: str
    patient_name: str
    patient_age: int | None
    patient_gender: str
    patient_phone: str


class PortalClient:
    """Thin, synchronous client around the ``/lis/*`` API."""

    def __init__(self, base_url: str, shared_secret: str, *, timeout: float = 15.0) -> None:
        if not base_url.strip():
            raise PortalError("Portal base URL is required.")
        if not shared_secret.strip():
            raise PortalError("Portal shared secret is required.")
        self._base_url = base_url.strip().rstrip("/")
        self._secret = shared_secret.strip()
        self._timeout = timeout

    # -- internals ---------------------------------------------------------
    def _request(self, method: str, path: str, json_body: dict[str, Any] | None = None) -> Any:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._secret}",
        }
        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(f"{self._base_url}{path}", data=data, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=self._timeout) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise PortalError(self._format_error(exc.code, detail), exc.code) from exc
        except error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise PortalError(f"Could not reach the portal: {reason}") from exc
        except TimeoutError as exc:
            raise PortalError("The portal request timed out.") from exc
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PortalError("The portal returned invalid JSON.") from exc

    @staticmethod
    def _format_error(status_code: int, detail: str) -> str:
        message = detail
        try:
            payload = json.loads(detail)
            if isinstance(payload, dict) and payload.get("error"):
                message = str(payload["error"])
        except json.JSONDecodeError:
            message = detail[:200]
        if status_code in (401, 403):
            return message or "The portal rejected the shared secret."
        return message or f"The portal responded with HTTP {status_code}."

    # -- endpoints ---------------------------------------------------------
    def health(self) -> dict[str, Any]:
        """GET /lis/health -> {pending_count, oldest_pending_age_hours, last_import_at}."""
        payload = self._request("GET", "/lis/health")
        return payload if isinstance(payload, dict) else {}

    def tests(self) -> list[dict[str, Any]]:
        """GET /lis/tests -> the portal's test catalog (id, name, category)."""
        payload = self._request("GET", "/lis/tests")
        items = (payload or {}).get("tests", []) if isinstance(payload, dict) else []
        return [item for item in items if isinstance(item, dict)]

    def pending_orders(self) -> list[PendingOrder]:
        """GET /lis/orders/pending -> pending orders with patient fields."""
        payload = self._request("GET", "/lis/orders/pending")
        rows = (payload or {}).get("orders", []) if isinstance(payload, dict) else []
        orders: list[PendingOrder] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_tests = row.get("tests") or []
            tests = [int(t) for t in raw_tests if isinstance(t, (int, float, str)) and str(t).strip().lstrip("-").isdigit()]
            orders.append(
                PendingOrder(
                    id=int(row.get("id") or 0),
                    clinic_id=_opt_int(row.get("clinic_id")),
                    patient_id=_opt_int(row.get("patient_id")),
                    tests=tests,
                    notes=str(row.get("notes") or ""),
                    created_at=str(row.get("created_at") or ""),
                    patient_name=str(row.get("patient_name") or ""),
                    patient_age=_opt_int(row.get("patient_age")),
                    patient_gender=str(row.get("patient_gender") or ""),
                    patient_phone=str(row.get("patient_phone") or ""),
                )
            )
        return orders

    def mark_imported(
        self,
        order_ids: Iterable[int],
        external_order_ids: Mapping[int, str] | None = None,
    ) -> int:
        """POST /lis/orders/mark-imported. Returns the number marked imported."""
        ids = [int(i) for i in order_ids]
        ext = {str(k): str(v) for k, v in (external_order_ids or {}).items()}
        payload = self._request(
            "POST",
            "/lis/orders/mark-imported",
            {"order_ids": ids, "external_order_ids": ext},
        )
        return int((payload or {}).get("imported", 0)) if isinstance(payload, dict) else 0

    def upload_result(self, order_id: int, pdf_bytes: bytes) -> dict[str, Any]:
        """POST /lis/results/upload. Stores the PDF and sets the order completed."""
        b64 = base64.b64encode(pdf_bytes).decode("ascii")
        payload = self._request(
            "POST",
            "/lis/results/upload",
            {"order_id": int(order_id), "pdf_base64": b64},
        )
        return payload if isinstance(payload, dict) else {}


def _opt_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
