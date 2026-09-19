from __future__ import annotations

import pytest

from spdxlims import instance, theme


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
