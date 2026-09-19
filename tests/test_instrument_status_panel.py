"""The analyzer status dots must reflect the live link, not a replayed capture.

The engine keeps one runtime_status row per (profile, device) and never expires
them. Re-parsing a stored capture writes that same row with transport "replay"
and state "active", so the newest row for a profile was often a replay - which
showed the COR 50 as connected while it was switched off.
"""

from __future__ import annotations

from spdxlims.pages.instrument_status_panel import InstrumentStatusPanel

states = InstrumentStatusPanel._states_by_profile

TCP_SERVER = {"type": "tcp_server", "listen_address": "0.0.0.0:5101", "remote_address": "10.0.0.3:5100"}
SERIAL = {"type": "serial"}


def _device(profile, device_id, transport, state, updated_at, settings=TCP_SERVER):
    return {
        "profile_id": profile,
        "device_id": device_id,
        "transport_type": transport,
        "session_state": state,
        "updated_at": updated_at,
        "selected_settings": settings,
    }


def test_a_replay_does_not_make_an_analyzer_look_connected():
    devices = [
        _device("cor50-lis", "0.0.0.0:5101", "tcp_server", "disconnected", "2026-09-18T19:40:00Z"),
        # Written by previewing a stored capture, and it is the newest row.
        _device("cor50-lis", "10.0.0.3:49158", "replay", "active", "2026-09-19T04:26:09Z"),
    ]

    assert states(devices) == {"cor50-lis": "disconnected"}


def test_a_live_client_connection_outranks_the_listener_row():
    devices = [
        _device("cor50-lis", "0.0.0.0:5101", "tcp_server", "disconnected", "2026-09-18T19:40:00Z"),
        _device("cor50-lis", "10.0.0.3:49160", "tcp_server", "active", "2026-09-19T15:00:00Z"),
    ]

    assert states(devices) == {"cor50-lis": "active"}


def test_a_client_that_went_away_is_reported_from_the_listener():
    """The engine records the disconnect on the listener, not on the client row."""
    devices = [
        _device("cor50-lis", "10.0.0.3:49157", "tcp_server", "active", "2026-09-12T16:54:24Z"),
        _device("cor50-lis", "0.0.0.0:5101", "tcp_server", "disconnected", "2026-09-18T19:40:00Z"),
    ]

    assert states(devices) == {"cor50-lis": "disconnected"}


def test_a_profile_with_nothing_but_replay_rows_is_unknown_rather_than_connected():
    devices = [_device("mindray-bc30s", "10.0.0.2:5100", "replay", "active", "2026-09-19T03:53:46Z",
                       {"type": "tcp_client", "remote_address": "10.0.0.2:5100"})]

    assert states(devices) == {}


def test_other_transports_are_untouched():
    devices = [
        _device("urinalysis-com6", "COM6", "serial", "idle", "2026-09-19T15:10:19Z", SERIAL),
        _device("cm250", r"\\DESKTOP-NV2MGRS\results", "file_drop", "active", "2026-09-18T21:30:51Z",
                {"type": "file_drop"}),
        _device("cm250", "180926.RES", "replay", "active", "2026-09-19T03:53:46Z", {"type": "file_drop"}),
    ]

    assert states(devices) == {"urinalysis-com6": "idle", "cm250": "active"}


def test_a_row_without_settings_still_counts():
    devices = [_device("cor50-lis", "COM3", "serial", "active", "2026-09-19T10:00:00Z", None)]

    assert states(devices) == {"cor50-lis": "active"}
