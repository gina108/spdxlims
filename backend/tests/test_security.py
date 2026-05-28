from datetime import datetime, timezone

from app.core.security import create_access_token, decode_token, safe_decode_token


def test_access_token_round_trip_includes_subject_and_extra_claims():
    token = create_access_token("user-123", {"role": "admin"})

    payload = decode_token(token)

    assert payload["sub"] == "user-123"
    assert payload["role"] == "admin"
    assert datetime.fromtimestamp(payload["exp"], timezone.utc) > datetime.now(timezone.utc)


def test_safe_decode_token_returns_none_for_invalid_token():
    assert safe_decode_token("not-a-valid-token") is None
