from __future__ import annotations

import json
import math
import serial
import struct
import sys
import time
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps
from niimprint import PrinterClient, SerialTransport
from niimprint.packet import NiimbotPacket
from serial.tools.list_ports import comports


NIIMBOT_VID = 0x3513
NIIMBOT_PID = 0x0002
PX_PER_MM_X = 8
PX_PER_MM_Y = 8
MAX_WIDTH_PX = 384


@dataclass
class BridgePrinter:
    id: str
    model: str
    connection: str
    status: str


@dataclass(frozen=True)
class LabelProfile:
    px_per_mm_x: int
    px_per_mm_y: int
    margin_x_ratio: float
    margin_top_ratio: float
    margin_bottom_ratio: float
    barcode_width_ratio: float
    barcode_top_ratio: float
    barcode_height_ratio: float
    text_gap_ratio: float
    patient_font_ratio: float
    detail_font_ratio: float
    order_top_ratio: float
    datetime_top_ratio: float
    min_barcode_height: int
    max_barcode_height: int


DEFAULT_PROFILE = LabelProfile(
    px_per_mm_x=PX_PER_MM_X,
    px_per_mm_y=PX_PER_MM_Y,
    margin_x_ratio=0.03,
    margin_top_ratio=0.01,
    margin_bottom_ratio=0.01,
    barcode_width_ratio=0.84,
    barcode_top_ratio=0.19,
    barcode_height_ratio=0.30,
    text_gap_ratio=0.055,
    patient_font_ratio=0.145,
    detail_font_ratio=0.085,
    order_top_ratio=0.73,
    datetime_top_ratio=0.87,
    min_barcode_height=40,
    max_barcode_height=62,
)


# Calibrated from physical test labels for the current NIIMBOT B1 + 50x30 stock.
B1_50X30_PROFILE = LabelProfile(
    px_per_mm_x=8,
    px_per_mm_y=8,
    margin_x_ratio=0.03,
    margin_top_ratio=0.008,
    margin_bottom_ratio=0.008,
    barcode_width_ratio=0.84,
    barcode_top_ratio=0.18,
    barcode_height_ratio=0.30,
    text_gap_ratio=0.055,
    patient_font_ratio=0.145,
    detail_font_ratio=0.085,
    order_top_ratio=0.72,
    datetime_top_ratio=0.86,
    min_barcode_height=40,
    max_barcode_height=62,
)


def main() -> int:
    if len(sys.argv) < 2:
        print("missing command", file=sys.stderr)
        return 2
    command = sys.argv[1].strip().lower()
    try:
        if command == "list-printers":
            printers = [printer.__dict__ for printer in detect_printers()]
            sys.stdout.write(json.dumps(printers))
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
    for port in comports():
        device = str(getattr(port, "device", "") or "").strip()
        description = str(getattr(port, "description", "") or "").strip()
        hwid = str(getattr(port, "hwid", "") or "").strip()
        vid = getattr(port, "vid", None)
        pid = getattr(port, "pid", None)
        if not device:
            continue
        if vid == NIIMBOT_VID and pid == NIIMBOT_PID:
            printers.append(BridgePrinter(id=f"usb:{device}", model="NIIMBOT B1", connection="usb", status="ready"))
            continue
        haystack = f"{description} {hwid}".upper()
        if "NIIMBOT" in haystack or "B1-I" in haystack:
            printers.append(BridgePrinter(id=f"usb:{device}", model="NIIMBOT B1", connection="usb", status="ready"))
    return printers


def print_label(payload: dict[str, Any]) -> None:
    printer_id = str(payload.get("printer_id") or "").strip()
    barcode_value = str(((payload.get("content") or {}).get("barcode_value")) or "").strip()
    human_text = str(((payload.get("content") or {}).get("human_text")) or "").strip()
    text_lines = list(((payload.get("content") or {}).get("text_lines")) or [])
    show_barcode = bool((payload.get("content") or {}).get("show_barcode", True))
    label = payload.get("label") or {}
    width_mm = int(label.get("width_mm") or 0)
    height_mm = int(label.get("height_mm") or 0)
    copies = max(1, int(payload.get("copies") or 1))
    if not printer_id:
        raise RuntimeError("printer_id is required")
    if show_barcode and not barcode_value:
        raise RuntimeError("content.barcode_value is required")
    if width_mm <= 0 or height_mm <= 0:
        raise RuntimeError("label size is required")

    density = max(1, min(5, int(payload.get("density") or 4)))
    port = resolve_port(printer_id)
    image = render_label(width_mm, height_mm, barcode_value, human_text, text_lines, show_barcode=show_barcode)
    print_b1_image(port, image, copies=copies, density=density)


