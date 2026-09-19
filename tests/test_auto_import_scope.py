"""Which installs run the in-app capture auto-import.

It posts one request per capture, synchronously, on the UI thread. On a
workstation with a few hundred captures to consider that froze the app for
minutes at a time - the symptom was "python is not responding" on close - and
it was redundant anyway: the machine wired to the analyzers already imports
into the same database the workstation reads.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spdxlims.engine_identity import is_remote_client
from spdxlims.instrument_importer import heartbeat_path, importer_is_running


@pytest.fixture()
def install():
    """Become an install of a given shape; cwd is restored before cleanup."""
    original = os.getcwd()
    made: list[tempfile.TemporaryDirectory] = []

    def _become(mode: str, server_url: str = "") -> Path:
        tmp = tempfile.TemporaryDirectory()
        made.append(tmp)
        data = Path(tmp.name) / "data"
        data.mkdir()
        payload = {"mode": mode}
        if server_url:
            payload["server_url"] = server_url
        (data / "deployment.json").write_text(json.dumps(payload), encoding="utf-8")
        os.chdir(tmp.name)
        return data

    yield _become
    os.chdir(original)  # before cleanup: Windows will not remove the cwd
    for tmp in made:
        tmp.cleanup()


def _should_skip(data_dir: Path) -> bool:
    """The guard exactly as results_page applies it."""
    return is_remote_client() or importer_is_running(data_dir)


def test_a_workstation_never_auto_imports(install):
    data = install("server", "http://10.0.0.10:8001")
    # No heartbeat here: the importer runs on the other machine entirely, so
    # without the remote-client check this workstation would import.
    assert importer_is_running(data) is False
    assert _should_skip(data) is True


def test_the_analyzer_machine_still_auto_imports_when_no_importer_runs(install):
    """Loopback server_url: this is the machine with the engine, and with no
    headless importer installed the app is the only thing that would import."""
    data = install("server", "http://127.0.0.1:8001")
    assert _should_skip(data) is False


def test_it_still_stands_down_for_the_headless_importer(install):
    data = install("server", "http://127.0.0.1:8001")
    heartbeat_path(data).write_text(
        json.dumps({"written_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8"
    )
    assert _should_skip(data) is True


def test_a_stale_heartbeat_hands_the_work_back(install):
    """If the importer task dies, the app on that machine takes over again."""
    data = install("server", "http://127.0.0.1:8001")
    heartbeat_path(data).write_text(
        json.dumps({"written_at": "2020-01-01T00:00:00+00:00"}), encoding="utf-8"
    )
    assert _should_skip(data) is False
