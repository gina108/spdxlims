from __future__ import annotations
import json
import logging
import sqlite3
from typing import Any

from spdxlims.db.records import InstrumentResultMappingRecord, InstrumentOrderMatchRecord


class InstrumentsMixin:
    def list_instrument_result_mappings(self, *, instrument_profile: str = "") -> list[InstrumentResultMappingRecord]:
        normalized_profile = self._normalize_instrument_key(instrument_profile)
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT m.id,
                       m.instrument_profile,
                       m.device_id,
                       m.raw_code,
                       m.raw_name,
                       m.specimen_type,
                       m.panel_hint,
                       m.test_id,
                       t.code AS test_code,
                       t.name AS test_name,
                       m.unit_override,
                       m.reference_range_override,
                       m.is_active,
                       m.value_slice_start,
                       m.value_slice_end,
                       m.value_multiplier,
                       m.decimal_places,
                       m.value_formula
                FROM instrument_result_mappings m
                INNER JOIN tests t ON t.id = m.test_id
                WHERE (? = '' OR m.instrument_profile = ?)
                ORDER BY m.instrument_profile, m.raw_code, m.specimen_type, m.panel_hint, t.name
                """,
                (normalized_profile, normalized_profile),
            ).fetchall()
        return [InstrumentResultMappingRecord(**dict(row)) for row in rows]

    def save_instrument_result_mapping(
        self,
        *,
        instrument_profile: str,
        device_id: str,
        raw_code: str,
        raw_name: str = "",
        specimen_type: str = "",
        panel_hint: str = "",
        test_id: int,
        unit_override: str = "",
        reference_range_override: str = "",
        value_slice_start: int | None = None,
        value_slice_end: int | None = None,
        value_multiplier: float | None = None,
        decimal_places: int | None = None,
        value_formula: str | None = None,
    ) -> None:
        normalized_profile = self._normalize_instrument_key(instrument_profile)
        normalized_device = self._normalize_optional_instrument_key(device_id)
        normalized_code = self._normalize_instrument_code(raw_code)
        normalized_specimen = self._normalize_optional_instrument_key(specimen_type)
        normalized_panel = self._normalize_optional_instrument_key(panel_hint)
        if not normalized_profile or not normalized_code:
            raise sqlite3.IntegrityError("Instrument profile and raw code are required.")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO instrument_result_mappings (
                    instrument_profile, device_id, raw_code, raw_name, specimen_type, panel_hint,
                    test_id, unit_override, reference_range_override,
                    value_slice_start, value_slice_end, value_multiplier, decimal_places, value_formula,
                    is_active, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now','localtime'))
                ON CONFLICT(instrument_profile, device_id, raw_code, specimen_type, panel_hint)
                DO UPDATE SET
                    raw_name = excluded.raw_name,
                    test_id = excluded.test_id,
                    unit_override = excluded.unit_override,
                    reference_range_override = excluded.reference_range_override,
                    value_slice_start = excluded.value_slice_start,
                    value_slice_end = excluded.value_slice_end,
                    value_multiplier = excluded.value_multiplier,
                    decimal_places = excluded.decimal_places,
                    value_formula = excluded.value_formula,
                    is_active = 1,
                    updated_at = datetime('now','localtime')
                """,
                (
                    normalized_profile,
                    normalized_device or "",
                    normalized_code,
                    raw_name.strip() or None,
                    normalized_specimen or "",
                    normalized_panel or "",
                    int(test_id),
                    unit_override.strip() or None,
                    reference_range_override.strip() or None,
                    value_slice_start,
                    value_slice_end,
                    value_multiplier,
                    decimal_places,
                    value_formula.strip() if value_formula and value_formula.strip() else None,
                ),
            )

    def resolve_instrument_result_mapping(
        self,
        *,
        instrument_profile: str,
        device_id: str,
        raw_code: str,
        specimen_type: str = "",
        panel_hint: str = "",
    ) -> InstrumentResultMappingRecord | None:
        normalized_profile = self._normalize_instrument_key(instrument_profile)
        normalized_device = self._normalize_optional_instrument_key(device_id)
        normalized_code = self._normalize_instrument_code(raw_code)
        normalized_specimen = self._normalize_optional_instrument_key(specimen_type)
        normalized_panel = self._normalize_optional_instrument_key(panel_hint)
        if not normalized_profile or not normalized_code:
            return None
        # For TCP server captures the device_id includes the ephemeral source port
        # (e.g. "10.0.0.3:51234"). Also try matching on the IP-only portion so that
        # mappings saved with a fixed port ("10.0.0.3:5100") still resolve.
        device_ip_only = normalized_device.rsplit(":", 1)[0] if normalized_device and ":" in normalized_device else None
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT m.id,
                       m.instrument_profile,
                       m.device_id,
                       m.raw_code,
                       m.raw_name,
                       m.specimen_type,
                       m.panel_hint,
                       m.test_id,
                       t.code AS test_code,
                       t.name AS test_name,
                       m.unit_override,
                       m.reference_range_override,
                       m.is_active,
                       m.value_slice_start,
                       m.value_slice_end,
                       m.value_multiplier,
                       m.decimal_places,
                       m.value_formula
                FROM instrument_result_mappings m
                INNER JOIN tests t ON t.id = m.test_id
                WHERE m.is_active = 1
                  AND m.instrument_profile = ?
                  AND m.raw_code = ?
                  AND (m.device_id = ? OR (? IS NOT NULL AND m.device_id LIKE ? || ':%') OR m.device_id = '' OR m.device_id IS NULL)
                  AND (m.specimen_type = ? OR m.specimen_type = '' OR m.specimen_type IS NULL)
                  AND (m.panel_hint = ? OR m.panel_hint = '' OR m.panel_hint IS NULL)
                ORDER BY
                  CASE WHEN m.device_id = ? THEN 0 ELSE 1 END,
                  CASE WHEN m.specimen_type = ? THEN 0 ELSE 1 END,
                  CASE WHEN m.panel_hint = ? THEN 0 ELSE 1 END,
                  m.id DESC
                LIMIT 1
                """,
                (
                    normalized_profile,
                    normalized_code,
                    normalized_device,
                    device_ip_only,
                    device_ip_only,
                    normalized_specimen,
                    normalized_panel,
                    normalized_device,
                    normalized_specimen,
                    normalized_panel,
                ),
            ).fetchall()
        if not rows:
            return None
        return InstrumentResultMappingRecord(**dict(rows[0]))

    def list_instrument_profiles(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT instrument_profile FROM instrument_result_mappings ORDER BY instrument_profile"
            ).fetchall()
        return [str(row["instrument_profile"]) for row in rows]

    def delete_instrument_result_mapping(self, mapping_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM instrument_result_mappings WHERE id = ?", (mapping_id,))

    def toggle_instrument_result_mapping_active(self, mapping_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE instrument_result_mappings SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END, updated_at = datetime('now','localtime') WHERE id = ?",
                (mapping_id,),
            )

    def update_instrument_result_mapping_profile(self, mapping_id: int, instrument_profile: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE instrument_result_mappings SET instrument_profile = ?, updated_at = datetime('now','localtime') WHERE id = ?",
                (instrument_profile, mapping_id),
            )

    def find_order_by_instrument_ids(
        self,
        *,
        sample_id: str = "",
        accession_id: str = "",
        order_number: str = "",
        patient_id: str = "",
    ) -> int | None:
        sample_id = (sample_id or "").strip()
        accession_id = (accession_id or "").strip()
        order_number = (order_number or "").strip()
        patient_id = (patient_id or "").strip()
        if not sample_id and not accession_id and not order_number and not patient_id:
            return None
        with self.connect() as connection:
            _open = "status NOT IN ('finalized', 'cancelled') AND COALESCE(is_preallocated, 0) = 0"
            for col, val in [
                ("sample_id", sample_id),
                ("accession_id", accession_id),
                ("order_number", order_number),
                ("order_number", patient_id),
            ]:
                if not val:
                    continue
                row = connection.execute(
                    f"SELECT id FROM orders WHERE {col} = ? AND {_open} ORDER BY created_at DESC LIMIT 1",
                    (val,),
                ).fetchone()
                if row is not None:
                    return int(row["id"])
        return None

    def get_instrument_order_match(self, profile_id: str) -> InstrumentOrderMatchRecord | None:
        profile_id = (profile_id or "").strip()
        if not profile_id:
            return None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT instrument_profile, instrument_field, order_field, auto_import, broadcast_enabled, broadcast_protocol, broadcast_encoding, broadcast_patient_id, broadcast_patient_name, broadcast_dob, broadcast_age, broadcast_sex, broadcast_doctor FROM instrument_order_match_config WHERE instrument_profile = ?",
                (profile_id,),
            ).fetchone()
        if row is None:
            return None
        return InstrumentOrderMatchRecord(
            instrument_profile=str(row["instrument_profile"]),
            instrument_field=str(row["instrument_field"]),
            order_field=str(row["order_field"]),
            auto_import=int(row["auto_import"]),
            broadcast_enabled=int(row["broadcast_enabled"] or 0),
            broadcast_protocol=str(row["broadcast_protocol"] or "hl7_orm"),
            broadcast_encoding=str(row["broadcast_encoding"] or "ascii"),
            broadcast_patient_id=int(row["broadcast_patient_id"] or 1),
            broadcast_patient_name=int(row["broadcast_patient_name"] or 1),
            broadcast_dob=int(row["broadcast_dob"] or 1),
            broadcast_age=int(row["broadcast_age"] or 1),
            broadcast_sex=int(row["broadcast_sex"] or 1),
            broadcast_doctor=int(row["broadcast_doctor"] or 1),
        )

    def save_instrument_order_match(
        self,
        profile_id: str,
        instrument_field: str,
        order_field: str,
        *,
        auto_import: bool = True,
        broadcast_enabled: bool = False,
        broadcast_protocol: str = "hl7_orm",
        broadcast_encoding: str = "ascii",
        broadcast_patient_id: bool = True,
        broadcast_patient_name: bool = True,
        broadcast_dob: bool = True,
        broadcast_age: bool = True,
        broadcast_sex: bool = True,
        broadcast_doctor: bool = True,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO instrument_order_match_config (
                    instrument_profile, instrument_field, order_field, auto_import,
                    broadcast_enabled, broadcast_protocol, broadcast_encoding, broadcast_patient_id,
                    broadcast_patient_name, broadcast_dob, broadcast_age, broadcast_sex, broadcast_doctor,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
                ON CONFLICT (instrument_profile) DO UPDATE SET
                    instrument_field = excluded.instrument_field,
                    order_field = excluded.order_field,
                    auto_import = excluded.auto_import,
                    broadcast_enabled = excluded.broadcast_enabled,
                    broadcast_protocol = excluded.broadcast_protocol,
                    broadcast_encoding = excluded.broadcast_encoding,
                    broadcast_patient_id = excluded.broadcast_patient_id,
                    broadcast_patient_name = excluded.broadcast_patient_name,
                    broadcast_dob = excluded.broadcast_dob,
                    broadcast_age = excluded.broadcast_age,
                    broadcast_sex = excluded.broadcast_sex,
                    broadcast_doctor = excluded.broadcast_doctor,
                    updated_at = datetime('now','localtime')
                """,
                (
                    profile_id, instrument_field, order_field, 1 if auto_import else 0,
                    1 if broadcast_enabled else 0, broadcast_protocol or "hl7_orm",
                    broadcast_encoding or "ascii",
                    1 if broadcast_patient_id else 0, 1 if broadcast_patient_name else 0,
                    1 if broadcast_dob else 0, 1 if broadcast_age else 0, 1 if broadcast_sex else 0,
                    1 if broadcast_doctor else 0,
                ),
            )

    def list_instrument_order_match_configs(self) -> list[InstrumentOrderMatchRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT instrument_profile, instrument_field, order_field, auto_import, broadcast_enabled, broadcast_protocol, broadcast_encoding, broadcast_patient_id, broadcast_patient_name, broadcast_dob, broadcast_age, broadcast_sex, broadcast_doctor FROM instrument_order_match_config ORDER BY instrument_profile"
            ).fetchall()
        return [
            InstrumentOrderMatchRecord(
                instrument_profile=str(row["instrument_profile"]),
                instrument_field=str(row["instrument_field"]),
                order_field=str(row["order_field"]),
                auto_import=int(row["auto_import"]),
                broadcast_enabled=int(row["broadcast_enabled"] or 0),
                broadcast_protocol=str(row["broadcast_protocol"] or "hl7_orm"),
            broadcast_encoding=str(row["broadcast_encoding"] or "ascii"),
                broadcast_patient_id=int(row["broadcast_patient_id"] or 1),
                broadcast_patient_name=int(row["broadcast_patient_name"] or 1),
                broadcast_dob=int(row["broadcast_dob"] or 1),
                broadcast_sex=int(row["broadcast_sex"] or 1),
                broadcast_doctor=int(row["broadcast_doctor"] or 1),
            )
            for row in rows
        ]

    @staticmethod
    def _payload_has_data(payload: dict[str, Any]) -> bool:
        text = str(payload.get("normalized_text") or payload.get("decoded_text") or "")
        visible = "".join(c for c in text if c.isprintable()).strip()
        return len(visible) > 1

    def load_instrument_captures_cache(self) -> dict[str, dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT capture_id, payload_json FROM (
                    SELECT capture_id, payload_json FROM instrument_captures_cache
                    WHERE has_data = 1 ORDER BY received_at DESC LIMIT 500
                )
                UNION ALL
                SELECT capture_id, payload_json FROM (
                    SELECT capture_id, payload_json FROM instrument_captures_cache
                    WHERE has_data = 0 ORDER BY received_at DESC LIMIT 10
                )
                """
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                data = json.loads(row["payload_json"])
                if isinstance(data, dict):
                    result[str(row["capture_id"])] = data
            except json.JSONDecodeError:
                pass
        return result

    def upsert_instrument_captures_cache(self, captures: list[dict[str, Any]]) -> None:
        if not captures:
            return
        with self.connect() as connection:
            for capture in captures:
                cid = str(capture.get("id") or "").strip()
                if not cid:
                    continue
                received_at = str(capture.get("received_at") or "")
                has_data = 1 if self._payload_has_data(capture) else 0
                connection.execute(
                    """
                    INSERT INTO instrument_captures_cache (capture_id, received_at, payload_json, cached_at, has_data)
                    VALUES (?, ?, ?, datetime('now','localtime'), ?)
                    ON CONFLICT (capture_id) DO UPDATE SET
                        received_at = excluded.received_at,
                        payload_json = excluded.payload_json,
                        cached_at = datetime('now','localtime'),
                        has_data = excluded.has_data
                    """,
                    (cid, received_at, json.dumps(capture), has_data),
                )
            connection.execute(
                """
                DELETE FROM instrument_captures_cache
                WHERE has_data = 1 AND capture_id NOT IN (
                    SELECT capture_id FROM instrument_captures_cache
                    WHERE has_data = 1
                    ORDER BY received_at DESC, cached_at DESC
                    LIMIT 500
                )
                """
            )
            connection.execute(
                """
                DELETE FROM instrument_captures_cache
                WHERE has_data = 0 AND capture_id NOT IN (
                    SELECT capture_id FROM instrument_captures_cache
                    WHERE has_data = 0
                    ORDER BY received_at DESC, cached_at DESC
                    LIMIT 10
                )
                """
            )
