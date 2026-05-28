from __future__ import annotations

from dataclasses import dataclass

from spdxlims.database import Database, ResultEntryRecord
from spdxlims.deployment import DeploymentService


@dataclass(slots=True)
class ResultService:
    database: Database
    deployment_service: DeploymentService

    def uses_server_backend(self) -> bool:
        return self.deployment_service.load().mode == 'server'

    def get_order_entries(self, order_id: int | str) -> list[ResultEntryRecord]:
        config = self.deployment_service.load()
        if config.mode != 'server':
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
        config = self.deployment_service.load()
        if config.mode != 'server':
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

    def deserialize_select_options(self, raw_value: str | None) -> list[str]:
        return self.database.deserialize_select_options(raw_value)
