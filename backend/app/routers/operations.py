from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.deps import require_roles
from app.models.models import AppUser

router = APIRouter(dependencies=[Depends(require_roles('admin', 'lab_manager'))])

DEFAULT_STATUS_PATH = Path(__file__).resolve().parent.parent / 'backup-status.json'
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / 'backup-config.json'
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class BackupStatusIn(BaseModel):
    status: str = 'unknown'
    destination: str = ''
    message: str = ''
    last_backup_at: datetime | None = None


class BackupStatusOut(BaseModel):
    configured: bool
    status: str = 'unknown'
    destination: str = ''
    message: str = ''
    last_backup_at: datetime | None = None
    age_hours: float | None = None
    warning: str = ''


class BackupConfig(BaseModel):
    enabled: bool = False
    destination: str = ''
    schedule: str = 'Daily at 8:00 PM'
    retention_days: int = 30
    include_database: bool = True
    include_assets: bool = True
    include_instrument_profiles: bool = True
    cloud_sync_note: str = ''
    restore_drill_date: str = ''


@router.get('/backup-status', response_model=BackupStatusOut)
def get_backup_status(_actor: AppUser = Depends(require_roles('admin', 'lab_manager'))):
    status_path = _status_path()
    if not status_path.exists():
        return BackupStatusOut(configured=False, warning='No backup status has been reported yet.')
    try:
        raw = json.loads(status_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return BackupStatusOut(configured=False, status='error', warning='Backup status file could not be read.')
    return _status_out(raw)


@router.get('/backup-config', response_model=BackupConfig)
def get_backup_config(_actor: AppUser = Depends(require_roles('admin', 'lab_manager'))):
    return _read_backup_config()


@router.put('/backup-config', response_model=BackupConfig)
def update_backup_config(payload: BackupConfig, _actor: AppUser = Depends(require_roles('admin', 'lab_manager'))):
    config = BackupConfig(
        enabled=payload.enabled,
        destination=payload.destination.strip(),
        schedule=payload.schedule.strip() or 'Daily at 8:00 PM',
        retention_days=max(1, payload.retention_days),
        include_database=payload.include_database,
        include_assets=payload.include_assets,
        include_instrument_profiles=payload.include_instrument_profiles,
        cloud_sync_note=payload.cloud_sync_note.strip(),
        restore_drill_date=payload.restore_drill_date.strip(),
    )
    _config_path().parent.mkdir(parents=True, exist_ok=True)
    _config_path().write_text(json.dumps(config.model_dump(mode='json'), indent=2), encoding='utf-8')
    return config


@router.post('/run-backup', response_model=BackupStatusOut)
def run_backup(_actor: AppUser = Depends(require_roles('admin', 'lab_manager'))):
    config = _read_backup_config()
    if not config.destination:
        raise HTTPException(status_code=400, detail='Set a backup destination before running a backup.')
    script_path = PROJECT_ROOT / 'scripts' / 'backup-server.ps1'
    if not script_path.exists():
        raise HTTPException(status_code=500, detail=f'Backup script not found: {script_path}')
    status_path = _status_path()
    command = [
        'powershell.exe',
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        str(script_path),
        '-OutputDir',
        config.destination,
        '-StatusPath',
        str(status_path),
    ]
    try:
        result = subprocess.run(command, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.SubprocessError) as exc:
        _write_backup_status('error', config.destination, str(exc))
        raise HTTPException(status_code=500, detail=f'Backup could not be started: {exc}') from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout or f'Backup failed with exit code {result.returncode}.').strip()
        _write_backup_status('error', config.destination, message)
        raise HTTPException(status_code=500, detail=message)
    if not status_path.exists():
        _write_backup_status('success', config.destination, 'Backup completed successfully.')
    try:
        raw = json.loads(status_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return BackupStatusOut(configured=True, status='success', destination=config.destination, message='Backup completed, but status file could not be read.')
    return _status_out(raw)


@router.post('/backup-status', response_model=BackupStatusOut)
def update_backup_status(payload: BackupStatusIn, actor: AppUser = Depends(require_roles('admin', 'lab_manager'))):
    status_path = _status_path()
    status_path.parent.mkdir(parents=True, exist_ok=True)
    raw = payload.model_dump(mode='json')
    raw['reported_by'] = str(actor.id)
    raw['reported_at'] = datetime.now(timezone.utc).isoformat()
    status_path.write_text(json.dumps(raw, indent=2), encoding='utf-8')
    return _status_out(raw)


def _status_path() -> Path:
    return Path(os.getenv('BACKUP_STATUS_PATH') or DEFAULT_STATUS_PATH)


def _config_path() -> Path:
    return Path(os.getenv('BACKUP_CONFIG_PATH') or DEFAULT_CONFIG_PATH)


def _read_backup_config() -> BackupConfig:
    config_path = _config_path()
    if not config_path.exists():
        return BackupConfig()
    try:
        raw = json.loads(config_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return BackupConfig()
    return BackupConfig.model_validate(raw if isinstance(raw, dict) else {})


def _write_backup_status(status: str, destination: str, message: str) -> None:
    status_path = _status_path()
    status_path.parent.mkdir(parents=True, exist_ok=True)
    raw = {
        'status': status,
        'destination': destination,
        'message': message,
        'last_backup_at': datetime.now(timezone.utc).isoformat() if status == 'success' else None,
    }
    status_path.write_text(json.dumps(raw, indent=2), encoding='utf-8')


def _status_out(raw: dict[str, object]) -> BackupStatusOut:
    last_backup_at = _parse_datetime(raw.get('last_backup_at'))
    age_hours = None
    warning = ''
    if last_backup_at is not None:
        now = datetime.now(timezone.utc)
        if last_backup_at.tzinfo is None:
            last_backup_at = last_backup_at.replace(tzinfo=timezone.utc)
        age_hours = round(max((now - last_backup_at).total_seconds(), 0) / 3600, 2)
        if age_hours > 30:
            warning = 'Last backup is older than 30 hours.'
    elif str(raw.get('status') or '').lower() not in {'disabled', 'not_configured'}:
        warning = 'No successful backup timestamp has been reported.'
    return BackupStatusOut(
        configured=True,
        status=str(raw.get('status') or 'unknown'),
        destination=str(raw.get('destination') or ''),
        message=str(raw.get('message') or ''),
        last_backup_at=last_backup_at,
        age_hours=age_hours,
        warning=warning,
    )


def _parse_datetime(raw_value: object) -> datetime | None:
    if raw_value is None:
        return None
    try:
        return datetime.fromisoformat(str(raw_value).replace('Z', '+00:00'))
    except ValueError:
        return None
