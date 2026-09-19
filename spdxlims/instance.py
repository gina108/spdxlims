from __future__ import annotations

"""Per-installation identity.

Two copies of SPDXLIMS run on the same machine: the production local install
and this server-version checkout. Without separate identities Windows groups
them under one taskbar button and the single-instance mutex lets only one of
them start at a time.

Identity is read from an optional ``app_instance.json`` sitting next to
``app.py``:

    {"key": "server", "display_name": "SPDXLIMS Server", "icon": "SDXserver.ico",
     "accent": "blue"}

When that file is absent every value falls back to what the app has always
used, so an install without the file is unaffected in every respect - same
mutex name, same icon, the purple accent, and no AppUserModelID is set at all.
See spdxlims/theme.py for the accents.
"""

import json
from dataclasses import dataclass
from pathlib import Path

_LEGACY_MUTEX = "Global\\SPDXLIMS_SingleInstance"
_DEFAULT_ICON = "SDXSquarePurple.png"


@dataclass(frozen=True)
class AppInstance:
    key: str
    display_name: str
    icon_name: str
    mutex_name: str
    app_user_model_id: str | None
    # Named in spdxlims/theme.py, which owns the shades and ignores a name it
    # does not know. Empty means the original purple.
    accent: str = ""

    @property
    def is_default(self) -> bool:
        return not self.key


def _app_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default() -> AppInstance:
    return AppInstance(
        key="",
        display_name="SPDXLIMS",
        icon_name=_DEFAULT_ICON,
        mutex_name=_LEGACY_MUTEX,
        app_user_model_id=None,
    )


def _load() -> AppInstance:
    marker = _app_root() / "app_instance.json"
    try:
        # utf-8-sig, not utf-8: this file is hand-written on Windows, and
        # PowerShell's `Set-Content -Encoding utf8` prepends a BOM. Plain utf-8
        # then raises, the except below swallows it, and the install silently
        # reverts to the default identity - a marker that looks correct but has
        # no effect. utf-8-sig reads BOM-less files identically.
        raw = json.loads(marker.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return _default()
    if not isinstance(raw, dict):
        return _default()
    # Only alphanumerics survive: the key becomes part of a kernel object name
    # and an AppUserModelID, neither of which tolerates arbitrary characters.
    key = "".join(ch for ch in str(raw.get("key") or "") if ch.isalnum())
    if not key:
        return _default()
    return AppInstance(
        key=key,
        display_name=str(raw.get("display_name") or "SPDXLIMS"),
        icon_name=str(raw.get("icon") or _DEFAULT_ICON),
        mutex_name=f"{_LEGACY_MUTEX}_{key}",
        app_user_model_id=f"SPDXLIMS.{key}",
        accent=str(raw.get("accent") or ""),
    )


_INSTANCE: AppInstance | None = None


def app_instance() -> AppInstance:
    """Return this installation's identity, reading the marker file once."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = _load()
    return _INSTANCE


def icon_path() -> Path:
    """Absolute path to this installation's window icon."""
    return _app_root() / "assets" / app_instance().icon_name


def apply_windows_identity() -> None:
    """Give this process its own taskbar identity on Windows.

    Windows groups taskbar buttons by AppUserModelID, falling back to the host
    executable when none is set - which is why two apps launched through
    pythonw.exe share one button. Must run before any window is created.

    The default instance sets nothing, leaving existing installs untouched.
    """
    instance = app_instance()
    if instance.app_user_model_id is None:
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(instance.app_user_model_id)
    except Exception:
        pass
