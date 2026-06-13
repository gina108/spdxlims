from spdxlims.whatsapp_phone import clean_country_code, normalize_whatsapp_phone


def test_plain_phone_uses_default_country_code() -> None:
    assert normalize_whatsapp_phone("4921227836", "52") == "524921227836"


def test_plus_phone_preserves_intentional_country_code() -> None:
    assert normalize_whatsapp_phone("+49 212 27836", "52") == "4921227836"


def test_double_zero_phone_preserves_international_country_code() -> None:
    assert normalize_whatsapp_phone("0049 212 27836", "52") == "4921227836"


def test_country_code_cleanup_defaults_to_mexico() -> None:
    assert clean_country_code("+1") == "1"
    assert clean_country_code("") == "52"
