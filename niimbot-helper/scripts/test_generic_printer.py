"""Test-print a label on a Windows system printer.

Usage
-----
List available printers:
    python niimbot-helper/scripts/test_generic_printer.py

Print a test label (default 50x30 mm):
    python niimbot-helper/scripts/test_generic_printer.py "Printer Name"

Print a test label at a specific size:
    python niimbot-helper/scripts/test_generic_printer.py "Printer Name" 50 30

Run from the repo root.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generic_printer_bridge import detect_printers, print_label, resolve_printer_name


def main() -> int:
    args = sys.argv[1:]

    if not args:
        printers = detect_printers()
        if not printers:
            print("No Windows printers found.")
            return 1
        print(f"Found {len(printers)} printer(s):\n")
        for p in printers:
            print(f"  {p.model}  [{p.status}]")
        print("\nRe-run with a printer name to send a test label:")
        print(f'  python {Path(__file__).name} "Printer Name"')
        return 0

    printer_name_arg = args[0]
    width_mm = int(args[1]) if len(args) >= 2 else 50
    height_mm = int(args[2]) if len(args) >= 3 else 30

    printer_id = f"system:{printer_name_arg}"
    try:
        resolve_printer_name(printer_id)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Printer : {printer_name_arg}")
    print(f"Size    : {width_mm} x {height_mm} mm")
    print("Sending to printer...")
    try:
        print_label({
            "printer_id": printer_id,
            "label": {"width_mm": width_mm, "height_mm": height_mm},
            "content": {
                "barcode_value": "TEST",
                "human_text": "TEST",
                "text_lines": ["TEST PRINT", "SPDXLIMS"],
                "show_barcode": True,
            },
            "copies": 1,
        })
    except Exception as exc:  # noqa: BLE001
        print(f"Print failed: {exc}", file=sys.stderr)
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
