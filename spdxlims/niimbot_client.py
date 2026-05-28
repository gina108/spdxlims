from __future__ import annotations

import json
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class NIIMBOTClientError(RuntimeError):
    pass


@dataclass(slots=True)
class NIIMBOTPrinter:
    id: str
    model: str
    connection: str
    status: str


class NIIMBOTClient:
    _helper_launch_attempted = False
    _helper_restart_attempted = False

    def __init__(self, base_url: str = "http://127.0.0.1:9091") -> None:
        self.base_url = base_url.rstrip("/")

    def health_check(self) -> dict[str, Any]:
        return self._get_json("/health", timeout=5)

    def list_printers(self) -> list[NIIMBOTPrinter]:
        payload = self._get_json("/printers", timeout=5)
        if not isinstance(payload, list):
            raise NIIMBOTClientError("Unexpected printers response from NIIMBOT helper.")
        printers: list[NIIMBOTPrinter] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            printers.append(
                NIIMBOTPrinter(
                    id=str(item.get("id") or ""),
                    model=str(item.get("model") or ""),
                    connection=str(item.get("connection") or ""),
                    status=str(item.get("status") or ""),
                )
            )
        return printers

    def print_label(
        self,
        *,
        printer_id: str,
        width_mm: int,
        height_mm: int,
        barcode_value: str,
        human_text: str,
        text_lines: list[str],
        show_barcode: bool = True,
        copies: int = 1,
    ) -> dict[str, Any]:
        payload = {
            "printer_id": printer_id,
            "label": {
                "width_mm": width_mm,
                "height_mm": height_mm,
            },
            "content": {
                "barcode_type": "code39",
                "barcode_value": barcode_value,
                "human_text": human_text,
                "text_lines": text_lines,
                "show_barcode": show_barcode,
            },
            "copies": copies,
        }
        return self._post_json("/print/niimbot-label", payload, timeout=90)

    def _get_json(self, path: str, *, timeout: float) -> Any:
        request = Request(self.base_url + path, method="GET")
        return self._read_json(request, timeout=timeout)

    def _post_json(self, path: str, payload: dict[str, Any], *, timeout: float) -> Any:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        return self._read_json(request, timeout=timeout)

    def _read_json(self, request: Request, *, timeout: float) -> Any:
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except TimeoutError as exc:
            if self._restart_helper_if_available():
                try:
                    with urlopen(request, timeout=timeout) as response:
                        raw = response.read().decode("utf-8")
                except (TimeoutError, socket.timeout) as retry_exc:
                    raise NIIMBOTClientError("The NIIMBOT helper timed out while responding.") from retry_exc
                except HTTPError as retry_exc:
                    detail = self._extract_http_error_message(retry_exc)
                    raise NIIMBOTClientError(detail or f"NIIMBOT helper HTTP error: {retry_exc.code}") from retry_exc
                except URLError as retry_exc:
                    raise NIIMBOTClientError("Could not connect to the NIIMBOT helper.") from retry_exc
            else:
                raise NIIMBOTClientError("The NIIMBOT helper timed out while responding.") from exc
        except socket.timeout as exc:
            if self._restart_helper_if_available():
                try:
                    with urlopen(request, timeout=timeout) as response:
                        raw = response.read().decode("utf-8")
                except (TimeoutError, socket.timeout) as retry_exc:
                    raise NIIMBOTClientError("The NIIMBOT helper timed out while responding.") from retry_exc
                except HTTPError as retry_exc:
                    detail = self._extract_http_error_message(retry_exc)
                    raise NIIMBOTClientError(detail or f"NIIMBOT helper HTTP error: {retry_exc.code}") from retry_exc
                except URLError as retry_exc:
                    raise NIIMBOTClientError("Could not connect to the NIIMBOT helper.") from retry_exc
            else:
                raise NIIMBOTClientError("The NIIMBOT helper timed out while responding.") from exc
        except URLError as exc:
            if self._start_helper_if_available():
                try:
                    with urlopen(request, timeout=timeout) as response:
                        raw = response.read().decode("utf-8")
                except TimeoutError as retry_exc:
                    raise NIIMBOTClientError("The NIIMBOT helper timed out while responding.") from retry_exc
                except socket.timeout as retry_exc:
                    raise NIIMBOTClientError("The NIIMBOT helper timed out while responding.") from retry_exc
                except HTTPError as retry_exc:
                    detail = self._extract_http_error_message(retry_exc)
                    raise NIIMBOTClientError(detail or f"NIIMBOT helper HTTP error: {retry_exc.code}") from retry_exc
                except URLError as retry_exc:
                    raise NIIMBOTClientError("Could not connect to the NIIMBOT helper.") from retry_exc
            else:
                raise NIIMBOTClientError("Could not connect to the NIIMBOT helper.") from exc
        except HTTPError as exc:
            detail = self._extract_http_error_message(exc)
            raise NIIMBOTClientError(detail or f"NIIMBOT helper HTTP error: {exc.code}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise NIIMBOTClientError("NIIMBOT helper returned invalid JSON.") from exc

    @staticmethod
    def _extract_http_error_message(exc: HTTPError) -> str:
        raw = exc.read().decode("utf-8", errors="ignore")
        if not raw:
            return ""
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        if isinstance(payload, dict):
            message = str(payload.get("error") or "").strip()
            if message:
                lowered = message.lower()
                if "access is denied" in lowered and "could not open port" in lowered:
                    return "The NIIMBOT port is busy. Close the NIIMBOT app or any other program using the printer, then try again."
                if "windows could not initialize com" in lowered:
                    return message
                if "cannot configure port" in lowered or "device attached to the system is not functioning" in lowered:
                    return (
                        "Windows could not initialize the NIIMBOT USB port. Reconnect the printer, wait a few "
                        "seconds, and try again. If it keeps happening, power-cycle the printer and close any "
                        "other label software."
                    )
                return message
        return raw

    @classmethod
    def _helper_executable(cls) -> Path:
        return Path(__file__).resolve().parents[1] / "niimbot-helper" / "helper.exe"

    @classmethod
    def _kill_helper_processes(cls) -> None:
        try:
            subprocess.run(
                ["taskkill", "/IM", "helper.exe", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                check=False,
                creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            )
        except OSError:
            pass

    def _start_helper_if_available(self) -> bool:
        cls = type(self)
        if cls._helper_launch_attempted:
            return False
        helper_path = self._helper_executable()
        if not helper_path.exists():
            cls._helper_launch_attempted = True
            return False
        creation_flags = 0
        for flag_name in ("CREATE_NO_WINDOW", "DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
            creation_flags |= int(getattr(subprocess, flag_name, 0))
        try:
            subprocess.Popen(
                [str(helper_path)],
                cwd=str(helper_path.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
        except OSError:
            cls._helper_launch_attempted = True
            return False
        cls._helper_launch_attempted = True
        return self._wait_for_helper(self.base_url)

    def _restart_helper_if_available(self) -> bool:
        cls = type(self)
        if cls._helper_restart_attempted:
            return False
        helper_path = self._helper_executable()
        if not helper_path.exists():
            cls._helper_restart_attempted = True
            return False
        cls._helper_restart_attempted = True
        cls._helper_launch_attempted = False
        self._kill_helper_processes()
        time.sleep(0.5)
        return self._start_helper_if_available()

    @classmethod
    def _wait_for_helper(cls, base_url: str, timeout_seconds: float = 6.0) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                request = Request(base_url.rstrip("/") + "/health", method="GET")
                with urlopen(request, timeout=1.5) as response:
                    return response.status == 200
            except Exception:
                time.sleep(0.25)
        return False
