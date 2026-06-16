from __future__ import annotations

import json
import logging
import os
import socket
import sys
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

try:
    import yaml as _yaml
except ImportError:
    _yaml = None

_PROFILES_DIR = Path(__file__).parent.parent / "instrument-connectivity" / "profiles"

_MLLP_START = b"\x0b"
_MLLP_END = b"\x1c\x0d"


def _find_profile_yaml(profile_id: str) -> Path | None:
    if _yaml is None or not profile_id:
        return None
    key = profile_id.lower().strip()
    exact = _PROFILES_DIR / f"{key}.yaml"
    if exact.exists():
        return exact
    try:
        for f in sorted(_PROFILES_DIR.glob("*.yaml")):
            stem = f.stem.lower()
            if stem in key or key in stem:
                return f
    except Exception:
        _log.debug("Error scanning profiles dir for %r", profile_id, exc_info=True)
    return None


def _get_transport_address(profile_id: str) -> tuple[str, int] | None:
    yaml_path = _find_profile_yaml(profile_id)
    if yaml_path is None:
        return None
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = _yaml.safe_load(f)
        addr = str((data or {}).get("transport", {}).get("remote_address") or "").strip()
        if not addr or ":" not in addr:
            return None
        host, port_str = addr.rsplit(":", 1)
        return host.strip(), int(port_str.strip())
    except Exception:
        _log.debug("Error reading transport address from %s", yaml_path, exc_info=True)
        return None


def _hl7_escape(value: str) -> str:
    return (value or "").replace("\\", "\\E\\").replace("|", "\\F\\").replace("^", "\\S\\").replace("&", "\\T\\")


def _hl7_date(value: str) -> str:
    if not value:
        return ""
    return value.replace("-", "").replace("/", "")[:8]


def _build_hl7_orm(
    profile_id: str,
    order_data: dict[str, Any],
    *,
    send_patient_id: bool = True,
    send_patient_name: bool = True,
    send_dob: bool = True,
    send_age: bool = True,
    send_sex: bool = True,
    send_doctor: bool = True,
    encoding: str = "ascii",
) -> str:
    now = datetime.now().strftime("%Y%m%d%H%M%S")
    msg_id = uuid.uuid4().hex[:10].upper()

    patient_id = _hl7_escape(str(order_data.get("patient_id") or "")) if send_patient_id else ""
    raw_name = str(order_data.get("patient_name") or "")
    parts = raw_name.split() if raw_name else []
    last = _hl7_escape(parts[-1]) if parts else ""
    first = _hl7_escape(" ".join(parts[:-1])) if len(parts) > 1 else ""
    patient_name = f"{last}^{first}" if send_patient_name else "^"
    dob = _hl7_date(str(order_data.get("patient_dob") or "")) if send_dob else ""
    sex_raw = str(order_data.get("patient_sex") or "").upper()
    sex = (sex_raw[:1] if sex_raw[:1] in {"M", "F", "O"} else "U") if send_sex else ""
    doctor = _hl7_escape(str(order_data.get("doctor_name") or "")) if send_doctor else ""
    order_number = _hl7_escape(str(order_data.get("order_number") or ""))
    sample_id = _hl7_escape(str(order_data.get("sample_id") or order_data.get("accession_id") or order_number))
    age_value = str(order_data.get("patient_age_value") or "")
    age_unit = str(order_data.get("patient_age_unit") or "a")[:1].upper()
    age_field = f"{age_value}{age_unit}" if send_age and age_value else ""

    msh = f"MSH|^~\\&|LIS||{_hl7_escape(profile_id)}||{now}||ORM^O01|{msg_id}|P|2.3.1"
    pid = f"PID|1||{patient_id}^^^LIS||{patient_name}||{dob}|{sex}|||||||||||||||{age_field}"
    obr = f"OBR|1|{order_number}|{sample_id}|CBC^Complete Blood Count|||{now}"
    if doctor:
        obr += f"|||||||||||{doctor}"

    lines = [msh, pid, obr]
    return "\r".join(lines) + "\r"


def broadcast_order(
    profile_id: str,
    order_data: dict[str, Any],
    *,
    send_patient_id: bool = True,
    send_patient_name: bool = True,
    send_dob: bool = True,
    send_age: bool = True,
    send_sex: bool = True,
    send_doctor: bool = True,
    protocol: str = "hl7_orm",
    encoding: str = "ascii",
    timeout: float = 5.0,
) -> None:
    """Send order data to the instrument. Raises RuntimeError on failure."""
    address = _get_transport_address(profile_id)
    if address is None:
        raise RuntimeError(f"No transport address found for profile '{profile_id}'.")
    host, port = address

    codec = "latin-1" if encoding in ("latin1", "iso-8859-1") else ("utf-8" if encoding == "utf8" else "ascii")

    if protocol in ("hl7_orm", "hl7_worklist"):
        message = _build_hl7_orm(
            profile_id, order_data,
            send_patient_id=send_patient_id,
            send_patient_name=send_patient_name,
            send_dob=send_dob,
            send_age=send_age,
            send_sex=send_sex,
            send_doctor=send_doctor,
            encoding=codec,
        )
        payload = _MLLP_START + message.encode(codec, errors="replace") + _MLLP_END
    else:
        raise RuntimeError(f"Protocol '{protocol}' not yet supported for outbound sending.")

    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(payload)
    except OSError as exc:
        raise RuntimeError(f"Could not connect to {host}:{port} — {exc}") from exc


def _read_engine_config() -> dict:
    env = os.environ.get("INSTRUMENT_ENGINE_DATA_DIR", "").strip()
    if env:
        candidates = [Path(env) / "engine.json"]
    else:
        root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
        candidates = [root / "data" / "instrument-engine" / "engine.json"]
    for path in candidates:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def get_engine_url() -> str:
    """Return the engine API base URL from engine.json in the data dir, or the default."""
    addr = (_read_engine_config().get("listen_addr") or "").strip()
    if not addr:
        return "http://127.0.0.1:9088"
    host, _, port = addr.rpartition(":")
    if host in ("", "0.0.0.0"):
        host = "127.0.0.1"
    return f"http://{host}:{port}"


_ENGINE_URL = get_engine_url()


def push_pending_order_to_engine(
    sample_id: str,
    tests: list[dict[str, str]],
    *,
    patient_id: str = "",
    patient_name: str = "",
    dob: str = "",
    sex: str = "",
    doctor_name: str = "",
    profile_id: str = "",
    timeout: float = 5.0,
) -> None:
    """Push a pending order to the Go engine so it can answer ASTM host queries.

    tests must be a list of {"test_code": "...", "test_name": "..."} dicts using
    the instrument's own test codes (not LIMS codes).

    Raises RuntimeError if the engine is unreachable or returns an error.
    """
    payload = {
        "sample_id": sample_id,
        "patient_id": patient_id,
        "patient_name": patient_name,
        "dob": dob,
        "sex": sex,
        "doctor_name": doctor_name,
        "tests": tests,
        "profile_id": profile_id,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{_ENGINE_URL}/api/v1/orders/pending",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status not in (200, 201):
                raise RuntimeError(f"Engine returned {resp.status}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach engine: {exc}") from exc
