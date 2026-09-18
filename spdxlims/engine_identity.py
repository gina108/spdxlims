"""Which checkout is allowed to drive the analyzers.

An analyzer can only be owned by one process. On this site the production
install runs the engine as the ``InstrumentConnectivityEngine`` Windows
service; a second checkout that starts its own engine will happily seize COM6,
the COR50 listener on 5101 and the Mindray socket, and consume CM250 drop files
before the real lab ever sees them.

A checkout therefore only touches hardware when it is the one the service runs
from. Every other checkout is a read-only consumer: it may poll the engine for
captures (``GET /api/v1/captures`` is a plain SELECT and never consumes), but it
must not open sessions, spawn an engine, or push orders to an instrument.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from urllib.parse import urlparse

SERVICE_NAME = "InstrumentConnectivityEngine"

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _deployment_config() -> dict:
    """Read data\\deployment.json the way app.py locates it (cwd-relative)."""
    try:
        raw = json.loads((Path.cwd() / "data" / "deployment.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def is_remote_client() -> bool:
    """True when this install is a workstation talking to a server elsewhere.

    Such a machine has no analyzers of its own, and critically no engine service
    either - so the "no service installed, therefore I am the only engine" rule
    below would otherwise let it spawn an engine and open the shared profiles.
    The CM250 profile watches a UNC path, which a workstation can reach, so it
    would consume the live lab's drop files from across the network.
    """
    config = _deployment_config()
    if str(config.get("mode") or "local").strip().lower() != "server":
        return False
    host = (urlparse(str(config.get("server_url") or "").strip()).hostname or "").lower()
    return bool(host) and host not in _LOOPBACK


def service_data_dir(service_name: str = SERVICE_NAME) -> Path | None:
    """Data directory of the installed engine service, or None if absent.

    Read from the registry rather than ``sc qc`` because the field labels in
    ``sc`` output are localised, and this site runs Spanish Windows.
    """
    try:
        import winreg
    except ImportError:  # non-Windows
        return None
    key = rf"SYSTEM\CurrentControlSet\Services\{service_name}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            image_path, _ = winreg.QueryValueEx(handle, "ImagePath")
    except OSError:
        return None
    try:
        tokens = shlex.split(str(image_path), posix=False)
    except ValueError:
        return None
    for index, token in enumerate(tokens):
        if token.lower() == "-data-dir" and index + 1 < len(tokens):
            return Path(tokens[index + 1].strip('"'))
    return None


def owns_hardware(runtime_dir: Path) -> bool:
    """True when the checkout using ``runtime_dir`` may open the analyzers.

    No service installed means this engine is the only one, so it owns the
    hardware by default - but only on a machine that could actually have
    analyzers wired to it, never on a client workstation.
    """
    if is_remote_client():
        return False
    installed = service_data_dir()
    if installed is None:
        return True
    try:
        return installed.resolve() == Path(runtime_dir).resolve()
    except OSError:
        return False
