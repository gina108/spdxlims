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

import shlex
from pathlib import Path

SERVICE_NAME = "InstrumentConnectivityEngine"


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
    hardware by default.
    """
    installed = service_data_dir()
    if installed is None:
        return True
    try:
        return installed.resolve() == Path(runtime_dir).resolve()
    except OSError:
        return False
