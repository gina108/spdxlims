"""The accent colour, per installation.

Two copies of SPDXLIMS run side by side on the same machine (see
spdxlims/instance.py) and looked identical, so it was easy to work in the wrong
window. The accent is therefore part of an installation's identity: set it in
``app_instance.json`` next to the key and the icon,

    {"key": "server", "display_name": "SPDXLIMS Server", "accent": "blue"}

and that copy wears blue chrome, while an install with no marker file keeps the
purple it has always had.

Rather than a second palette to keep in step with the first, the theme's colours
are turned by the angle between the two accents on the colour wheel, and only
the ones that are actually purple: lightness and saturation are untouched, so
contrast against the dark background is exactly as designed, and a shade added
to the theme later is carried along without being listed anywhere. Status
colours (the green/yellow/blue dots, error red) are nowhere near the purple band
and stay put.

Printed output is deliberately not recoloured. A report belongs to the lab, not
to whichever copy of the app produced it.
"""

from __future__ import annotations

import colorsys
import re

from spdxlims.instance import app_instance

# Hue in degrees. "purple" is where the theme already is, so it changes nothing.
ACCENT_HUES: dict[str, float] = {"purple": 264.0, "blue": 212.0}
DEFAULT_ACCENT = "purple"

# Everything the theme uses as purple falls inside this band; the accents that
# can be reached are the ones a band this wide can be turned onto.
_PURPLE_BAND = (235.0, 310.0)
_MIN_SATURATION = 0.08

_HEX_PATTERN = re.compile(r"#([0-9a-fA-F]{6})\b")


def accent_name() -> str:
    """The accent this installation asked for, or the original purple."""
    requested = str(app_instance().accent or "").strip().lower()
    return requested if requested in ACCENT_HUES else DEFAULT_ACCENT


def _hue_shift() -> float:
    return ACCENT_HUES[accent_name()] - ACCENT_HUES[DEFAULT_ACCENT]


def color(value: str) -> str:
    """This installation's stand-in for one colour, purple or not."""
    shift = _hue_shift()
    return value if shift == 0 else _turn(value, shift)


def rgb(value: str) -> tuple[int, int, int]:
    text = color(value).lstrip("#")
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def recolor(stylesheet: str) -> str:
    """Swap every purple in a stylesheet for this installation's accent."""
    shift = _hue_shift()
    if shift == 0:
        return stylesheet
    return _HEX_PATTERN.sub(lambda match: _turn(match.group(0), shift), stylesheet)


def turn_pixmap(pixmap):
    """The same turn applied to an image, for the purple wordmark in the drawer.

    Typed loosely so this module stays importable without Qt (the headless
    importer pulls in spdxlims.instance through it).
    """
    shift = _hue_shift()
    if shift == 0:
        return pixmap
    from PySide6.QtGui import QColor, QImage, QPixmap

    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() == 0:
                continue
            hue = pixel.hslHueF()
            if hue < 0:  # grey: no hue to turn
                continue
            degrees = hue * 360.0
            if pixel.hslSaturationF() < _MIN_SATURATION or not (_PURPLE_BAND[0] <= degrees <= _PURPLE_BAND[1]):
                continue
            turned = QColor.fromHslF(
                ((degrees + shift) % 360.0) / 360.0,
                pixel.hslSaturationF(),
                pixel.lightnessF(),
                pixel.alphaF(),
            )
            image.setPixelColor(x, y, turned)
    return QPixmap.fromImage(image)


def _turn(value: str, shift: float) -> str:
    text = value.lstrip("#")
    if len(text) != 6:
        return value
    try:
        red, green, blue = (int(text[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return value
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    degrees = hue * 360.0
    if saturation < _MIN_SATURATION or not (_PURPLE_BAND[0] <= degrees <= _PURPLE_BAND[1]):
        return value
    turned = colorsys.hls_to_rgb(((degrees + shift) % 360.0) / 360.0, lightness, saturation)
    return "#" + "".join(f"{round(channel * 255):02x}" for channel in turned)
