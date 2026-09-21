from __future__ import annotations

from dataclasses import dataclass

from spdxlims.database import ResultEntryRecord
from spdxlims.service_base import ServiceBase


@dataclass(slots=True)
class ResultService(ServiceBase):

    def get_order_entries(self, order_id: int | str) -> list[ResultEntryRecord]:
        if self._is_local():
            return self.database.get_order_result_entries(int(order_id))
        payload = self.deployment_service.request_json('GET', f'/api/results/orders/{order_id}/entries')
        if not isinstance(payload, list):
            return []
        entries: list[ResultEntryRecord] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            entries.append(
                ResultEntryRecord(
                    order_test_id=str(item.get('order_test_id') or ''),
                    order_id=str(item.get('order_id') or ''),
                    order_number=str(item.get('order_number') or ''),
                    patient_name=str(item.get('patient_name') or ''),
                    doctor_name=item.get('doctor_name'),
                    patient_sex=item.get('patient_sex'),
                    patient_age_days=item.get('patient_age_days'),
                    test_id=str(item.get('test_id') or ''),
                    test_name=str(item.get('test_name') or ''),
                    specimen_type=item.get('specimen_type'),
                    item_type=str(item.get('item_type') or 'test'),
                    result_kind=str(item.get('result_kind') or 'text'),
                    select_options=item.get('select_options'),
                    default_result_value=item.get('default_result_value'),
                    result_value=item.get('result_value'),
                    unit=item.get('unit'),
                    lower_value=item.get('lower_value'),
                    upper_value=item.get('upper_value'),
                    flag=item.get('flag'),
                    reference_text=item.get('reference_text'),
                    comments=item.get('comments'),
                    test_status=str(item.get('test_status') or 'pending'),
                    is_outsourced=1 if item.get('is_outsourced') else 0,
                    source_label=item.get('source_label'),
                    formula=item.get('formula'),
                )
            )
        return entries

    def save_result_entry(
        self,
        *,
        order_test_id: int | str,
        result_value: str,
        unit: str,
        lower_value: str | None,
        upper_value: str | None,
        reference_text: str,
        comments: str,
        result_kind: str,
    ) -> None:
        if self._is_local():
            self.database.save_result_entry(
                order_test_id=int(order_test_id),
                result_value=result_value,
                unit=unit,
                lower_value=lower_value,
                upper_value=upper_value,
                reference_text=reference_text,
                comments=comments,
                result_kind=result_kind,
            )
            return
        self.deployment_service.request_json(
            'POST',
            f'/api/results/order-items/{order_test_id}',
            {
                'result_value': result_value,
                'unit': unit,
                'lower_value': lower_value,
                'upper_value': upper_value,
                'reference_text': reference_text,
                'comments': comments,
                'result_kind': result_kind,
            },
        )

    # --- which analyzer captures have already been imported ---
    #
    # In local mode this lives in the app's own order_ui_state. In server mode
    # it has to come from the server: each workstation keeps its own SQLite, so
    # a capture linked on LAB1 looked pending on LAB2 and could be imported a
    # second time over results someone had corrected by hand.

    CAPTURE_SCOPE = "instrument_capture"

    def linked_instrument_captures(self) -> dict[str, dict]:
        if self._is_local():
            return {
                str(key): value
                for key, value in self.database.get_order_ui_scope(self.CAPTURE_SCOPE).items()
                if isinstance(value, dict)
            }
        payload = self.deployment_service.request_json('GET', '/api/results/instrument-capture-links')
        if not isinstance(payload, list):
            # A server that cannot answer must not make every capture look
            # unlinked - that invites a second import of every one of them.
            raise RuntimeError('Server did not return the instrument capture links.')
        links: dict[str, dict] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            capture_id = str(item.get('capture_id') or '').strip()
            if not capture_id:
                continue
            links[capture_id] = {
                'order_id': str(item.get('order_id') or ''),
                'order_number': str(item.get('order_number') or ''),
                'linked_at': str(item.get('linked_at') or ''),
            }
        return links

    def mark_instrument_capture_linked(self, capture_id: str, order_id: int | str, linked_at: str) -> None:
        """Only local mode needs this; the server records the link as part of
        the import itself, so every workstation sees it without a second call."""
        if not capture_id:
            return
        if not self._is_local():
            return
        self.database.set_order_ui_value(
            self.CAPTURE_SCOPE,
            capture_id,
            {"order_id": order_id, "linked_at": linked_at},
        )

    def deserialize_select_options(self, raw_value: str | None) -> list[str]:
        return self.database.deserialize_select_options(raw_value)
