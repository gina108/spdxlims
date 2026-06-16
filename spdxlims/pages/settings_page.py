from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtPrintSupport import QPrinterInfo
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFontComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database
from spdxlims.deployment import DeploymentConfig, DeploymentService
from spdxlims.i18n import SUPPORTED_LANGUAGES, tr
from spdxlims.lab_profile_service import LabProfileService
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.report_export import FILENAME_PART_KEYS, get_pdf_export_settings, save_pdf_export_settings
from spdxlims.sat_catalogs import REGIMEN_FISCAL_OPTIONS
from spdxlims.whatsapp_phone import COUNTRY_CODE_OPTIONS
from spdxlims.whatsapp_templates import get_whatsapp_templates, save_whatsapp_templates

REPORT_FLAG_STYLE_OPTIONS: list[tuple[str, str]] = [
    ("arrows", "Up/Down Arrows"),
    ("asterisks", "Asterisks"),
    ("text", "Bajo/Alto"),
]


class AccordionSection(QWidget):
    def __init__(self, expanded: bool = True) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.toggle_button = QPushButton()
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.clicked.connect(self._sync_state)
        self.toggle_button.setStyleSheet(
            """
            QPushButton {
                text-align: left;
                padding: 9px 14px;
                border: 1px solid #243244;
                border-radius: 10px;
                background-color: #111B27;
                color: #F4F7FB;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #162132;
                border-color: #30415A;
            }
            QPushButton:checked {
                background-color: #5B2AA8;
                border-color: #9B6CF3;
                color: #FFFFFF;
            }
            """
        )
        layout.addWidget(self.toggle_button)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(12, 0, 12, 0)
        self.content_layout.setSpacing(0)
        layout.addWidget(self.content)
        self._sync_state()

    def set_title(self, title: str) -> None:
        prefix = "▾" if self.toggle_button.isChecked() else "▸"
        self.toggle_button.setText(f"{prefix}  {title}")

    def _sync_state(self) -> None:
        self.content.setVisible(self.toggle_button.isChecked())
        current_text = self.toggle_button.text()
        if "  " in current_text:
            self.set_title(current_text.split("  ", 1)[1])


