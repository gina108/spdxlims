from app.routers.patients import _normalize_status_filter


def test_normalize_status_filter_accepts_known_values_case_insensitively():
    assert _normalize_status_filter(" ACTIVE ") == "active"
    assert _normalize_status_filter("Archived") == "archived"
    assert _normalize_status_filter("all") == "all"


def test_normalize_status_filter_defaults_unknown_values_to_active():
    assert _normalize_status_filter("deleted") == "active"
    assert _normalize_status_filter("") == "active"
