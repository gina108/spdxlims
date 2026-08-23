import importlib

import dotenv
import pytest


def test_production_requires_non_default_jwt_secret(monkeypatch):
    # Import first. config.py calls load_dotenv() at module scope, so importing
    # it populates os.environ from backend/.env -- including JWT_SECRET_KEY on a
    # developer machine. Clearing the variable before this line would be undone
    # right here, which is why this assertion never used to fire.
    import app.core.config as config

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    # Stop the reload below from reading .env back in. Patch it on the dotenv
    # module rather than on config: reload re-executes
    # `from dotenv import load_dotenv`, which would rebind a config-level patch
    # back to the real function before it is called.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        importlib.reload(config)


def test_cors_origins_are_read_from_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:8001, https://lims.example.test")

    import app.core.config as config
    reloaded = importlib.reload(config)

    assert reloaded.settings.cors_origins == ["http://localhost:8001", "https://lims.example.test"]
