"""Headless importer: analyzer captures -> the server database.

The engine runs as a Windows service and is always on, but until now the only
thing that moved its captures into Postgres was a 30-second timer inside the
desktop app. That made a GUI the delivery mechanism for lab results: close the
app on the main PC and the second workstation stops seeing new analyzer data.

This module does the same job with no window, so it can run beside the engine as
a scheduled task. It polls the engine for captures, posts each new one to the
backend, and records which ones it has already imported.

It must run on the machine wired to the analyzers: the engine binds loopback, so
a workstation cannot reach it. Local mode needs nothing from this - there the
desktop app imports straight into its own SQLite.

Run it with::

    python -m spdxlims.instrument_importer            # loop forever
    python -m spdxlims.instrument_importer --once     # a single pass
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from spdxlims.database import Database
from spdxlims.deployment import DeploymentService
from spdxlims.engine_identity import is_remote_client
from spdxlims.instrument_broadcast import get_engine_url
from spdxlims.log import get_logger, setup_logging

_log = get_logger(__name__)

CAPTURE_SCOPE = "instrument_capture"
# Captures that matched no order. Kept so they are not re-posted every cycle:
# most never match (they belong to the other database) and would otherwise be
# retried forever, several hundred times a minute, for as long as the service runs.
UNMATCHED_SCOPE = "instrument_capture_unmatched"
HEARTBEAT_NAME = "instrument-importer.heartbeat"
DEFAULT_INTERVAL = 30.0
DEFAULT_LIMIT = 500
# A capture older than this will not be attempted again. The engine retains 30
# days; an order is normally registered before its sample runs, so anything
# still unmatched after two days belongs to the other database.
DEFAULT_MAX_AGE_HOURS = 48.0
# How long to wait before re-attempting a capture that matched no order.
DEFAULT_RETRY_AFTER_MINUTES = 10.0

# The backend answers 400 when no order matched the capture and 409 when an
# order matched but none of its tests did. Both are ordinary: analyzers produce
# runs for samples the lab has not registered, or panels it did not order. They
# are not errors and must not be logged every cycle.
_EXPECTED = {400, 409}


@dataclass
class ImportSummary:
    considered: int = 0
    imported: int = 0
    results_written: int = 0
    skipped: int = 0
    failed: int = 0
    aged_out: int = 0
    backed_off: int = 0
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"{self.considered} capture(s) considered, {self.imported} imported "
            f"({self.results_written} result(s)), {self.skipped} unmatched, {self.failed} failed, "
            f"{self.backed_off} backed off, {self.aged_out} aged out"
        )


def heartbeat_path(data_dir: Path) -> Path:
    return Path(data_dir) / HEARTBEAT_NAME


def importer_is_running(data_dir: Path, *, max_age_seconds: float = DEFAULT_INTERVAL * 3) -> bool:
    """True when a headless importer wrote a heartbeat recently.

    The desktop app checks this so the two never import the same capture at
    once. A stale heartbeat means the task died, and the app takes over again.
    """
    try:
        raw = heartbeat_path(data_dir).read_text(encoding="utf-8")
        written = datetime.fromisoformat(json.loads(raw)["written_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if written.tzinfo is None:
        written = written.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - written).total_seconds() < max_age_seconds


class InstrumentImporter:
    def __init__(
        self,
        database: Database,
        deployment_service: DeploymentService,
        *,
        data_dir: Path,
        engine_url: str | None = None,
        limit: int = DEFAULT_LIMIT,
        timeout: float = 15.0,
        max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
        retry_after_minutes: float = DEFAULT_RETRY_AFTER_MINUTES,
    ) -> None:
        self.database = database
        self.deployment_service = deployment_service
        self.data_dir = Path(data_dir)
        self.engine_url = (engine_url or get_engine_url()).rstrip("/")
        self.limit = limit
        self.timeout = timeout
        self.max_age_hours = max_age_hours
        self.retry_after_minutes = retry_after_minutes

    # ── Engine ───────────────────────────────────────────────────────────

    def fetch_captures(self) -> list[dict]:
        url = f"{self.engine_url}/api/v1/captures?limit={self.limit}"
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return [c for c in payload if isinstance(c, dict)] if isinstance(payload, list) else []

    # ── Backend ──────────────────────────────────────────────────────────

    def _post_import(self, result: dict) -> tuple[int, dict | None]:
        """POST one capture. Returns (status_code, payload)."""
        config = self.deployment_service.load()
        body = json.dumps({"result": result, "allow_patient_fallback": False}).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        token = self.deployment_service.access_token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"{config.server_url.rstrip('/')}/api/results/import-instrument"
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            exc.read()
            return exc.code, None

    def _import_one(self, result: dict) -> tuple[int, dict | None]:
        """POST, re-authenticating once if the token has expired."""
        status, payload = self._post_import(result)
        if status in (401, 403):
            self.deployment_service.logout()
            if not self.deployment_service.try_auto_login():
                return status, None
            status, payload = self._post_import(result)
        return status, payload

    # ── Cycle ────────────────────────────────────────────────────────────

    def linked_capture_ids(self) -> set[str]:
        return {str(k) for k in self.database.get_order_ui_scope(CAPTURE_SCOPE)}

    @staticmethod
    def _parse_timestamp(value: object) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _too_old(self, capture: dict, now: datetime) -> bool:
        if self.max_age_hours <= 0:
            return False
        received = self._parse_timestamp(capture.get("received_at"))
        if received is None:
            return False
        return (now - received).total_seconds() > self.max_age_hours * 3600

    def _backing_off(self, record: object, now: datetime) -> bool:
        if not isinstance(record, dict) or self.retry_after_minutes <= 0:
            return False
        last = self._parse_timestamp(record.get("last_tried"))
        if last is None:
            return False
        return (now - last).total_seconds() < self.retry_after_minutes * 60

    def _record_unmatched(self, capture_id: str, previous: object, now: datetime) -> None:
        attempts = int(previous.get("attempts") or 0) if isinstance(previous, dict) else 0
        self.database.set_order_ui_value(
            UNMATCHED_SCOPE,
            capture_id,
            {"attempts": attempts + 1, "last_tried": now.isoformat()},
        )

    def _clear_unmatched(self, capture_id: str) -> None:
        try:
            self.database.delete_order_ui_value(UNMATCHED_SCOPE, capture_id)
        except Exception:
            _log.debug("Could not clear unmatched marker for %s", capture_id, exc_info=True)

    def mark_linked(self, capture_id: str, order_id: str) -> None:
        self.database.set_order_ui_value(
            CAPTURE_SCOPE,
            capture_id,
            {"order_id": order_id, "linked_at": datetime.now().isoformat(timespec="seconds")},
        )

    def _should_import(self, capture: dict) -> dict | None:
        """Return the parsed result to import, or None to skip this capture."""
        profile_id = str(capture.get("profile_id") or "").strip()
        if profile_id:
            match_cfg = self.database.get_instrument_order_match(profile_id)
            if match_cfg is not None and not match_cfg.auto_import:
                return None
        parsed = capture.get("parsed_json")
        if isinstance(parsed, str) and parsed.strip():
            try:
                parsed = json.loads(parsed)
            except json.JSONDecodeError:
                return None
        if not isinstance(parsed, dict):
            return None
        message = parsed.get("message")
        if not isinstance(message, dict) or not message.get("observations"):
            return None
        return parsed

    def run_once(self) -> ImportSummary:
        summary = ImportSummary()
        if not self.deployment_service.is_authenticated() and not self.deployment_service.try_auto_login():
            summary.errors.append("Could not authenticate against the server.")
            return summary
        try:
            captures = self.fetch_captures()
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            summary.errors.append(f"Could not reach the instrument engine: {exc}")
            return summary

        now = datetime.now(timezone.utc)
        linked = self.linked_capture_ids()
        unmatched = self.database.get_order_ui_scope(UNMATCHED_SCOPE)
        for capture in captures:
            capture_id = str(capture.get("id") or "").strip()
            if not capture_id or capture_id in linked:
                continue
            if self._too_old(capture, now):
                summary.aged_out += 1
                continue
            previous = unmatched.get(capture_id)
            if self._backing_off(previous, now):
                summary.backed_off += 1
                continue
            result = self._should_import(capture)
            if result is None:
                continue
            summary.considered += 1
            status, payload = self._import_one(result)
            if status == 200 and isinstance(payload, dict):
                count = int(payload.get("imported_count") or 0)
                if count > 0:
                    self.mark_linked(capture_id, str(payload.get("order_id") or ""))
                    self._clear_unmatched(capture_id)
                    summary.imported += 1
                    summary.results_written += count
                    _log.info(
                        "Imported capture %s -> order %s (%d result(s), matched by %s)",
                        capture_id, payload.get("order_number") or payload.get("order_id"),
                        count, payload.get("matched_by"),
                    )
                else:
                    self._record_unmatched(capture_id, previous, now)
                    summary.skipped += 1
            elif status in _EXPECTED:
                self._record_unmatched(capture_id, previous, now)
                summary.skipped += 1
            else:
                summary.failed += 1
                message = f"capture {capture_id}: HTTP {status}"
                summary.errors.append(message)
                _log.warning("Import failed for %s", message)
        return summary

    def write_heartbeat(self) -> None:
        payload = {"written_at": datetime.now(timezone.utc).isoformat(), "engine_url": self.engine_url}
        try:
            heartbeat_path(self.data_dir).write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            _log.debug("Could not write importer heartbeat", exc_info=True)

    def run_forever(self, interval: float = DEFAULT_INTERVAL) -> None:
        _log.info("Instrument importer started (engine %s, every %.0fs)", self.engine_url, interval)
        while True:
            self.write_heartbeat()
            try:
                summary = self.run_once()
            except Exception:  # never let one bad cycle kill the task
                _log.exception("Import cycle failed")
            else:
                if summary.imported or summary.failed:
                    _log.info("Import cycle: %s", summary)
                for error in summary.errors:
                    _log.warning("%s", error)
            time.sleep(interval)


def build_importer(
    root: Path | None = None,
    *,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    retry_after_minutes: float = DEFAULT_RETRY_AFTER_MINUTES,
) -> InstrumentImporter:
    data_dir = (Path(root) if root else Path.cwd()) / "data"
    database = Database(data_dir / "spdxlims.db")
    database.initialize()
    return InstrumentImporter(
        database,
        DeploymentService(data_dir / "deployment.json"),
        data_dir=data_dir,
        max_age_hours=max_age_hours,
        retry_after_minutes=retry_after_minutes,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import analyzer captures into the server database.")
    parser.add_argument("--once", action="store_true", help="run a single pass and exit")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, help="seconds between passes")
    parser.add_argument(
        "--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS,
        help="ignore captures older than this; 0 disables the cutoff",
    )
    parser.add_argument(
        "--retry-after-minutes", type=float, default=DEFAULT_RETRY_AFTER_MINUTES,
        help="wait this long before re-attempting a capture that matched no order; 0 disables backoff",
    )
    parser.add_argument("--root", type=Path, default=None, help="install root holding data\\ (default: cwd)")
    args = parser.parse_args(argv)

    root = args.root or Path.cwd()
    setup_logging(root / "data")

    if is_remote_client():
        print(
            "This machine is a client workstation. The engine binds loopback, so the importer "
            "must run on the PC wired to the analyzers.",
            file=sys.stderr,
        )
        return 2

    importer = build_importer(
        root,
        max_age_hours=args.max_age_hours,
        retry_after_minutes=args.retry_after_minutes,
    )
    if importer.deployment_service.load().mode != "server":
        print(
            "Deployment mode is 'local'. The desktop app imports straight into SQLite there, "
            "so the headless importer has nothing to do.",
            file=sys.stderr,
        )
        return 2

    if args.once:
        importer.write_heartbeat()
        summary = importer.run_once()
        print(summary)
        for error in summary.errors:
            print(f"  ! {error}", file=sys.stderr)
        return 1 if summary.errors else 0

    importer.run_forever(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
