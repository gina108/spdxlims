from __future__ import annotations
import ast as _ast
import base64
import json
import operator as _operator
import re
import re as _re
import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from spdxlims.db.panels import GRAM_NEGATIVE
from spdxlims.db.records import TestReferenceRangeRecord
from spdxlims.i18n import tr


class ResultsMixin:
    def get_order_receipt_lines(self, order_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.order_number,
                       TRIM(p.first_name || ' ' || p.last_name) AS patient_name,
                       p.sex AS patient_sex,
                       p.age_value,
                       p.age_unit,
                       COALESCE(o.ordered_at, o.created_at) AS order_date,
                       COALESCE(ot.display_name, t.name) AS test_name,
                       COALESCE(t.price, 0.0) AS price,
                       t.code
                FROM order_tests ot
                INNER JOIN orders o ON o.id = ot.order_id
                INNER JOIN patients p ON p.id = o.patient_id
                INNER JOIN tests t ON t.id = ot.test_id
                WHERE ot.order_id = ?
                  AND t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                ORDER BY ot.sort_order, ot.id
                """,
                (order_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_order_label_entries(self, order_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT ot.id AS order_test_id,
                       o.order_number,
                       o.accession_id,
                       o.sample_id,
                       o.client_id,
                       TRIM(p.first_name || ' ' || p.last_name || CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END) AS patient_name,
                       p.sex AS patient_sex,
                       p.age_value,
                       p.age_unit,
                       COALESCE(ot.display_name, t.name) AS display_name,
                       t.name AS test_name,
                       t.specimen_type,
                       t.code AS test_code,
                       CASE WHEN t.code = '__PANEL_HEADING__' THEN 'heading'
                            WHEN t.code = '__PANEL_COMMENT__' THEN 'comment'
                            ELSE 'test'
                       END AS item_type,
                       o.created_at
                FROM order_tests ot
                INNER JOIN orders o ON o.id = ot.order_id
                INNER JOIN patients p ON p.id = o.patient_id
                INNER JOIN tests t ON t.id = ot.test_id
                WHERE ot.order_id = ?
                ORDER BY ot.sort_order, ot.id
                """,
                (order_id,),
            ).fetchall()
        labels: list[dict[str, Any]] = []
        current_group = ''
        for row in rows:
            data = dict(row)
            item_type = data.get('item_type')
            if item_type == 'heading':
                current_group = str(data.get('display_name') or '').strip()
                continue
            if item_type == 'comment':
                continue
            specimen_type = str(data.get('specimen_type') or '')
            labels.append({
                'order_test_id': data.get('order_test_id'),
                'order_number': data.get('order_number'),
                'accession_id': data.get('accession_id') or '',
                'sample_id': data.get('sample_id') or '',
                'client_id': data.get('client_id'),
                'patient_name': data.get('patient_name'),
                'patient_sex': data.get('patient_sex'),
                'age_value': data.get('age_value'),
                'age_unit': data.get('age_unit'),
                'test_name': data.get('display_name') or data.get('test_name'),
                'specimen_type': specimen_type,
                'specimen_code': self._specimen_code(specimen_type),
                'test_code': data.get('test_code') or '',
                'group_label': current_group,
                'created_at': data.get('created_at'),
            })
        return labels

    def get_live_report_preview(self, order_id: int, *, apply_culture_layout: bool = True) -> dict[str, Any] | None:
        """Build the live preview.

        `apply_culture_layout=False` is used by get_saved_report_preview, which
        needs the raw rows (with their order_test_ids intact) as the scaffold to
        merge snapshot values onto. Culture rows carry no order_test_id, so
        collapsing them before that merge would make a finalized report render
        current values instead of its frozen snapshot.
        """
        context = self._get_report_context(order_id)
        if context is None:
            return None
        entries = self.get_order_result_entries(order_id)
        settings = self.get_lab_settings()
        outsourced_order_test_ids = self._get_outsourced_order_test_ids(order_id)
        with self.connect() as connection:
            images_by_order_test = self._result_images_by_order_test(connection, order_id)
        preview_items = [
            {
                "order_test_id": entry.order_test_id,
                "test_id": entry.test_id,
                "item_type": entry.item_type,
                "result_kind": entry.result_kind,
                "test_name": entry.test_name,
                "result_value": entry.result_value,
                "unit": entry.unit,
                "reference_text": entry.reference_text,
                "lower_value": entry.lower_value,
                "upper_value": entry.upper_value,
                "flag": entry.flag,
                "comments": entry.comments,
                "images": images_by_order_test.get(entry.order_test_id, []),
                "sort_order": index,
                "source_label": entry.source_label,
            }
            for index, entry in enumerate(entries)
            if entry.order_test_id not in outsourced_order_test_ids
            and not (entry.item_type in {"heading", "comment"} and not (entry.source_label or "").strip())
        ]
        return {
            **self.get_report_layout_settings(),
            "source": "live",
            "report_status": "draft",
            "report_version": None,
            "finalized_at": None,
            "order_id": context["order_id"],
            "order_number": context["order_number"],
            "accession_id": context["accession_id"],
            "sample_id": context["sample_id"],
            "ordered_at": context["ordered_at"],
            "reported_at": context["reported_at"],
            "order_status": context["order_status"],
            "patient_name": context["patient_name"],
            "patient_sex": context["patient_sex"],
            "patient_dob": context["patient_dob"],
            "patient_age_value": context["patient_age_value"],
            "patient_age_unit": context["patient_age_unit"],
            "doctor_name": context["doctor_name"],
            "client_name": context["client_name"],
            "lab_name": settings.lab_name,
            "lab_address": settings.address,
            "lab_phone": settings.phone,
            "lab_email": settings.email,
            "director_name": settings.director_name,
            "director_license": settings.director_license,
            "footer_text": settings.report_footer,
            "header_image_path": context.get("client_header_image_path") or settings.header_image_path,
            "footer_signature_image_path": context.get("client_footer_signature_image_path") or settings.footer_signature_image_path,
            "client_header_image_path": context.get("client_header_image_path") or "",
            "client_footer_signature_image_path": context.get("client_footer_signature_image_path") or "",
            "general_comments": context["notes"],
            "outsourced_panels": self.get_outsourced_panel_preview_sections(order_id),
            "items": self._maybe_apply_culture_layout(
                self._inject_panel_title_rows(
                    self._restore_panel_catalog_structure(preview_items),
                    self.get_panel_report_metadata_by_name(),
                ),
                apply_culture_layout,
                order_id,
            ),
        }

    def _maybe_apply_culture_layout(
        self, items: list[dict[str, Any]], enabled: bool, order_id: int | None = None
    ) -> list[dict[str, Any]]:
        return self._apply_culture_layout(items, order_id) if enabled else items

    def get_saved_report_preview(self, order_id: int) -> dict[str, Any] | None:
        current_settings = self.get_lab_settings()
        with self.connect() as connection:
            report_row = connection.execute(
                """
                SELECT r.id,
                       r.order_id,
                       r.report_version,
                       r.status,
                       r.finalized_at,
                       r.patient_snapshot_name,
                       r.patient_snapshot_sex,
                       r.patient_snapshot_dob,
                       r.doctor_snapshot_name,
                       r.lab_snapshot_name,
                       r.lab_snapshot_address,
                       r.lab_snapshot_phone,
                       r.lab_snapshot_email,
                       r.director_snapshot_name,
                       r.director_snapshot_license,
                       r.footer_snapshot_text,
                       r.header_image_snapshot_path,
                       r.footer_signature_snapshot_path,
                       r.general_comments,
                       o.order_number,
                       o.accession_id,
                       o.sample_id,
                       o.ordered_at,
                       o.reported_at,
                       o.status AS order_status,
                       c.name AS client_name,
                       p.age_value AS patient_age_value,
                       p.age_unit AS patient_age_unit
                FROM reports r
                INNER JOIN orders o ON o.id = r.order_id
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN clients c ON c.id = o.client_id
                WHERE r.order_id = ?
                """,
                (order_id,),
            ).fetchone()
            if report_row is None:
                return None
            item_rows = connection.execute(
                """
                SELECT order_test_id,
                       item_type_snapshot,
                       test_name_snapshot,
                       result_value_snapshot,
                       unit_snapshot,
                       reference_text_snapshot,
                       lower_value_snapshot_text,
                       upper_value_snapshot_text,
                       flag_snapshot,
                       comments_snapshot,
                       sort_order
                FROM report_items
                WHERE report_id = ?
                ORDER BY sort_order, id
                """,
                (report_row["id"],),
            ).fetchall()
            outsourced_rows = connection.execute(
                """
                SELECT panel_label,
                       source_pdf_path,
                       row_index,
                       col_1,
                       col_2,
                       col_3,
                       col_4,
                       col_5
                FROM report_outsourced_rows
                WHERE report_id = ?
                ORDER BY panel_label, row_index, id
                """,
                (report_row["id"],),
            ).fetchall()
            snapshot_images_by_order_test = self._report_snapshot_images_by_order_test(connection, int(report_row["id"]))
        current_outsourced_sections = self.get_outsourced_panel_preview_sections(int(report_row["order_id"]))
        outsourced_sections = current_outsourced_sections or self._group_outsourced_rows(outsourced_rows)
        saved_items = [
            {
                "order_test_id": row["order_test_id"],
                "item_type": row["item_type_snapshot"] or "test",
                "test_name": row["test_name_snapshot"],
                "result_value": row["result_value_snapshot"],
                "unit": row["unit_snapshot"],
                "reference_text": row["reference_text_snapshot"],
                "lower_value": row["lower_value_snapshot_text"],
                "upper_value": row["upper_value_snapshot_text"],
                "flag": row["flag_snapshot"],
                "comments": row["comments_snapshot"],
                "sort_order": row["sort_order"],
            }
            for row in item_rows
        ]
        live_preview = self.get_live_report_preview(
            int(report_row["order_id"]), apply_culture_layout=False
        )
        rendered_items = self._merge_saved_result_values_into_live_items(
            saved_items,
            list((live_preview or {}).get("items") or []),
        )
        # Finalized reports render their snapshot images (immutable), overriding any
        # live images that may have changed since the report was finalized.
        if snapshot_images_by_order_test:
            for item in rendered_items:
                order_test_id = item.get("order_test_id")
                if order_test_id is not None and int(order_test_id) in snapshot_images_by_order_test:
                    item["images"] = snapshot_images_by_order_test[int(order_test_id)]
        # Prefer live patient/order data over the snapshot so edits are reflected
        # immediately without having to re-finalize. Snapshots are the fallback.
        live_ctx = live_preview or {}
        return {
            **self.get_report_layout_settings(),
            "source": "saved",
            "report_status": report_row["status"],
            "report_version": report_row["report_version"],
            "finalized_at": report_row["finalized_at"],
            "order_id": report_row["order_id"],
            "order_number": live_ctx.get("order_number") or report_row["order_number"],
            "accession_id": live_ctx.get("accession_id") or report_row["accession_id"],
            "sample_id": live_ctx.get("sample_id") or report_row["sample_id"],
            "ordered_at": live_ctx.get("ordered_at") or report_row["ordered_at"],
            "reported_at": live_ctx.get("reported_at") or report_row["reported_at"],
            "order_status": live_ctx.get("order_status") or report_row["order_status"],
            "patient_name": live_ctx.get("patient_name") or report_row["patient_snapshot_name"],
            "patient_sex": live_ctx.get("patient_sex") or report_row["patient_snapshot_sex"],
            "patient_dob": live_ctx.get("patient_dob") or report_row["patient_snapshot_dob"],
            "patient_age_value": live_ctx.get("patient_age_value") or report_row["patient_age_value"],
            "patient_age_unit": live_ctx.get("patient_age_unit") or report_row["patient_age_unit"],
            "doctor_name": live_ctx.get("doctor_name") or report_row["doctor_snapshot_name"],
            "client_name": live_ctx.get("client_name") or report_row["client_name"],
            "lab_name": report_row["lab_snapshot_name"],
            "lab_address": report_row["lab_snapshot_address"],
            "lab_phone": report_row["lab_snapshot_phone"],
            "lab_email": report_row["lab_snapshot_email"],
            "director_name": report_row["director_snapshot_name"],
            "director_license": report_row["director_snapshot_license"],
            "footer_text": report_row["footer_snapshot_text"],
            "header_image_path": report_row["header_image_snapshot_path"] or live_ctx.get("client_header_image_path") or current_settings.header_image_path,
            "footer_signature_image_path": report_row["footer_signature_snapshot_path"] or live_ctx.get("client_footer_signature_image_path") or current_settings.footer_signature_image_path,
            "client_header_image_path": live_ctx.get("client_header_image_path") or "",
            "client_footer_signature_image_path": live_ctx.get("client_footer_signature_image_path") or "",
            "general_comments": report_row["general_comments"],
            "outsourced_panels": self.get_outsourced_panel_preview_sections(order_id),
            # Applied last, once snapshot values are merged onto the raw rows.
            # The report version selects the frozen culture rows for this report.
            "items": self._apply_culture_layout(
                rendered_items,
                int(report_row["order_id"]),
                int(report_row["report_version"] or 0),
            ),
        }

    @classmethod
    def _merge_saved_result_values_into_live_items(
        cls,
        saved_items: list[dict[str, Any]],
        live_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not live_items:
            return saved_items
        # Build a name→source_label lookup so sub-headings (e.g. "EXAMEN DE LAS
        # CARACTERISTICAS FISICAS" inside "EXAMEN GENERAL DE ORINA") regain their
        # panel affiliation and stay with the rest of the panel during pagination.
        # Only map names that appear exactly once to avoid ambiguous collisions.
        _seen: set[str] = set()
        _dupes: set[str] = set()
        live_source_by_heading: dict[str, str] = {}
        for item in live_items:
            if item.get("order_test_id") is not None:
                continue
            src = str(item.get("source_label") or "").strip()
            name = str(item.get("test_name") or "").strip()
            if not src or not name:
                continue
            if name in _seen:
                _dupes.add(name)
            else:
                _seen.add(name)
                live_source_by_heading[name] = src
        for dupe in _dupes:
            live_source_by_heading.pop(dupe, None)
        saved_by_order_test_id: dict[Any, dict[str, Any]] = {
            item["order_test_id"]: item
            for item in saved_items
            if item.get("order_test_id") is not None
        }
        # Build the set of ambiguous heading names (same name, different source_labels
        # in live) so we can leave those headings' source_label untouched.
        _ambiguous_heading_names: set[str] = set()
        _seen_src_by_name: dict[str, str] = {}
        for item in live_items:
            if item.get("order_test_id") is not None:
                continue
            src = str(item.get("source_label") or "").strip()
            name = str(item.get("test_name") or "").strip()
            if not src or not name:
                continue
            if name in _seen_src_by_name and _seen_src_by_name[name] != src:
                _ambiguous_heading_names.add(name)
            else:
                _seen_src_by_name[name] = src
        # Headings/comments carry no order_test_id (they are injected from the
        # panel structure), so manual subtitle edits captured in the snapshot are
        # matched back by the order_test_id of the nearest following anchored
        # item, rather than by raw position -- a plain position counter drifts
        # out of sync whenever some headings *do* have a real order_test_id
        # (e.g. panel sub-headings) interleaved with anchorless ones (e.g.
        # injected panel-title rows), since only the anchorless ones advance it.
        saved_anchors = cls._next_anchor_order_test_ids(saved_items)
        saved_by_type_and_anchor: dict[tuple[str, Any], list[dict[str, Any]]] = {}
        for saved_item, anchor in zip(saved_items, saved_anchors):
            saved_type = str(saved_item.get("item_type") or "")
            if saved_type in {"heading", "comment"}:
                saved_by_type_and_anchor.setdefault((saved_type, anchor), []).append(saved_item)
        live_anchors = cls._next_anchor_order_test_ids(live_items)
        anchor_positions: dict[tuple[str, Any], int] = {}
        # Iterate live_items so the current panel structure (injected headings,
        # panel_meta rows) is always present, even when the saved snapshot was
        # captured from a stale preview that was missing those rows.
        merged: list[dict[str, Any]] = []
        for live_index, live_item in enumerate(live_items):
            item = dict(live_item)
            order_test_id = item.get("order_test_id")
            item_type = str(item.get("item_type") or "")
            if order_test_id is not None:
                saved_item = saved_by_order_test_id.get(order_test_id)
                if saved_item is not None:
                    for key in ("test_name", "result_value", "unit", "reference_text", "lower_value", "upper_value", "flag", "comments"):
                        item[key] = saved_item.get(key)
            elif item_type in {"heading", "comment"}:
                name = str(item.get("test_name") or "").strip()
                if name in _ambiguous_heading_names:
                    item["source_label"] = None
                elif not str(item.get("source_label") or "").strip():
                    restored = live_source_by_heading.get(name)
                    if restored:
                        item["source_label"] = restored
                # Re-apply a manual subtitle edit, but let a stale catalog form
                # (e.g. "Quimica Clinica (CHEM) - 1 tests") refresh to the current
                # panel name. Both stale and current normalize to the same label.
                key = (item_type, live_anchors[live_index])
                candidates = saved_by_type_and_anchor.get(key) or []
                position = anchor_positions.get(key, 0)
                anchor_positions[key] = position + 1
                saved_item = candidates[position] if position < len(candidates) else None
                if saved_item is not None:
                    saved_name = str(saved_item.get("test_name") or "").strip()
                    if saved_name and (
                        cls._normalize_report_panel_label(saved_name).casefold()
                        != cls._normalize_report_panel_label(name).casefold()
                    ):
                        item["test_name"] = saved_item.get("test_name")
            merged.append(item)
        return merged

    @staticmethod
    def _next_anchor_order_test_ids(items: list[dict[str, Any]]) -> list[Any]:
        """For each item, the order_test_id of the nearest following non-heading/comment item.

        Heading/comment rows can carry a synthetic order_test_id in a saved snapshot
        (they get persisted as ``__PANEL_HEADING__`` / ``__PANEL_COMMENT__`` order_tests
        by some order-creation flows) while the live structure leaves the very same
        headings anchorless. If those synthetic ids were allowed to anchor, a panel
        title and its first sub-heading -- which share one anchor in the live list --
        would land in different anchor buckets in the saved list, and the heading merge
        would mismatch them (e.g. printing "FORMULA ROJA" in place of the panel title
        "BIOMETRIA HEMATICA"). Excluding heading/comment ids keeps both lists aligned."""
        anchors: list[Any] = [None] * len(items)
        next_anchor: Any = None
        for index in range(len(items) - 1, -1, -1):
            anchors[index] = next_anchor
            item_type = str(items[index].get("item_type") or "")
            order_test_id = items[index].get("order_test_id")
            if order_test_id is not None and item_type not in {"heading", "comment"}:
                next_anchor = order_test_id
        return anchors

    def _restore_panel_catalog_structure(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        structures = self._panel_catalog_structures()
        if not structures:
            return items
        grouped_order_items: dict[str, list[dict[str, Any]]] = {}
        group_order: list[str] = []
        passthrough: list[dict[str, Any]] = []
        for item in items:
            raw_label = self._normalize_report_panel_label(str(item.get("source_label") or ""))
            structure = structures.get(raw_label.casefold())
            label = str((structure or {}).get("name") or raw_label).strip()
            if not label:
                passthrough.append(item)
                continue
            if label not in grouped_order_items:
                group_order.append(label)
            grouped_order_items.setdefault(label, []).append(item)
        if not grouped_order_items:
            return items
        restored: list[dict[str, Any]] = []
        restored.extend(passthrough)
        for label in group_order:
            order_items = grouped_order_items[label]
            structure = structures.get(label.casefold())
            if structure is None:
                restored.extend(self._normalize_panel_source_items(order_items, label, structures))
                continue
            if any(str(item.get("item_type") or "test") in {"heading", "comment"} for item in order_items):
                restored.extend(self._normalize_panel_source_items(order_items, structure["name"], structures))
                continue
            by_test_id = {
                int(item["test_id"]): item
                for item in order_items
                if item.get("test_id") is not None
            }
            used_test_ids: set[int] = set()
            for panel_item in structure["items"]:
                item_type = str(panel_item.get("item_type") or "test")
                if item_type in {"heading", "comment"}:
                    restored.append(
                        {
                            "order_test_id": None,
                            "test_id": None,
                            "item_type": item_type,
                            "test_name": str(panel_item.get("heading_text") or panel_item.get("label") or ""),
                            "result_value": "",
                            "unit": "",
                            "reference_text": "",
                            "lower_value": "",
                            "upper_value": "",
                            "flag": "",
                            "comments": "",
                            "source_label": structure["name"],
                        }
                    )
                    continue
                test_id = panel_item.get("test_id")
                if test_id is None:
                    continue
                matched = by_test_id.get(int(test_id))
                if matched is None:
                    continue
                normalized = dict(matched)
                normalized["source_label"] = structure["name"]
                restored.append(normalized)
                used_test_ids.add(int(test_id))
            for item in order_items:
                test_id = item.get("test_id")
                if test_id is None or int(test_id) not in used_test_ids:
                    normalized = dict(item)
                    normalized["source_label"] = structure["name"]
                    restored.append(normalized)
        return restored

    def _normalize_panel_source_items(
        self,
        items: list[dict[str, Any]],
        label: str,
        structures: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        structure = structures.get(label.casefold())
        resolved_label = str((structure or {}).get("name") or label).strip()
        normalized_items: list[dict[str, Any]] = []
        for item in items:
            normalized = dict(item)
            normalized["source_label"] = resolved_label
            normalized_items.append(normalized)
        return normalized_items

    def _panel_catalog_structures(self) -> dict[str, dict[str, Any]]:
        with self.connect() as connection:
            panel_rows = connection.execute("SELECT id, code, name FROM test_panels WHERE is_active = 1").fetchall()
            item_rows = connection.execute(
                "SELECT panel_id, item_type, test_id, heading_text, sort_order FROM test_panel_items ORDER BY panel_id, sort_order, id"
            ).fetchall()
        items_by_panel_id: dict[int, list[dict[str, Any]]] = {}
        for row in item_rows:
            items_by_panel_id.setdefault(int(row["panel_id"]), []).append(dict(row))
        structures: dict[str, dict[str, Any]] = {}
        for row in panel_rows:
            name = str(row["name"] or "").strip()
            code = str(row["code"] or "").strip()
            if not name:
                continue
            structure = {
                "name": name,
                "code": code,
                "items": items_by_panel_id.get(int(row["id"]), []),
            }
            for key in {name, code, self._normalize_report_panel_label(f"{name} ({code})"), self._normalize_report_panel_label(f"{name} ({code}) - 1 tests")}:
                normalized_key = str(key or "").strip()
                if normalized_key:
                    structures[normalized_key.casefold()] = structure
        return structures

    def _apply_culture_layout(
        self,
        items: list[dict[str, Any]],
        order_id: int | None = None,
        report_version: int = 0,
    ) -> list[dict[str, Any]]:
        """Rewrite culture panels' rows into the banded microbiology layout.

        Runs after _inject_panel_title_rows, so a culture panel arrives here as
        its injected `heading` row followed by its test rows. Those are replaced
        by culture_* rows that report_layout renders as bands and name/value
        pairs. Panels that are not culture panels pass through untouched.
        """
        culture_panels = self.get_culture_panels_by_name()
        frotis_panels = self.get_frotis_panels_by_name()
        if not culture_panels and not frotis_panels:
            return items
        culture_codes = self.get_culture_panel_codes_by_name()

        def config_for(item: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
            label = self._normalize_report_panel_label(str(item.get("source_label") or ""))
            if not label:
                return None
            key = label.casefold()
            if key in culture_panels:
                return ("cultivo", culture_panels[key])
            if key in frotis_panels:
                return ("frotis", frotis_panels[key])
            return None

        rendered: list[dict[str, Any]] = []
        index = 0
        sort_order = 0

        def emit(item_type: str, name: str, value: str = "") -> None:
            nonlocal sort_order
            rendered.append(
                {
                    "order_test_id": None,
                    "test_id": None,
                    "item_type": item_type,
                    "test_name": name,
                    "result_value": value,
                    "unit": "",
                    "reference_text": "",
                    "lower_value": "",
                    "upper_value": "",
                    "flag": "",
                    "comments": "",
                    "sort_order": sort_order,
                }
            )
            sort_order += 1

        def emit_triple(item_type: str, name: str, value: str, third: str) -> None:
            # The third column rides in `unit`, which every preview item already has.
            nonlocal sort_order
            rendered.append(
                {
                    "order_test_id": None,
                    "test_id": None,
                    "item_type": item_type,
                    "test_name": name,
                    "result_value": value,
                    "unit": third,
                    "reference_text": "",
                    "lower_value": "",
                    "upper_value": "",
                    "flag": "",
                    "comments": "",
                    "sort_order": sort_order,
                }
            )
            sort_order += 1

        while index < len(items):
            item = items[index]
            matched = config_for(item)
            if matched is None:
                # _inject_panel_title_rows emits the panel-name heading without a
                # source_label, so it would otherwise survive as a duplicate of
                # the title band that replaces it.
                if str(item.get("item_type") or "") == "heading" and not str(item.get("source_label") or "").strip():
                    heading_name = str(item.get("test_name") or "").strip().casefold()
                    if heading_name in culture_panels or heading_name in frotis_panels:
                        index += 1
                        continue
                normalized = dict(item)
                normalized["sort_order"] = sort_order
                rendered.append(normalized)
                sort_order += 1
                index += 1
                continue
            kind, config = matched

            # Collect the whole run of rows belonging to this culture panel.
            label = self._normalize_report_panel_label(str(item.get("source_label") or ""))
            block: list[dict[str, Any]] = []
            while index < len(items):
                candidate = items[index]
                candidate_label = self._normalize_report_panel_label(str(candidate.get("source_label") or ""))
                if candidate_label.casefold() != label.casefold():
                    break
                block.append(candidate)
                index += 1

            by_name = {
                str(row.get("test_name") or "").strip().casefold(): row
                for row in block
                if str(row.get("item_type") or "test") == "test"
            }

            def value_of(name: str) -> str:
                row = by_name.get(str(name).strip().casefold())
                return str((row or {}).get("result_value") or "").strip()

            emit("culture_title", config["title"] or label)

            if kind == "cultivo":
                panel_code = culture_codes.get(label.casefold(), "")
                culture_data = (
                    self.get_order_culture_data(order_id, panel_code, report_version)
                    if order_id is not None and panel_code
                    else {"gram": "", "rows": []}
                )
                if config["pathogens_heading"]:
                    emit("culture_section", config["pathogens_heading"])
                # Free-form rows typed by the tech. Blank rows are dropped so the
                # printed report never shows empty lines.
                for entry in culture_data["rows"]:
                    if entry["label"] or entry["value"]:
                        emit("culture_pair", entry["label"], entry["value"])

                if config["isolate_name"]:
                    emit("culture_isolate", config["isolate_label"], value_of(config["isolate_name"]))

                for name in config["extra_names"]:
                    row = by_name.get(name.strip().casefold()) or {}
                    emit("culture_pair", name, f"{value_of(name)} {str(row.get('unit') or '').strip()}".strip())

                gram = culture_data["gram"]
                if gram == GRAM_NEGATIVE:
                    antibiotics = config["antibiotic_names_negative"]
                    gram_label = config["gram_label_negative"]
                else:
                    antibiotics = config["antibiotic_names_positive"]
                    gram_label = config["gram_label_positive"]
                if antibiotics:
                    if config["susceptibility_heading"]:
                        emit("culture_section", config["susceptibility_heading"])
                    if gram_label:
                        emit("culture_subheading", gram_label)
                    emit_triple(
                        "culture_table_header",
                        config["antibiogram_col_1"],
                        config["antibiogram_col_2"],
                        config["antibiogram_col_3"],
                    )
                    concentrations = config["antibiotic_concentrations"]
                    for name in antibiotics:
                        emit_triple(
                            "culture_triple",
                            name,
                            value_of(name),
                            str(concentrations.get(name, "")).strip(),
                        )

                if config["method_note"]:
                    emit("culture_note", config["method_note"])
                continue

            if kind == "frotis":
                # Labelled narrative blocks: "Serie roja: <prose>". Falls back to
                # every test row in the panel when no sections are configured, so
                # a frotis panel still renders something useful before setup.
                names = config["section_names"] or [
                    str(row.get("test_name") or "").strip()
                    for row in block
                    if str(row.get("item_type") or "test") == "test"
                ]
                for name in names:
                    emit("frotis_block", name, value_of(name))
                if config["method_note"]:
                    emit("culture_note", config["method_note"])
                continue

        return rendered

    def _inject_panel_title_rows(self, items: list[dict[str, Any]], panel_metadata: dict[str, dict[str, str]] | None = None) -> list[dict[str, Any]]:
        panel_counts: dict[str, int] = {}
        for item in items:
            label = self._normalize_report_panel_label(str(item.get("source_label") or ""))
            if not label or str(item.get("item_type") or "test") != "test":
                continue
            panel_counts[label] = panel_counts.get(label, 0) + 1

        rendered: list[dict[str, Any]] = []
        active_panel = ""
        next_sort_order = 0
        metadata = panel_metadata or {}

        def append_panel_meta(panel_name: str) -> None:
            nonlocal next_sort_order
            values = metadata.get(panel_name) or {}
            specimen_type = str(values.get("specimen_type") or "").strip()
            method = str(values.get("method") or "").strip()
            if not specimen_type and not method:
                return
            # Only the halves that have a value: a panel with a method and no
            # specimen type used to print "Tipo de Muestra:" followed by nothing.
            parts = []
            if method:
                parts.append(f"{tr('Methodology')}: {method}")
            if specimen_type:
                parts.append(f"{tr('Specimen Type')}: {specimen_type}")
            rendered.append(
                {
                    "order_test_id": None,
                    "item_type": "panel_meta",
                    "test_name": "",
                    "result_value": "",
                    "unit": "",
                    "reference_text": "",
                    "lower_value": "",
                    "upper_value": "",
                    "flag": "",
                    "comments": " | ".join(parts),
                    "sort_order": next_sort_order,
                }
            )
            next_sort_order += 1

        for item in items:
            normalized = dict(item)
            item_type = str(normalized.get("item_type") or "test")
            label = self._normalize_report_panel_label(str(normalized.get("source_label") or ""))
            normalized["source_label"] = label
            if item_type in {"test", "heading", "comment"} and label and label != active_panel:
                if active_panel:
                    append_panel_meta(active_panel)
                rendered.append(
                    {
                        "order_test_id": None,
                        "item_type": "heading",
                        "test_name": label,
                        "result_value": "",
                        "unit": "",
                        "reference_text": "",
                        "lower_value": "",
                        "upper_value": "",
                        "flag": "",
                        "comments": "",
                        "sort_order": next_sort_order,
                    }
                )
                next_sort_order += 1
                active_panel = label
            normalized["sort_order"] = next_sort_order
            rendered.append(normalized)
            next_sort_order += 1
            if item_type == "heading" and not label:
                active_panel = ""
        if active_panel:
            append_panel_meta(active_panel)
        return rendered

    @staticmethod
    def _normalize_report_panel_label(value: str) -> str:
        label = value.strip()
        if not label:
            return ""
        label = re.sub(r"\s*-\s*\d+\s+tests\s*$", "", label, flags=re.IGNORECASE).strip()
        return re.sub(r"\s+\([A-Z0-9_-]{1,20}\)$", "", label).strip()

    def finalize_report(
        self,
        order_id: int,
        *,
        header_image_path: str | None = None,
        footer_signature_image_path: str | None = None,
        preview_override: dict[str, Any] | None = None,
    ) -> int:
        preview = dict(preview_override) if preview_override is not None else self.get_live_report_preview(order_id)
        if preview is None:
            raise sqlite3.IntegrityError("Order not found.")
        preview["items"] = [dict(item) for item in list(preview.get("items") or [])]
        preview["outsourced_panels"] = [
            {
                "panel_label": str(section.get("panel_label") or ""),
                "source_pdf_path": str(section.get("source_pdf_path") or ""),
                "rows": [
                    {
                        "row_index": index,
                        "col_1": str(row.get("col_1") or ""),
                        "col_2": str(row.get("col_2") or ""),
                        "col_3": str(row.get("col_3") or ""),
                        "col_4": str(row.get("col_4") or ""),
                        "col_5": str(row.get("col_5") or ""),
                    }
                    for index, row in enumerate(list(section.get("rows") or []))
                ],
            }
            for section in list(preview.get("outsourced_panels") or [])
        ]
        if header_image_path is not None:
            preview["header_image_path"] = self._copy_report_branding_asset(header_image_path, "header") if header_image_path.strip() else ""
        if footer_signature_image_path is not None:
            preview["footer_signature_image_path"] = self._copy_report_branding_asset(footer_signature_image_path, "footer") if footer_signature_image_path.strip() else ""
        for index, item in enumerate(preview["items"]):
            item["sort_order"] = index
        reportable_items = [item for item in preview["items"] if item["item_type"] != "heading"]
        outsourced_sections = [section for section in preview["outsourced_panels"] if list(section.get("rows") or [])]
        if not reportable_items and not outsourced_sections:
            raise sqlite3.IntegrityError("The selected order has no reportable items.")
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id, report_version FROM reports WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            next_version = int(existing["report_version"]) + 1 if existing is not None else 1
            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO reports (
                        order_id, report_version, status, finalized_at, patient_snapshot_name, patient_snapshot_sex,
                        patient_snapshot_dob, doctor_snapshot_name, lab_snapshot_name, lab_snapshot_address,
                        lab_snapshot_phone, lab_snapshot_email, director_snapshot_name, director_snapshot_license,
                        footer_snapshot_text, header_image_snapshot_path, footer_signature_snapshot_path, general_comments
                    ) VALUES (?, ?, 'final', datetime('now','localtime'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                    ,
                    (
                        order_id,
                        next_version,
                        preview["patient_name"],
                        preview["patient_sex"],
                        preview["patient_dob"],
                        preview["doctor_name"],
                        preview["lab_name"],
                        preview["lab_address"],
                        preview["lab_phone"],
                        preview["lab_email"],
                        preview["director_name"],
                        preview["director_license"],
                        preview["footer_text"],
                        preview["header_image_path"],
                        preview["footer_signature_image_path"],
                        preview["general_comments"],
                    ),
                )
                report_id = int(cursor.lastrowid)
            else:
                report_id = int(existing["id"])
                connection.execute(
                    """
                    UPDATE reports
                    SET report_version = ?,
                        status = 'final',
                        finalized_at = datetime('now','localtime'),
                        patient_snapshot_name = ?,
                        patient_snapshot_sex = ?,
                        patient_snapshot_dob = ?,
                        doctor_snapshot_name = ?,
                        lab_snapshot_name = ?,
                        lab_snapshot_address = ?,
                        lab_snapshot_phone = ?,
                        lab_snapshot_email = ?,
                        director_snapshot_name = ?,
                        director_snapshot_license = ?,
                        footer_snapshot_text = ?,
                        header_image_snapshot_path = ?,
                        footer_signature_snapshot_path = ?,
                        general_comments = ?
                    WHERE id = ?
                    """
                    ,
                    (
                        next_version,
                        preview["patient_name"],
                        preview["patient_sex"],
                        preview["patient_dob"],
                        preview["doctor_name"],
                        preview["lab_name"],
                        preview["lab_address"],
                        preview["lab_phone"],
                        preview["lab_email"],
                        preview["director_name"],
                        preview["director_license"],
                        preview["footer_text"],
                        preview["header_image_path"],
                        preview["footer_signature_image_path"],
                        preview["general_comments"],
                        report_id,
                    ),
                )
                connection.execute("DELETE FROM report_items WHERE report_id = ?", (report_id,))
                connection.execute("DELETE FROM report_outsourced_rows WHERE report_id = ?", (report_id,))
                connection.execute("DELETE FROM report_item_images WHERE report_id = ?", (report_id,))
            for item in preview["items"]:
                order_test_id = item.get("order_test_id")
                if not order_test_id:
                    order_test_id = self._resolve_report_item_order_test_id(connection, order_id, item)
                connection.execute(
                    """
                    INSERT INTO report_items (
                        report_id, order_test_id, test_name_snapshot, result_value_snapshot, unit_snapshot,
                        reference_text_snapshot, lower_value_snapshot, upper_value_snapshot,
                        lower_value_snapshot_text, upper_value_snapshot_text, flag_snapshot,
                        comments_snapshot, sort_order, item_type_snapshot
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                    ,
                    (
                        report_id,
                        order_test_id or None,
                        item["test_name"],
                        item["result_value"] or None,
                        item["unit"] or None,
                        item["reference_text"] or None,
                        self._decimal_to_float(item["lower_value"]),
                        self._decimal_to_float(item["upper_value"]),
                        item["lower_value"] or None,
                        item["upper_value"] or None,
                        item["flag"] or None,
                        item["comments"] or None,
                        item["sort_order"],
                        item["item_type"],
                    ),
                )
            for item in preview["items"]:
                if str(item.get("result_kind") or "") != "image":
                    continue
                order_test_id = item.get("order_test_id")
                if not order_test_id:
                    continue
                connection.execute(
                    """
                    INSERT INTO report_item_images (report_id, order_test_id, image_data, mime_type, caption, sort_order)
                    SELECT ?, order_test_id, image_data, mime_type, caption, sort_order
                    FROM result_images
                    WHERE order_test_id = ?
                    """,
                    (report_id, order_test_id),
                )
            for section in outsourced_sections:
                for row in list(section.get("rows") or []):
                    connection.execute(
                        """
                        INSERT INTO report_outsourced_rows (
                            report_id, panel_label, source_pdf_path, row_index, col_1, col_2, col_3, col_4, col_5
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            report_id,
                            section.get("panel_label") or "",
                            section.get("source_pdf_path") or "",
                            int(row.get("row_index") or 0),
                            row.get("col_1") or None,
                            row.get("col_2") or None,
                            row.get("col_3") or None,
                            row.get("col_4") or None,
                            row.get("col_5") or None,
                        ),
                    )
            connection.execute(
                """
                UPDATE order_tests
                SET status = 'reported'
                WHERE order_id = ?
                  AND test_id IN (
                      SELECT id FROM tests WHERE code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                  )
                """,
                (order_id,),
            )
            connection.execute(
                "UPDATE orders SET status = 'finalized', reported_at = datetime('now','localtime'), updated_at = datetime('now','localtime') WHERE id = ?",
                (order_id,),
            )
        # Freeze the culture rows against this version. They live outside
        # report_items (they are not test results), so they need their own
        # snapshot for the finalized report to keep rendering what was signed.
        self.snapshot_order_culture_data(order_id, next_version)
        return report_id

    def delete_saved_report(self, order_id: int) -> None:
        with self.connect() as connection:
            report_row = connection.execute(
                "SELECT id FROM reports WHERE order_id = ?", (order_id,)
            ).fetchone()
            if report_row is None:
                return
            report_id = report_row["id"]
            connection.execute("DELETE FROM report_outsourced_rows WHERE report_id = ?", (report_id,))
            connection.execute("DELETE FROM report_item_images WHERE report_id = ?", (report_id,))
            connection.execute("DELETE FROM report_items WHERE report_id = ?", (report_id,))
            connection.execute("DELETE FROM reports WHERE id = ?", (report_id,))

    def save_result_entry(self, order_test_id: int, result_value: str, unit: str, lower_value: str | None, upper_value: str | None, reference_text: str, comments: str, result_kind: str) -> None:
        normalized_value = result_value.strip()
        if result_kind == "numeric":
            normalized_value = normalized_value.replace(",", "")
        normalized_unit = unit.strip()
        normalized_reference = reference_text.strip()
        normalized_comments = comments.strip()
        flag = self._calculate_flag(result_kind, normalized_value, lower_value, upper_value)
        with self.connect() as connection:
            existing = connection.execute("SELECT id FROM results WHERE order_test_id = ?", (order_test_id,)).fetchone()
            if existing:
                connection.execute("UPDATE results SET result_value = ?, unit = ?, lower_value = ?, upper_value = ?, lower_value_text = ?, upper_value_text = ?, flag = ?, reference_text = ?, comments = ?, entered_at = datetime('now','localtime') WHERE order_test_id = ?", (normalized_value or None, normalized_unit or None, self._decimal_to_float(lower_value), self._decimal_to_float(upper_value), lower_value, upper_value, flag, normalized_reference or None, normalized_comments or None, order_test_id))
            else:
                connection.execute("INSERT INTO results (order_test_id, result_value, unit, lower_value, upper_value, lower_value_text, upper_value_text, flag, reference_text, comments, entered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))", (order_test_id, normalized_value or None, normalized_unit or None, self._decimal_to_float(lower_value), self._decimal_to_float(upper_value), lower_value, upper_value, flag, normalized_reference or None, normalized_comments or None))
            connection.execute("UPDATE order_tests SET status = 'entered' WHERE id = ?", (order_test_id,))
            connection.execute("UPDATE orders SET status = 'in_progress', updated_at = datetime('now','localtime') WHERE id = (SELECT order_id FROM order_tests WHERE id = ?)", (order_test_id,))
            order_row = connection.execute("SELECT order_id FROM order_tests WHERE id = ?", (order_test_id,)).fetchone()
            if order_row is not None:
                _recalculate_formula_tests(connection, int(order_row["order_id"]))

    def list_result_images(self, order_test_id: int, *, include_data: bool = False) -> list[dict[str, Any]]:
        columns = "id, mime_type, caption, sort_order, created_at"
        if include_data:
            columns += ", image_data"
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT {columns} FROM result_images WHERE order_test_id = ? ORDER BY sort_order, id",
                (order_test_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_result_image(self, order_test_id: int, image_data: bytes, mime_type: str = "image/png", caption: str = "") -> int:
        with self.connect() as connection:
            next_sort_row = connection.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort FROM result_images WHERE order_test_id = ?",
                (order_test_id,),
            ).fetchone()
            next_sort = int(next_sort_row["next_sort"]) if next_sort_row is not None else 0
            cursor = connection.execute(
                "INSERT INTO result_images (order_test_id, image_data, mime_type, caption, sort_order, created_at) VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))",
                (order_test_id, sqlite3.Binary(image_data), mime_type or "image/png", (caption or "").strip() or None, next_sort),
            )
            self._refresh_image_result_summary(connection, order_test_id)
            return int(cursor.lastrowid)

    def update_result_image_caption(self, image_id: int, caption: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE result_images SET caption = ? WHERE id = ?",
                ((caption or "").strip() or None, image_id),
            )

    def delete_result_image(self, image_id: int) -> None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT order_test_id FROM result_images WHERE id = ?", (image_id,)
            ).fetchone()
            connection.execute("DELETE FROM result_images WHERE id = ?", (image_id,))
            if row is not None:
                self._refresh_image_result_summary(connection, int(row["order_test_id"]))

    def reorder_result_images(self, order_test_id: int, ordered_ids: list[int]) -> None:
        with self.connect() as connection:
            for sort_order, image_id in enumerate(ordered_ids):
                connection.execute(
                    "UPDATE result_images SET sort_order = ? WHERE id = ? AND order_test_id = ?",
                    (sort_order, image_id, order_test_id),
                )

    def _refresh_image_result_summary(self, connection: sqlite3.Connection, order_test_id: int) -> None:
        count_row = connection.execute(
            "SELECT COUNT(*) AS count FROM result_images WHERE order_test_id = ?",
            (order_test_id,),
        ).fetchone()
        count = int(count_row["count"]) if count_row is not None else 0
        summary = tr("{count} image(s)").format(count=count) if count else ""
        existing = connection.execute(
            "SELECT id FROM results WHERE order_test_id = ?", (order_test_id,)
        ).fetchone()
        if existing:
            connection.execute(
                "UPDATE results SET result_value = ?, flag = 'none', entered_at = datetime('now','localtime') WHERE order_test_id = ?",
                (summary or None, order_test_id),
            )
        else:
            connection.execute(
                "INSERT INTO results (order_test_id, result_value, flag, entered_at) VALUES (?, ?, 'none', datetime('now','localtime'))",
                (order_test_id, summary or None),
            )
        new_status = "entered" if count else "pending"
        connection.execute("UPDATE order_tests SET status = ? WHERE id = ?", (new_status, order_test_id))
        connection.execute(
            "UPDATE orders SET status = 'in_progress', updated_at = datetime('now','localtime') WHERE id = (SELECT order_id FROM order_tests WHERE id = ?)",
            (order_test_id,),
        )

    @staticmethod
    def _encode_image_rows(rows: list[Any]) -> list[dict[str, Any]]:
        encoded: list[dict[str, Any]] = []
        for row in rows:
            data = row["image_data"]
            if data is None:
                continue
            encoded.append(
                {
                    "mime_type": str(row["mime_type"] or "image/png"),
                    "caption": str(row["caption"] or ""),
                    "data": base64.b64encode(bytes(data)).decode("ascii"),
                }
            )
        return encoded

    def _result_images_by_order_test(self, connection: sqlite3.Connection, order_id: int) -> dict[int, list[dict[str, Any]]]:
        rows = connection.execute(
            """
            SELECT ri.order_test_id, ri.image_data, ri.mime_type, ri.caption
            FROM result_images ri
            INNER JOIN order_tests ot ON ot.id = ri.order_test_id
            WHERE ot.order_id = ?
            ORDER BY ri.order_test_id, ri.sort_order, ri.id
            """,
            (order_id,),
        ).fetchall()
        grouped: dict[int, list[Any]] = {}
        for row in rows:
            grouped.setdefault(int(row["order_test_id"]), []).append(row)
        return {key: self._encode_image_rows(value) for key, value in grouped.items()}

    def _report_snapshot_images_by_order_test(self, connection: sqlite3.Connection, report_id: int) -> dict[int, list[dict[str, Any]]]:
        rows = connection.execute(
            """
            SELECT order_test_id, image_data, mime_type, caption
            FROM report_item_images
            WHERE report_id = ?
            ORDER BY order_test_id, sort_order, id
            """,
            (report_id,),
        ).fetchall()
        grouped: dict[int, list[Any]] = {}
        for row in rows:
            grouped.setdefault(int(row["order_test_id"]), []).append(row)
        return {key: self._encode_image_rows(value) for key, value in grouped.items()}

    def _resolve_reference_range(self, connection: sqlite3.Connection, test_id: int, patient_sex: str | None, patient_age_days: int | None) -> sqlite3.Row | None:
        rows = connection.execute("SELECT sex, age_min_days, age_max_days, COALESCE(lower_value_text, CAST(lower_value AS TEXT)) AS lower_value, COALESCE(upper_value_text, CAST(upper_value AS TEXT)) AS upper_value, unit, reference_text FROM test_reference_ranges WHERE test_id = ? ORDER BY CASE WHEN sex IS NULL OR sex = '' THEN 1 ELSE 0 END, CASE WHEN age_min_days IS NULL THEN 1 ELSE 0 END, age_min_days, CASE WHEN age_max_days IS NULL THEN 1 ELSE 0 END, age_max_days", (test_id,)).fetchall()
        for row in rows:
            sex = row["sex"]
            if sex and patient_sex and sex != patient_sex:
                continue
            if sex and not patient_sex:
                continue
            min_days = row["age_min_days"]
            max_days = row["age_max_days"]
            if patient_age_days is not None:
                if min_days is not None and patient_age_days < min_days:
                    continue
                if max_days is not None and patient_age_days > max_days:
                    continue
            return row
        return None

    @staticmethod
    def _resolve_age_days(date_of_birth: str | None, age_value: int | None, age_unit: str | None) -> int | None:
        # date_of_birth may come back as a non-string (e.g. an int year) for
        # patients imported with a partial DOB, so coerce before parsing and
        # fall through to age_value/age_unit when it isn't a usable date.
        dob_text = str(date_of_birth).strip() if date_of_birth is not None else ""
        if dob_text:
            try:
                dob = datetime.strptime(dob_text, "%Y-%m-%d").date()
                return max((date.today() - dob).days, 0)
            except ValueError:
                pass
        if age_value is None or not age_unit:
            return None
        if age_unit == "days":
            return age_value
        if age_unit == "months":
            return age_value * 30
        if age_unit == "years":
            return age_value * 365
        return None

    @staticmethod
    def _calculate_flag(result_kind: str, result_value: str, lower_value: str | None, upper_value: str | None) -> str:
        if result_kind != "numeric" or not result_value:
            return "none"
        from decimal import Decimal, InvalidOperation
        def _to_decimal_local(value: Any) -> Decimal | None:
            if value is None:
                return None
            normalized = str(value).strip().replace(",", "")
            if not normalized:
                return None
            try:
                return Decimal(normalized)
            except InvalidOperation:
                return None
        numeric_value = _to_decimal_local(result_value)
        if numeric_value is None:
            return "none"
        lower_decimal = _to_decimal_local(lower_value)
        upper_decimal = _to_decimal_local(upper_value)
        if lower_decimal is not None and numeric_value < lower_decimal:
            return "low"
        if upper_decimal is not None and numeric_value > upper_decimal:
            return "high"
        if lower_decimal is not None or upper_decimal is not None:
            return "normal"
        return "none"


_FORMULA_OPS: dict = {
    _ast.Add: _operator.add,
    _ast.Sub: _operator.sub,
    _ast.Mult: _operator.mul,
    _ast.Div: _operator.truediv,
    _ast.USub: _operator.neg,
}


def _safe_eval_formula_node(node: _ast.AST) -> float:
    if isinstance(node, _ast.BinOp) and type(node.op) in _FORMULA_OPS:
        return _FORMULA_OPS[type(node.op)](_safe_eval_formula_node(node.left), _safe_eval_formula_node(node.right))
    if isinstance(node, _ast.UnaryOp) and type(node.op) in _FORMULA_OPS:
        return _FORMULA_OPS[type(node.op)](_safe_eval_formula_node(node.operand))
    if isinstance(node, _ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    raise ValueError(f"Unsupported node: {type(node).__name__}")


def _evaluate_formula(formula: str, values_by_code: dict[str, float]) -> float | None:
    expr = formula.upper()
    for code, value in values_by_code.items():
        expr = _re.sub(r'\[' + _re.escape(code) + r'\]', str(value), expr)
    if _re.search(r'\[', expr):
        return None
    try:
        tree = _ast.parse(expr, mode='eval')
        return _safe_eval_formula_node(tree.body)
    except (ValueError, ZeroDivisionError, SyntaxError, TypeError):
        return None


def _format_formula_result(value: float) -> str:
    if value == int(value) and abs(value) < 1e10:
        return str(int(value))
    return f"{value:.6g}"


def _recalculate_formula_tests(connection: sqlite3.Connection, order_id: int) -> None:
    formula_rows = connection.execute(
        "SELECT ot.id AS order_test_id, t.formula FROM order_tests ot INNER JOIN tests t ON t.id = ot.test_id WHERE ot.order_id = ? AND t.formula IS NOT NULL AND t.formula != ''",
        (order_id,),
    ).fetchall()
    if not formula_rows:
        return
    result_rows = connection.execute(
        "SELECT t.code, r.result_value FROM order_tests ot INNER JOIN tests t ON t.id = ot.test_id LEFT JOIN results r ON r.order_test_id = ot.id WHERE ot.order_id = ?",
        (order_id,),
    ).fetchall()
    values_by_code: dict[str, float] = {}
    for row in result_rows:
        code = str(row["code"] or "").strip().upper()
        raw = str(row["result_value"] or "").strip()
        if code and raw:
            try:
                values_by_code[code] = float(Decimal(raw.replace(",", "")))
            except (InvalidOperation, ValueError):
                pass
    for formula_row in formula_rows:
        formula_test_id = int(formula_row["order_test_id"])
        formula = str(formula_row["formula"] or "").strip()
        if not formula:
            continue
        computed = _evaluate_formula(formula, values_by_code)
        if computed is None:
            continue
        result_str = _format_formula_result(computed)
        existing = connection.execute("SELECT id FROM results WHERE order_test_id = ?", (formula_test_id,)).fetchone()
        if existing:
            connection.execute(
                "UPDATE results SET result_value = ?, flag = 'none', entered_at = datetime('now','localtime') WHERE order_test_id = ?",
                (result_str, formula_test_id),
            )
        else:
            connection.execute(
                "INSERT INTO results (order_test_id, result_value, flag, entered_at) VALUES (?, ?, 'none', datetime('now','localtime'))",
                (formula_test_id, result_str),
            )
        connection.execute("UPDATE order_tests SET status = 'entered' WHERE id = ?", (formula_test_id,))
