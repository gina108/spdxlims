from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib import parse

from spdxlims.database import OrderBrowserRecord, OrderSummaryRecord
from spdxlims.service_base import ServiceBase


@dataclass(slots=True)
class ServerOrderDetail:
    id: str
    order_number: str
    accession_id: str | None
    sample_id: str | None
    patient_id: str | None
    doctor_id: str | None
    client_id: str | None
    status: str
    notes: str | None
    is_preallocated: int
    items: list[dict[str, str | None]]


@dataclass(slots=True)
class OrderService(ServiceBase):

    def list_recent_orders(self) -> list[OrderSummaryRecord]:
        if self._is_local():
            return self.database.list_recent_orders()
        payload = self.deployment_service.request_json("GET", "/api/orders/recent")
        if not isinstance(payload, list):
            return []
        return [
            OrderSummaryRecord(
                id=str(item.get("id") or ""),
                order_number=str(item.get("order_number") or ""),
                patient_name=str(item.get("patient_name") or ""),
                doctor_name=item.get("doctor_name"),
                status=str(item.get("status") or ""),
                created_at=str(item.get("created_at") or ""),
                item_count=int(item.get("item_count") or 0),
            )
            for item in payload if isinstance(item, dict)
        ]

    def next_order_number(self) -> str:
        if self._is_local():
            return self.database.next_order_number()
        payload = self.deployment_service.request_json("GET", "/api/orders/next-number")
        if not isinstance(payload, dict):
            return ""
        value = str(payload.get("order_number") or "").strip()
        if not value:
            raise RuntimeError("Server returned an empty order number.")
        return value

    def search_orders(self, search_text: str = "") -> list[OrderBrowserRecord]:
        if self._is_local():
            return self.database.search_orders(search_text)
        payload = self.deployment_service.request_json("GET", f"/api/orders/search?search={parse.quote(search_text)}")
        if not isinstance(payload, list):
            return []
        return [
            OrderBrowserRecord(
                id=str(item.get("id") or ""),
                order_number=str(item.get("order_number") or ""),
                order_date=str(item.get("order_date") or ""),
                patient_name=str(item.get("patient_name") or ""),
                client_name=item.get("client_name"),
                doctor_name=item.get("doctor_name"),
                status=str(item.get("status") or ""),
                item_count=int(item.get("item_count") or 0),
            )
            for item in payload if isinstance(item, dict)
        ]

    def list_doctor_choices(self) -> list[tuple[str, str]] | list[tuple[int, str]]:
        if self._is_local():
            return self.database.list_doctor_choices(active_only=True)
        return self._list_provider_choices("doctor")

    def list_client_choices(self) -> list[tuple[str, str]] | list[tuple[int, str]]:
        if self._is_local():
            return self.database.list_client_choices(active_only=True)
        return self._list_provider_choices("clinic")

    def list_test_choices(self) -> list[tuple[str, str]] | list[tuple[int, str]]:
        if self._is_local():
            return self.database.list_test_choices()
        payload = self.deployment_service.request_json("GET", "/api/orders/test-choices")
        if not isinstance(payload, list):
            return []
        return [
            (str(item.get("id") or ""), str(item.get("label") or ""))
            for item in payload if isinstance(item, dict) and item.get("id") and item.get("label")
        ]

    def list_panel_choices(self) -> list[tuple[str, str]] | list[tuple[int, str]]:
        if self._is_local():
            return self.database.list_panel_choices()
        payload = self.deployment_service.request_json("GET", "/api/orders/panel-choices")
        if not isinstance(payload, list):
            return []
        return [
            (str(item.get("id") or ""), str(item.get("label") or ""))
            for item in payload if isinstance(item, dict) and item.get("id") and item.get("label")
        ]

    def get_panel_order_items(self, panel_id: int | str) -> list[dict[str, str | int | None]]:
        if self._is_local():
            return [
                {
                    "item_type": item.item_type,
                    "test_id": item.test_id,
                    "heading_text": item.heading_text,
                    "sort_order": item.sort_order,
                    "label": item.label,
                }
                for item in self.database.get_panel_order_items(int(panel_id))
            ]
        payload = self.deployment_service.request_json("GET", f"/api/orders/panels/{panel_id}/order-items")
        if not isinstance(payload, list):
            return []
        items: list[dict[str, str | int | None]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "item_type": str(item.get("item_type") or "test"),
                    "test_id": str(item.get("test_id")) if item.get("test_id") is not None else None,
                    "heading_text": str(item.get("heading_text")) if item.get("heading_text") is not None else None,
                    "sort_order": int(item.get("sort_order") or 0),
                    "label": str(item.get("label") or ""),
                }
            )
        return items

    def get_order_detail(self, order_id: int | str) -> ServerOrderDetail:
        if self._is_local():
            raise RuntimeError("Order detail API path is only used in server mode.")
        payload = self.deployment_service.request_json("GET", f"/api/orders/{order_id}")
        return self._parse_order_detail(payload)

    def get_order_detail_by_number(self, order_number: str) -> ServerOrderDetail:
        if self._is_local():
            raise RuntimeError("Order detail API path is only used in server mode.")
        normalized = order_number.strip()
        if not normalized:
            raise RuntimeError("Order number is required.")
        payload = self.deployment_service.request_json("GET", f"/api/orders/by-number/{normalized}")
        return self._parse_order_detail(payload)

    def update_simple_order(
        self,
        order_id: int | str,
        *,
        patient_id: int | str,
        test_ids: list[int | str],
        items: list[dict[str, Any]] | None = None,
        accession_id: str | None,
        sample_id: str | None,
        status: str,
        notes: str,
        doctor_id: int | str | None = None,
        client_id: int | str | None = None,
    ) -> ServerOrderDetail:
        if self._is_local():
            raise RuntimeError("Order update API path is only used in server mode.")
        payload = self.deployment_service.request_json(
            "PUT",
            f"/api/orders/{order_id}",
            {
                "patient_id": str(patient_id),
                "test_ids": [str(test_id) for test_id in test_ids],
                "items": [
                    {"test_id": str(item.get("test_id")), "source": str(item.get("source") or "")}
                    for item in (items or []) if item.get("test_id") is not None
                ],
                "accession_id": accession_id,
                "sample_id": sample_id,
                "status": status,
                "notes": notes,
                "doctor_id": str(doctor_id) if doctor_id is not None else None,
                "client_id": str(client_id) if client_id is not None else None,
            },
        )
        return self._parse_order_detail(payload)

    def create_simple_order(
        self,
        *,
        patient_id: int | str,
        test_ids: list[int | str],
        items: list[dict[str, Any]] | None = None,
        accession_id: str | None,
        sample_id: str | None,
        status: str,
        notes: str,
        doctor_id: int | str | None = None,
        client_id: int | str | None = None,
    ) -> dict[str, str]:
        if self._is_local():
            raise RuntimeError("Simple order API path is only used in server mode.")
        payload = self.deployment_service.request_json(
            "POST",
            "/api/orders",
            {
                "patient_id": str(patient_id),
                "test_ids": [str(test_id) for test_id in test_ids],
                "items": [
                    {"test_id": str(item.get("test_id")), "source": str(item.get("source") or "")}
                    for item in (items or []) if item.get("test_id") is not None
                ],
                "accession_id": accession_id,
                "sample_id": sample_id,
                "status": status,
                "notes": notes,
                "doctor_id": str(doctor_id) if doctor_id is not None else None,
                "client_id": str(client_id) if client_id is not None else None,
            },
        )
        if not isinstance(payload, dict) or not payload.get("id"):
            raise RuntimeError("Server did not return the created order.")
        return {"id": str(payload.get("id")), "order_number": str(payload.get("order_number") or "")}

    def _parse_order_detail(self, payload: Any) -> ServerOrderDetail:
        if not isinstance(payload, dict) or not payload.get("id"):
            raise RuntimeError("Server did not return a valid order detail.")
        raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
        items: list[dict[str, str | None]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "item_type": str(item.get("item_type") or "test"),
                    "test_id": str(item.get("test_id")) if item.get("test_id") is not None else None,
                    "label": str(item.get("label") or ""),
                    "source": str(item.get("source") or ""),
                }
            )
        return ServerOrderDetail(
            id=str(payload.get("id")),
            order_number=str(payload.get("order_number") or ""),
            accession_id=str(payload.get("accession_id")) if payload.get("accession_id") is not None else None,
            sample_id=str(payload.get("sample_id")) if payload.get("sample_id") is not None else None,
            patient_id=str(payload.get("patient_id")) if payload.get("patient_id") is not None else None,
            doctor_id=str(payload.get("doctor_id")) if payload.get("doctor_id") is not None else None,
            client_id=str(payload.get("client_id")) if payload.get("client_id") is not None else None,
            status=str(payload.get("status") or ""),
            notes=str(payload.get("notes")) if payload.get("notes") is not None else None,
            is_preallocated=int(payload.get("is_preallocated") or 0),
            items=items,
        )

    def _list_provider_choices(self, provider_type: str) -> list[tuple[str, str]]:
        payload = self.deployment_service.request_json("GET", f"/api/orders/provider-choices?provider_type={provider_type}")
        if not isinstance(payload, list):
            return []
        return [
            (str(item.get("id") or ""), str(item.get("label") or ""))
            for item in payload if isinstance(item, dict) and item.get("id") and item.get("label")
        ]
