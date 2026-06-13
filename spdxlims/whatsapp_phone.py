from __future__ import annotations

import re


DEFAULT_COUNTRY_CODE = "52"


COUNTRY_CODE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("52", "Mexico (+52)"),
    ("1", "United States / Canada (+1)"),
    ("502", "Guatemala (+502)"),
    ("503", "El Salvador (+503)"),
    ("504", "Honduras (+504)"),
    ("506", "Costa Rica (+506)"),
    ("507", "Panama (+507)"),
    ("34", "Spain (+34)"),
    ("49", "Germany (+49)"),
)


def clean_country_code(value: str | None) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    return digits or DEFAULT_COUNTRY_CODE


def normalize_whatsapp_phone(phone: str | None, default_country_code: str | None) -> str:
    raw = str(phone or "").strip()
    if not raw:
        return ""
    digits = re.sub(r"\D+", "", raw)
    if not digits:
        return ""
    if raw.startswith("+"):
        return digits
    if raw.startswith("00") and len(digits) > 2:
        return digits[2:]
    return f"{clean_country_code(default_country_code)}{digits}"
