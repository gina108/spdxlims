from __future__ import annotations
import sqlite3
from typing import Any

from spdxlims.db.records import DoctorRecord
from spdxlims.i18n import tr


class DoctorsMixin:
    def list_doctors(self, *, status_filter: str = 'all') -> list[DoctorRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, full_name, license_number, phone, email, is_active
                FROM doctors
                WHERE (? = 'all' OR (? = 'active' AND is_active = 1) OR (? = 'archived' AND is_active = 0))
                ORDER BY is_active DESC, full_name, id
                """,
                (status_filter, status_filter, status_filter),
            ).fetchall()
        return [DoctorRecord(**dict(row)) for row in rows]

    def list_doctor_choices(self, *, active_only: bool = False, include_ids: list[int] | None = None) -> list[tuple[int, str]]:
        include_ids = [int(value) for value in (include_ids or []) if value is not None]
        with self.connect() as connection:
            if active_only and include_ids:
                placeholders = ", ".join("?" for _ in include_ids)
                rows = connection.execute(
                    f"SELECT id, full_name, license_number, is_active FROM doctors WHERE is_active = 1 OR id IN ({placeholders}) ORDER BY is_active DESC, full_name, id",
                    include_ids,
                ).fetchall()
            elif active_only:
                rows = connection.execute(
                    "SELECT id, full_name, license_number, is_active FROM doctors WHERE is_active = 1 ORDER BY full_name, id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, full_name, license_number, is_active FROM doctors ORDER BY is_active DESC, full_name, id"
                ).fetchall()
        return [
            (
                row["id"],
                ((row["full_name"] if not row["license_number"] else f'{row["full_name"]} ({row["license_number"]})') + ('' if row["is_active"] else f' [{tr("Archived")}]')),
            )
            for row in rows
        ]

    def get_doctor(self, doctor_id: int) -> DoctorRecord | None:
        with self.connect() as connection:
            row = connection.execute("SELECT id, full_name, license_number, phone, email, is_active FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
        return DoctorRecord(**dict(row)) if row is not None else None

    def create_doctor(self, payload: dict[str, Any]) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO doctors (full_name, license_number, phone, email, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, 1, datetime('now','localtime'), datetime('now','localtime'))",
                (
                    payload["full_name"].strip(),
                    payload.get("license_number") or None,
                    payload.get("phone") or None,
                    payload.get("email") or None,
                ),
            )
            return int(cursor.lastrowid)

    def update_doctor(self, doctor_id: int, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE doctors SET full_name = ?, license_number = ?, phone = ?, email = ?, updated_at = datetime('now','localtime') WHERE id = ?",
                (
                    payload["full_name"].strip(),
                    payload.get("license_number") or None,
                    payload.get("phone") or None,
                    payload.get("email") or None,
                    doctor_id,
                ),
            )

    def archive_doctor(self, doctor_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE doctors SET is_active = 0, updated_at = datetime('now','localtime') WHERE id = ?", (doctor_id,))

    def unarchive_doctor(self, doctor_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE doctors SET is_active = 1, updated_at = datetime('now','localtime') WHERE id = ?", (doctor_id,))
