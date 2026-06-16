from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QTextDocument
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database
from spdxlims.niimbot_client import NIIMBOTClient, NIIMBOTClientError
from spdxlims.i18n import tr


class OrderLabelsDialog(QDialog):
    # Code 128B symbol patterns: [bar1, space1, bar2, space2, bar3, space3] widths
    _CODE128_PATTERNS: list[list[int]] = [
        [2,1,2,2,2,2],[2,2,2,1,2,2],[2,2,2,2,2,1],[1,2,1,2,2,3],[1,2,1,3,2,2],
        [1,3,1,2,2,2],[1,2,2,2,1,3],[1,2,2,3,1,2],[1,3,2,2,1,2],[2,2,1,2,1,3],
        [2,2,1,3,1,2],[2,3,1,2,1,2],[1,1,2,2,3,2],[1,2,2,1,3,2],[1,2,2,2,3,1],
        [1,1,3,2,2,2],[1,2,3,1,2,2],[1,2,3,2,2,1],[2,2,3,2,1,1],[2,2,1,1,3,2],
        [2,2,1,2,3,1],[2,1,3,2,1,2],[2,2,3,1,1,2],[3,1,2,1,3,1],[3,1,1,2,2,2],
        [3,2,1,1,2,2],[3,2,1,2,2,1],[3,1,2,2,1,2],[3,2,2,1,1,2],[3,2,2,2,1,1],
        [2,1,2,1,2,3],[2,1,2,3,2,1],[2,3,2,1,2,1],[1,1,1,3,2,3],[1,3,1,1,2,3],
        [1,3,1,3,2,1],[1,1,2,3,1,3],[1,3,2,1,1,3],[1,3,2,3,1,1],[2,1,1,3,1,3],
        [2,3,1,1,1,3],[2,3,1,3,1,1],[1,1,2,1,3,3],[1,1,2,3,3,1],[1,3,2,1,3,1],
        [1,1,3,1,2,3],[1,1,3,3,2,1],[1,3,3,1,2,1],[3,1,3,1,2,1],[2,1,1,3,3,1],
        [2,3,1,1,3,1],[2,1,3,1,1,3],[2,1,3,3,1,1],[2,1,3,1,3,1],[3,1,1,1,2,3],
        [3,1,1,3,2,1],[3,3,1,1,2,1],[3,1,2,1,1,3],[3,1,2,3,1,1],[3,3,2,1,1,1],
        [3,1,4,1,1,1],[2,2,1,4,1,1],[4,3,1,1,1,1],[1,1,1,2,2,4],[1,1,1,4,2,2],
        [1,2,1,1,2,4],[1,2,1,4,2,1],[1,4,1,1,2,2],[1,4,1,2,2,1],[1,1,2,2,1,4],
        [1,1,2,4,1,2],[1,2,2,1,1,4],[1,2,2,4,1,1],[1,4,2,1,1,2],[1,4,2,2,1,1],
        [2,4,1,2,1,1],[2,2,1,1,1,4],[4,1,3,1,1,1],[2,4,1,1,1,2],[1,3,4,1,1,1],
        [1,1,1,2,4,2],[1,2,1,1,4,2],[1,2,1,2,4,1],[1,1,4,2,1,2],[1,2,4,1,1,2],
        [1,2,4,2,1,1],[4,1,1,2,1,2],[4,2,1,1,1,2],[4,2,1,2,1,1],[2,1,2,1,4,1],
        [2,1,4,1,2,1],[4,1,2,1,2,1],[1,1,1,1,4,3],[1,1,1,3,4,1],[1,3,1,1,4,1],
        [1,1,4,1,1,3],[1,1,4,3,1,1],[4,1,1,1,1,3],[4,1,1,3,1,1],[1,1,3,1,4,1],
        [1,1,4,1,3,1],[3,1,1,1,4,1],[4,1,1,1,3,1],[2,1,1,4,1,2],[2,1,1,2,1,4],
        [2,1,1,2,3,2],  # 105: START C
    ]
    _CODE128_STOP: list[int] = [2,3,3,1,1,1,2]  # 13-module stop symbol

    @classmethod
    def _encode_code128b(cls, text: str) -> list[int]:
        """Return Code 128B symbol values [START_B, data..., check] (stop rendered separately)."""
        START_B = 104
        symbols: list[int] = [START_B]
        for ch in text:
            v = ord(ch)
            symbols.append((v - 32) if 32 <= v <= 127 else 0)
        check = START_B
        for i, val in enumerate(symbols[1:], 1):
            check += i * val
        symbols.append(check % 103)
        return symbols

    def __init__(self, database: Database, order_id: int | None = None, label_rows: list[dict[str, object]] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.order_id = order_id
        self.label_rows: list[dict[str, object]] = list(label_rows or [])
        self.client_id: int | None = None
        self._loading_preferences = False
        self.show_barcode = True
        self.show_patient_name = True
        self.setWindowTitle(tr("Print Labels"))
        self.setModal(True)
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(
                min(860, max(720, available.width() - 120)),
                min(620, max(520, available.height() - 120)),
            )
        else:
            self.resize(820, 620)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        self.info = QLabel()
        self.info.setWordWrap(True)
        root.addWidget(self.info)

        self._panel_extras: dict[str, QSpinBox] = {}
        controls = QGridLayout()
        self._controls = controls
        controls.setVerticalSpacing(8)
        controls.setHorizontalSpacing(10)
        self.size_combo = QComboBox()
        self.size_combo.currentIndexChanged.connect(self._refresh_preview)
        self.size_combo.addItem('40 x 20 mm', 'vial_small')
        self.size_combo.addItem('50 x 20 mm', 'tube_small')
        self.size_combo.addItem('50 x 25 mm', 'small')
        self.size_combo.addItem('50 x 30 mm', 'small_tall')
        self.size_combo.addItem('62 x 30 mm', 'medium')
        self.size_combo.addItem('100 x 50 mm', 'large')
        self.template_label = QLabel()
        self.template_combo = QComboBox()
        self.template_combo.addItem(tr('General Lab'), 'general')
        self.template_label.hide()
        self.template_combo.hide()
        self.code_combo = QComboBox()
        self.code_combo.currentIndexChanged.connect(self._refresh_preview)
        self.code_combo.addItem(tr('Barcode + Patient Name'), 'barcode_name')
        self.code_combo.addItem(tr('Barcode Only'), 'barcode_only')
        self.payload_combo = QComboBox()
        self.payload_combo.currentIndexChanged.connect(self._on_payload_changed)
        self.payload_combo.addItem(tr('Order ID only'), 'order_only')
        self.payload_combo.addItem(tr('Order ID + specimen code'), 'order_specimen')
        self.payload_combo.addItem(tr('Accession ID only'), 'accession_only')
        self.payload_combo.addItem(tr('Sample ID only'), 'sample_only')
        self.payload_combo.addItem(tr('Order ID + accession ID'), 'order_accession')
        self.show_order_number_text = QCheckBox(tr("Show Order Number Text"))
        self.show_order_number_text.stateChanged.connect(self._refresh_preview)
        self.show_datetime = QCheckBox(tr("Show Date, Sex & Age"))
        self.show_datetime.stateChanged.connect(self._refresh_preview)
        self.copies_label = QLabel()
        self.copies_input = QSpinBox()
        self.copies_input.setRange(1, 99)
        self.copies_input.setValue(1)
        self.copies_input.valueChanged.connect(self._refresh_preview)
        controls.addWidget(self.show_order_number_text, 0, 0, 1, 2)
        controls.addWidget(self.show_datetime, 0, 2, 1, 2)
        controls.addWidget(self.copies_label, 1, 0)
        controls.addWidget(self.copies_input, 1, 1)
        root.addLayout(controls)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(300)
        root.addWidget(self.preview)

        buttons = QHBoxLayout()
        self.close_button = QPushButton(tr("Close"))
        self.close_button.clicked.connect(self.reject)
        self.print_niimbot_button = QPushButton(tr("Print to NIIMBOT"))
        self.print_niimbot_button.clicked.connect(self.print_to_niimbot)
        self.print_button = QPushButton(tr("Print Labels"))
        self.print_button.clicked.connect(self.print_labels)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.print_niimbot_button)
        buttons.addWidget(self.print_button)
        root.addLayout(buttons)

        self._load_preview()

    def _load_preview(self) -> None:
        if not self.label_rows and self.order_id is not None:
            self.label_rows = self.database.get_order_label_entries(self.order_id)
        if not self.label_rows:
            self.info.setText(tr("No printable labels were found for this order."))
            self.print_button.setEnabled(False)
            self.print_niimbot_button.setEnabled(False)
            return
        self.info.setText(tr("Preview the specimen labels for the selected order before printing."))
        self.copies_label.setText(tr("Copies"))
        self.show_order_number_text.setText(tr("Show Order Number Text"))
        self.show_datetime.setText(tr("Show Date, Sex & Age"))
        self.client_id = self._resolve_client_id()
        self._load_saved_preferences()
        if self.order_id is not None:
            self._load_panel_extras()

    def _load_panel_extras(self) -> None:
        panel_codes = self.database.get_order_panel_codes(self.order_id)
        if not panel_codes:
            return
        saved_extras = self.database.get_panel_extra_copies()
        header_row = 2
        header = QLabel("Copias extra por panel:")
        self._controls.addWidget(header, header_row, 0, 1, 4)
        for i, code in enumerate(panel_codes, start=1):
            spin = QSpinBox()
            spin.setRange(0, 20)
            spin.setValue(saved_extras.get(code, 0))
            spin.valueChanged.connect(self._on_panel_extra_changed)
            self._controls.addWidget(QLabel(f"  {code}:"), header_row + i, 0)
            self._controls.addWidget(spin, header_row + i, 1)
            self._panel_extras[code] = spin
        self._refresh_preview()

    def _on_panel_extra_changed(self) -> None:
        self.database.save_panel_extra_copies({code: spin.value() for code, spin in self._panel_extras.items()})
        self._refresh_preview()

    def _resolve_client_id(self) -> int | None:
        if not self.label_rows:
            return None
        value = self.label_rows[0].get('client_id')
        if value in (None, ''):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _load_saved_preferences(self) -> None:
        preferences = self.database.get_label_print_preferences(self.client_id)
        self._loading_preferences = True
        size_index = self.size_combo.findData(preferences.get('size') or 'small_tall')
        if size_index >= 0:
            self.size_combo.setCurrentIndex(size_index)
        self.template_combo.setCurrentIndex(0)
        payload_index = self.payload_combo.findData(preferences.get('payload') or 'order_only')
        if payload_index >= 0:
            self.payload_combo.setCurrentIndex(payload_index)
        self.show_barcode = str(preferences.get('show_barcode') or '1') == '1'
        self.show_patient_name = str(preferences.get('show_patient_name') or '1') == '1'
        self.show_order_number_text.setChecked(str(preferences.get('show_order_number_text') or '0') == '1')
        self.show_datetime.setChecked(str(preferences.get('show_datetime') or '0') == '1')
        try:
            self.copies_input.setValue(max(1, int(str(preferences.get('copies') or '1'))))
        except ValueError:
            self.copies_input.setValue(1)
        self._loading_preferences = False
        self._refresh_preview()

    def _save_label_preferences(self) -> None:
        if not hasattr(self, "show_order_number_text") or not hasattr(self, "show_datetime"):
            return
        self.database.save_label_print_preferences(
            str(self.template_combo.currentData() or 'general'),
            str(self.payload_combo.currentData() or 'order_only'),
            self.client_id,
            show_barcode=self.show_barcode,
            show_patient_name=self.show_patient_name,
            show_order_number_text=self.show_order_number_text.isChecked(),
            show_datetime=self.show_datetime.isChecked(),
        )

    def _on_template_changed(self) -> None:
        if not hasattr(self, "payload_combo"):
            return
        self._apply_template_defaults()
        if not self._loading_preferences:
            self._save_label_preferences()

    def _on_payload_changed(self) -> None:
        self._refresh_preview()
        if not self._loading_preferences:
            self._save_label_preferences()

    def _apply_template_defaults(self) -> None:
        if not hasattr(self, "payload_combo"):
            return
        payload_defaults = {
            'general': 'order_only',
            'chemistry': 'order_specimen',
            'hematology': 'order_specimen',
            'microbiology': 'order_accession',
            'analyzer': 'order_only',
        }
        payload_key = payload_defaults.get(self.template_combo.currentData(), 'order_only')
        payload_index = self.payload_combo.findData(payload_key)
        if payload_index >= 0 and payload_index != self.payload_combo.currentIndex():
            self.payload_combo.setCurrentIndex(payload_index)
            return
        if not self._loading_preferences:
            self._refresh_preview()

    def _refresh_preview(self) -> None:
        if not self.label_rows:
            return
        copies = self._copies_count()
        base_row = self._base_label_row(self.label_rows)
        if base_row is None:
            return
        expanded_rows: list[dict[str, object]] = []
        for copy_number in range(1, copies + 1):
            item = dict(base_row)
            item['copy_number'] = copy_number
            item['copies_total'] = copies
            expanded_rows.append(item)
        self.preview.setHtml(
            self._build_label_html(
                expanded_rows,
                self.size_combo.currentData(),
                self.template_combo.currentData(),
                self.payload_combo.currentData(),
                show_barcode=self.show_barcode,
                show_patient_name=self.show_patient_name,
                show_order_number_text=self.show_order_number_text.isChecked(),
                show_datetime=self.show_datetime.isChecked(),
            )
        )

    def _copies_count(self) -> int:
        base = max(1, int(self.copies_input.value()))
        extras = sum(spin.value() for spin in self._panel_extras.values())
        return base + extras

    def print_labels(self) -> None:
        printer = QPrinter(QPrinter.HighResolution)
        preview = QPrintPreviewDialog(printer, self)
        document = QTextDocument()
        document.setHtml(self.preview.toHtml())
        print_method = getattr(document, "print", None) or getattr(document, "print_", None)
        if print_method is None:
            QMessageBox.critical(self, tr("Print Failed"), tr("This Qt build does not support document printing."))
            return
        preview.paintRequested.connect(print_method)
        preview.exec()

    def print_to_niimbot(self) -> None:
        if not self.label_rows:
            QMessageBox.warning(self, tr("Missing Selection"), tr("No printable labels were found for this order."))
            return
        base_row = self._base_label_row(self.label_rows)
        if base_row is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("No printable labels were found for this order."))
            return
        copies = self._copies_count()
        width_mm, height_mm = self._niimbot_label_size(self.size_combo.currentData())
        client = NIIMBOTClient()
        try:
            printers = client.list_printers()
            printer = next((item for item in printers if item.id and item.status.lower() != "offline"), None)
            if printer is None:
                raise NIIMBOTClientError(tr("No NIIMBOT printer was reported by the local helper."))
            token = self._build_token(base_row, "order_only")
            safe_token = "".join(character if character.isalnum() else "" for character in token.upper()) or token.upper()
            patient_name = str(base_row.get("patient_name") or "").strip()
            client.print_label(
                printer_id=printer.id,
                width_mm=width_mm,
                height_mm=height_mm,
                barcode_value=safe_token,
                human_text=safe_token,
                text_lines=self._label_text_lines(base_row),
                show_barcode=self.show_barcode,
                copies=copies,
            )
        except NIIMBOTClientError as exc:
            QMessageBox.warning(self, tr("NIIMBOT Print Failed"), str(exc))
            return
        QMessageBox.information(
            self,
            tr("Printed"),
            tr("Sent {count} NIIMBOT label(s) to the printer.", count=str(copies)),
        )

    def _base_label_row(self, rows: list[dict[str, object]]) -> dict[str, object] | None:
        if not rows:
            return None
        first_row = dict(rows[0])
        first_row['test_name'] = ''
        first_row['specimen_type'] = ''
        first_row['group_label'] = ''
        return first_row

    def _label_text_lines(self, row: dict[str, object]) -> list[str]:
        lines: list[str] = []
        if self.show_order_number_text.isChecked():
            order_number = str(row.get("order_number") or "").strip()
            if order_number:
                lines.append(order_number)
        if self.show_patient_name:
            patient_name = str(row.get("patient_name") or "").strip()
            if patient_name:
                lines.append(patient_name)
        if self.show_datetime.isChecked():
            dsa_parts: list[str] = []
            created_at = str(row.get("created_at") or "").strip()
            if created_at:
                dsa_parts.append(created_at)
            patient_sex = str(row.get("patient_sex") or "").strip()
            if patient_sex:
                dsa_parts.append(patient_sex)
            age_value = row.get("age_value")
            if age_value is not None:
                age_unit = str(row.get("age_unit") or "").lower()
                unit_abbr = {"years": "a", "months": "m", "days": "d"}.get(age_unit, age_unit[:1] if age_unit else "")
                dsa_parts.append(f"{age_value}{unit_abbr}")
            if dsa_parts:
                lines.append("  ".join(dsa_parts))
        return lines

    @classmethod
    def _build_label_html(
        cls,
        rows: list[dict[str, object]],
        size_key: str | None,
        template_key: str | None,
        payload_key: str | None,
        *,
        show_barcode: bool,
        show_patient_name: bool,
        show_order_number_text: bool,
        show_datetime: bool,
    ) -> str:
        profiles = {
            'vial_small': {'width': '40mm', 'padding': '5px', 'name': '10px', 'title': '12px', 'meta': '8px'},
            'tube_small': {'width': '50mm', 'padding': '5px', 'name': '10px', 'title': '12px', 'meta': '8px'},
            'small': {'width': '50mm', 'padding': '6px', 'name': '11px', 'title': '13px', 'meta': '9px'},
            'small_tall': {'width': '50mm', 'padding': '8px', 'name': '12px', 'title': '14px', 'meta': '10px'},
            'medium': {'width': '62mm', 'padding': '8px', 'name': '13px', 'title': '16px', 'meta': '10px'},
            'large': {'width': '100mm', 'padding': '12px', 'name': '16px', 'title': '20px', 'meta': '12px'},
        }
        templates = {
            'general': {'accent': '#222', 'subtitle': ''},
            'chemistry': {'accent': '#1f6f8b', 'subtitle': 'CHEM'},
            'hematology': {'accent': '#8b1f4a', 'subtitle': 'HEMA'},
            'microbiology': {'accent': '#2f6b2f', 'subtitle': 'MICRO'},
            'analyzer': {'accent': '#444', 'subtitle': 'ANALYZER'},
        }
        profile = profiles.get(size_key or 'medium', profiles['medium'])
        template = templates.get(template_key or 'general', templates['general'])
        blocks: list[str] = []
        for row in rows:
            token = cls._build_token(row, payload_key)
            machine_block = ''
            if show_barcode:
                machine_block = cls._code128_html(token)
            copies_text = ''
            if int(row.get('copies_total', 1) or 1) > 1:
                copies_text = f'<div style="font-size:{profile["meta"]};color:#666;">{tr("Copy")} {row.get("copy_number", 1)}/{row.get("copies_total", 1)}</div>'
            group_text = str(row.get('group_label') or '')
            subtitle = template['subtitle']
            accession = str(row.get('accession_id') or '')
            sample = str(row.get('sample_id') or '')
            id_line = ''
            if accession or sample:
                id_line = f'<div style="font-size:{profile["meta"]};color:#444;margin-top:2px;">{accession} {sample}</div>'
            subtitle_line = f'<div style="font-size:{profile["meta"]};font-weight:700;color:{template["accent"]};margin-top:2px;">{subtitle}</div>' if subtitle else ''
            patient_line = f'<div style="font-size:{profile["name"]};margin-top:4px;">{row.get("patient_name", "")}</div>' if show_patient_name and row.get("patient_name") else ''
            order_text_line = f'<div style="font-size:{profile["meta"]};margin-top:4px;">{row.get("order_number", "")}</div>' if show_order_number_text and row.get("order_number") else ''
            _dsa_parts: list[str] = []
            if show_datetime:
                if row.get("created_at"):
                    _dsa_parts.append(str(row.get("created_at", "")))
                if row.get("patient_sex"):
                    _dsa_parts.append(str(row.get("patient_sex", "")))
                if row.get("age_value") is not None:
                    _age_unit = str(row.get("age_unit") or "").lower()
                    _unit_abbr = {"years": "a", "months": "m", "days": "d"}.get(_age_unit, _age_unit[:1] if _age_unit else "")
                    _dsa_parts.append(f'{row.get("age_value")}{_unit_abbr}')
            datetime_line = f'<div style="font-size:{profile["meta"]};color:#666;margin-top:4px;">{" · ".join(_dsa_parts)}</div>' if _dsa_parts else ''
            test_line = f'<div style="font-size:{profile["name"]};margin-top:8px;">{row.get("test_name", "")}</div>' if row.get("test_name") else ''
            specimen_line = f'<div style="font-size:{profile["meta"]};color:#444;margin-top:4px;">{row.get("specimen_type") or ""}</div>' if row.get("specimen_type") else ''
            group_line = f'<div style="font-size:{profile["meta"]};color:#444;margin-top:2px;">{group_text}</div>' if group_text else ''
            blocks.append(
                f'<div style="border:1px solid {template["accent"]};padding:{profile["padding"]};margin:10px auto;page-break-inside:avoid;width:{profile["width"]};">'
                f'{subtitle_line}'
                f'{patient_line}'
                f'{order_text_line}'
                f'{datetime_line}'
                f'{test_line}'
                f'{specimen_line}'
                f'{group_line}'
                f'{id_line}'
                f"{machine_block}{copies_text}"
                "</div>"
            )
        return '<html><body style="font-family:Segoe UI, Arial, sans-serif;">' + ''.join(blocks) + '</body></html>'

    def _render_niimbot_label_image(self, row: dict[str, object], size_key: str | None) -> QImage:
        width_mm, height_mm = self._niimbot_label_size(size_key)
        px_per_mm = 12
        width_px = width_mm * px_per_mm
        height_px = height_mm * px_per_mm
        image = QImage(width_px, height_px, QImage.Format_ARGB32)
        image.fill(QColor("#ffffff"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        margin = max(12, int(width_px * 0.03))
        barcode_top = margin + 10
        barcode_height = max(90, int(height_px * 0.42))
        token = self._build_token(row, "order_only")
        safe_token = ''.join(character if character.isalnum() else '' for character in token.upper()) or token.upper()
        current_top = barcode_top + 8
        if self.show_barcode:
            self._draw_code128(painter, safe_token, margin, barcode_top, width_px - (margin * 2), barcode_height)
            current_top = barcode_top + barcode_height + 8
        painter.setPen(QColor("#111111"))
        order_to_name_gap = max(16, int(height_px * 0.05))
        name_to_date_gap = max(12, int(height_px * 0.04))

        if self.show_order_number_text.isChecked():
            order_number = str(row.get("order_number") or "").strip()
            if order_number:
                order_font = QFont("Segoe UI", max(18, int(height_px * 0.11)))
                painter.setFont(order_font)
                painter.drawText(margin, current_top, width_px - (margin * 2), 42, Qt.AlignHCenter | Qt.AlignVCenter, order_number)
                current_top += 42 + order_to_name_gap

        if self.show_patient_name:
            patient_name = str(row.get("patient_name") or "").strip()
            if patient_name:
                patient_font = QFont("Segoe UI", max(16, int(height_px * 0.095)))
                painter.setFont(patient_font)
                patient_height = max(28, int(height_px * 0.14))
                painter.drawText(margin, current_top, width_px - (margin * 2), patient_height, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, patient_name)
                current_top += patient_height + name_to_date_gap

        if self.show_datetime.isChecked():
            dsa_parts: list[str] = []
            created_at = str(row.get("created_at") or "").strip()
            if created_at:
                dsa_parts.append(created_at)
            patient_sex = str(row.get("patient_sex") or "").strip()
            if patient_sex:
                dsa_parts.append(patient_sex)
            age_value = row.get("age_value")
            if age_value is not None:
                age_unit = str(row.get("age_unit") or "").lower()
                unit_abbr = {"years": "a", "months": "m", "days": "d"}.get(age_unit, age_unit[:1] if age_unit else "")
                dsa_parts.append(f"{age_value}{unit_abbr}")
            if dsa_parts:
                datetime_font = QFont("Segoe UI", max(12, int(height_px * 0.07)))
                painter.setFont(datetime_font)
                painter.drawText(margin, current_top, width_px - (margin * 2), max(24, int(height_px * 0.09)), Qt.AlignLeft | Qt.AlignTop, "  ".join(dsa_parts))

        painter.end()
        return image

    @classmethod
    def _draw_code128(cls, painter: QPainter, token: str, x: int, y: int, width: int, height: int) -> None:
        symbols = cls._encode_code128b(token)
        units: list[tuple[bool, int]] = []
        for sym in symbols:
            for i, w in enumerate(cls._CODE128_PATTERNS[sym]):
                units.append((i % 2 == 0, w))
        for i, w in enumerate(cls._CODE128_STOP):
            units.append((i % 2 == 0, w))
        total_units = sum(u for _, u in units) or 1
        unit_px = max(1.0, width / total_units)
        cursor = float(x)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#111111"))
        for is_bar, unit_width in units:
            segment_width = unit_width * unit_px
            if is_bar:
                painter.drawRect(int(round(cursor)), y, max(1, int(round(segment_width))), height)
            cursor += segment_width

    @staticmethod
    def _niimbot_label_size(size_key: str | None) -> tuple[int, int]:
        size_map = {
            "vial_small": (40, 20),
            "tube_small": (50, 20),
            "small": (50, 25),
            "small_tall": (50, 30),
            "medium": (62, 30),
            "large": (100, 50),
        }
        return size_map.get(size_key or "small_tall", (50, 30))

    @staticmethod
    def _build_token(row: dict[str, object], payload_key: str | None) -> str:
        order_number = str(row.get('order_number') or '').upper().replace(' ', '')
        accession_id = str(row.get('accession_id') or '').upper().replace(' ', '')
        sample_id = str(row.get('sample_id') or '').upper().replace(' ', '')
        specimen_code = str(row.get('specimen_code') or 'SPC').upper().replace(' ', '')
        payload = payload_key or 'order_only'
        if payload == 'accession_only':
            return (accession_id or order_number or specimen_code)[:36]
        if payload == 'sample_only':
            return (sample_id or order_number or specimen_code)[:36]
        if payload == 'order_accession':
            return f'{order_number}-{accession_id or specimen_code}'[:36]
        if payload == 'order_specimen':
            return f'{order_number}-{specimen_code}'[:36]
        return (order_number or accession_id or sample_id or specimen_code)[:36]

    @classmethod
    def _code128_html(cls, token: str) -> str:
        symbols = cls._encode_code128b(token)
        bars: list[str] = []
        for sym in symbols:
            for i, w in enumerate(cls._CODE128_PATTERNS[sym]):
                color = '#111' if i % 2 == 0 else '#fff'
                bars.append(f'<span style="display:inline-block;width:{w}px;height:42px;background:{color};"></span>')
        for i, w in enumerate(cls._CODE128_STOP):
            color = '#111' if i % 2 == 0 else '#fff'
            bars.append(f'<span style="display:inline-block;width:{w}px;height:42px;background:{color};"></span>')
        return '<div style="margin-top:8px;line-height:0;">' + ''.join(bars) + f'</div><div style="font-size:10px;font-family:Consolas,monospace;margin-top:4px;">{token}</div>'
