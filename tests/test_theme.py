from __future__ import annotations

import pytest

from pathlib import Path

from spdxlims import instance, theme

_ASSETS = Path(__file__).resolve().parents[1] / "assets"


@pytest.fixture()
def accent(monkeypatch):
    """Pretend this install asked for a given accent in app_instance.json."""

    def _set(name: str) -> None:
        monkeypatch.setattr(
            instance,
            "_INSTANCE",
            instance.AppInstance(
                key="server",
                display_name="SPDXLIMS Server",
                icon_name="SDXserver.ico",
                mutex_name="test",
                app_user_model_id=None,
                accent=name,
            ),
        )

    return _set


def test_an_install_without_a_marker_keeps_the_original_purple(monkeypatch):
    monkeypatch.setattr(instance, "_INSTANCE", None)
    monkeypatch.setattr(instance, "_app_root", lambda: instance.Path("/nonexistent"))

    assert theme.accent_name() == "purple"
    assert theme.color("#bd93f9") == "#bd93f9"
    assert theme.recolor("QPushButton { background: #bd93f9; }") == "QPushButton { background: #bd93f9; }"


def test_blue_turns_every_purple_in_a_stylesheet(accent):
    accent("blue")

    turned = theme.recolor("QPushButton { background: #bd93f9; border: 1px solid #392c4b; }")

    assert "#bd93f9" not in turned
    assert "#392c4b" not in turned
    # Same lightness, blue hue.
    assert turned.count("#") == 2


@pytest.mark.parametrize("keep", ["#3ddc84", "#4db8ff", "#f5c451", "#e06c75", "#1f232a", "#c3ccdf"])
def test_status_colours_and_neutrals_are_left_alone(accent, keep):
    accent("blue")

    assert theme.color(keep) == keep


def test_an_accent_the_theme_does_not_know_falls_back_to_purple(accent):
    accent("chartreuse")

    assert theme.accent_name() == "purple"
    assert theme.color("#bd93f9") == "#bd93f9"


def test_the_turn_keeps_lightness_so_contrast_is_unchanged(accent):
    accent("blue")

    for shade in ("#bd93f9", "#634b8a", "#392c4b"):
        before = sum(int(shade[i:i + 2], 16) for i in (1, 3, 5))
        after_hex = theme.color(shade)
        after = sum(int(after_hex[i:i + 2], 16) for i in (1, 3, 5))
        assert abs(before - after) <= 8


# ── The window icon follows the accent too ───────────────────────────────

def test_turn_icon_leaves_a_purple_install_completely_alone(accent):
    """Returns the very same object, so production does no work and no Qt is
    imported on the default path."""
    accent("purple")
    sentinel = object()
    assert theme.turn_icon(sentinel) is sentinel


def test_turn_icon_leaves_an_unknown_accent_alone(accent):
    accent("chartreuse")
    sentinel = object()
    assert theme.turn_icon(sentinel) is sentinel


def test_turn_icon_turns_the_colour_and_keeps_every_size(accent):
    """An .ico carries several resolutions; Windows picks between them, so a
    turn that collapsed them would leave the taskbar icon soft."""
    QtGui = pytest.importorskip("PySide6.QtGui")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QtWidgets.QApplication.instance() is None:
        try:
            QtWidgets.QApplication([])
        except Exception:  # no display of any kind available
            pytest.skip("Qt could not start")

    source = QtGui.QIcon(str(_ASSETS / "SDX.ico"))
    if not source.availableSizes():
        pytest.skip("icon asset unavailable")

    accent("blue")
    turned = theme.turn_icon(source)

    assert [(s.width(), s.height()) for s in turned.availableSizes()] == \
           [(s.width(), s.height()) for s in source.availableSizes()]

    def dominant_hue(pixmap):
        image = pixmap.toImage().convertToFormat(QtGui.QImage.Format_ARGB32)
        hues = {}
        for y in range(image.height()):
            for x in range(image.width()):
                colour = image.pixelColor(x, y)
                if colour.alpha() < 40 or colour.hslHueF() < 0 or colour.hslSaturationF() < 0.15:
                    continue
                bucket = round(colour.hslHueF() * 360 / 10) * 10
                hues[bucket] = hues.get(bucket, 0) + 1
        return max(hues, key=hues.get) if hues else None

    biggest = source.availableSizes()[-1]
    assert 235 <= dominant_hue(source.pixmap(biggest)) <= 310   # purple before
    assert 190 <= dominant_hue(turned.pixmap(biggest)) < 235    # blue after
