"""Windows label printing bridge for generic system printers.

Routing:
  - "Generic / Text Only" driver  →  raw TSPL via win32print RAW
  - any other raster driver        →  GDI bitmap via win32ui + PIL.ImageWin

Commands:
  list-printers     → JSON array of Windows-installed printers
  print-label       → render and print a label (same JSON payload as niimbot_bridge)

Run from the repo root:
  python niimbot-helper/scripts/generic_printer_bridge.py list-printers
  python niimbot-helper/scripts/generic_printer_bridge.py print-label < payload.json
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from niimbot_bridge import BridgePrinter, render_label

import win32con
import win32print
import win32ui
from PIL import ImageWin


def main() -> int:
    if len(sys.argv) < 2:
        print("missing command", file=sys.stderr)
        return 2
    command = sys.argv[1].strip().lower()
    try:
        if command == "list-printers":
            printers = detect_printers()
            sys.stdout.write(json.dumps([p.__dict__ for p in printers]))
            return 0
        if command == "print-label":
            payload = json.loads(sys.stdin.read() or "{}")
            print_label(payload)
            sys.stdout.write(json.dumps({"ok": True}))
            return 0
        print(f"unknown command: {command}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1


def detect_printers() -> list[BridgePrinter]:
    printers: list[BridgePrinter] = []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    for info in win32print.EnumPrinters(flags, None, 2):
        name = str(info.get("pPrinterName") or "").strip()
        if not name:
            continue
        status = "ready" if (info.get("Status") or 0) == 0 else "busy"
        printers.append(BridgePrinter(id=f"system:{name}", model=name, connection="system", status=status))
    return printers


def print_label(payload: dict[str, Any]) -> None:
    printer_id = str(payload.get("printer_id") or "").strip()
    if not printer_id:
        raise RuntimeError("printer_id is required")
    printer_name = resolve_printer_name(printer_id)

    content = payload.get("content") or {}
    barcode_value = str(content.get("barcode_value") or "").strip()
    human_text = str(content.get("human_text") or "").strip()
    text_lines = list(content.get("text_lines") or [])
    show_barcode = bool(content.get("show_barcode", True))
    label = payload.get("label") or {}
    width_mm = int(label.get("width_mm") or 0)
    height_mm = int(label.get("height_mm") or 0)
    copies = max(1, int(payload.get("copies") or 1))
    gap_mm = max(0, int(payload.get("gap_mm") or 3))

    if show_barcode and not barcode_value:
        raise RuntimeError("content.barcode_value is required")
    if width_mm <= 0 or height_mm <= 0:
        raise RuntimeError("label size is required")

    image = render_label(width_mm, height_mm, barcode_value, human_text, text_lines, show_barcode=show_barcode)
    driver = _get_printer_driver(printer_name)

    if _is_tspl_driver(driver):
        _print_tspl(printer_name, image, width_mm, height_mm, gap_mm, copies)
    else:
        _print_gdi(image, printer_name, copies)


def resolve_printer_name(printer_id: str) -> str:
    lowered = printer_id.lower()
    if lowered == "system_default":
        return win32print.GetDefaultPrinter()
    if lowered.startswith("system:"):
        name = printer_id[len("system:"):].strip()
        if not name:
            return win32print.GetDefaultPrinter()
        return name
    raise RuntimeError(f"Unsupported printer_id for generic bridge: {printer_id!r}")


def _get_printer_driver(printer_name: str) -> str:
    h = win32print.OpenPrinter(printer_name)
    try:
        info = win32print.GetPrinter(h, 2)
        return str(info.get("pDriverName") or "")
    finally:
        win32print.ClosePrinter(h)


def _is_tspl_driver(driver_name: str) -> bool:
    lowered = driver_name.lower()
    return "text only" in lowered or "generic text" in lowered


# ── TSPL path ────────────────────────────────────────────────────────────────

def _print_tspl(
    printer_name: str,
    image: Any,
    width_mm: int,
    height_mm: int,
    gap_mm: int,
    copies: int,
) -> None:
    width_px, height_px = image.size
    width_bytes = math.ceil(width_px / 8)
    bitmap_bytes = _image_to_tspl_bitmap(image)

    header = (
        f"SIZE {width_mm} mm, {height_mm} mm\r\n"
        f"GAP {gap_mm} mm, 0 mm\r\n"
        "CLS\r\n"
        f"BITMAP 0,0,{width_bytes},{height_px},0,"
    ).encode("ascii")
    footer = f"\r\nPRINT {copies},1\r\n".encode("ascii")

    _raw_print(printer_name, header + bitmap_bytes + footer)


def _image_to_tspl_bitmap(image: Any) -> bytes:
    # TSPL BITMAP on the YAEN D3: bit 0 = print (black), bit 1 = no-print (white).
    # render_label() returns black text as pixel 0, white bg as pixel 255.
    # Converting directly to mode "1" maps 0→0 (black→print) and 255→1 (white→no-print).
    mono = image.convert("L").convert("1")
    width_px, height_px = mono.size
    width_bytes = math.ceil(width_px / 8)
    result = bytearray()
    for y in range(height_px):
        bits = "".join("0" if mono.getpixel((x, y)) == 0 else "1" for x in range(width_px))
        bits = bits.ljust(width_bytes * 8, "0")
        result.extend(int(bits, 2).to_bytes(width_bytes, "big"))
    return bytes(result)


def _raw_print(printer_name: str, data: bytes) -> None:
    h = win32print.OpenPrinter(printer_name)
    try:
        win32print.StartDocPrinter(h, 1, ("SPDXLIMS Label", None, "RAW"))
        try:
            win32print.StartPagePrinter(h)
            win32print.WritePrinter(h, data)
            win32print.EndPagePrinter(h)
        finally:
            win32print.EndDocPrinter(h)
    finally:
        win32print.ClosePrinter(h)


# ── GDI path (raster drivers with real Windows driver support) ───────────────

def _print_gdi(image: Any, printer_name: str, copies: int) -> None:
    hdc = win32ui.CreateDC()
    hdc.CreatePrinterDC(printer_name)
    try:
        page_w = hdc.GetDeviceCaps(win32con.HORZRES)
        page_h = hdc.GetDeviceCaps(win32con.VERTRES)
        img_w, img_h = image.size
        scale = min(page_w / img_w, page_h / img_h)
        dest_w = max(1, int(img_w * scale))
        dest_h = max(1, int(img_h * scale))
        x = (page_w - dest_w) // 2
        y = (page_h - dest_h) // 2
        dib = ImageWin.Dib(image.convert("RGB"))
        hdc.StartDoc("SPDXLIMS Label")
        for _ in range(copies):
            hdc.StartPage()
            dib.draw(hdc.GetHandleAttrib(), (x, y, x + dest_w, y + dest_h))
            hdc.EndPage()
        hdc.EndDoc()
    finally:
        hdc.DeleteDC()


if __name__ == "__main__":
    raise SystemExit(main())