def print_b1_image(port: str, image: Image.Image, *, copies: int, density: int) -> None:
    client = open_printer_client(port)
    try:
        reset_transport_buffers(client)
        for _copy_number in range(copies):
            transceive_required(client, 0x21, bytes((density,)), respoffset=16)
            transceive_required(client, 0x23, b"\x03", respoffset=16)
            # Newer B1 firmware expects total pages and page color in PrintStart.
            transceive_required(client, 0x01, struct.pack(">H5B", 1, 0, 0, 0, 0, 0))
            transceive_required(client, 0x03, b"\x01")
            # Printing one page per copy is more reliable than relying on the
            # printer firmware to duplicate the page internally.
            transceive_required(client, 0x13, struct.pack(">HHH", image.height, image.width, 1))

            for packet in encode_image_rows(image):
                client._send(packet)

            transceive_required(client, 0xE3, b"\x01")
            finish_b1_print(client)
    finally:
        close_printer_client(client)


def open_printer_client(port: str) -> PrinterClient:
    last_exc: Exception | None = None
    for dtr_state, rts_state in ((True, True), (False, False)):
        try:
            return PrinterClient(open_serial_transport(port, dtr_state=dtr_state, rts_state=rts_state))
        except Exception as exc:  # noqa: BLE001
            if not is_serial_configuration_error(exc):
                raise
            last_exc = exc
            time.sleep(0.2)
    if last_exc is not None:
        raise RuntimeError(describe_serial_error(port, last_exc)) from last_exc
    raise RuntimeError(f"Could not open NIIMBOT printer on {port}.")


def open_serial_transport(port: str, *, dtr_state: bool, rts_state: bool) -> SerialTransport:
    transport = SerialTransport.__new__(SerialTransport)
    serial_port = serial.Serial()
    serial_port.port = port
    serial_port.baudrate = 115200
    serial_port.timeout = 0.5
    serial_port.write_timeout = 2
    serial_port.dsrdtr = False
    serial_port.rtscts = False
    serial_port.xonxoff = False
    serial_port.dtr = dtr_state
    serial_port.rts = rts_state
    serial_port.open()
    transport._serial = serial_port
    return transport


def close_printer_client(client: PrinterClient) -> None:
    serial_port = getattr(getattr(client, "_transport", None), "_serial", None)
    if serial_port is None:
        return
    try:
        serial_port.close()
    except Exception:
        return


def is_serial_configuration_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return "cannot configure port" in message or "device attached to the system is not functioning" in message


def describe_serial_error(port: str, exc: Exception) -> str:
    message = str(exc or "").strip()
    lowered = message.lower()
    if "access is denied" in lowered:
        return f"{port} is busy. Close the NIIMBOT app or any other program using the printer, then try again."
    if "cannot configure port" in lowered or "device attached to the system is not functioning" in lowered:
        return (
            f"Windows could not initialize {port}. Reconnect the NIIMBOT printer, wait a few seconds, "
            "and try again. If it keeps happening, power-cycle the printer and close any other label software."
        )
    return message or f"Could not open NIIMBOT printer on {port}."


def reset_transport_buffers(client: PrinterClient) -> None:
    serial_port = getattr(getattr(client, "_transport", None), "_serial", None)
    if serial_port is None:
        return
    try:
        serial_port.reset_input_buffer()
        serial_port.reset_output_buffer()
    except Exception:
        return


def transceive_required(client: PrinterClient, reqcode: int, data: bytes, *, respoffset: int = 1) -> NiimbotPacket:
    packet = transceive(client, reqcode, data, respoffset=respoffset)
    if packet is None:
        raise RuntimeError(f"printer did not respond to command 0x{reqcode:02X}")
    if packet.data and packet.data[0] == 0 and reqcode in {0x01, 0x03, 0x13, 0x21, 0x23, 0xE3, 0xF3}:
        raise RuntimeError(f"printer rejected command 0x{reqcode:02X}")
    return packet


def transceive(client: PrinterClient, reqcode: int, data: bytes, *, respoffset: int = 1) -> NiimbotPacket | None:
    respcode = reqcode + respoffset
    client._send(NiimbotPacket(reqcode, data))
    response: NiimbotPacket | None = None
    for _ in range(10):
        for packet in client._recv():
            if packet.type == 0xDB:
                raise RuntimeError(f"printer returned an error for command 0x{reqcode:02X}")
            if packet.type == respcode:
                response = packet
        if response is not None:
            return response
        time.sleep(0.1)
    return None


def encode_image_rows(image: Image.Image):
    encoded = ImageOps.invert(image.convert("L")).convert("1")
    bytes_per_row = math.ceil(encoded.width / 8)
    for y in range(encoded.height):
        bits = "".join("0" if encoded.getpixel((x, y)) == 0 else "1" for x in range(encoded.width))
        line_data = int(bits, 2).to_bytes(bytes_per_row, "big")
        yield NiimbotPacket(0x85, struct.pack(">H3BB", y, 0, 0, 0, 1) + line_data)