class SettingsPage(DataAwarePage):
    def __init__(self, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__()
        self.database = database
        self.deployment_service = deployment_service
        self.lab_profile_service = LabProfileService(deployment_service)
        self._cached_server_profile: dict[str, str] | None = None
        self._cached_profile_server_url = ''
        self._server_profile_dirty = True
        self._hidden_report_footer = ""
        self._hidden_director_name = ""
        self._hidden_director_license = ""
        root = QVBoxLayout(self)
        self.lab_section = AccordionSection(expanded=False)
        self.lab_group = QGroupBox()
        self.lab_form = QFormLayout(self.lab_group)
        self.lab_labels: dict[str, QLabel] = {}

        self.reports_section = AccordionSection(expanded=False)
        self.reports_group = QGroupBox()
        self.reports_form = QFormLayout(self.reports_group)
        self.report_labels: dict[str, QLabel] = {}
        self.pdf_export_group = QGroupBox()
        self.pdf_export_form = QFormLayout(self.pdf_export_group)
        self.pdf_export_labels: dict[str, QLabel] = {}
        self.printing_section = AccordionSection(expanded=False)
        self.printing_group = QGroupBox()
        self.printing_form = QFormLayout(self.printing_group)
        self.printing_labels: dict[str, QLabel] = {}
        self.receipt_group = QGroupBox()
        self.receipt_form = QFormLayout(self.receipt_group)
        self.receipt_labels: dict[str, QLabel] = {}
        self.whatsapp_section = AccordionSection(expanded=False)
        self.whatsapp_group = QGroupBox()
        self.whatsapp_form = QFormLayout(self.whatsapp_group)
        self.whatsapp_labels: dict[str, QLabel] = {}
        self.operations_section = AccordionSection(expanded=False)
        self.operations_group = QGroupBox()
        self.operations_form = QFormLayout(self.operations_group)
        self.operations_labels: dict[str, QLabel] = {}
        self.connection_section = AccordionSection(expanded=False)

        self.lab_name = QLineEdit()
        self.address = QLineEdit()
        self.phone = QLineEdit()
        self.email = QLineEdit()
        self.logo_path = QLineEdit()
        self.header_image_path = QLineEdit()
        self.footer_signature_image_path = QLineEdit()
        self.report_flag_style = QComboBox()
        for value, label in REPORT_FLAG_STYLE_OPTIONS:
            self.report_flag_style.addItem(label, value)
        self.keep_panels_together = QCheckBox()
        self.report_font_family = QFontComboBox()
        self.report_font_size = QSpinBox()
        self.report_font_size.setRange(8, 18)
        self.report_font_size.setValue(12)
        self.report_font_bold = QCheckBox()
        self.report_abnormal_bold = QCheckBox()
        self.report_subheading_font_family = QFontComboBox()
        self.report_subheading_font_size = QSpinBox()
        self.report_subheading_font_size.setRange(8, 18)
        self.report_subheading_font_size.setValue(13)
        self.report_subheading_font_bold = QCheckBox()
        self.report_subheading_font_bold.setChecked(True)
        self.report_footer_gap_mm = QSpinBox()
        self.report_footer_gap_mm.setRange(0, 60)
        self.report_footer_gap_mm.setValue(8)
        self.report_footer_gap_mm.setSuffix(" mm")
        self.report_sex_format = QComboBox()
        self.report_sex_format.addItem("M / F", "short")
        self.report_sex_format.addItem("MASC / FEM", "medium")
        self.report_sex_format.addItem("MASCULINO / FEMENINO", "full")
        self.report_date_format = QComboBox()
        self.report_date_format.addItem("", "auto")
        self.report_date_format.addItem("", "date_only")
        self.report_date_format.addItem("", "with_time")
        self.report_header_fields_widget = QWidget()
        _hf_layout = QGridLayout(self.report_header_fields_widget)
        _hf_layout.setContentsMargins(0, 0, 0, 0)
        _hf_layout.setSpacing(4)
        _hf_layout.setColumnStretch(0, 1)
        self.report_show_doctor = QCheckBox()
        self.report_show_doctor.setChecked(True)
        self.report_doctor_col = QComboBox()
        self.report_doctor_col.addItem("", "left")
        self.report_doctor_col.addItem("", "right")
        self.report_show_client = QCheckBox()
        self.report_show_client.setChecked(True)
        self.report_client_col = QComboBox()
        self.report_client_col.addItem("", "left")
        self.report_client_col.addItem("", "right")
        self.report_show_sex = QCheckBox()
        self.report_show_sex.setChecked(True)
        self.report_sex_col = QComboBox()
        self.report_sex_col.addItem("", "left")
        self.report_sex_col.addItem("", "right")
        self.report_show_age = QCheckBox()
        self.report_show_age.setChecked(True)
        self.report_age_col = QComboBox()
        self.report_age_col.addItem("", "left")
        self.report_age_col.addItem("", "right")
        self.report_age_col.setCurrentIndex(1)
        self.report_show_dob = QCheckBox()
        self.report_show_dob.setChecked(True)
        self.report_dob_col = QComboBox()
        self.report_dob_col.addItem("", "left")
        self.report_dob_col.addItem("", "right")
        self.report_dob_col.setCurrentIndex(1)
        self.report_show_ordered_at = QCheckBox()
        self.report_show_ordered_at.setChecked(True)
        self.report_ordered_at_col = QComboBox()
        self.report_ordered_at_col.addItem("", "left")
        self.report_ordered_at_col.addItem("", "right")
        self.report_ordered_at_col.setCurrentIndex(1)
        self.report_show_reported_at = QCheckBox()
        self.report_show_reported_at.setChecked(True)
        self.report_reported_at_col = QComboBox()
        self.report_reported_at_col.addItem("", "left")
        self.report_reported_at_col.addItem("", "right")
        self.report_reported_at_col.setCurrentIndex(1)
        for _hf_row, (_cb, _combo) in enumerate([
            (self.report_show_doctor, self.report_doctor_col),
            (self.report_show_client, self.report_client_col),
            (self.report_show_sex, self.report_sex_col),
            (self.report_show_age, self.report_age_col),
            (self.report_show_dob, self.report_dob_col),
            (self.report_show_ordered_at, self.report_ordered_at_col),
            (self.report_show_reported_at, self.report_reported_at_col),
        ]):
            _hf_layout.addWidget(_cb, _hf_row, 0)
            _hf_layout.addWidget(_combo, _hf_row, 1)
            _cb.toggled.connect(_combo.setEnabled)
            _combo.setEnabled(_cb.isChecked())
        self.sat_rfc = QLineEdit()
        self.sat_fiscal_regime = QComboBox()
        self.sat_fiscal_regime.addItem('', '')
        for code, label in REGIMEN_FISCAL_OPTIONS:
            self.sat_fiscal_regime.addItem(label, code)
        self.sat_postal_code = QLineEdit()
        self.sat_certificate_path = QLineEdit()
        self.sat_key_path = QLineEdit()
        self.language_combo = QComboBox()

        for code, label in SUPPORTED_LANGUAGES:
            self.language_combo.addItem(label, code)

        self.logo_row, self.logo_browse = self._file_picker_row(self.logo_path)
        self.header_row, self.header_browse = self._file_picker_row(self.header_image_path)
        self.footer_row, self.footer_browse = self._file_picker_row(self.footer_signature_image_path)
        self.pdf_export_folder = QLineEdit()
        self.pdf_export_folder_row, self.pdf_export_folder_browse = self._folder_picker_row(self.pdf_export_folder)
        self.pdf_export_help = QLabel()
        self.pdf_export_help.setWordWrap(True)
        self.printing_help = QLabel()
        self.printing_help.setWordWrap(True)
        self.printing_default_size = QComboBox()
        self.printing_default_size.addItem('40 x 20 mm', 'vial_small')
        self.printing_default_size.addItem('50 x 20 mm', 'tube_small')
        self.printing_default_size.addItem('50 x 25 mm', 'small')
        self.printing_default_size.addItem('50 x 30 mm', 'small_tall')
        self.printing_default_size.addItem('62 x 30 mm', 'medium')
        self.printing_default_size.addItem('100 x 50 mm', 'large')
        self.printing_default_payload = QComboBox()
        self.printing_default_payload.addItem(tr('Order ID only'), 'order_only')
        self.printing_default_payload.addItem(tr('Order ID + specimen code'), 'order_specimen')
        self.printing_default_payload.addItem(tr('Accession ID only'), 'accession_only')
        self.printing_default_payload.addItem(tr('Sample ID only'), 'sample_only')
        self.printing_default_payload.addItem(tr('Order ID + accession ID'), 'order_accession')
        self.printing_show_barcode = QCheckBox()
        self.printing_show_patient_name = QCheckBox()
        self.printing_show_order_number_text = QCheckBox()
        self.printing_show_datetime = QCheckBox()
        self.printing_content_options = QWidget()
        printing_content_layout = QVBoxLayout(self.printing_content_options)
        printing_content_layout.setContentsMargins(0, 0, 0, 0)
        printing_content_layout.setSpacing(6)
        printing_content_layout.addWidget(self.printing_show_barcode)
        printing_content_layout.addWidget(self.printing_show_order_number_text)
        printing_content_layout.addWidget(self.printing_show_patient_name)
        printing_content_layout.addWidget(self.printing_show_datetime)
        self.printing_default_copies = QSpinBox()
        self.printing_default_copies.setRange(1, 99)
        self.printing_default_copies.setValue(1)
        self.printing_panel_extra_group = QGroupBox()
        self._panel_extra_copies_layout = QVBoxLayout(self.printing_panel_extra_group)
        self._panel_extra_copies_layout.setContentsMargins(8, 8, 8, 8)
        self._panel_extra_copies_layout.setSpacing(4)
        self._panel_extra_copy_spins: dict[str, QSpinBox] = {}
        self.receipt_auto_print = QCheckBox()
        self.receipt_paper_format = QComboBox()
        self.receipt_paper_format.addItem('Carta / Oficio', 'letter')
        self.receipt_paper_format.addItem('Ticket 80 mm', 'ticket_80mm')
        self.receipt_paper_format.addItem('Ticket 58 mm', 'ticket_58mm')
        self.printing_printer = QComboBox()
        self.printing_printer_row, self.printing_printer_refresh = self._printer_row(
            self.printing_printer, self._refresh_label_printers
        )
        self.receipt_printer = QComboBox()
        self.receipt_printer_row, self.receipt_printer_refresh = self._printer_row(
            self.receipt_printer, self._refresh_receipt_printers
        )
        self.report_printer = QComboBox()
        self.report_printer_row, self.report_printer_refresh = self._printer_row(
            self.report_printer, self._refresh_report_printers
        )
        self.whatsapp_help = QLabel()
        self.whatsapp_help.setWordWrap(True)
        self.whatsapp_country_code = QComboBox()
        for code, label in COUNTRY_CODE_OPTIONS:
            self.whatsapp_country_code.addItem(label, code)
        self.whatsapp_country_code.setEditable(True)
        self.whatsapp_placeholders = QWidget()
        whatsapp_placeholders_layout = QHBoxLayout(self.whatsapp_placeholders)
        whatsapp_placeholders_layout.setContentsMargins(0, 0, 0, 0)
        whatsapp_placeholders_layout.setSpacing(8)
        self.whatsapp_placeholder_fields: dict[str, QLineEdit] = {}
        for key in ("name", "order_number", "patient_name"):
            field = QLineEdit()
            field.setReadOnly(True)
            field.setFocusPolicy(Qt.ClickFocus)
            field.setCursorPosition(0)
            self.whatsapp_placeholder_fields[key] = field
            whatsapp_placeholders_layout.addWidget(field)
        self.whatsapp_patient_message = QTextEdit()
        self.whatsapp_patient_message.setFixedHeight(90)
        self.whatsapp_client_message = QTextEdit()
        self.whatsapp_client_message.setFixedHeight(90)
        self.backup_enabled = QCheckBox()
        self.backup_destination = QLineEdit()
        self.backup_destination.setPlaceholderText(r"D:\SPDXLIMS Backups or \\server\share\SPDXLIMS")
        self.backup_destination_row, self.backup_destination_browse = self._folder_picker_row(self.backup_destination)
        self.backup_schedule = QLineEdit()
        self.backup_schedule.setPlaceholderText("Daily at 8:00 PM")
        self.backup_retention_days = QSpinBox()
        self.backup_retention_days.setRange(1, 3650)
        self.backup_retention_days.setValue(30)
        self.backup_include_database = QCheckBox()
        self.backup_include_assets = QCheckBox()
        self.backup_include_instrument_profiles = QCheckBox()
        self.backup_cloud_sync_note = QLineEdit()
        self.backup_cloud_sync_note.setPlaceholderText("Optional cloud/offsite sync notes")
        self.backup_restore_drill_date = QLineEdit()
        self.backup_restore_drill_date.setPlaceholderText("YYYY-MM-DD")
        self.backup_status = QLabel()
        self.backup_status.setWordWrap(True)
        self.backup_options = QWidget()
        backup_options_layout = QVBoxLayout(self.backup_options)
        backup_options_layout.setContentsMargins(0, 0, 0, 0)
        backup_options_layout.setSpacing(6)
        backup_options_layout.addWidget(self.backup_include_database)
        backup_options_layout.addWidget(self.backup_include_assets)
        backup_options_layout.addWidget(self.backup_include_instrument_profiles)
        self.backup_actions = QWidget()
        backup_actions_layout = QHBoxLayout(self.backup_actions)
        backup_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.save_backup_config_button = QPushButton()
        self.save_backup_config_button.clicked.connect(lambda _checked=False: self.save_backup_config())
        self.refresh_backup_button = QPushButton()
        self.refresh_backup_button.clicked.connect(lambda _checked=False: self.refresh_backup_status())
        self.run_backup_now_button = QPushButton()
        self.run_backup_now_button.clicked.connect(self.run_backup_now)
        backup_actions_layout.addWidget(self.save_backup_config_button)
        backup_actions_layout.addWidget(self.refresh_backup_button)
        backup_actions_layout.addWidget(self.run_backup_now_button)
        backup_actions_layout.addStretch(1)
        self.pdf_export_filename_options = QWidget()
        filename_options_layout = QVBoxLayout(self.pdf_export_filename_options)
        filename_options_layout.setContentsMargins(0, 0, 0, 0)
        filename_options_layout.setSpacing(6)
        filename_options_layout.addWidget(self.pdf_export_help)
        self.pdf_export_part_checks: dict[str, QCheckBox] = {}
        for key in FILENAME_PART_KEYS:
            checkbox = QCheckBox()
            self.pdf_export_part_checks[key] = checkbox
            filename_options_layout.addWidget(checkbox)
        self.header_library = QListWidget()
        self.header_library.setMinimumHeight(120)
        self.header_library_help = QLabel()
        self.header_library_help.setWordWrap(True)
        self.add_header_button = QPushButton()
        self.add_header_button.clicked.connect(self._add_header_asset)
        self.remove_header_button = QPushButton()
        self.remove_header_button.clicked.connect(self._remove_selected_header_asset)
        self.set_default_header_button = QPushButton()
        self.set_default_header_button.clicked.connect(self._set_default_header_asset)
        self.header_actions_row = QWidget()
        header_actions_layout = QHBoxLayout(self.header_actions_row)
        header_actions_layout.setContentsMargins(0, 0, 0, 0)
        header_actions_layout.addWidget(self.add_header_button)
        header_actions_layout.addWidget(self.set_default_header_button)
        header_actions_layout.addWidget(self.remove_header_button)
        header_actions_layout.addStretch(1)
        self.header_library_block = QWidget()
        header_library_layout = QVBoxLayout(self.header_library_block)
        header_library_layout.setContentsMargins(0, 0, 0, 0)
        header_library_layout.setSpacing(6)
        header_library_layout.addWidget(self.header_library_help)
        header_library_layout.addWidget(self.header_library)
        header_library_layout.addWidget(self.header_actions_row)

        self.footer_library = QListWidget()
        self.footer_library.setMinimumHeight(120)
        self.footer_library_help = QLabel()
        self.footer_library_help.setWordWrap(True)
        self.add_footer_button = QPushButton()
        self.add_footer_button.clicked.connect(self._add_footer_asset)
        self.remove_footer_button = QPushButton()
        self.remove_footer_button.clicked.connect(self._remove_selected_footer_asset)
        self.set_default_footer_button = QPushButton()
        self.set_default_footer_button.clicked.connect(self._set_default_footer_asset)
        self.footer_actions_row = QWidget()
        footer_actions_layout = QHBoxLayout(self.footer_actions_row)
        footer_actions_layout.setContentsMargins(0, 0, 0, 0)
        footer_actions_layout.addWidget(self.add_footer_button)
        footer_actions_layout.addWidget(self.set_default_footer_button)
        footer_actions_layout.addWidget(self.remove_footer_button)
        footer_actions_layout.addStretch(1)
        self.footer_library_block = QWidget()
        footer_library_layout = QVBoxLayout(self.footer_library_block)
        footer_library_layout.setContentsMargins(0, 0, 0, 0)
        footer_library_layout.setSpacing(6)
        footer_library_layout.addWidget(self.footer_library_help)
        footer_library_layout.addWidget(self.footer_library)
        footer_library_layout.addWidget(self.footer_actions_row)

        self._add_lab_row("lab_name", self.lab_name)
        self._add_lab_row("address", self.address)
        self._add_lab_row("phone", self.phone)
        self._add_lab_row("email", self.email)
        self._add_lab_row("sat_rfc", self.sat_rfc)
        self._add_lab_row("sat_fiscal_regime", self.sat_fiscal_regime)
        self._add_lab_row("sat_postal_code", self.sat_postal_code)
        self._add_lab_row("sat_certificate_path", self.sat_certificate_path)
        self._add_lab_row("sat_key_path", self.sat_key_path)
        self._add_lab_row("language", self.language_combo)

        self._add_report_row("logo", self.logo_row)
        self._add_report_row("header", self.header_row)
        self._add_report_row("header_library", self.header_library_block)
        self._add_report_row("footer", self.footer_row)
        self._add_report_row("footer_library", self.footer_library_block)
        self._add_report_row("report_flag_style", self.report_flag_style)
        self._add_report_row("keep_panels_together", self.keep_panels_together)
        self._add_report_row("report_font_family", self.report_font_family)
        self._add_report_row("report_font_size", self.report_font_size)
        self._add_report_row("report_font_bold", self.report_font_bold)
        self._add_report_row("report_abnormal_bold", self.report_abnormal_bold)
        self._add_report_row("report_subheading_font_family", self.report_subheading_font_family)
        self._add_report_row("report_subheading_font_size", self.report_subheading_font_size)
        self._add_report_row("report_subheading_font_bold", self.report_subheading_font_bold)
        self._add_report_row("report_footer_gap_mm", self.report_footer_gap_mm)
        self._add_report_row("report_header_fields", self.report_header_fields_widget)
        self._add_report_row("report_sex_format", self.report_sex_format)
        self._add_report_row("report_date_format", self.report_date_format)
        self._add_printing_row("printer", self.printing_printer_row)
        self._add_printing_row("help", self.printing_help)
        self._add_printing_row("default_size", self.printing_default_size)
        self._add_printing_row("default_payload", self.printing_default_payload)
        self._add_printing_row("content_fields", self.printing_content_options)
        self._add_printing_row("default_copies", self.printing_default_copies)
        self._add_receipt_row("printer", self.receipt_printer_row)
        self._add_receipt_row("auto_print", self.receipt_auto_print)
        self._add_receipt_row("paper_format", self.receipt_paper_format)
        self._add_pdf_export_row("printer", self.report_printer_row)
        self._add_pdf_export_row("folder", self.pdf_export_folder_row)
        self._add_pdf_export_row("filename_parts", self.pdf_export_filename_options)
        self._add_whatsapp_row("help", self.whatsapp_help)
        self._add_whatsapp_row("country_code", self.whatsapp_country_code)
        self._add_whatsapp_row("placeholders", self.whatsapp_placeholders)
        self._add_whatsapp_row("patient_message", self.whatsapp_patient_message)
        self._add_whatsapp_row("client_message", self.whatsapp_client_message)
        self._add_operations_row("backup_enabled", self.backup_enabled)
        self._add_operations_row("backup_destination", self.backup_destination_row)
        self._add_operations_row("backup_schedule", self.backup_schedule)
        self._add_operations_row("backup_retention", self.backup_retention_days)
        self._add_operations_row("backup_include", self.backup_options)
        self._add_operations_row("backup_cloud_sync", self.backup_cloud_sync_note)
        self._add_operations_row("backup_restore_drill", self.backup_restore_drill_date)
        self._add_operations_row("backup_status", self.backup_status)
        self.operations_form.addRow(QLabel(""), self.backup_actions)

        self.lab_section.content_layout.addWidget(self.lab_group)
        self.reports_section.content_layout.addWidget(self.reports_group)
        self.reports_section.content_layout.addWidget(self.pdf_export_group)

        _print_columns = QWidget()
        _print_columns_layout = QHBoxLayout(_print_columns)
        _print_columns_layout.setContentsMargins(0, 8, 0, 0)
        _print_columns_layout.setSpacing(16)
        _print_columns_layout.addWidget(self.printing_group, 1)
        _print_columns_layout.addWidget(self.receipt_group, 1)
        self.printing_section.content_layout.addWidget(_print_columns)
        self.printing_section.content_layout.addWidget(self.printing_panel_extra_group)

        self.whatsapp_section.content_layout.addWidget(self.whatsapp_group)
        self.operations_section.content_layout.addWidget(self.operations_group)

        self.connection_group = QGroupBox()
        self.connection_form = QFormLayout(self.connection_group)
        self.connection_labels: dict[str, QLabel] = {}
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(tr("Local Mode"), "local")
        self.mode_combo.addItem(tr("Server Mode"), "server")
        self.server_url = QLineEdit()
        self.server_url.setPlaceholderText("http://127.0.0.1:8001")
        self.login_email = QLineEdit()
        self.login_email.setPlaceholderText("admin@spdxlims.local")
        self.login_password = QLineEdit()
        self.login_password.setEchoMode(QLineEdit.Password)
        self.connection_status = QLabel()
        self.connection_status.setWordWrap(True)
        self.session_status = QLabel()
        self.session_status.setWordWrap(True)
        self.test_connection_button = QPushButton()
        self.test_connection_button.clicked.connect(self.test_server_connection)
        self.login_button = QPushButton()
        self.login_button.clicked.connect(self.login_to_server)
        self.logout_button = QPushButton()
        self.logout_button.clicked.connect(self.logout_from_server)

        self._add_connection_row("mode", self.mode_combo)
        self._add_connection_row("server_url", self.server_url)
        self._add_connection_row("login_email", self.login_email)
        self._add_connection_row("login_password", self.login_password)
        self.connection_form.addRow(self.test_connection_button, self.connection_status)
        self.connection_form.addRow(self.login_button, self.logout_button)
        self.connection_form.addRow(QLabel(""), self.session_status)

        self.service_status_label = QLabel()
        self.service_status_label.setWordWrap(True)
        self.install_service_button = QPushButton()
        self.install_service_button.clicked.connect(self._install_backend_service)
        self.uninstall_service_button = QPushButton()
        self.uninstall_service_button.clicked.connect(self._uninstall_backend_service)
        self.start_service_button = QPushButton()
        self.start_service_button.clicked.connect(self._start_backend_service)
        self.stop_service_button = QPushButton()
        self.stop_service_button.clicked.connect(self._stop_backend_service)
        self.refresh_service_button = QPushButton()
        self.refresh_service_button.clicked.connect(lambda: threading.Thread(target=self._bg_refresh_service_status, daemon=True).start())

        service_btn_row = QHBoxLayout()
        service_btn_row.addWidget(self.install_service_button)
        service_btn_row.addWidget(self.uninstall_service_button)
        service_btn_row.addWidget(self.start_service_button)
        service_btn_row.addWidget(self.stop_service_button)
        service_btn_row.addWidget(self.refresh_service_button)
        service_btn_row.addStretch(1)

        self._add_connection_row("service_status", self.service_status_label)
        self.connection_form.addRow(QLabel(""), service_btn_row)

        self.save_button = QPushButton()
        self.save_button.clicked.connect(self.save_settings)

        root.addWidget(self.lab_section)
        root.addWidget(self.reports_section)
        root.addWidget(self.printing_section)
        root.addWidget(self.whatsapp_section)
        root.addWidget(self.operations_section)
        self.connection_section.content_layout.addWidget(self.connection_group)

        root.addWidget(self.connection_section)
        root.addWidget(self.save_button)
        root.addStretch(1)

        self.retranslate_ui()
        self.load_deployment_settings()
        self.load_settings(force_server_refresh=True)

    def _add_lab_row(self, key: str, field: QWidget) -> None:
        label = QLabel()
        self.lab_labels[key] = label
        self.lab_form.addRow(label, field)

    def _add_report_row(self, key: str, field: QWidget) -> None:
        label = QLabel()
        self.report_labels[key] = label
        self.reports_form.addRow(label, field)

    def _add_printing_row(self, key: str, field: QWidget) -> None:
        label = QLabel()
        self.printing_labels[key] = label
        self.printing_form.addRow(label, field)

    def _add_receipt_row(self, key: str, field: QWidget) -> None:
        label = QLabel()
        self.receipt_labels[key] = label
        self.receipt_form.addRow(label, field)

    def _add_connection_row(self, key: str, field: QWidget) -> None:
        label = QLabel()
        self.connection_labels[key] = label
        self.connection_form.addRow(label, field)

    def _add_operations_row(self, key: str, field: QWidget) -> None:
        label = QLabel()
        self.operations_labels[key] = label
        self.operations_form.addRow(label, field)

    def _add_pdf_export_row(self, key: str, field: QWidget) -> None:
        label = QLabel()
        self.pdf_export_labels[key] = label
        self.pdf_export_form.addRow(label, field)

    def _add_whatsapp_row(self, key: str, field: QWidget) -> None:
        label = QLabel()
        self.whatsapp_labels[key] = label
        self.whatsapp_form.addRow(label, field)

    def _printer_row(self, combo: QComboBox, refresh_slot: object) -> tuple[QWidget, QPushButton]:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        button = QPushButton("⟳")
        button.setFixedWidth(32)
        button.setToolTip(tr("Refresh printer list"))
        button.clicked.connect(refresh_slot)
        layout.addWidget(combo)
        layout.addWidget(button)
        return container, button

    @staticmethod
    def _list_system_printer_names() -> list[str]:
        return [p.printerName() for p in QPrinterInfo.availablePrinters()]

    def _populate_label_printers(self, saved: str = "") -> None:
        self.printing_printer.blockSignals(True)
        self.printing_printer.clear()
        self.printing_printer.addItem(tr("NIIMbot B1 (via helper)"), "niimbot:B1")
        self.printing_printer.addItem(tr("Default system printer"), "system_default")
        for name in self._list_system_printer_names():
            self.printing_printer.addItem(name, f"system:{name}")
        idx = self.printing_printer.findData(saved or "niimbot:B1")
        self.printing_printer.setCurrentIndex(idx if idx >= 0 else 0)
        self.printing_printer.blockSignals(False)

    def _populate_system_printer_combo(self, combo: QComboBox, saved: str = "") -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("Default system printer"), "system_default")
        for name in self._list_system_printer_names():
            combo.addItem(name, f"system:{name}")
        idx = combo.findData(saved or "system_default")
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _refresh_label_printers(self) -> None:
        self._populate_label_printers(str(self.printing_printer.currentData() or ""))

    def _refresh_receipt_printers(self) -> None:
        self._populate_system_printer_combo(self.receipt_printer, str(self.receipt_printer.currentData() or ""))

    def _refresh_report_printers(self) -> None:
        self._populate_system_printer_combo(self.report_printer, str(self.report_printer.currentData() or ""))

    def _file_picker_row(self, target: QLineEdit) -> tuple[QWidget, QPushButton]:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        button = QPushButton()
        button.clicked.connect(lambda: self._pick_file(target))
        layout.addWidget(target)
        layout.addWidget(button)
        return container, button

    def _folder_picker_row(self, target: QLineEdit) -> tuple[QWidget, QPushButton]:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        button = QPushButton()
        button.clicked.connect(lambda: self._pick_folder(target))
        layout.addWidget(target)
        layout.addWidget(button)
        return container, button

    def _pick_file(self, target: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Choose Image"),
            "",
            tr("Images (*.png *.jpg *.jpeg)"),
        )
        if path:
            target.setText(path)

    def _pick_folder(self, target: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("Choose Folder"), target.text().strip() or "")
        if path:
            target.setText(path)

    def refresh_on_show(self) -> None:
        self.load_deployment_settings()
        self.load_settings(force_server_refresh=False)

    def retranslate_ui(self) -> None:
        self.lab_section.set_title(tr("Lab Info"))
        self.reports_section.set_title(tr("Reports"))
        self.printing_section.set_title(tr("Printing Options"))
        self.whatsapp_section.set_title(tr("WhatsApp Messages"))
        self.operations_section.set_title(tr("Operations"))
        self.connection_section.set_title(tr("Server Connection"))
        self.lab_group.setTitle("")
        self.reports_group.setTitle("")
        self.pdf_export_group.setTitle(tr("PDF Export"))
        self.printing_group.setTitle(tr("Labels"))
        self.receipt_group.setTitle(tr("Receipts"))
        self.printing_panel_extra_group.setTitle(tr("Extra Copies by Panel"))
        self.whatsapp_group.setTitle("")
        self.operations_group.setTitle(tr("Backup Configuration"))
        self.connection_group.setTitle("")
        self.lab_labels["lab_name"].setText(tr("Lab Name"))
        self.lab_labels["address"].setText(tr("Address"))
        self.lab_labels["phone"].setText(tr("Phone"))
        self.lab_labels["email"].setText(tr("Email"))
        self.lab_labels["sat_rfc"].setText(tr("Lab RFC"))
        self.lab_labels["sat_fiscal_regime"].setText(tr("Lab Fiscal Regime"))
        self.lab_labels["sat_postal_code"].setText(tr("Lab Postal Code"))
        self.lab_labels["sat_certificate_path"].setText(tr("CSD Certificate Path"))
        self.lab_labels["sat_key_path"].setText(tr("CSD Key Path"))
        self.lab_labels["language"].setText(tr("Language"))
        self.report_labels["logo"].setText(tr("Logo"))
        self.report_labels["header"].setText(tr("Header Banner"))
        self.report_labels["header_library"].setText(tr("Available Headers"))
        self.report_labels["footer"].setText(tr("Footer Signature"))
        self.report_labels["footer_library"].setText(tr("Available Footers"))
        self.report_labels["report_flag_style"].setText(tr("Flag Style"))
        self.report_labels["keep_panels_together"].setText(tr("Panel Page Breaks"))
        self.keep_panels_together.setText(tr("Keep each panel on one page when possible"))
        self.report_labels["report_font_family"].setText(tr("Report Font"))
        self.report_labels["report_font_size"].setText(tr("Test Row Font Size"))
        self.report_labels["report_font_bold"].setText(tr("Test Row Bold"))
        self.report_font_bold.setText(tr("Bold test rows"))
        self.report_labels["report_abnormal_bold"].setText(tr("Abnormal Result Bold"))
        self.report_abnormal_bold.setText(tr("Bold abnormal results"))
        self.report_labels["report_subheading_font_family"].setText(tr("Subheading Font"))
        self.report_labels["report_subheading_font_size"].setText(tr("Subheading Font Size"))
        self.report_labels["report_subheading_font_bold"].setText(tr("Subheading Bold"))
        self.report_subheading_font_bold.setText(tr("Bold subheadings"))
        self.report_labels["report_footer_gap_mm"].setText(tr("Footer Bottom Skip"))
        self.report_labels["report_header_fields"].setText(tr("Header Fields"))
        self.report_show_doctor.setText(tr("Doctor"))
        self.report_show_client.setText(tr("Origin / Client"))
        self.report_show_sex.setText(tr("Sex"))
        self.report_show_age.setText(tr("Age"))
        self.report_show_dob.setText(tr("Date of Birth"))
        self.report_show_ordered_at.setText(tr("Appointment Date"))
        self.report_show_reported_at.setText(tr("Print Date"))
        for _col_combo in [
            self.report_doctor_col, self.report_client_col, self.report_sex_col,
            self.report_age_col, self.report_dob_col, self.report_ordered_at_col,
            self.report_reported_at_col,
        ]:
            _cur_col = _col_combo.currentData()
            _col_combo.setItemText(0, tr("Left column"))
            _col_combo.setItemText(1, tr("Right column"))
            _idx = _col_combo.findData(_cur_col)
            if _idx >= 0:
                _col_combo.setCurrentIndex(_idx)
        self.report_labels["report_sex_format"].setText(tr("Sex Format"))
        self.report_labels["report_date_format"].setText(tr("Date Format"))
        current_date_format = self.report_date_format.currentData()
        self.report_date_format.clear()
        self.report_date_format.addItem(tr("Auto (date only or with time)"), "auto")
        self.report_date_format.addItem(tr("Date only (DD/MM/YYYY)"), "date_only")
        self.report_date_format.addItem(tr("Always with time (DD/MM/YYYY HH:MM)"), "with_time")
        idx = self.report_date_format.findData(current_date_format)
        if idx >= 0:
            self.report_date_format.setCurrentIndex(idx)
        self.pdf_export_labels["printer"].setText(tr("Printer"))
        self.pdf_export_labels["folder"].setText(tr("PDF Save Folder"))
        self.pdf_export_labels["filename_parts"].setText(tr("PDF File Name"))
        self.pdf_export_help.setText(tr("Choose which fields are included in the exported PDF file name."))
        self.printing_labels["printer"].setText(tr("Printer"))
        self.printing_labels["help"].setText("")
        self.printing_labels["default_size"].setText(tr("Default Label Size"))
        self.printing_labels["default_payload"].setText(tr("Default Barcode Payload"))
        self.printing_labels["content_fields"].setText(tr("Default Label Fields"))
        self.printing_show_barcode.setText(tr("Barcode"))
        self.printing_show_order_number_text.setText(tr("Order Number"))
        self.printing_show_patient_name.setText(tr("Patient Name"))
        self.printing_show_datetime.setText(tr("Date, Sex & Age"))
        self.printing_labels["default_copies"].setText(tr("Default Copies"))
        self.printing_help.setText(tr("Set the default label printing values used when the print-label dialog opens."))
        self.receipt_labels["printer"].setText(tr("Printer"))
        self.receipt_labels["auto_print"].setText(tr("Auto-print"))
        self.receipt_auto_print.setText(tr("Print receipt automatically when created"))
        self.receipt_labels["paper_format"].setText(tr("Paper Format"))
        self.whatsapp_labels["help"].setText("")
        self.whatsapp_labels["country_code"].setText(tr("Default WhatsApp Country Code"))
        self.whatsapp_labels["placeholders"].setText(tr("Placeholders"))
        self.whatsapp_labels["patient_message"].setText(tr("Patient Message"))
        self.whatsapp_labels["client_message"].setText(tr("Client Message"))
        self.whatsapp_help.setText(tr("Set the default country code for WhatsApp and customize the automatic messages. Type patient phone numbers without country code unless you intentionally start with +. You can use: {name}, {order_number}, and {patient_name}."))
        self.operations_labels["backup_enabled"].setText(tr("Enable Backups"))
        self.operations_labels["backup_destination"].setText(tr("Backup Destination"))
        self.operations_labels["backup_schedule"].setText(tr("Schedule"))
        self.operations_labels["backup_retention"].setText(tr("Keep Backups"))
        self.operations_labels["backup_include"].setText(tr("Include"))
        self.operations_labels["backup_cloud_sync"].setText(tr("Cloud/Offsite Notes"))
        self.operations_labels["backup_restore_drill"].setText(tr("Last Restore Drill"))
        self.operations_labels["backup_status"].setText(tr("Backup Status"))
        self.backup_enabled.setText(tr("Server backups are configured"))
        self.backup_include_database.setText(tr("PostgreSQL database"))
        self.backup_include_assets.setText(tr("Uploaded report assets"))
        self.backup_include_instrument_profiles.setText(tr("Instrument profiles and runtime links"))
        self.whatsapp_placeholder_fields["name"].setText("{name}")
        self.whatsapp_placeholder_fields["name"].setToolTip(tr("Copy and paste this placeholder into a WhatsApp message template."))
        self.whatsapp_placeholder_fields["order_number"].setText("{order_number}")
        self.whatsapp_placeholder_fields["order_number"].setToolTip(tr("Copy and paste this placeholder into a WhatsApp message template."))
        self.whatsapp_placeholder_fields["patient_name"].setText("{patient_name}")
        self.whatsapp_placeholder_fields["patient_name"].setToolTip(tr("Copy and paste this placeholder into a WhatsApp message template."))
        self.pdf_export_part_checks["order_number"].setText(tr("Order Number"))
        self.pdf_export_part_checks["patient_name"].setText(tr("Patient Name"))
        self.pdf_export_part_checks["client_name"].setText(tr("Client Name"))
        self.pdf_export_part_checks["doctor_name"].setText(tr("Doctor Name"))
        self.header_library_help.setText(tr("Add multiple header images here so each report can use a different header."))
        self.add_header_button.setText(tr("Add Header"))
        self.set_default_header_button.setText(tr("Set Default Header"))
        self.remove_header_button.setText(tr("Remove Header"))
        self.footer_library_help.setText(tr("Add multiple footer images here so each report can use a different footer."))
        self.add_footer_button.setText(tr("Add Footer"))
        self.set_default_footer_button.setText(tr("Set Default Footer"))
        self.remove_footer_button.setText(tr("Remove Footer"))
        current_flag_style = self.report_flag_style.currentData()
        self.report_flag_style.clear()
        for value, label in REPORT_FLAG_STYLE_OPTIONS:
            self.report_flag_style.addItem(tr(label), value)
        index = self.report_flag_style.findData(current_flag_style)
        self.report_flag_style.setCurrentIndex(index if index >= 0 else 0)
        self.connection_labels["mode"].setText(tr("Deployment Mode"))
        self.connection_labels["server_url"].setText(tr("Server URL"))
        self.connection_labels["login_email"].setText(tr("Email"))
        self.connection_labels["login_password"].setText(tr("Password"))
        self.connection_labels["service_status"].setText(tr("Backend Service"))
        self.install_service_button.setText(tr("Install Service"))
        self.uninstall_service_button.setText(tr("Uninstall Service"))
        self.start_service_button.setText(tr("Start"))
        self.stop_service_button.setText(tr("Stop"))
        self.refresh_service_button.setText(tr("Refresh"))
        self.logo_browse.setText(tr("Browse"))
        self.header_browse.setText(tr("Browse"))
        self.footer_browse.setText(tr("Browse"))
        self.pdf_export_folder_browse.setText(tr("Browse"))
        self.backup_destination_browse.setText(tr("Browse"))
        current_print_payload = self.printing_default_payload.currentData()
        self.printing_default_payload.clear()
        self.printing_default_payload.addItem(tr('Order ID only'), 'order_only')
        self.printing_default_payload.addItem(tr('Order ID + specimen code'), 'order_specimen')
        self.printing_default_payload.addItem(tr('Accession ID only'), 'accession_only')
        self.printing_default_payload.addItem(tr('Sample ID only'), 'sample_only')
        self.printing_default_payload.addItem(tr('Order ID + accession ID'), 'order_accession')
        payload_index = self.printing_default_payload.findData(current_print_payload or 'order_only')
        self.printing_default_payload.setCurrentIndex(payload_index if payload_index >= 0 else 0)
        current_language = self.language_combo.currentData()
        self.language_combo.clear()
        for code, label in SUPPORTED_LANGUAGES:
            self.language_combo.addItem(tr(label), code)
        index = self.language_combo.findData(current_language)
        self.language_combo.setCurrentIndex(index if index >= 0 else 0)
        current_mode = self.mode_combo.currentData()
        self.mode_combo.clear()
        self.mode_combo.addItem(tr("Local Mode"), "local")
        self.mode_combo.addItem(tr("Server Mode"), "server")
        mode_index = self.mode_combo.findData(current_mode or "local")
        self.mode_combo.setCurrentIndex(mode_index if mode_index >= 0 else 0)
        self.test_connection_button.setText(tr("Test Server Connection"))
        self.login_button.setText(tr("Log In"))
        self.logout_button.setText(tr("Log Out"))
        self.save_backup_config_button.setText(tr("Save Backup Config"))
        self.refresh_backup_button.setText(tr("Refresh Backup Status"))
        self.run_backup_now_button.setText(tr("Run Backup Now"))
        self.save_button.setText(tr("Save Settings"))

    def load_settings(self, *, force_server_refresh: bool = False) -> None:
        settings = self.database.get_lab_settings()
        profile = None
        config = self.deployment_service.load()
        server_url = config.server_url.strip()
        if config.mode == "server" and server_url:
            if force_server_refresh or self._server_profile_dirty or self._cached_profile_server_url != server_url:
                try:
                    self._cached_server_profile = self.lab_profile_service.load_profile()
                except RuntimeError:
                    self._cached_server_profile = None
                self._cached_profile_server_url = server_url
                self._server_profile_dirty = False
            profile = self._cached_server_profile
        self.lab_name.setText((profile or {}).get("lab_name", settings.lab_name))
        self.address.setText((profile or {}).get("address", settings.address))
        self.phone.setText((profile or {}).get("phone", settings.phone))
        self.email.setText((profile or {}).get("email", settings.email))
        self.logo_path.setText((profile or {}).get("logo_path", settings.logo_path))
        self.header_image_path.setText((profile or {}).get("header_image_path", settings.header_image_path))
        self.footer_signature_image_path.setText((profile or {}).get("footer_signature_image_path", settings.footer_signature_image_path))
        self._hidden_report_footer = ""
        self._hidden_director_name = ""
        self._hidden_director_license = ""
        flag_style_index = self.report_flag_style.findData(settings.report_flag_style)
        self.report_flag_style.setCurrentIndex(flag_style_index if flag_style_index >= 0 else 0)
        self.keep_panels_together.setChecked(bool(settings.keep_panels_together))
        self.report_font_family.setCurrentFont(QFont(settings.report_font_family or "Segoe UI"))
        self.report_font_size.setValue(max(8, min(18, int(settings.report_font_size or 12))))
        self.report_font_bold.setChecked(bool(settings.report_font_bold))
        self.report_abnormal_bold.setChecked(bool(settings.report_abnormal_bold))
        self.report_subheading_font_family.setCurrentFont(QFont(settings.report_subheading_font_family or "Segoe UI"))
        self.report_subheading_font_size.setValue(max(8, min(18, int(settings.report_subheading_font_size or 13))))
        self.report_subheading_font_bold.setChecked(bool(settings.report_subheading_font_bold))
        self.report_footer_gap_mm.setValue(max(0, min(60, int(settings.report_footer_gap_mm or 8))))
        sex_fmt_index = self.report_sex_format.findData(settings.report_sex_format or "short")
        self.report_sex_format.setCurrentIndex(sex_fmt_index if sex_fmt_index >= 0 else 0)
        date_fmt_index = self.report_date_format.findData(settings.report_date_format or "auto")
        self.report_date_format.setCurrentIndex(date_fmt_index if date_fmt_index >= 0 else 0)
        self.report_show_doctor.setChecked(bool(settings.report_show_doctor))
        self.report_show_client.setChecked(bool(settings.report_show_client))
        self.report_show_sex.setChecked(bool(settings.report_show_sex))
        self.report_show_age.setChecked(bool(settings.report_show_age))
        self.report_show_dob.setChecked(bool(settings.report_show_dob))
        self.report_show_ordered_at.setChecked(bool(settings.report_show_ordered_at))
        self.report_show_reported_at.setChecked(bool(settings.report_show_reported_at))
        for _combo, _val, _default in [
            (self.report_doctor_col, settings.report_doctor_col, "left"),
            (self.report_client_col, settings.report_client_col, "left"),
            (self.report_sex_col, settings.report_sex_col, "left"),
            (self.report_age_col, settings.report_age_col, "right"),
            (self.report_dob_col, settings.report_dob_col, "right"),
            (self.report_ordered_at_col, settings.report_ordered_at_col, "right"),
            (self.report_reported_at_col, settings.report_reported_at_col, "right"),
        ]:
            _idx = _combo.findData(_val or _default)
            _combo.setCurrentIndex(_idx if _idx >= 0 else 0)
        self.sat_rfc.setText(settings.sat_rfc)
        sat_index = self.sat_fiscal_regime.findData(settings.sat_fiscal_regime)
        self.sat_fiscal_regime.setCurrentIndex(sat_index if sat_index >= 0 else 0)
        self.sat_postal_code.setText(settings.sat_postal_code)
        self.sat_certificate_path.setText(settings.sat_certificate_path)
        self.sat_key_path.setText(settings.sat_key_path)
        index = self.language_combo.findData(settings.ui_language)
        self.language_combo.setCurrentIndex(index if index >= 0 else 0)
        self._load_header_library()
        self._load_footer_library()
        self._load_pdf_export_settings()
        self._load_printing_settings()
        self._load_receipt_settings()
        self._load_whatsapp_templates()
        country_code = self.database.get_whatsapp_country_code()
        country_index = self.whatsapp_country_code.findData(country_code)
        self.whatsapp_country_code.setCurrentIndex(country_index if country_index >= 0 else 0)
        if country_index < 0:
            self.whatsapp_country_code.setEditText(f"+{country_code}")
        self.load_backup_config(silent=True)

    def _load_header_library(self) -> None:
        branding = self.database.get_report_branding_options()
        selected_header = str(branding.get("selected_header") or "").strip()
        self.header_library.clear()
        for raw_path in branding.get("headers", []):
            value = str(raw_path or "").strip()
            if not value:
                continue
            label = value.split("\\")[-1].split("/")[-1] or value
            if value == selected_header:
                label = f"{label} [{tr('Default')}]"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, value)
            self.header_library.addItem(item)

    def _add_header_asset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Choose Report Header Image"),
            "",
            tr("Images (*.png *.jpg *.jpeg)"),
        )
        if not path:
            return
        saved_path = self.database.add_report_branding_asset(path, "header")
        if saved_path:
            self.header_image_path.setText(saved_path)
        self._load_header_library()

    def _selected_header_item_path(self) -> str:
        item = self.header_library.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "").strip()

    def _set_default_header_asset(self) -> None:
        selected_path = self._selected_header_item_path()
        if not selected_path:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a header first."))
            return
        branding = self.database.get_report_branding_options()
        self.database.save_report_branding_options(
            list(branding.get("headers", [])),
            list(branding.get("footers", [])),
            selected_path,
            str(branding.get("selected_footer") or ""),
        )
        self.header_image_path.setText(selected_path)
        self._load_header_library()

    def _remove_selected_header_asset(self) -> None:
        selected_path = self._selected_header_item_path()
        if not selected_path:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a header first."))
            return
        branding = self.database.get_report_branding_options()
        headers = [value for value in branding.get("headers", []) if str(value or "").strip() != selected_path]
        next_selected = str(branding.get("selected_header") or "")
        if next_selected == selected_path:
            next_selected = headers[0] if headers else ""
        self.database.save_report_branding_options(
            headers,
            list(branding.get("footers", [])),
            next_selected,
            str(branding.get("selected_footer") or ""),
        )
        if self.header_image_path.text().strip() == selected_path:
            self.header_image_path.setText(next_selected)
        self._load_header_library()

    def _load_footer_library(self) -> None:
        branding = self.database.get_report_branding_options()
        selected_footer = str(branding.get("selected_footer") or "").strip()
        self.footer_library.clear()
        for raw_path in branding.get("footers", []):
            value = str(raw_path or "").strip()
            if not value:
                continue
            label = value.split("\\")[-1].split("/")[-1] or value
            if value == selected_footer:
                label = f"{label} [{tr('Default')}]"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, value)
            self.footer_library.addItem(item)

    def _add_footer_asset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Choose Report Footer Image"),
            "",
            tr("Images (*.png *.jpg *.jpeg)"),
        )
        if not path:
            return
        self.database.add_report_branding_asset(path, "footer")
        self._load_footer_library()

    def _selected_footer_item_path(self) -> str:
        item = self.footer_library.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "").strip()

    def _set_default_footer_asset(self) -> None:
        selected_path = self._selected_footer_item_path()
        if not selected_path:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a footer first."))
            return
        branding = self.database.get_report_branding_options()
        self.database.save_report_branding_options(
            list(branding.get("headers", [])),
            list(branding.get("footers", [])),
            str(branding.get("selected_header") or ""),
            selected_path,
        )
        self.footer_signature_image_path.setText(selected_path)
        self._load_footer_library()

    def _remove_selected_footer_asset(self) -> None:
        selected_path = self._selected_footer_item_path()
        if not selected_path:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a footer first."))
            return
        branding = self.database.get_report_branding_options()
        footers = [v for v in branding.get("footers", []) if str(v or "").strip() != selected_path]
        next_selected = str(branding.get("selected_footer") or "")
        if next_selected == selected_path:
            next_selected = footers[0] if footers else ""
        self.database.save_report_branding_options(
            list(branding.get("headers", [])),
            footers,
            str(branding.get("selected_header") or ""),
            next_selected,
        )
        if self.footer_signature_image_path.text().strip() == selected_path:
            self.footer_signature_image_path.setText(next_selected)
        self._load_footer_library()

    def _load_pdf_export_settings(self) -> None:
        settings = get_pdf_export_settings(self.database)
        self._populate_system_printer_combo(self.report_printer, str(settings.get("printer") or "system_default"))
        self.pdf_export_folder.setText(str(settings.get("folder_path") or ""))
        selected_parts = list(settings.get("filename_parts") or ["order_number"])
        for key, checkbox in self.pdf_export_part_checks.items():
            checkbox.setChecked(key in selected_parts)

    def _load_printing_settings(self) -> None:
        settings = self.database.get_label_print_preferences()
        self._populate_label_printers(str(settings.get("printer") or "niimbot:B1"))
        size_index = self.printing_default_size.findData(settings.get("size") or "small_tall")
        self.printing_default_size.setCurrentIndex(size_index if size_index >= 0 else 0)
        payload_index = self.printing_default_payload.findData(settings.get("payload") or "order_only")
        self.printing_default_payload.setCurrentIndex(payload_index if payload_index >= 0 else 0)
        self.printing_show_barcode.setChecked(str(settings.get("show_barcode") or "1") == "1")
        self.printing_show_patient_name.setChecked(str(settings.get("show_patient_name") or "1") == "1")
        self.printing_show_order_number_text.setChecked(str(settings.get("show_order_number_text") or "0") == "1")
        self.printing_show_datetime.setChecked(str(settings.get("show_datetime") or "0") == "1")
        try:
            self.printing_default_copies.setValue(max(1, int(str(settings.get("copies") or "1"))))
        except ValueError:
            self.printing_default_copies.setValue(1)
        self._load_panel_extra_copies()

    def _load_panel_extra_copies(self) -> None:
        while self._panel_extra_copies_layout.count():
            item = self._panel_extra_copies_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._panel_extra_copy_spins.clear()
        panels = self.database.list_panels(status_filter="active")
        saved_extras = self.database.get_panel_extra_copies()
        if not panels:
            self.printing_panel_extra_group.setVisible(False)
            return
        self.printing_panel_extra_group.setVisible(True)
        for panel in panels:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            label = QLabel(f"{panel.code} — {panel.name}")
            spin = QSpinBox()
            spin.setRange(0, 20)
            spin.setValue(saved_extras.get(panel.code, 0))
            row_layout.addWidget(label, 1)
            row_layout.addWidget(spin)
            self._panel_extra_copies_layout.addWidget(row)
            self._panel_extra_copy_spins[panel.code] = spin

    def _load_receipt_settings(self) -> None:
        settings = self.database.get_receipt_print_preferences()
        self._populate_system_printer_combo(self.receipt_printer, str(settings.get("printer") or "system_default"))
        self.receipt_auto_print.setChecked(str(settings.get("auto_print") or "0") == "1")
        paper_index = self.receipt_paper_format.findData(settings.get("paper_format") or "letter")
        self.receipt_paper_format.setCurrentIndex(paper_index if paper_index >= 0 else 0)

    def _load_whatsapp_templates(self) -> None:
        templates = get_whatsapp_templates(self.database)
        self.whatsapp_patient_message.setPlainText(templates["patient"])
        self.whatsapp_client_message.setPlainText(templates["client"])

    def load_deployment_settings(self) -> None:
        config = self.deployment_service.load()
        index = self.mode_combo.findData(config.mode)
        self.mode_combo.setCurrentIndex(index if index >= 0 else 0)
        self.server_url.setText(config.server_url)
        if config.email:
            self.login_email.setText(config.email)
        if config.password:
            self.login_password.setText(config.password)
        threading.Thread(target=self._bg_refresh_service_status, daemon=True).start()
        if config.mode == "server":
            self.connection_status.setText(tr("Desktop is configured to target server {server_url}.", server_url=config.server_url))
            self._refresh_session_status()
            self.load_backup_config(silent=True)
            self.refresh_backup_status(silent=True)
            return
        self.connection_status.setText(tr("Desktop is configured for local SQLite mode."))
        self._refresh_session_status()
        self.backup_status.setText(tr("Backup configuration is available in server mode."))

    def save_settings(self) -> None:
        if not self.lab_name.text().strip():
            QMessageBox.warning(self, tr("Missing Data"), tr("Lab name is required."))
            return

        mode = str(self.mode_combo.currentData() or "local")
        server_url = self.server_url.text().strip()
        if mode == "server" and not server_url:
            QMessageBox.warning(self, tr("Missing Data"), tr("Server URL is required when server mode is selected."))
            return

        settings_payload = {
            "lab_name": self.lab_name.text(),
            "address": self.address.text(),
            "phone": self.phone.text(),
            "email": self.email.text(),
            "logo_path": self.logo_path.text(),
            "header_image_path": self.header_image_path.text(),
            "footer_signature_image_path": self.footer_signature_image_path.text(),
            "report_footer": "",
            "director_name": "",
            "director_license": "",
            "report_flag_style": self.report_flag_style.currentData(),
            "keep_panels_together": "1" if self.keep_panels_together.isChecked() else "0",
            "report_font_family": self.report_font_family.currentFont().family(),
            "report_font_size": str(self.report_font_size.value()),
            "report_font_bold": "1" if self.report_font_bold.isChecked() else "0",
            "report_abnormal_bold": "1" if self.report_abnormal_bold.isChecked() else "0",
            "report_subheading_font_family": self.report_subheading_font_family.currentFont().family(),
            "report_subheading_font_size": str(self.report_subheading_font_size.value()),
            "report_subheading_font_bold": "1" if self.report_subheading_font_bold.isChecked() else "0",
            "report_footer_gap_mm": str(self.report_footer_gap_mm.value()),
            "report_sex_format": self.report_sex_format.currentData(),
            "report_date_format": self.report_date_format.currentData(),
            "report_show_doctor": "1" if self.report_show_doctor.isChecked() else "0",
            "report_show_client": "1" if self.report_show_client.isChecked() else "0",
            "report_show_sex": "1" if self.report_show_sex.isChecked() else "0",
            "report_show_age": "1" if self.report_show_age.isChecked() else "0",
            "report_show_dob": "1" if self.report_show_dob.isChecked() else "0",
            "report_show_ordered_at": "1" if self.report_show_ordered_at.isChecked() else "0",
            "report_show_reported_at": "1" if self.report_show_reported_at.isChecked() else "0",
            "report_doctor_col": self.report_doctor_col.currentData() or "left",
            "report_client_col": self.report_client_col.currentData() or "left",
            "report_sex_col": self.report_sex_col.currentData() or "left",
            "report_age_col": self.report_age_col.currentData() or "right",
            "report_dob_col": self.report_dob_col.currentData() or "right",
            "report_ordered_at_col": self.report_ordered_at_col.currentData() or "right",
            "report_reported_at_col": self.report_reported_at_col.currentData() or "right",
            "sat_rfc": self.sat_rfc.text(),
            "sat_fiscal_regime": self.sat_fiscal_regime.currentData(),
            "sat_postal_code": self.sat_postal_code.text(),
            "sat_certificate_path": self.sat_certificate_path.text(),
            "sat_key_path": self.sat_key_path.text(),
            "ui_language": self.language_combo.currentData(),
        }
        self.database.save_lab_settings(settings_payload)
        selected_filename_parts = [key for key in FILENAME_PART_KEYS if self.pdf_export_part_checks[key].isChecked()]
        default_print_copies = str(max(1, int(self.printing_default_copies.value())))
        show_barcode = self.printing_show_barcode.isChecked()
        show_patient_name = self.printing_show_patient_name.isChecked()
        derived_code_type = "barcode_name" if show_patient_name else "barcode_only"
        current_print_preferences = self.database.get_label_print_preferences()
        self.database.save_label_print_preferences(
            str(current_print_preferences.get("template") or "general"),
            str(self.printing_default_payload.currentData() or "order_only"),
            size=str(self.printing_default_size.currentData() or "small_tall"),
            code_type=derived_code_type,
            copies=default_print_copies,
            show_barcode=show_barcode,
            show_patient_name=show_patient_name,
            show_order_number_text=self.printing_show_order_number_text.isChecked(),
            show_datetime=self.printing_show_datetime.isChecked(),
            printer=str(self.printing_printer.currentData() or "niimbot:B1"),
        )
        self.database.save_receipt_print_preferences(
            auto_print=self.receipt_auto_print.isChecked(),
            paper_format=str(self.receipt_paper_format.currentData() or "letter"),
            printer=str(self.receipt_printer.currentData() or "system_default"),
        )
        self.database.save_panel_extra_copies(
            {code: spin.value() for code, spin in self._panel_extra_copy_spins.items()}
        )
        save_pdf_export_settings(
            self.database,
            folder_path=self.pdf_export_folder.text(),
            filename_parts=selected_filename_parts,
            printer=str(self.report_printer.currentData() or "system_default"),
        )
        save_whatsapp_templates(
            self.database,
            patient=self.whatsapp_patient_message.toPlainText(),
            client=self.whatsapp_client_message.toPlainText(),
        )
        self.database.save_whatsapp_country_code(str(self.whatsapp_country_code.currentText() or self.whatsapp_country_code.currentData() or ""))
        self._server_profile_dirty = True
        existing_cfg = self.deployment_service.load()
        ui_email = self.login_email.text().strip()
        ui_password = self.login_password.text()
        saved_config = self.deployment_service.save(
            DeploymentConfig(
                mode=mode,
                server_url=server_url or "http://127.0.0.1:8001",
                api_timeout_seconds=existing_cfg.api_timeout_seconds,
                email=ui_email or existing_cfg.email,
                password=ui_password or existing_cfg.password,
            )
        )
        server_profile_message = None
        if mode == "server":
            try:
                saved_profile = self.lab_profile_service.save_profile(settings_payload)
                self._cached_server_profile = saved_profile
                self._cached_profile_server_url = server_url or saved_config.server_url
                self._server_profile_dirty = False
                settings_payload["logo_path"] = saved_profile.get("logo_path", settings_payload["logo_path"])
                settings_payload["header_image_path"] = saved_profile.get("header_image_path", settings_payload["header_image_path"])
                settings_payload["footer_signature_image_path"] = saved_profile.get("footer_signature_image_path", settings_payload["footer_signature_image_path"])
                server_profile_message = tr("Shared server branding was updated.")
            except RuntimeError as exc:
                QMessageBox.warning(self, tr("Server Sync Failed"), str(exc))
        apply_language = getattr(self.window(), "apply_language", None)
        if callable(apply_language):
            apply_language(self.language_combo.currentData())
        self.load_settings(force_server_refresh=True)
        self.load_deployment_settings()
        refresh_status = getattr(self.window(), "refresh_deployment_status", None)
        if callable(refresh_status):
            refresh_status()
        self.notify_data_changed()
        saved_message = tr("Lab settings were saved.")
        if saved_config.mode == "server":
            saved_message = tr("Lab settings were saved. Server mode is configured for {server_url}.", server_url=saved_config.server_url)
            if server_profile_message:
                saved_message = f"{saved_message} {server_profile_message}"
        QMessageBox.information(self, tr("Saved"), saved_message)

    def test_server_connection(self) -> None:
        result = self.deployment_service.ping(self.server_url.text().strip())
        if result.ok:
            env_suffix = f" ({result.environment})" if result.environment else ""
            message = tr("Server connection successful{env_suffix}.", env_suffix=env_suffix)
            self.connection_status.setText(message)
            QMessageBox.information(self, tr("Connection Test"), message)
            return
        self.connection_status.setText(result.message)
        QMessageBox.warning(self, tr("Connection Test"), result.message)

    def login_to_server(self) -> None:
        mode = str(self.mode_combo.currentData() or "local")
        server_url = self.server_url.text().strip()
        email = self.login_email.text().strip()
        password = self.login_password.text()
        if mode != "server":
            QMessageBox.warning(self, tr("Login"), tr("Switch to server mode before logging in."))
            return
        if not server_url:
            QMessageBox.warning(self, tr("Missing Data"), tr("Server URL is required when server mode is selected."))
            return
        if not email or not password:
            QMessageBox.warning(self, tr("Missing Data"), tr("Email and password are required."))
            return

        existing = self.deployment_service.load()
        self.deployment_service.save(
            DeploymentConfig(
                mode=mode,
                server_url=server_url,
                api_timeout_seconds=existing.api_timeout_seconds,
            )
        )
        try:
            result = self.deployment_service.login(email, password)
        except RuntimeError as exc:
            self._refresh_session_status()
            QMessageBox.warning(self, tr("Login Failed"), str(exc))
            return
        self.deployment_service.save(
            DeploymentConfig(
                mode=mode,
                server_url=server_url,
                api_timeout_seconds=existing.api_timeout_seconds,
                email=email,
                password=password,
            )
        )
        self._refresh_session_status()
        self.load_backup_config(silent=True)
        self.refresh_backup_status(silent=True)
        refresh_status = getattr(self.window(), "refresh_deployment_status", None)
        if callable(refresh_status):
            refresh_status()
        QMessageBox.information(self, tr("Login"), tr("Logged in as {email}.", email=result.email))

    def logout_from_server(self) -> None:
        self.deployment_service.logout()
        self._refresh_session_status()
        self.load_backup_config(silent=True)
        self.refresh_backup_status(silent=True)
        refresh_status = getattr(self.window(), "refresh_deployment_status", None)
        if callable(refresh_status):
            refresh_status()

    def _backend_dir(self) -> Path | None:
        root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
        candidate = root / "backend"
        return candidate if (candidate / "app" / "main.py").exists() else None

    def _bg_refresh_service_status(self) -> None:
        result = subprocess.run(
            ["sc", "query", "SPDXLIMSBackend"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            text = tr("Not installed")
        else:
            state = ""
            for line in result.stdout.splitlines():
                if "STATE" in line and ":" in line:
                    parts = line.split(":")
                    if len(parts) > 1:
                        state = parts[1].strip().split()[1] if len(parts[1].strip().split()) > 1 else parts[1].strip()
            text = state or tr("Unknown")
        QTimer.singleShot(0, lambda: self.service_status_label.setText(text))

    def _install_backend_service(self) -> None:
        backend_dir = self._backend_dir()
        if backend_dir is None:
            QMessageBox.warning(self, tr("Backend Service"), tr("Backend directory not found."))
            return
        result = subprocess.run(
            [sys.executable, str(backend_dir / "service.py"), "install"],
            capture_output=True, text=True, cwd=str(backend_dir),
        )
        msg = result.stdout.strip() or result.stderr.strip() or tr("Done.")
        QMessageBox.information(self, tr("Backend Service"), msg)
        threading.Thread(target=self._bg_refresh_service_status, daemon=True).start()

    def _uninstall_backend_service(self) -> None:
        backend_dir = self._backend_dir()
        if backend_dir is None:
            QMessageBox.warning(self, tr("Backend Service"), tr("Backend directory not found."))
            return
        result = subprocess.run(
            [sys.executable, str(backend_dir / "service.py"), "remove"],
            capture_output=True, text=True, cwd=str(backend_dir),
        )
        msg = result.stdout.strip() or result.stderr.strip() or tr("Done.")
        QMessageBox.information(self, tr("Backend Service"), msg)
        threading.Thread(target=self._bg_refresh_service_status, daemon=True).start()

    def _start_backend_service(self) -> None:
        result = subprocess.run(["sc", "start", "SPDXLIMSBackend"], capture_output=True, text=True, timeout=15)
        msg = result.stdout.strip() or result.stderr.strip() or tr("Start command sent.")
        QMessageBox.information(self, tr("Backend Service"), msg)
        threading.Thread(target=self._bg_refresh_service_status, daemon=True).start()

    def _stop_backend_service(self) -> None:
        result = subprocess.run(["sc", "stop", "SPDXLIMSBackend"], capture_output=True, text=True, timeout=15)
        msg = result.stdout.strip() or result.stderr.strip() or tr("Stop command sent.")
        QMessageBox.information(self, tr("Backend Service"), msg)
        threading.Thread(target=self._bg_refresh_service_status, daemon=True).start()

    def _refresh_session_status(self) -> None:
        label = self.deployment_service.session_label()
        if label:
            self.session_status.setText(tr("Logged in as {session}.", session=label))
            return
        self.session_status.setText(tr("Not logged in to the server."))

    def load_backup_config(self, *, silent: bool = False) -> None:
        config = self.deployment_service.load()
        if config.mode != "server":
            self.backup_status.setText(tr("Backup configuration is available in server mode."))
            return
        if not self.deployment_service.is_authenticated():
            self.backup_status.setText(tr("Log in as an admin or lab manager to view backup configuration."))
            return
        try:
            payload = self.deployment_service.request_json("GET", "/api/operations/backup-config")
        except RuntimeError as exc:
            self.backup_status.setText(str(exc))
            if not silent:
                QMessageBox.warning(self, tr("Backup Configuration"), str(exc))
            return
        if not isinstance(payload, dict):
            self.backup_status.setText(tr("Server did not return backup configuration."))
            return
        self.backup_enabled.setChecked(bool(payload.get("enabled")))
        self.backup_destination.setText(str(payload.get("destination") or ""))
        self.backup_schedule.setText(str(payload.get("schedule") or "Daily at 8:00 PM"))
        try:
            self.backup_retention_days.setValue(max(1, int(payload.get("retention_days") or 30)))
        except (TypeError, ValueError):
            self.backup_retention_days.setValue(30)
        self.backup_include_database.setChecked(bool(payload.get("include_database", True)))
        self.backup_include_assets.setChecked(bool(payload.get("include_assets", True)))
        self.backup_include_instrument_profiles.setChecked(bool(payload.get("include_instrument_profiles", True)))
        self.backup_cloud_sync_note.setText(str(payload.get("cloud_sync_note") or ""))
        self.backup_restore_drill_date.setText(str(payload.get("restore_drill_date") or ""))

    def save_backup_config(self, *, show_confirmation: bool = True) -> bool:
        config = self.deployment_service.load()
        if config.mode != "server":
            QMessageBox.warning(self, tr("Backup Configuration"), tr("Switch to server mode before saving backup configuration."))
            return False
        if not self.deployment_service.is_authenticated():
            QMessageBox.warning(self, tr("Backup Configuration"), tr("Log in as an admin or lab manager to save backup configuration."))
            return False
        payload = {
            "enabled": self.backup_enabled.isChecked(),
            "destination": self.backup_destination.text().strip(),
            "schedule": self.backup_schedule.text().strip() or "Daily at 8:00 PM",
            "retention_days": int(self.backup_retention_days.value()),
            "include_database": self.backup_include_database.isChecked(),
            "include_assets": self.backup_include_assets.isChecked(),
            "include_instrument_profiles": self.backup_include_instrument_profiles.isChecked(),
            "cloud_sync_note": self.backup_cloud_sync_note.text().strip(),
            "restore_drill_date": self.backup_restore_drill_date.text().strip(),
        }
        try:
            self.deployment_service.request_json("PUT", "/api/operations/backup-config", payload)
        except RuntimeError as exc:
            QMessageBox.warning(self, tr("Backup Configuration"), str(exc))
            return False
        self.load_backup_config(silent=True)
        if show_confirmation:
            QMessageBox.information(self, tr("Backup Configuration"), tr("Backup configuration was saved."))
        return True

    def run_backup_now(self) -> None:
        config = self.deployment_service.load()
        if config.mode != "server":
            QMessageBox.warning(self, tr("Backup"), tr("Switch to server mode before running a backup."))
            return
        if not self.deployment_service.is_authenticated():
            QMessageBox.warning(self, tr("Backup"), tr("Log in as an admin or lab manager to run a backup."))
            return
        if not self.save_backup_config(show_confirmation=False):
            return
        try:
            payload = self.deployment_service.request_json("POST", "/api/operations/run-backup")
        except RuntimeError as exc:
            self.backup_status.setText(str(exc))
            QMessageBox.warning(self, tr("Backup"), str(exc))
            return
        if isinstance(payload, dict):
            self._show_backup_status_payload(payload)
        QMessageBox.information(self, tr("Backup"), tr("Backup completed successfully."))

    def refresh_backup_status(self, *, silent: bool = False) -> None:
        config = self.deployment_service.load()
        if config.mode != "server":
            self.backup_status.setText(tr("Backup status is available in server mode."))
            return
        if not self.deployment_service.is_authenticated():
            self.backup_status.setText(tr("Log in as an admin or lab manager to view backup status."))
            return
        try:
            payload = self.deployment_service.request_json("GET", "/api/operations/backup-status")
        except RuntimeError as exc:
            self.backup_status.setText(str(exc))
            if not silent:
                QMessageBox.warning(self, tr("Backup Status"), str(exc))
            return
        if not isinstance(payload, dict):
            self.backup_status.setText(tr("Server did not return backup status."))
            return
        self._show_backup_status_payload(payload)

    def _show_backup_status_payload(self, payload: dict[str, object]) -> None:
        status = str(payload.get("status") or tr("unknown"))
        timestamp = str(payload.get("last_backup_at") or tr("never"))
        destination = str(payload.get("destination") or tr("not reported"))
        warning = str(payload.get("warning") or "")
        message = tr("Status: {status}. Last backup: {timestamp}. Destination: {destination}.", status=status, timestamp=timestamp, destination=destination)
        if warning:
            message = f"{message} {warning}"
        self.backup_status.setText(message)
