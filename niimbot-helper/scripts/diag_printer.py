"""Diagnostic script — probes the NIIMBOT B1 and shows raw responses.

Run from the repo root:
    python niimbot-helper/scripts/diag_printer.py [COM4]

Each test opens a fresh connection so earlier failures can't contaminate later tests.
"""
from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from niimbot_bridge import (
    detect_printers,
    open_printer_client,
    close_printer_client,
    reset_transport_buffers,
)
from niimprint import PrinterClient
from niimprint.packet import NiimbotPacket


def send_raw(client: PrinterClient, reqcode: int, data: bytes) -> list[NiimbotPacket]:
    client._send(NiimbotPacket(reqcode, data))
    received: list[NiimbotPacket] = []
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        for pkt in client._recv():
            received.append(pkt)
        time.sleep(0.05)
    return received


def fmt(packets: list[NiimbotPacket]) -> str:
    if not packets:
        return "(no response)"
    return "  |  ".join(f"type=0x{p.type:02X} data=[{p.data.hex()}]" for p in packets)


def fresh_client(port: str) -> PrinterClient:
    time.sleep(0.3)
    client = open_printer_client(port)
    time.sleep(0.15)
    reset_transport_buffers(client)
    return client


def run_sequence(port: str, label: str, steps: list[tuple[int, bytes]]) -> None:
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"{'='*60}")
    client = fresh_client(port)
    try:
        for reqcode, data in steps:
            packets = send_raw(client, reqcode, data)
            status = fmt(packets)
            has_db = any(p.type == 0xDB for p in packets)
            ok = any(p.type == reqcode + 1 or p.type == reqcode + 0x10 for p in packets)
            flag = "✓" if ok else ("✗ ERROR" if has_db else "? no match")
            print(f"  0x{reqcode:02X}  [{data.hex()}]  →  {status}  {flag}")
            if has_db:
                print("       ^ printer sent error — stopping this test")
                break
    finally:
        close_printer_client(client)


def main() -> None:
    if len(sys.argv) >= 2:
        port = sys.argv[1]
    else:
        printers = detect_printers()
        if not printers:
            print("No NIIMBOT printer found.")
            return
        port = printers[0].id.split(":", 1)[1]

    print(f"Port: {port}")

    W, H = 384, 240  # 50x30mm label

    # Test A: original sequence with 7-byte PrintStart
    run_sequence(port, "Original: density→labeltype1→PrintStart(7byte)", [
        (0x21, bytes([4])),
        (0x23, b"\x01"),
        (0x01, struct.pack(">H5B", 1, 0, 0, 0, 0, 0)),
    ])

    # Test B: 2-byte PrintStart
    run_sequence(port, "2-byte PrintStart: density→labeltype1→PrintStart(2byte)", [
        (0x21, bytes([4])),
        (0x23, b"\x01"),
        (0x01, struct.pack(">H", 1)),
    ])

    # Test C: label type 3 + 7-byte PrintStart
    run_sequence(port, "LabelType3 + PrintStart(7byte)", [
        (0x21, bytes([4])),
        (0x23, b"\x03"),
        (0x01, struct.pack(">H5B", 1, 0, 0, 0, 0, 0)),
    ])

    # Test D: label type 2 (continuous) + 7-byte PrintStart
    run_sequence(port, "LabelType2(continuous) + PrintStart(7byte)", [
        (0x21, bytes([4])),
        (0x23, b"\x02"),
        (0x01, struct.pack(">H5B", 1, 0, 0, 0, 0, 0)),
    ])

    # Test E: label type 3 + 2-byte PrintStart
    run_sequence(port, "LabelType3 + PrintStart(2byte)", [
        (0x21, bytes([4])),
        (0x23, b"\x03"),
        (0x01, struct.pack(">H", 1)),
    ])

    # Test F: label type 2 + 2-byte PrintStart
    run_sequence(port, "LabelType2(continuous) + PrintStart(2byte)", [
        (0x21, bytes([4])),
        (0x23, b"\x02"),
        (0x01, struct.pack(">H", 1)),
    ])

    # Test G: density 3 (original) + label type 1 + 7-byte
    run_sequence(port, "Density3 + LabelType1 + PrintStart(7byte) [original params]", [
        (0x21, bytes([3])),
        (0x23, b"\x01"),
        (0x01, struct.pack(">H5B", 1, 0, 0, 0, 0, 0)),
    ])

    # Test H: if any PrintStart works, try the full sequence
    run_sequence(port, "Full sequence: density→type1→start→prepare→dim→(no image)", [
        (0x21, bytes([4])),
        (0x23, b"\x01"),
        (0x01, struct.pack(">H5B", 1, 0, 0, 0, 0, 0)),
        (0x03, b"\x01"),
        (0x13, struct.pack(">HHH", H, W, 1)),
    ])

    print("\nDone. Paste results here.")


if __name__ == "__main__":
    main()