def finish_b1_print(client: PrinterClient) -> None:
    time.sleep(0.3)
    deadline = time.monotonic() + 30
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            packet = transceive(client, 0xA3, b"\x01", respoffset=16)
            if packet is not None and len(packet.data) >= 4:
                page, page_print_progress, page_feed_progress = struct.unpack(">HBB", packet.data[:4])
                if page >= 1 and page_print_progress >= 100 and page_feed_progress >= 100:
                    break
        except Exception as exc:
            last_error = exc
        time.sleep(0.3)
    else:
        if last_error is not None:
            raise RuntimeError(f"printer did not report job completion: {last_error}")
        raise RuntimeError("printer did not report job completion")

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            packet = transceive(client, 0xF3, b"\x01")
        except Exception as exc:
            last_error = exc
            packet = None
        if packet is not None and packet.data and packet.data[0]:
            return
        time.sleep(0.2)
    if last_error is not None:
        raise RuntimeError(f"printer did not finish the job: {last_error}")
    raise RuntimeError("printer did not finish the job")


def resolve_port(printer_id: str) -> str:
    if printer_id.lower().startswith("usb:"):
        return printer_id.split(":", 1)[1].strip()
    printers = detect_printers()
    if len(printers) == 1:
        return printers[0].id.split(":", 1)[1]
    raise RuntimeError("Could not resolve NIIMBOT USB port.")


def get_label_profile(width_mm: int, height_mm: int) -> LabelProfile:
    if width_mm == 50 and height_mm == 30:
        return B1_50X30_PROFILE
    return DEFAULT_PROFILE


def render_label(
    width_mm: int,
    height_mm: int,
    barcode_value: str,
    human_text: str,
    text_lines: list[str],
    *,
    show_barcode: bool = True,
) -> Image.Image:
    profile = get_label_profile(width_mm, height_mm)
    width_px = min(MAX_WIDTH_PX, max(96, width_mm * profile.px_per_mm_x))
    height_px = max(96, height_mm * profile.px_per_mm_y)
    image = Image.new("L", (width_px, height_px), 255)
    draw = ImageDraw.Draw(image)

    margin_x = max(8, int(width_px * profile.margin_x_ratio))
    margin_top = max(3, int(height_px * profile.margin_top_ratio))
    margin_bottom = max(3, int(height_px * profile.margin_bottom_ratio))
    available_height = height_px - margin_top - margin_bottom
    visible_lines = [str(line or "").strip() for line in text_lines if str(line or "").strip()]

    text_top = margin_top + max(8, int(height_px * 0.06))
    if show_barcode:
        barcode_width = max(110, int(width_px * profile.barcode_width_ratio))
        barcode_left = (width_px - barcode_width) // 2
        barcode_top = margin_top + int(available_height * profile.barcode_top_ratio)
        barcode_height = max(profile.min_barcode_height, min(int(available_height * profile.barcode_height_ratio), profile.max_barcode_height))
        draw_code39(draw, sanitize_code39(barcode_value), barcode_left, barcode_top, barcode_width, barcode_height)
        text_top = barcode_top + barcode_height + max(8, int(height_px * profile.text_gap_ratio))
    text_bottom_limit = height_px - margin_bottom
    if visible_lines and text_top < text_bottom_limit:
        order_text = visible_lines[0] if len(visible_lines) >= 1 else ""
        patient_text = visible_lines[1] if len(visible_lines) >= 2 else ""
        datetime_text = visible_lines[2] if len(visible_lines) >= 3 else ""

        order_font = load_font(max(24, min(32, int(height_px * 0.16))))
        patient_font = load_font(max(18, min(24, int(height_px * 0.12))))
        detail_font = load_font(max(13, min(17, int(height_px * profile.detail_font_ratio))))
        order_to_name_gap = max(10, int(height_px * 0.05))
        name_to_date_gap = max(8, int(height_px * 0.04))

        current_top = text_top
        if order_text:
            draw_centered_fit_text(
                draw,
                order_text,
                order_font,
                width_px,
                margin_x,
                current_top,
                max_width=width_px - (margin_x * 2),
            )
            current_top += text_height(draw, order_text, order_font) + order_to_name_gap
        if patient_text and current_top < text_bottom_limit:
            draw_centered_fit_text(
                draw,
                patient_text,
                patient_font,
                width_px,
                margin_x,
                current_top,
                max_width=width_px - (margin_x * 2),
            )
            current_top += text_height(draw, patient_text, patient_font) + name_to_date_gap
        if datetime_text and current_top < text_bottom_limit:
            draw_centered_fit_text(
                draw,
                datetime_text,
                detail_font,
                width_px,
                margin_x,
                current_top,
                max_width=width_px - (margin_x * 2),
            )

    image = image.point(lambda px: 0 if px < 180 else 255, mode="1")
    return image.convert("L")


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_name in ("arial.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_centered_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width_px: int, top: int) -> None:
    left, _top, right, bottom = draw.textbbox((0, 0), text, font=font)
    text_width = max(1, right - left)
    draw.text(((width_px - text_width) / 2, top), text, font=font, fill=0)


def draw_centered_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    width_px: int,
    margin: int,
    top: int,
    bottom_limit: int,
) -> int:
    max_width = max(40, width_px - (margin * 2))
    words = text.split()
    if not words:
        return top

    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        left, _t, right, _b = draw.textbbox((0, 0), trial, font=font)
        if (right - left) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)

    line_height = max(1, font.size + 4)
    available_lines = max(1, (bottom_limit - top) // line_height)
    for line in lines[:available_lines]:
        draw_centered_text(draw, line, font, width_px, top)
        top += line_height
    return top + 2


def draw_centered_fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    width_px: int,
    margin: int,
    top: int,
    *,
    max_width: int,
) -> None:
    candidate = font
    while True:
        left, _t, right, _b = draw.textbbox((0, 0), text, font=candidate)
        if (right - left) <= max_width or getattr(candidate, "size", 8) <= 9:
            break
        candidate = load_font(max(9, candidate.size - 1))
    left, _t, right, _b = draw.textbbox((0, 0), text, font=candidate)
    text_width = max(1, right - left)
    x = max(margin, (width_px - text_width) / 2)
    draw.text((x, top), text, font=candidate, fill=0)


