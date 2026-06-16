from __future__ import annotations
import sqlite3
from typing import Any

from spdxlims.db.records import PatientRecord


class PatientsMixin:
    def list_patients(self, *, status_filter: str = 'active') -> list[PatientRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, patient_code, first_name, last_name, middle_name, sex, date_of_birth, age_value, age_unit, phone, is_active
                FROM patients
                WHERE COALESCE(patient_code, '') != '__PREALLOCATED__'
                  AND (? = 'all' OR (? = 'active' AND is_active = 1) OR (? = 'archived' AND is_active = 0))
                ORDER BY is_active DESC, created_at DESC, id DESC
                """
                , (status_filter, status_filter, status_filter)
            ).fetchall()
        return [PatientRecord(**dict(row)) for row in rows]

    def list_patient_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, first_name, last_name, middle_name, age_value, age_unit FROM patients WHERE COALESCE(patient_code, '') != '__PREALLOCATED__' AND is_active = 1 ORDER BY last_name, first_name, id"
            ).fetchall()
        return [
            (
                row["id"],
                self._format_patient_label(
                    row["first_name"],
                    row["last_name"],
                    row["middle_name"],
                    row["age_value"],
                    row["age_unit"],
                ),
            )
            for row in rows
        ]

    def get_patient(self, patient_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, patient_code, first_name, last_name, middle_name, sex, date_of_birth, age_value, age_unit, phone, email, address, national_id, is_active FROM patients WHERE id = ?",
                (patient_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def create_patient(self, payload: dict[str, Any]) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO patients (patient_code, first_name, last_name, middle_name, sex, date_of_birth, age_value, age_unit, phone, email, address, national_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(payload.get("patient_code") or "").strip() or None,
                    payload["first_name"].strip(),
                    payload["last_name"].strip(),
                    str(payload.get("middle_name") or "").strip() or None,
                    str(payload.get("sex") or "").strip() or None,
                    str(payload.get("date_of_birth") or "").strip() or None,
                    payload.get("age_value"),
                    str(payload.get("age_unit") or "").strip() or None,
                    str(payload.get("phone") or "").strip() or None,
                    str(payload.get("email") or "").strip() or None,
                    str(payload.get("address") or "").strip() or None,
                    str(payload.get("national_id") or "").strip() or None,
                ),
            )
            return int(cursor.lastrowid)

    def update_patient(self, patient_id: int, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE patients SET first_name = ?, last_name = ?, middle_name = ?, sex = ?, date_of_birth = ?, age_value = ?, age_unit = ?, phone = ?, email = ?, address = ?, national_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (
                    payload["first_name"].strip(),
                    payload["last_name"].strip(),
                    str(payload.get("middle_name") or "").strip() or None,
                    str(payload.get("sex") or "").strip() or None,
                    str(payload.get("date_of_birth") or "").strip() or None,
                    payload.get("age_value"),
                    str(payload.get("age_unit") or "").strip() or None,
                    str(payload.get("phone") or "").strip() or None,
                    str(payload.get("email") or "").strip() or None,
                    str(payload.get("address") or "").strip() or None,
                    str(payload.get("national_id") or "").strip() or None,
                    patient_id,
                ),
            )

    def archive_patient(self, patient_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE patients SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND COALESCE(patient_code, '') != '__PREALLOCATED__'",
                (patient_id,),
            )

    def unarchive_patient(self, patient_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE patients SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND COALESCE(patient_code, '') != '__PREALLOCATED__'",
                (patient_id,),
            )

    def _get_or_create_preallocated_patient(self, connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT id FROM patients WHERE patient_code = '__PREALLOCATED__' LIMIT 1").fetchone()
        if row is not None:
            return int(row["id"])
        cursor = connection.execute(
            "INSERT INTO patients (patient_code, first_name, last_name, middle_name, phone, email, address, national_id) VALUES ('__PREALLOCATED__', 'Unassigned', 'Barcode', NULL, NULL, NULL, NULL, NULL)"
        )
        return int(cursor.lastrowid)
