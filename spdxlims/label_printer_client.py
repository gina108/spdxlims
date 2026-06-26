from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class LabelPrinterError(RuntimeError):
    pass


@dataclass(slots=True)
class LabelPrinter:
    id: str
    model: str
    connection: str
    status: str


class LabelPrinterClient:
    """Dispatches label print jobs to the correct bridge (NIIMBOT or Windows GDI)."""

    def list_printers(self) -> list[LabelPrinter]:
        printers: list[LabelPrinter] = []
        for script in (self._niimbot_script(), self._generic_script()):
            if not script.exists():
                continue
            try:
                result = self._run_bridge(script, "list-printers", None)
                if isinstance(result, list):
                    for item in result:
                        if isinstance(item, dict) and item.get("id"):
                            printers.append(LabelPrinter(
                                id=str(item.get("id") or ""),
                                model=str(item.get("model") or ""),
                                connection=str(item.get("connection") or ""),
                                status=str(item.get("status") or ""),
                            ))
            except LabelPrinterError:
                pass
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
        density: int = 4,
    ) -> dict[str, Any]:
        payload = {
            "printer_id": printer_id,
            "label": {"width_mm": width_mm, "height_mm": height_mm},
            "content": {
                "barcode_type": "code39",
                "barcode_value": barcode_value,
                "human_text": human_text,
                "text_lines": text_lines,
                "show_barcode": show_barcode,
            },
            "copies": copies,
            "density": max(1, min(5, density)),
        }
        script = self._niimbot_script() if printer_id.startswith("niimbot:") else self._generic_script()
        return self._run_bridge(script, "print-label", json.dumps(payload).encode("utf-8"))

    def _run_bridge(self, script: Path, command: str, stdin_data: bytes | None) -> Any:
        if not script.exists():
            raise LabelPrinterError(
                f"Bridge script not found: {script.name}. "
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
            raise LabelPrinterError("The label printer bridge timed out.") from exc
        except OSError as exc:
            raise LabelPrinterError(f"Could not start the label printer bridge: {exc}") from exc
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise LabelPrinterError(self._translate_error(message) or f"Bridge exited with code {result.returncode}.")
        raw = result.stdout.decode("utf-8", errors="replace").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LabelPrinterError("The label printer bridge returned invalid JSON.") from exc

    @staticmethod
    def _translate_error(message: str) -> str:
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
    def _niimbot_script(cls) -> Path:
        return Path(__file__).resolve().parents[1] / "niimbot-helper" / "scripts" / "niimbot_bridge.py"

    @classmethod
    def _generic_script(cls) -> Path:
        return Path(__file__).resolve().parents[1] / "niimbot-helper" / "scripts" / "generic_printer_bridge.py"
