from __future__ import annotations

from spdxlims.pages.administrative_page import AdministrativePage


def create_page(context):
    return AdministrativePage(context.database)
