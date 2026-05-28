from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.routers import operations


def test_backup_config_round_trip_uses_config_file(monkeypatch, tmp_path):
    config_path = tmp_path / "backup-config.json"
    monkeypatch.setenv("BACKUP_CONFIG_PATH", str(config_path))

    payload = operations.BackupConfig(
        enabled=True,
        destination=r"D:\SPDXLIMS Backups",
        schedule="Daily at 8:00 PM",
        retention_days=45,
        include_database=True,
        include_assets=True,
        include_instrument_profiles=False,
        cloud_sync_note="Synced by OneDrive",
        restore_drill_date="2026-05-27",
    )

    config_path.write_text(json.dumps(payload.model_dump(mode="json")), encoding="utf-8")

    loaded = operations._read_backup_config()

    assert loaded.enabled is True
    assert loaded.destination == r"D:\SPDXLIMS Backups"
    assert loaded.retention_days == 45
    assert loaded.include_instrument_profiles is False
    assert loaded.cloud_sync_note == "Synced by OneDrive"


def test_backup_status_warns_when_last_backup_is_old():
    old_timestamp = datetime.now(timezone.utc) - timedelta(hours=31)

    status = operations._status_out(
        {
            "status": "success",
            "destination": r"D:\SPDXLIMS Backups",
            "last_backup_at": old_timestamp.isoformat(),
        }
    )

    assert status.configured is True
    assert status.age_hours is not None
    assert status.age_hours >= 31
    assert status.warning == "Last backup is older than 30 hours."