def text_height(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    _left, top, _right, bottom = draw.textbbox((0, 0), text, font=font)
    return max(1, bottom - top)


CODE39_PATTERNS = {
    "0": "nnnwwnwnn", "1": "wnnwnnnnw", "2": "nnwwnnnnw", "3": "wnwwnnnnn",
    "4": "nnnwwnnnw", "5": "wnnwwnnnn", "6": "nnwwwnnnn", "7": "nnnwnnwnw",
    "8": "wnnwnnwnn", "9": "nnwwnnwnn", "A": "wnnnnwnnw", "B": "nnwnnwnnw",
    "C": "wnwnnwnnn", "D": "nnnnwwnnw", "E": "wnnnwwnnn", "F": "nnwnwwnnn",
    "G": "nnnnnwwnw", "H": "wnnnnwwnn", "I": "nnwnnwwnn", "J": "nnnnwwwnn",
    "K": "wnnnnnnww", "L": "nnwnnnnww", "M": "wnwnnnnwn", "N": "nnnnwnnww",
    "O": "wnnnwnnwn", "P": "nnwnwnnwn", "Q": "nnnnnnwww", "R": "wnnnnnwwn",
    "S": "nnwnnnwwn", "T": "nnnnwnwwn", "U": "wwnnnnnnw", "V": "nwwnnnnnw",
    "W": "wwwnnnnnn", "X": "nwnnwnnnw", "Y": "wwnnwnnnn", "Z": "nwwnwnnnn",
    "-": "nwnnnnwnw", ".": "wwnnnnwnn", " ": "nwwnnnwnn", "$": "nwnwnwnnn",
    "/": "nwnwnnnwn", "+": "nwnnnwnwn", "%": "nnnwnwnwn", "*": "nwnnwnwnn",
}


def sanitize_code39(value: str) -> str:
    cleaned = "".join(ch for ch in value.upper() if ch in CODE39_PATTERNS and ch != "*")
    return cleaned or "LABEL"


def draw_code39(draw: ImageDraw.ImageDraw, token: str, x: int, y: int, width: int, height: int) -> None:
    encoded = "*" + token + "*"
    units: list[tuple[bool, int]] = []
    for character in encoded:
        pattern = CODE39_PATTERNS.get(character, CODE39_PATTERNS["-"])
        for index, width_code in enumerate(pattern):
            is_bar = index % 2 == 0
            unit_width = 3 if width_code == "w" else 1
            units.append((is_bar, unit_width))
        units.append((False, 1))
    total_units = sum(unit for _is_bar, unit in units) or 1
    unit_px = max(1.0, width / total_units)
    cursor = float(x)
    for is_bar, unit_width in units:
        segment_width = unit_width * unit_px
        if is_bar:
            draw.rectangle((int(round(cursor)), y, max(int(round(cursor + segment_width)) - 1, int(round(cursor))), y + height), fill=0)
        cursor += segment_width


if __name__ == "__main__":
    raise SystemExit(main())
