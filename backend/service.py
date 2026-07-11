"""Windows service wrapper for the SPDXLIMS FastAPI backend.

Usage (run from an elevated command prompt):
  python service.py install    -- register as auto-start Windows service
  python service.py start      -- start the service
  python service.py stop       -- stop the service
  python service.py remove     -- unregister and delete the service
  python service.py status     -- print current service state and exit
  python service.py debug      -- run in foreground (no service, Ctrl-C to stop)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
SERVICE_NAME = "SPDXLIMSBackend"
SERVICE_DISPLAY = "SPDXLIMS Backend API"
SERVICE_DESCRIPTION = "FastAPI backend for the SPDXLIMS clinical laboratory information system"
DEFAULT_PORT = 8001


def _load_env() -> dict[str, str]:
    env = os.environ.copy()
    env_file = BACKEND_DIR / ".env"
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip()
    return env


def _python_exe() -> str:
    """Return a real python.exe for launching uvicorn.

    When this module runs inside the Windows service host, sys.executable is
    pythonservice.exe, which cannot run "-m uvicorn". Prefer the backend venv's
    python.exe so the service starts reliably regardless of the host process.
    """
    candidate = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def _uvicorn_cmd() -> list[str]:
    return [_python_exe(), "-m", "uvicorn", "app.main:app",
            "--host", "0.0.0.0", "--port", str(DEFAULT_PORT)]


def run_debug() -> None:
    """Run uvicorn in the foreground (dev / smoke-test helper)."""
    env = _load_env()
    proc = subprocess.Popen(_uvicorn_cmd(), cwd=str(BACKEND_DIR), env=env)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()


def print_status() -> None:
    result = subprocess.run(
        ["sc", "query", SERVICE_NAME],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        print(f"Service '{SERVICE_NAME}' is not installed.")
    else:
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                print(line)


try:
    import win32event
    import win32service
    import win32serviceutil
    import servicemanager
    _HAS_WIN32 = True
except ImportError:
    _HAS_WIN32 = False


if _HAS_WIN32:
    class SPDXLIMSBackendService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = SERVICE_DISPLAY
        _svc_description_ = SERVICE_DESCRIPTION

        def __init__(self, args: list[str]) -> None:
            win32serviceutil.ServiceFramework.__init__(self, args)
            self._stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._process: subprocess.Popen | None = None

        def SvcStop(self) -> None:
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            if self._process is not None:
                self._process.terminate()
            win32event.SetEvent(self._stop_event)

        def SvcDoRun(self) -> None:
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            env = _load_env()
            self._process = subprocess.Popen(
                _uvicorn_cmd(),
                cwd=str(BACKEND_DIR),
                env=env,
            )
            win32event.WaitForSingleObject(self._stop_event, win32event.INFINITE)
            if self._process is not None:
                try:
                    self._process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._process.kill()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "debug":
        run_debug()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        print_status()
        return
    if not _HAS_WIN32:
        print("pywin32 is required to manage the Windows service.")
        print("Run: pip install pywin32")
        sys.exit(1)
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(SPDXLIMSBackendService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(SPDXLIMSBackendService)


if __name__ == "__main__":
    main()
