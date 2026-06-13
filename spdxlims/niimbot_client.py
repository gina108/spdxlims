from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class NIIMBOTClientError(RuntimeError):
    pass


@dataclass(slots=True)
class NIIMBOTPrinter:
    id: str
    model: str
    connection: str
    status: str


class NIIMBOTClient:
    def list_printers(self) -> list[NIIMBOTPrinter]:
        payload = self._run_bridge("list-printers", stdin_data=None)
        if not isinstance(payload, list):
            raise NIIMBOTClientError("Unexpected printers response from NIIMBOT bridge.")
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
        return self._run_bridge("print-label", stdin_data=json.dumps(payload).encode("utf-8"))

    def _run_bridge(self, command: str, *, stdin_data: bytes | None) -> Any:
        script = self._bridge_script()
        if not script.exists():
            raise NIIMBOTClientError(
                "The NIIMBOT bridge script was not found. "
                "Make sure the niimbot-helper directory is present next to the application."
            )
        creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            result = subprocess.run(
                [sys.executable, str(script), command],
                input=stdin_data,
                capture_output=True,
                timeout=90,
                creationflags=creation_flags,
            )
        except subprocess.TimeoutExpired as exc:
            raise NIIMBOTClientError("The NIIMBOT bridge timed out.") from exc
        except OSError as exc:
            raise NIIMBOTClientError(f"Could not start the NIIMBOT bridge: {exc}") from exc
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise NIIMBOTClientError(self._translate_bridge_error(message) or f"NIIMBOT bridge exited with code {result.returncode}.")
        raw = result.stdout.decode("utf-8", errors="replace").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise NIIMBOTClientError("The NIIMBOT bridge returned invalid JSON.") from exc

    @staticmethod
    def _translate_bridge_error(message: str) -> str:
        if not message:
            return message
        lowered = message.lower()
        if "access is denied" in lowered and ("port" in lowered or "niimbot" in lowered):
            return "The NIIMBOT port is busy. Close the NIIMBOT app or any other program using the printer, then try again."
        if "cannot configure port" in lowered or "device attached to the system is not functioning" in lowered:
            return (
                "Windows could not initialize the NIIMBOT USB port. Reconnect the printer, wait a few "
                "seconds, and try again. If it keeps happening, power-cycle the printer and close any "
                "other label software."
            )
        return message

    @classmethod
    def _bridge_script(cls) -> Path:
        return Path(__file__).resolve().parents[1] / "niimbot-helper" / "scripts" / "niimbot_bridge.py"
