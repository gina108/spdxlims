from __future__ import annotations

from spdxlims.pages.equipment_page import EquipmentPage


def create_page(context):
    return EquipmentPage(context.database)
