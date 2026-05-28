from __future__ import annotations

from spdxlims.database import Database
from spdxlims.i18n import tr

WHATSAPP_MESSAGE_SETTINGS_KEY = "whatsapp_message_templates"


def default_whatsapp_templates() -> dict[str, str]:
    return {
        "patient": tr(
            "Hello {name}, your lab report for order {order_number} has been reviewed and approved."
        ),
        "client": tr(
            "Hello {name}, the lab report for patient {patient_name} and order {order_number} has been reviewed and approved."
        ),
    }


def get_whatsapp_templates(database: Database) -> dict[str, str]:
    defaults = default_whatsapp_templates()
    ui_state = database.get_ui_state()
    raw = ui_state.get(WHATSAPP_MESSAGE_SETTINGS_KEY, {})
    if not isinstance(raw, dict):
        return defaults
    return {
        "patient": str(raw.get("patient") or defaults["patient"]),
        "client": str(raw.get("client") or defaults["client"]),
    }


def save_whatsapp_templates(database: Database, *, patient: str, client: str) -> None:
    defaults = default_whatsapp_templates()
    ui_state = database.get_ui_state()
    ui_state[WHATSAPP_MESSAGE_SETTINGS_KEY] = {
        "patient": patient.strip() or defaults["patient"],
        "client": client.strip() or defaults["client"],
    }
    database.save_ui_state(ui_state)
