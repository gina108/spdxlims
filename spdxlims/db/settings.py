from __future__ import annotations
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from spdxlims.db.records import LabSettingsRecord
from spdxlims.whatsapp_phone import DEFAULT_COUNTRY_CODE, clean_country_code


class SettingsMixin:
    def get_lab_settings(self) -> LabSettingsRecord:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT lab_name, address, phone, email, logo_path, header_image_path, footer_signature_image_path, report_footer, director_name, director_license, sat_rfc, sat_fiscal_regime, sat_postal_code, sat_certificate_path, sat_key_path, ui_language, report_flag_style, keep_panels_together, report_font_family, report_font_size, report_font_bold, report_abnormal_bold, report_subheading_font_family, report_subheading_font_size, report_subheading_font_bold, report_footer_gap_mm, ui_state, report_sex_format, report_date_format, report_show_doctor, report_show_client, report_show_sex, report_show_age, report_show_dob, report_show_ordered_at, report_show_reported_at, pac_provider, pac_environment, pac_username, pac_password, cfdi_tax_treatment FROM lab_settings WHERE id = 1"
            ).fetchone()
        return LabSettingsRecord(**dict(row))

    def save_lab_settings(self, payload: dict[str, str]) -> None:
        header_image_path = self._copy_asset(payload.get("header_image_path", ""), "header")
        footer_image_path = self._copy_asset(payload.get("footer_signature_image_path", ""), "footer_signature")
        logo_path = self._copy_asset(payload.get("logo_path", ""), "logo")
        with self.connect() as connection:
            connection.execute(
                "UPDATE lab_settings SET lab_name = ?, address = ?, phone = ?, email = ?, logo_path = ?, header_image_path = ?, footer_signature_image_path = ?, report_footer = ?, director_name = ?, director_license = ?, sat_rfc = ?, sat_fiscal_regime = ?, sat_postal_code = ?, sat_certificate_path = ?, sat_key_path = ?, ui_language = ?, report_flag_style = ?, keep_panels_together = ?, report_font_family = ?, report_font_size = ?, report_font_bold = ?, report_abnormal_bold = ?, report_subheading_font_family = ?, report_subheading_font_size = ?, report_subheading_font_bold = ?, report_footer_gap_mm = ?, ui_state = ?, report_sex_format = ?, report_date_format = ?, report_show_doctor = ?, report_show_client = ?, report_show_sex = ?, report_show_age = ?, report_show_dob = ?, report_show_ordered_at = ?, report_show_reported_at = ?, report_doctor_col = ?, report_client_col = ?, report_sex_col = ?, report_age_col = ?, report_dob_col = ?, report_ordered_at_col = ?, report_reported_at_col = ?, pac_provider = ?, pac_environment = ?, pac_username = ?, pac_password = ?, cfdi_tax_treatment = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (
                    payload.get("lab_name", "").strip(),
                    payload.get("address", "").strip(),
                    payload.get("phone", "").strip(),
                    payload.get("email", "").strip(),
                    logo_path,
                    header_image_path,
                    footer_image_path,
                    payload.get("report_footer", "").strip(),
                    payload.get("director_name", "").strip(),
                    payload.get("director_license", "").strip(),
                    payload.get("sat_rfc", "").strip(),
                    payload.get("sat_fiscal_regime", "").strip(),
                    payload.get("sat_postal_code", "").strip(),
                    payload.get("sat_certificate_path", "").strip(),
                    payload.get("sat_key_path", "").strip(),
                    payload.get("ui_language", "es").strip() or "es",
                    payload.get("report_flag_style", "arrows").strip() or "arrows",
                    1 if str(payload.get("keep_panels_together", "0")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    payload.get("report_font_family", "Segoe UI").strip() or "Segoe UI",
                    self._bounded_int(payload.get("report_font_size"), 8, 18, 12),
                    1 if str(payload.get("report_font_bold", "0")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    1 if str(payload.get("report_abnormal_bold", "0")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    payload.get("report_subheading_font_family", "Segoe UI").strip() or "Segoe UI",
                    self._bounded_int(payload.get("report_subheading_font_size"), 8, 18, 13),
                    1 if str(payload.get("report_subheading_font_bold", "1")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    self._bounded_int(payload.get("report_footer_gap_mm"), 0, 60, 8),
                    payload.get("ui_state", self.get_ui_state_json()),
                    payload.get("report_sex_format", "short").strip() or "short",
                    payload.get("report_date_format", "auto").strip() or "auto",
                    1 if str(payload.get("report_show_doctor", "1")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    1 if str(payload.get("report_show_client", "1")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    1 if str(payload.get("report_show_sex", "1")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    1 if str(payload.get("report_show_age", "1")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    1 if str(payload.get("report_show_dob", "1")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    1 if str(payload.get("report_show_ordered_at", "1")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    1 if str(payload.get("report_show_reported_at", "1")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    payload.get("report_doctor_col", "left").strip() or "left",
                    payload.get("report_client_col", "left").strip() or "left",
                    payload.get("report_sex_col", "left").strip() or "left",
                    payload.get("report_age_col", "right").strip() or "right",
                    payload.get("report_dob_col", "right").strip() or "right",
                    payload.get("report_ordered_at_col", "right").strip() or "right",
                    payload.get("report_reported_at_col", "right").strip() or "right",
                    payload.get("pac_provider", "facturama").strip() or "facturama",
                    payload.get("pac_environment", "sandbox").strip() or "sandbox",
                    payload.get("pac_username", "").strip(),
                    payload.get("pac_password", ""),
                    payload.get("cfdi_tax_treatment", "exempt").strip() or "exempt",
                ),
            )

    def get_report_layout_settings(self) -> dict[str, Any]:
        settings = self.get_lab_settings()
        return {
            "flag_display_mode": settings.report_flag_style,
            "keep_panels_together": bool(settings.keep_panels_together),
            "report_font_family": settings.report_font_family,
            "report_font_size": settings.report_font_size,
            "report_font_bold": bool(settings.report_font_bold),
            "report_abnormal_bold": bool(settings.report_abnormal_bold),
            "report_subheading_font_family": settings.report_subheading_font_family,
            "report_subheading_font_size": settings.report_subheading_font_size,
            "report_subheading_font_bold": bool(settings.report_subheading_font_bold),
            "report_footer_gap_mm": settings.report_footer_gap_mm,
            "report_sex_format": settings.report_sex_format,
            "report_date_format": settings.report_date_format,
            "report_show_doctor": bool(settings.report_show_doctor),
            "report_show_client": bool(settings.report_show_client),
            "report_show_sex": bool(settings.report_show_sex),
            "report_show_age": bool(settings.report_show_age),
            "report_show_dob": bool(settings.report_show_dob),
            "report_show_ordered_at": bool(settings.report_show_ordered_at),
            "report_show_reported_at": bool(settings.report_show_reported_at),
            "report_doctor_col": settings.report_doctor_col,
            "report_client_col": settings.report_client_col,
            "report_sex_col": settings.report_sex_col,
            "report_age_col": settings.report_age_col,
            "report_dob_col": settings.report_dob_col,
            "report_ordered_at_col": settings.report_ordered_at_col,
            "report_reported_at_col": settings.report_reported_at_col,
        }

    def get_ui_state(self) -> dict[str, Any]:
        settings = self.get_lab_settings()
        try:
            data = json.loads(settings.ui_state or '{}')
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def get_ui_state_json(self) -> str:
        return json.dumps(self.get_ui_state(), ensure_ascii=False)

    # --- per-order UI state (see _migrate_order_ui_state_table) ---
    # These replace the per-order maps that used to be nested inside the
    # ui_state blob. Reads are single-row or single-scope instead of parsing
    # the entire history on every access.

    def get_order_ui_value(self, scope: str, entity_id: Any) -> Any | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM order_ui_state WHERE scope = ? AND entity_id = ?",
                (scope, str(entity_id)),
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return None

    def get_order_ui_scope(self, scope: str) -> dict[str, Any]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT entity_id, value FROM order_ui_state WHERE scope = ?",
                (scope,),
            ).fetchall()
        values: dict[str, Any] = {}
        for row in rows:
            try:
                values[str(row["entity_id"])] = json.loads(row["value"])
            except json.JSONDecodeError:
                continue
        return values

    def set_order_ui_value(self, scope: str, entity_id: Any, value: Any) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO order_ui_state (scope, entity_id, value, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(scope, entity_id)
                DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """,
                (scope, str(entity_id), json.dumps(value, ensure_ascii=False)),
            )

    def delete_order_ui_value(self, scope: str, entity_id: Any) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM order_ui_state WHERE scope = ? AND entity_id = ?",
                (scope, str(entity_id)),
            )

    def save_ui_state(self, ui_state: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE lab_settings SET ui_state = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (json.dumps(ui_state, ensure_ascii=False),),
            )

    def get_whatsapp_country_code(self) -> str:
        ui_state = self.get_ui_state()
        return clean_country_code(str(ui_state.get("whatsapp_country_code") or DEFAULT_COUNTRY_CODE))

    def save_whatsapp_country_code(self, country_code: str) -> None:
        ui_state = self.get_ui_state()
        ui_state["whatsapp_country_code"] = clean_country_code(country_code)
        self.save_ui_state(ui_state)

    def get_report_branding_options(self) -> dict[str, Any]:
        settings = self.get_lab_settings()
        ui_state = self.get_ui_state()
        stored = ui_state.get("report_branding")
        if not isinstance(stored, dict):
            stored = {}
        headers = self._normalize_report_branding_paths(stored.get("headers"), settings.header_image_path)
        footers = self._normalize_report_branding_paths(stored.get("footers"), settings.footer_signature_image_path)
        selected_header = str(stored.get("selected_header") or settings.header_image_path or (headers[0] if headers else ""))
        selected_footer = str(stored.get("selected_footer") or settings.footer_signature_image_path or (footers[0] if footers else ""))
        if selected_header and selected_header not in headers:
            headers.insert(0, selected_header)
        if selected_footer and selected_footer not in footers:
            footers.insert(0, selected_footer)
        return {
            "headers": headers,
            "footers": footers,
            "selected_header": selected_header,
            "selected_footer": selected_footer,
        }

    def save_report_branding_options(
        self,
        header_paths: list[str],
        footer_paths: list[str],
        selected_header: str,
        selected_footer: str,
    ) -> None:
        branding = {
            "headers": self._normalize_report_branding_paths(header_paths),
            "footers": self._normalize_report_branding_paths(footer_paths),
            "selected_header": selected_header.strip(),
            "selected_footer": selected_footer.strip(),
        }
        ui_state = self.get_ui_state()
        ui_state["report_branding"] = branding
        self.save_ui_state(ui_state)

    def add_report_branding_asset(self, raw_path: str, kind: str) -> str:
        copied_path = self._copy_report_branding_asset(raw_path, kind)
        if not copied_path:
            return ""
        branding = self.get_report_branding_options()
        key = "headers" if kind == "header" else "footers"
        selected_key = "selected_header" if kind == "header" else "selected_footer"
        paths = list(branding[key])
        if copied_path not in paths:
            paths.append(copied_path)
        branding[key] = paths
        branding[selected_key] = copied_path
        self.save_report_branding_options(
            branding["headers"],
            branding["footers"],
            branding["selected_header"],
            branding["selected_footer"],
        )
        return copied_path

    def get_label_print_preferences(self, client_id: int | None = None) -> dict[str, str]:
        ui_state = self.get_ui_state()
        stored = ui_state.get("label_print_defaults")
        if not isinstance(stored, dict):
            stored = {}
        default_prefs = stored.get("default")
        if not isinstance(default_prefs, dict):
            default_prefs = {}
        preferences = {
            "template": str(default_prefs.get("template") or "general"),
            "payload": str(default_prefs.get("payload") or "order_only"),
            "size": str(default_prefs.get("size") or "small_tall"),
            "grouping": str(default_prefs.get("grouping") or "per_test"),
            "code_type": str(default_prefs.get("code_type") or "barcode_name"),
            "copies": str(default_prefs.get("copies") or "1"),
            "show_barcode": "1" if default_prefs.get("show_barcode", True) else "0",
            "show_patient_name": "1" if default_prefs.get("show_patient_name", str(default_prefs.get("code_type") or "barcode_name") == "barcode_name") else "0",
            "show_order_number_text": "1" if bool(default_prefs.get("show_order_number_text")) else "0",
            "show_datetime": "1" if bool(default_prefs.get("show_datetime")) else "0",
            "printer": str(default_prefs.get("printer") or "niimbot:B1"),
            "density": str(default_prefs.get("density") or "4"),
        }
        if client_id is not None:
            client_map = stored.get("clients")
            if isinstance(client_map, dict):
                client_prefs = client_map.get(str(client_id))
                if isinstance(client_prefs, dict):
                    if client_prefs.get("template"):
                        preferences["template"] = str(client_prefs["template"])
                    if client_prefs.get("payload"):
                        preferences["payload"] = str(client_prefs["payload"])
        return preferences

    def get_order_panel_codes(self, order_id: int) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT COALESCE(ot.source_label, '') AS panel_code
                FROM order_tests ot
                INNER JOIN tests t ON t.id = ot.test_id
                WHERE ot.order_id = ?
                  AND t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                  AND COALESCE(ot.source_label, '') != ''
                ORDER BY panel_code
                """,
                (order_id,),
            ).fetchall()
        return [str(row["panel_code"]) for row in rows]

    def get_panel_extra_copies(self) -> dict[str, int]:
        ui_state = self.get_ui_state()
        stored = ui_state.get("label_print_defaults")
        if not isinstance(stored, dict):
            return {}
        extras = stored.get("panel_extra_copies")
        if not isinstance(extras, dict):
            return {}
        result: dict[str, int] = {}
        for k, v in extras.items():
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if n > 0:
                result[str(k)] = n
        return result

    def save_panel_extra_copies(self, extra_copies: dict[str, int]) -> None:
        ui_state = self.get_ui_state()
        stored = ui_state.get("label_print_defaults")
        if not isinstance(stored, dict):
            stored = {}
        stored["panel_extra_copies"] = {k: v for k, v in extra_copies.items() if v > 0}
        ui_state["label_print_defaults"] = stored
        self.save_ui_state(ui_state)

    def save_label_print_preferences(
        self,
        template: str,
        payload: str,
        client_id: int | None = None,
        *,
        size: str | None = None,
        grouping: str | None = None,
        code_type: str | None = None,
        copies: str | None = None,
        show_barcode: bool | None = None,
        show_patient_name: bool | None = None,
        show_order_number_text: bool | None = None,
        show_datetime: bool | None = None,
        printer: str | None = None,
        density: str | None = None,
    ) -> None:
        ui_state = self.get_ui_state()
        stored = ui_state.get("label_print_defaults")
        if not isinstance(stored, dict):
            stored = {}
        if client_id is None:
            default_prefs = stored.get("default")
            if not isinstance(default_prefs, dict):
                default_prefs = {}
            default_prefs["template"] = template
            default_prefs["payload"] = payload
            if size is not None:
                default_prefs["size"] = size
            if grouping is not None:
                default_prefs["grouping"] = grouping
            if code_type is not None:
                default_prefs["code_type"] = code_type
            if copies is not None:
                default_prefs["copies"] = copies
            if show_barcode is not None:
                default_prefs["show_barcode"] = bool(show_barcode)
            if show_patient_name is not None:
                default_prefs["show_patient_name"] = bool(show_patient_name)
            if show_order_number_text is not None:
                default_prefs["show_order_number_text"] = bool(show_order_number_text)
            if show_datetime is not None:
                default_prefs["show_datetime"] = bool(show_datetime)
            if printer is not None:
                default_prefs["printer"] = printer
            if density is not None:
                default_prefs["density"] = density
            stored["default"] = default_prefs
        else:
            client_map = stored.get("clients")
            if not isinstance(client_map, dict):
                client_map = {}
            client_map[str(client_id)] = {"template": template, "payload": payload}
            stored["clients"] = client_map
        ui_state["label_print_defaults"] = stored
        self.save_ui_state(ui_state)

    def get_receipt_print_preferences(self) -> dict[str, str]:
        ui_state = self.get_ui_state()
        stored = ui_state.get("receipt_print_defaults")
        if not isinstance(stored, dict):
            stored = {}
        return {
            "auto_print": str(stored.get("auto_print") or "0"),
            "paper_format": str(stored.get("paper_format") or "letter"),
            "printer": str(stored.get("printer") or "system_default"),
        }

    def save_receipt_print_preferences(self, *, auto_print: bool, paper_format: str, printer: str = "system_default") -> None:
        ui_state = self.get_ui_state()
        ui_state["receipt_print_defaults"] = {
            "auto_print": "1" if auto_print else "0",
            "paper_format": paper_format,
            "printer": printer,
        }
        self.save_ui_state(ui_state)
