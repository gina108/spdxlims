import importlib

import pytest


def test_production_requires_non_default_jwt_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    import app.core.config as config

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        importlib.reload(config)


def test_cors_origins_are_read_from_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:8001, https://lims.example.test")

    import app.core.config as config
    reloaded = importlib.reload(config)

    assert reloaded.settings.cors_origins == ["http://localhost:8001", "https://lims.example.test"]
