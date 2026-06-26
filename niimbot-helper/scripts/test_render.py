"""Quick render test — saves label PNGs without needing the printer.

Run from the repo root:
    python niimbot-helper/scripts/test_render.py

Outputs label_render_*.png files next to this script.
"""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from niimbot_bridge import render_label, encode_image_rows
from PIL import Image, ImageDraw, ImageFont


CASES = [
    {
        "name": "50x30_full",
        "width_mm": 50,
        "height_mm": 30,
        "barcode_value": "ORD-2026-001",
        "human_text": "ORD-2026-001",
        "text_lines": ["ORD-2026-001", "GARCIA LOPEZ, JUAN", "2026-06-16  M  45a"],
        "show_barcode": True,
    },
    {
        "name": "50x30_no_barcode",
        "width_mm": 50,
        "height_mm": 30,
        "barcode_value": "",
        "human_text": "ORD-2026-001",
        "text_lines": ["ORD-2026-001", "GARCIA LOPEZ, JUAN", "2026-06-16  M  45a"],
        "show_barcode": False,
    },
    {
        "name": "50x30_barcode_only",
        "width_mm": 50,
        "height_mm": 30,
        "barcode_value": "ORD2026001",
        "human_text": "ORD2026001",
        "text_lines": [],
        "show_barcode": True,
    },
    {
        "name": "50x20_tube",
        "width_mm": 50,
        "height_mm": 20,
        "barcode_value": "ORD-2026-001",
        "human_text": "ORD-2026-001",
        "text_lines": ["ORD-2026-001", "GARCIA LOPEZ, JUAN"],
        "show_barcode": True,
    },
    {
        "name": "40x20_vial",
        "width_mm": 40,
        "height_mm": 20,
        "barcode_value": "ORD2026001",
        "human_text": "ORD2026001",
        "text_lines": ["ORD-2026-001", "GARCIA, JUAN"],
        "show_barcode": True,
    },
]


def pixel_stats(image: Image.Image) -> str:
    """Return a quick summary of pixel values to detect all-white/all-black issues."""
    gray = image.convert("L")
    pixels = list(gray.getdata())
    total = len(pixels)
    white = sum(1 for p in pixels if p >= 200)
    black = sum(1 for p in pixels if p <= 50)
    pct_white = white / total * 100
    pct_black = black / total * 100
    return f"white={pct_white:.1f}% black={pct_black:.1f}% total={total}px"


def encoded_stats(image: Image.Image) -> str:
    """Simulate encode_image_rows and report how many bits are set (print dots)."""
    from PIL import ImageOps
    encoded = ImageOps.invert(image.convert("L")).convert("1")
    total_bits = 0
    set_bits = 0
    for y in range(encoded.height):
        for x in range(encoded.width):
            total_bits += 1
            if encoded.getpixel((x, y)) != 0:
                set_bits += 1
    pct = set_bits / total_bits * 100 if total_bits else 0
    return f"print_dots={pct:.1f}% ({set_bits}/{total_bits})"


def main() -> None:
    out_dir = Path(__file__).parent
    print(f"Saving PNGs to: {out_dir}\n")

    all_ok = True
    for case in CASES:
        name = case["name"]
        try:
            img = render_label(
                case["width_mm"],
                case["height_mm"],
                case["barcode_value"],
                case["human_text"],
                case["text_lines"],
                show_barcode=case["show_barcode"],
            )
            # Save the raw render
            out_path = out_dir / f"label_render_{name}.png"
            img.save(str(out_path))

            pstats = pixel_stats(img)
            estats = encoded_stats(img)
            status = "OK"

            # Warn if almost entirely white (blank label)
            gray = img.convert("L")
            pixels = list(gray.getdata())
            pct_white = sum(1 for p in pixels if p >= 200) / len(pixels) * 100
            if pct_white > 98:
                status = "BLANK WARNING"
                all_ok = False

            print(f"[{status}] {name}")
            print(f"  size: {img.width}x{img.height}px ({case['width_mm']}x{case['height_mm']}mm)")
            print(f"  pixels: {pstats}")
            print(f"  encoded: {estats}")
            print(f"  saved: {out_path.name}")
        except Exception as exc:
            print(f"[ERROR] {name}: {exc}")
            all_ok = False
        print()

    if all_ok:
        print("All renders look OK. Open the PNG files to visually inspect.")
    else:
        print("WARNING: One or more labels appear blank or errored. Check the PNG files.")


if __name__ == "__main__":
    main()
