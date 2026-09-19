"""Config files are hand-edited on Windows, where a BOM is easy to introduce.

PowerShell's `Set-Content -Encoding utf8` writes UTF-8 *with* a BOM on Windows
PowerShell 5.1. Every reader here catches its own parse errors and falls back to
a default, so a BOM produced no error anywhere - just a file that looked right
and did nothing. These pin the tolerance in place.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

BOM = "﻿"


def _write_with_bom(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(BOM + json.dumps(payload), encoding="utf-8")


def test_the_fixture_really_writes_a_bom(tmp_path):
    """Guard the guard: if this stops writing a BOM the others prove nothing."""
    target = tmp_path / "x.json"
    _write_with_bom(target, {"a": 1})
    assert target.read_bytes()[:3] == b"\xef\xbb\xbf"
    with pytest.raises(ValueError):
        json.loads(target.read_text(encoding="utf-8"))


def test_app_instance_marker_survives_a_bom(tmp_path, monkeypatch):
    import spdxlims.instance as instance

    _write_with_bom(tmp_path / "app_instance.json", {
        "key": "lab2", "display_name": "SPDXLIMS LAB2", "accent": "blue",
    })
    monkeypatch.setattr(instance, "_app_root", lambda: tmp_path)
    monkeypatch.setattr(instance, "_INSTANCE", None)

    loaded = instance._load()
    assert loaded.key == "lab2"
    assert loaded.accent == "blue"
    assert loaded.display_name == "SPDXLIMS LAB2"


def test_deployment_config_survives_a_bom(tmp_path):
    from spdxlims.deployment import DeploymentService

    config = tmp_path / "deployment.json"
    _write_with_bom(config, {"mode": "server", "server_url": "http://10.0.0.10:8001"})

    loaded = DeploymentService(config).load()
    assert loaded.mode == "server"          # not silently "local"
    assert loaded.server_url == "http://10.0.0.10:8001"


def test_remote_client_detection_survives_a_bom(tmp_path):
    """A BOM here used to read as 'not a remote client', which is what lets a
    checkout open the analyzers."""
    from spdxlims.engine_identity import is_remote_client

    _write_with_bom(tmp_path / "data" / "deployment.json", {
        "mode": "server", "server_url": "http://10.0.0.10:8001",
    })
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert is_remote_client() is True
    finally:
        os.chdir(cwd)


def test_engine_url_survives_a_bom(tmp_path, monkeypatch):
    import spdxlims.instrument_broadcast as broadcast

    _write_with_bom(tmp_path / "engine.json", {"listen_addr": "127.0.0.1:9099"})
    monkeypatch.setenv("INSTRUMENT_ENGINE_DATA_DIR", str(tmp_path))
    assert broadcast.get_engine_url() == "http://127.0.0.1:9099"


def test_plain_utf8_without_a_bom_still_works(tmp_path):
    """utf-8-sig must not regress the ordinary case."""
    from spdxlims.deployment import DeploymentService

    config = tmp_path / "deployment.json"
    config.write_text(json.dumps({"mode": "server"}), encoding="utf-8")
    assert DeploymentService(config).load().mode == "server"


def test_genuinely_broken_json_still_falls_back(tmp_path):
    """Tolerating a BOM must not start accepting corrupt files."""
    from spdxlims.deployment import DeploymentService

    config = tmp_path / "deployment.json"
    config.write_text("{not json", encoding="utf-8")
    assert DeploymentService(config).load().mode == "local"
