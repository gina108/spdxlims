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


def turn_icon(icon):
    """The same turn applied to a window icon, across every size it carries.

    An .ico holds several resolutions and Windows picks between them - the
    taskbar, the alt-tab switcher and the title bar all ask for different ones.
    Turning a single pixmap and rebuilding from that would throw the rest away
    and leave the icon soft wherever Windows wanted a size we no longer had, so
    each available size is turned and kept.

    Typed loosely for the same reason as turn_pixmap: this module has to import
    without Qt for the headless importer.
    """
    if _hue_shift() == 0:
        return icon
    from PySide6.QtGui import QIcon

    sizes = icon.availableSizes()
    if not sizes:
        return icon
    turned = QIcon()
    for size in sizes:
        turned.addPixmap(turn_pixmap(icon.pixmap(size)))
    return turned


def write_accent_icon(icon, path) -> bool:
    """Save this install's turned icon, for things that need a file on disk.

    A desktop shortcut stores a *path* to an icon, so it cannot follow the
    accent the way the running window does - it keeps showing whatever the
    shipped asset looks like. That left a blue install with a blue icon in the
    taskbar and a purple one on the desktop.

    Returns False when there is nothing to do, which includes a purple install:
    the shipped asset is already correct there, so the shortcut should point
    straight at it.
    """
    if _hue_shift() == 0:
        return False
    import struct

    from PySide6.QtCore import QBuffer

    # Every size the source carries, so Windows still has a crisp one for the
    # desktop, the taskbar and the small list views instead of scaling 256 down.
    images = []
    for size in sorted(icon.availableSizes(), key=lambda s: s.width()):
        if size.width() > 256 or size.height() > 256:
            continue
        pixmap = icon.pixmap(size)
        buffer = QBuffer()
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        if pixmap.save(buffer, "PNG"):
            images.append((pixmap.width(), pixmap.height(), bytes(buffer.data())))
    if not images:
        return False

    # ICONDIR, then one ICONDIRENTRY each, then the PNG payloads. A 256px side
    # is written as 0 - the field is one byte and 256 does not fit.
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    blobs = b""
    for width, height, blob in images:
        entries += struct.pack(
            "<BBBBHHII", width % 256, height % 256, 0, 0, 1, 32, len(blob), offset
        )
        offset += len(blob)
        blobs += blob
    try:
        path.write_bytes(header + entries + blobs)
    except OSError:
        return False
    return True


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
