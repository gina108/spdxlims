from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import yaml as _yaml
except ImportError:
    _yaml = None  # type: ignore[assignment]

_PROFILES_DIR = Path(__file__).parent.parent.parent / "instrument-connectivity" / "profiles"

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QFormLayout,
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database, EquipmentRecord, InstrumentOrderMatchRecord
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.pages.machine_setup_wizard import MachineSetupWizard


class EquipmentPage(DataAwarePage):
    ENGINE_URL = "http://127.0.0.1:9088"
    ANALYZER_CODE_CHOICES = {
        "urinalysis-com6": [
            ("LEU", "Leukocytes", "EGO-LEU", ""),
            ("NIT", "Nitrite", "EGO-NIT", ""),
            ("URO", "Urobilinogen", "EGO-URO", "mg/dL"),
            ("PRO", "Protein", "EGO-PRO", "mg/dL"),
            ("PH", "Urine pH", "EGO-PH", ""),
            ("BLO", "Blood", "EGO-BLO", ""),
            ("SG", "Specific Gravity", "EGO-SG", ""),
            ("KET", "Ketones", "EGO-KET", ""),
            ("BIL", "Bilirubin", "EGO-BIL", ""),
            ("GLU", "Glucose", "EGO-GLU", ""),
        ],
        "cor50-lis": [
            ("TP_0", "Prothrombin Time (s)", "LIS-PT", "s"),
            ("TP_1", "Prothrombin Time Activity (%)", "LIS-PT-PCT", "%"),
            ("TP_2", "ISI", "LIS-ISI", "ratio"),
            ("TP_3", "INR", "LIS-INR", "ratio"),
            ("TP_4", "Fibrinogen", "LIS-FIB", "mg/dL"),
            ("APTT", "APTT", "LIS-APTT", "s"),
            ("Testigo", "PT Control", "LIS-TESTIGO", "s"),
        ],
        "cm250": [
            ("GLU L", "Glucose", "CM250-GLU", "mg/dL"),
            ("URE Lb", "Urea", "CM250-URE", "mg/dL"),
            ("CRE L", "Creatinine", "CM250-CRE", "mg/dL"),
            ("A-COL", "Total Cholesterol", "CM250-COL", "mg/dL"),
            ("A-TG", "Triglycerides", "CM250-TG", "mg/dL"),
            ("A-HDL", "HDL Cholesterol", "CM250-HDL", "mg/dL"),
            ("BT AA", "Total Bilirubin", "CM250-BT", "mg/dL"),
            ("BD AA", "Direct Bilirubin", "CM250-BD", "mg/dL"),
            ("ALP Lb", "Alkaline Phosphatase", "CM250-ALP", "U/L"),
            ("AUR Lb", "Uric Acid", "CM250-AUR", "mg/dL"),
            ("GOT Lb", "AST", "CM250-GOT", "U/L"),
            ("GPT Lb", "ALT", "CM250-GPT", "U/L"),
            ("PT", "Prothrombin Time", "CM250-PT", "s"),
            ("ALB", "Albumin", "CM250-ALB", "g/dL"),
        ],
    }

    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        self.selected_equipment_id: int | None = None
        self.equipment_records: list[EquipmentRecord] = []
        self.discovery_rows: list[dict[str, object]] = []

        root = QHBoxLayout(self)

        self.tabs = QTabWidget()
        self.form_tab = QWidget()
        self.discovery_tab = QWidget()
        self.mapping_tab = QWidget()
        self.order_match_tab = QWidget()
        self.tabs.addTab(self.form_tab, "")
        self.tabs.addTab(self.discovery_tab, "")
        self.tabs.addTab(self.mapping_tab, "")
        self.tabs.addTab(self.order_match_tab, "")

        self._build_form_tab()
        self._build_discovery_tab()
        self._build_mapping_tab()
        self._build_order_match_tab()
        self._build_inventory_panel()

        root.addWidget(self.tabs, 2)
        root.addWidget(self.table_group, 3)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.retranslate_ui()
        self.refresh_equipment()
        self.refresh_mapping_choices()
        self.refresh_analyzer_code_choices()
        self.refresh_order_match_configs()

    def _build_form_tab(self) -> None:
        layout = QVBoxLayout(self.form_tab)
        self.form_group = QGroupBox()
        self.form_layout = QFormLayout(self.form_group)
        self.labels: dict[str, QLabel] = {}

        self.name = QLineEdit()
        self.equipment_type = QLineEdit()
        self.manufacturer = QLineEdit()
        self.model = QLineEdit()
        self.serial_number = QLineEdit()
        self.location = QLineEdit()
        self.status = QComboBox()
        self.last_maintenance_date = QLineEdit()
        self.next_maintenance_date = QLineEdit()
        self.notes = QTextEdit()
        self.notes.setMinimumHeight(120)

        self._add_form_row("name", self.name)
        self._add_form_row("equipment_type", self.equipment_type)
        self._add_form_row("manufacturer", self.manufacturer)
        self._add_form_row("model", self.model)
        self._add_form_row("serial_number", self.serial_number)
        self._add_form_row("location", self.location)
        self._add_form_row("status", self.status)
        self._add_form_row("last_maintenance_date", self.last_maintenance_date)
        self._add_form_row("next_maintenance_date", self.next_maintenance_date)
        self._add_form_row("notes", self.notes)

        button_row = QHBoxLayout()
        self.new_button = QPushButton()
        self.save_button = QPushButton()
        self.delete_button = QPushButton()
        self.new_button.clicked.connect(self.new_equipment)
        self.save_button.clicked.connect(self.save_equipment)
        self.delete_button.clicked.connect(self.delete_selected_equipment)
        button_row.addWidget(self.new_button)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.delete_button)
        self.form_layout.addRow(button_row)

        layout.addWidget(self.form_group)
        layout.addStretch(1)

    def _build_discovery_tab(self) -> None:
        layout = QVBoxLayout(self.discovery_tab)

        setup_group = QGroupBox()
        setup_layout = QFormLayout(setup_group)
        self.connection_mode = QComboBox()
        self.connection_mode.addItem("Analyzer sends to this PC", "network_inbound")
        self.connection_mode.addItem("This PC connects to analyzer", "network_outbound")
        self.connection_mode.addItem("Serial / USB adapter", "serial")
        self.connection_mode.addItem("File folder", "file_drop")
        self.setup_ip = QLineEdit()
        self.setup_port = QLineEdit()
        self.setup_serial = QLineEdit()
        self.setup_profile = QLineEdit()
        self.setup_summary = QLabel()
        self.setup_summary.setWordWrap(True)
        self.apply_setup_button = QPushButton()
        self.apply_setup_button.clicked.connect(self.apply_setup_to_form)
        setup_layout.addRow(QLabel(tr("Connection Type")), self.connection_mode)
        setup_layout.addRow(QLabel(tr("Analyzer IP")), self.setup_ip)
        setup_layout.addRow(QLabel(tr("LIS Port")), self.setup_port)
        setup_layout.addRow(QLabel(tr("Serial Port")), self.setup_serial)
        setup_layout.addRow(QLabel(tr("Profile ID")), self.setup_profile)
        setup_layout.addRow(self.apply_setup_button)
        setup_layout.addRow(self.setup_summary)

        scan_group = QGroupBox()
        scan_layout = QVBoxLayout(scan_group)
        scan_form = QFormLayout()
        self.scan_mode = QComboBox()
        self.scan_mode.addItem("Quick scan", "quick")
        self.scan_mode.addItem("Full subnet scan", "full")
        self.scan_mode.addItem("Custom", "custom")
        self.scan_cidrs = QLineEdit()
        self.scan_ports = QLineEdit()
        self.scan_host_limit = QLineEdit()
        scan_form.addRow(QLabel(tr("Scan Mode")), self.scan_mode)
        scan_form.addRow(QLabel(tr("Network CIDRs")), self.scan_cidrs)
        scan_form.addRow(QLabel(tr("Probe Ports")), self.scan_ports)
        scan_form.addRow(QLabel(tr("Host Limit")), self.scan_host_limit)
        scan_layout.addLayout(scan_form)

        scan_buttons = QHBoxLayout()
        self.scan_button = QPushButton()
        self.use_discovery_button = QPushButton()
        self.open_connectivity_button = QPushButton()
        self.scan_button.clicked.connect(self.scan_equipment)
        self.use_discovery_button.clicked.connect(self.fill_form_from_discovery)
        self.open_connectivity_button.clicked.connect(self.open_connectivity_console)
        scan_buttons.addWidget(self.scan_button)
        scan_buttons.addWidget(self.use_discovery_button)
        scan_buttons.addWidget(self.open_connectivity_button)
        scan_layout.addLayout(scan_buttons)

        self.scan_status = QLabel()
        self.scan_status.setWordWrap(True)
        self.discovery_table = QTableWidget(0, 5)
        self.discovery_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.discovery_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.discovery_table.horizontalHeader().setStretchLastSection(True)
        scan_layout.addWidget(self.scan_status)
        scan_layout.addWidget(self.discovery_table)

        layout.addWidget(setup_group)
        layout.addWidget(scan_group, 1)

    def _build_mapping_tab(self) -> None:
        outer = QHBoxLayout(self.mapping_tab)
        outer.setSpacing(12)

        # --- left column: input form ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        mapping_group = QGroupBox()
        mapping_layout = QFormLayout(mapping_group)
        self.mapping_profile = QComboBox()
        self.mapping_profile.setEditable(True)
        self.mapping_profile.setInsertPolicy(QComboBox.NoInsert)
        self.mapping_device = QLineEdit()
        self.mapping_raw_code = QComboBox()
        self.mapping_raw_code.setObjectName("analyzerCodeCombo")
        self.mapping_raw_code.setEditable(True)
        self.mapping_raw_code.setInsertPolicy(QComboBox.NoInsert)
        self.mapping_raw_name = QLineEdit()
        self.mapping_test = QComboBox()
        self.mapping_test.setEditable(True)
        self.mapping_test.setInsertPolicy(QComboBox.NoInsert)
        self.mapping_test.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.mapping_test.completer().setFilterMode(Qt.MatchContains)
        self.mapping_test.completer().setCaseSensitivity(Qt.CaseInsensitive)
        self.mapping_unit = QLineEdit()
        self.mapping_slice_start = QLineEdit()
        self.mapping_slice_start.setPlaceholderText(tr("e.g. 2"))
        self.mapping_slice_end = QLineEdit()
        self.mapping_slice_end.setPlaceholderText(tr("e.g. 5"))
        self.mapping_multiplier = QLineEdit()
        self.mapping_multiplier.setPlaceholderText("e.g. *1000  /10  +5  -2  x*10+5")
        self.mapping_decimal_places = QLineEdit()
        self.mapping_decimal_places.setPlaceholderText(tr("e.g. 2"))
        slice_row = QHBoxLayout()
        slice_row.addWidget(QLabel(tr("From")))
        slice_row.addWidget(self.mapping_slice_start, 1)
        slice_row.addWidget(QLabel(tr("To")))
        slice_row.addWidget(self.mapping_slice_end, 1)
        slice_container = QWidget()
        slice_container.setLayout(slice_row)
        self.save_mapping_button = QPushButton()
        self.mapping_profile.currentTextChanged.connect(self.refresh_analyzer_code_choices)
        self.mapping_profile.currentTextChanged.connect(self.refresh_mappings)
        self.mapping_profile.currentIndexChanged.connect(self._clear_mapping_fields)
        self.mapping_raw_code.currentIndexChanged.connect(self._apply_selected_analyzer_code)
        self.save_mapping_button.clicked.connect(self.save_test_mapping)
        mapping_layout.addRow(QLabel(tr("Profile ID")), self.mapping_profile)
        mapping_layout.addRow(QLabel(tr("Device ID")), self.mapping_device)
        mapping_layout.addRow(QLabel(tr("Analyzer Code")), self.mapping_raw_code)
        mapping_layout.addRow(QLabel(tr("Analyzer Test Name")), self.mapping_raw_name)
        mapping_layout.addRow(QLabel(tr("LIMS Test")), self.mapping_test)
        mapping_layout.addRow(QLabel(tr("Unit Override")), self.mapping_unit)
        mapping_layout.addRow(QLabel(tr("Char Range")), slice_container)
        mapping_layout.addRow(QLabel(tr("Formula")), self.mapping_multiplier)
        mapping_layout.addRow(QLabel(tr("Decimal Places")), self.mapping_decimal_places)
        mapping_layout.addRow(self.save_mapping_button)
        self.mapping_status = QLabel()
        self.mapping_status.setWordWrap(True)
        left_layout.addWidget(mapping_group)
        left_layout.addWidget(self.mapping_status)
        left_layout.addStretch(1)

        # --- right column: filtered mapping table ---
        self.mapping_table_group = QGroupBox()
        right_layout = QVBoxLayout(self.mapping_table_group)
        self.mapping_table = QTableWidget(0, 4)
        self.mapping_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.mapping_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.horizontalHeader().setStretchLastSection(True)
        self.mapping_table.setColumnWidth(0, 220)
        self.delete_mapping_button = QPushButton()
        self.delete_mapping_button.clicked.connect(self._delete_selected_mapping)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self.delete_mapping_button)
        right_layout.addLayout(btn_row)
        right_layout.addWidget(self.mapping_table, 1)

        outer.addWidget(left_widget, 1)
        outer.addWidget(self.mapping_table_group, 2)

    def _build_inventory_panel(self) -> None:
        self.table_group = QGroupBox()
        table_layout = QVBoxLayout(self.table_group)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.table = QTableWidget(0, 8)
        self.table.setObjectName("equipmentTable")
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(self.load_selected_equipment)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMinimumHeight(420)

        self.wizard_button = QPushButton()
        self.wizard_button.setStyleSheet("font-weight: bold; padding: 6px 12px;")
        self.wizard_button.clicked.connect(self._launch_setup_wizard)

        action_row = QHBoxLayout()
        self.edit_selected_button = QPushButton()
        self.delete_selected_button = QPushButton()
        self.refresh_button = QPushButton()
        self.edit_selected_button.clicked.connect(self.load_selected_equipment)
        self.delete_selected_button.clicked.connect(self.delete_selected_equipment)
        self.refresh_button.clicked.connect(self.refresh_on_show)
        action_row.addWidget(self.edit_selected_button)
        action_row.addWidget(self.delete_selected_button)
        action_row.addWidget(self.refresh_button)

        table_layout.addWidget(self.info)
        table_layout.addWidget(self.wizard_button)
        table_layout.addLayout(action_row)
        table_layout.addWidget(self.table)

    def _add_form_row(self, key: str, field: QWidget) -> None:
        label = QLabel()
        self.labels[key] = label
        self.form_layout.addRow(label, field)

    def retranslate_ui(self) -> None:
        self.tabs.setTabText(0, tr("Equipment"))
        self.tabs.setTabText(1, tr("Discovery"))
        self.tabs.setTabText(2, tr("Test Mapping"))
        self.tabs.setTabText(3, "Emparejamiento de orden")
        self.form_group.setTitle(tr("Register Equipment"))
        self.table_group.setTitle(tr("Lab Equipment"))
        self.info.setText(tr("Select equipment to edit it, delete retired duplicates, or use discovery to register connected analyzers."))
        self.labels["name"].setText(tr("Equipment Name"))
        self.labels["equipment_type"].setText(tr("Equipment Type"))
        self.labels["manufacturer"].setText(tr("Manufacturer"))
        self.labels["model"].setText(tr("Model"))
        self.labels["serial_number"].setText(tr("Serial Number"))
        self.labels["location"].setText(tr("Location"))
        self.labels["status"].setText(tr("Equipment Status"))
        self.labels["last_maintenance_date"].setText(tr("Last Maintenance"))
        self.labels["next_maintenance_date"].setText(tr("Next Maintenance"))
        self.labels["notes"].setText(tr("Notes"))
        self.new_button.setText(tr("New Equipment"))
        self.save_button.setText(tr("Save Equipment"))
        self.delete_button.setText(tr("Delete Equipment"))
        self.wizard_button.setText("+ Agregar Equipo Nuevo (Asistente)")
        self.edit_selected_button.setText(tr("Edit Selected"))
        self.delete_selected_button.setText(tr("Delete Selected"))
        self.refresh_button.setText(tr("Refresh"))
        self.apply_setup_button.setText(tr("Apply Setup Hints"))
        self.scan_button.setText(tr("Scan Network and Serial"))
        self.use_discovery_button.setText(tr("Use Selected Device"))
        self.open_connectivity_button.setText(tr("Open Connectivity Console"))
        self.save_mapping_button.setText(tr("Save Test Mapping"))
        self.delete_mapping_button.setText(tr("Delete Selected Mapping"))
        self.last_maintenance_date.setPlaceholderText("YYYY-MM-DD")
        self.next_maintenance_date.setPlaceholderText("YYYY-MM-DD")
        self.scan_cidrs.setPlaceholderText("10.0.0.0/24")
        self.scan_ports.setPlaceholderText("5100,5000,2575,3001,4000,8080,9100")
        self.scan_host_limit.setPlaceholderText("64 or 254")
        self.setup_summary.setText(tr("Choose how the analyzer connects. The page will fill the right fields and notes for the equipment record."))
        self.scan_status.setText(tr("Run discovery to see connected network devices and serial ports."))
        self.mapping_status.setText(tr("Map analyzer result codes to LIMS tests here. Saved mappings are used when importing instrument results."))
        current_status = self.status.currentData()
        self.status.clear()
        self.status.addItem(tr("Active"), "active")
        self.status.addItem(tr("Maintenance"), "maintenance")
        self.status.addItem(tr("Out of Service"), "out_of_service")
        self.status.addItem(tr("Retired"), "retired")
        status_index = self.status.findData(current_status)
        self.status.setCurrentIndex(status_index if status_index >= 0 else 0)
        self.table.setHorizontalHeaderLabels([tr("Name"), tr("Type"), tr("Model"), tr("Serial"), tr("Location"), tr("Status"), tr("Next Maintenance"), tr("ID")])
        self.discovery_table.setHorizontalHeaderLabels([tr("Source"), tr("Device"), tr("Address"), tr("Ports"), tr("Likely Profile")])
        self.mapping_table_group.setTitle(self.mapping_profile.currentText().strip() or tr("Saved Mappings"))

    def refresh_on_show(self) -> None:
        self.refresh_equipment()
        self.refresh_mapping_choices()
        self._refresh_mapping_profile_choices()
        self.refresh_analyzer_code_choices()
        self.refresh_mappings()
        self.refresh_order_match_configs()
        self._refresh_order_match_profile_choices()

    def _on_tab_changed(self, index: int) -> None:
        self.table_group.setVisible(index in {0, 1})

    def _refresh_mapping_profile_choices(self) -> None:
        current = self.mapping_profile.currentText()
        self.mapping_profile.blockSignals(True)
        self.mapping_profile.clear()
        db_profiles = set(self.database.list_instrument_profiles())
        yaml_profiles: set[str] = set()
        try:
            yaml_profiles = {p.stem for p in _PROFILES_DIR.glob("*.yaml")}
        except Exception:
            pass
        for profile in sorted(db_profiles | yaml_profiles):
            self.mapping_profile.addItem(profile)
        self.mapping_profile.setCurrentText(current)
        self.mapping_profile.blockSignals(False)

    def _refresh_order_match_profile_choices(self) -> None:
        current = self.order_match_profile.currentText()
        self.order_match_profile.blockSignals(True)
        self.order_match_profile.clear()
        profiles: list[str] = self.database.list_instrument_profiles()
        for cfg in self.database.list_instrument_order_match_configs():
            if cfg.instrument_profile not in profiles:
                profiles.append(cfg.instrument_profile)
        profiles.sort()
        for profile in profiles:
            self.order_match_profile.addItem(profile)
        if current:
            self.order_match_profile.setCurrentText(current)
        self.order_match_profile.blockSignals(False)

    def refresh_equipment(self) -> None:
        self.equipment_records = self.database.list_equipment()
        self.table.blockSignals(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setRowCount(len(self.equipment_records))
        for row_index, record in enumerate(self.equipment_records):
            values = [
                record.name,
                record.equipment_type or "",
                self._format_model(record.manufacturer, record.model),
                record.serial_number or "",
                record.location or "",
                self._format_status(record.status),
                record.next_maintenance_date or "",
                str(record.id),
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, record.id)
                self.table.setItem(row_index, column_index, item)
        self.table.setColumnHidden(7, True)
        self.table.blockSignals(False)

    def refresh_mapping_choices(self) -> None:
        selected = self.mapping_test.currentData()
        self.mapping_test.blockSignals(True)
        self.mapping_test.clear()
        for test_id, label in self.database.list_test_choices():
            self.mapping_test.addItem(label, test_id)
        self.mapping_test.lineEdit().setPlaceholderText(tr("Search by name or code"))
        idx = self.mapping_test.findData(selected) if selected is not None else -1
        self.mapping_test.setCurrentIndex(idx)
        if idx < 0:
            self.mapping_test.lineEdit().clear()
        self.mapping_test.blockSignals(False)

    def _find_profile_yaml(self, profile: str) -> "Path | None":
        """Find the YAML profile file for a given profile ID, with fuzzy fallback."""
        if _yaml is None:
            return None
        key = profile.lower().strip()
        if not key:
            return None
        exact = _PROFILES_DIR / f"{key}.yaml"
        if exact.exists():
            return exact
        try:
            for yaml_file in sorted(_PROFILES_DIR.glob("*.yaml")):
                stem = yaml_file.stem.lower()
                if stem in key or key in stem:
                    return yaml_file
        except Exception:
            pass
        return None

    def _get_profile_codes(self, profile: str) -> list[tuple[str, str, str, str]]:
        """Return (code, name, test_code, unit) for the given profile.
        Reads from the engine YAML profile when available; falls back to ANALYZER_CODE_CHOICES.
        Both the alphabetic primary code and any numeric alias codes are included."""
        yaml_path = self._find_profile_yaml(profile)
        if yaml_path is not None:
            try:
                with open(yaml_path, encoding="utf-8") as f:
                    data = _yaml.safe_load(f)
                mapping = (data or {}).get("mapping", {})
                entries = mapping.get("test_mappings", [])
                aliases_map: dict[str, list[str]] = {
                    str(k): [str(v) for v in vs]
                    for k, vs in (mapping.get("test_code_aliases") or {}).items()
                }
                codes: list[tuple[str, str, str, str]] = []
                for e in entries:
                    if e.get("match_type") != "exact" or not e.get("pattern"):
                        continue
                    primary = str(e["pattern"]).strip()
                    name = str(e.get("canonical_assay") or "").strip()
                    unit = str(e.get("normalized_units") or "").strip()
                    component_index = e.get("component_index")
                    if component_index is not None:
                        code = f"{primary}_{component_index}"
                        codes.append((code, name, "", unit))
                    else:
                        codes.append((primary, name, "", unit))
                        for alias in aliases_map.get(primary, []):
                            alias_str = str(alias).strip()
                            if alias_str:
                                codes.append((alias_str, f"{name} ({primary})", "", unit))
                if codes:
                    return codes
            except Exception:
                pass
        profile_key = profile.lower().strip()
        return self.ANALYZER_CODE_CHOICES.get(
            profile_key,
            self.ANALYZER_CODE_CHOICES.get(
                next((k for k in self.ANALYZER_CODE_CHOICES if k in profile_key), ""), []
            ),
        )

    def refresh_analyzer_code_choices(self) -> None:
        current_code = self._mapping_raw_code_text()
        profile = self.mapping_profile.currentText().strip()
        alias_groups = self._get_alias_groups(profile)
        # Deduplicate by alias group — later entry (numeric alias) overwrites earlier (alphabetic primary)
        _by_group: dict[frozenset, tuple[str, str, str, str]] = {}
        for entry in self._get_profile_codes(profile):
            code = entry[0]
            group = alias_groups.get(code.upper(), frozenset({code.upper()}))
            _by_group[group] = entry
        choices = list(_by_group.values())
        self.mapping_raw_code.blockSignals(True)
        self.mapping_raw_code.clear()
        self.mapping_raw_code.addItem(tr("Select analyzer code"), None)
        for code, name, test_code, unit in choices:
            label = f"{code} - {name}"
            self.mapping_raw_code.addItem(
                label,
                {"code": code, "name": name, "test_code": test_code, "unit": unit},
            )
        if current_code:
            index = self.mapping_raw_code.findText(current_code, Qt.MatchFixedString)
            if index < 0:
                for item_index in range(self.mapping_raw_code.count()):
                    data = self.mapping_raw_code.itemData(item_index)
                    if isinstance(data, dict) and data.get("code") == current_code:
                        index = item_index
                        break
            if index >= 0:
                self.mapping_raw_code.setCurrentIndex(index)
            else:
                self.mapping_raw_code.setEditText(current_code)
        self.mapping_raw_code.blockSignals(False)
        self._apply_selected_analyzer_code()

    def _get_alias_groups(self, profile: str) -> dict[str, frozenset[str]]:
        """Maps each code (uppercased) to the full set of equivalent codes for that parameter."""
        yaml_path = self._find_profile_yaml(profile)
        if yaml_path is None:
            return {}
        try:
            with open(yaml_path, encoding="utf-8") as f:
                data = _yaml.safe_load(f)
            aliases_map = ((data or {}).get("mapping") or {}).get("test_code_aliases") or {}
            groups: dict[str, frozenset[str]] = {}
            for primary, aliases in aliases_map.items():
                group: frozenset[str] = frozenset(
                    {str(primary).upper()} | {str(a).upper() for a in (aliases or [])}
                )
                for code in group:
                    groups[code] = group
            return groups
        except Exception:
            return {}

    def refresh_mappings(self) -> None:
        profile = self.mapping_profile.currentText().strip()
        self.mapping_table_group.setTitle(profile or tr("Saved Mappings"))
        mappings = self.database.list_instrument_result_mappings(instrument_profile=profile)
        mapped_exact = {m.raw_code.upper() for m in mappings}
        mapped_stripped = {m.raw_code.upper().replace("%", "").replace("#", "") for m in mappings}
        alias_groups = self._get_alias_groups(profile)
        known_codes = self._get_profile_codes(profile)

        def _is_covered(code: str) -> bool:
            up = code.upper()
            if up in mapped_exact:
                return True
            if up.replace("%", "").replace("#", "") in mapped_stripped:
                return True
            return bool(alias_groups.get(up, frozenset()) & mapped_exact)

        # One entry per alias group; later entries (numeric aliases) overwrite earlier ones
        # so the numeric code is shown rather than the alphabetic primary code.
        _unmapped_by_group: dict[frozenset, tuple[str, str, str]] = {}
        for code, name, _test_code, unit in known_codes:
            if _is_covered(code):
                continue
            group = alias_groups.get(code.upper(), frozenset({code.upper()}))
            _unmapped_by_group[group] = (code, name, unit)
        unmapped_codes = list(_unmapped_by_group.values())
        self.mapping_table.setHorizontalHeaderLabels([
            tr("Analyzer Code"), tr("LIMS Test"), tr("Unit"), tr("Device"),
        ])
        self.mapping_table.setRowCount(len(mappings) + len(unmapped_codes))
        for row_index, mapping in enumerate(mappings):
            code_display = f"{mapping.raw_code} - {mapping.raw_name}" if mapping.raw_name else mapping.raw_code
            values = [
                code_display,
                f"{mapping.test_name} ({mapping.test_code})",
                mapping.unit_override or "",
                mapping.device_id or "",
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, mapping.id)
                self.mapping_table.setItem(row_index, column_index, item)
        gray = QColor(150, 150, 150)
        for i, (code, name, unit) in enumerate(unmapped_codes):
            row_index = len(mappings) + i
            code_display = f"{code} - {name}" if name else code
            for column_index, value in enumerate([code_display, tr("Not mapped"), unit, ""]):
                item = QTableWidgetItem(value)
                item.setForeground(gray)
                item.setData(Qt.UserRole, None)
                self.mapping_table.setItem(row_index, column_index, item)

    def _delete_selected_mapping(self) -> None:
        row = self.mapping_table.currentRow()
        if row < 0:
            QMessageBox.information(self, tr("No Selection"), tr("Select a mapping to delete."))
            return
        item = self.mapping_table.item(row, 0)
        mapping_id = item.data(Qt.UserRole) if item else None
        if mapping_id is None:
            return
        code = item.text() if item else ""
        confirm = QMessageBox.question(
            self,
            tr("Delete Mapping"),
            tr("Delete the mapping for analyzer code '{code}'?", code=code),
        )
        if confirm != QMessageBox.Yes:
            return
        self.database.delete_instrument_result_mapping(int(mapping_id))
        self.refresh_mappings()

    def save_equipment(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, tr("Missing Data"), tr("Equipment name is required."))
            return
        payload = self._equipment_payload()
        try:
            if self.selected_equipment_id is None:
                self.selected_equipment_id = self.database.create_equipment(payload)
            else:
                self.database.update_equipment(self.selected_equipment_id, payload)
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        self.refresh_equipment()
        self.notify_data_changed()

    def delete_selected_equipment(self) -> None:
        equipment_id = self._selected_equipment_id()
        if equipment_id is None:
            QMessageBox.information(self, tr("Missing Selection"), tr("Select equipment first."))
            return
        record = next((item for item in self.equipment_records if item.id == equipment_id), None)
        name = record.name if record else str(equipment_id)
        answer = QMessageBox.question(
            self,
            tr("Delete Equipment"),
            tr("Delete equipment '{name}'? This removes it from the local equipment list.", name=name),
        )
        if answer != QMessageBox.Yes:
            return
        self.database.delete_equipment(equipment_id)
        if self.selected_equipment_id == equipment_id:
            self.new_equipment()
        self.refresh_equipment()
        self.notify_data_changed()

    def load_selected_equipment(self) -> None:
        equipment_id = self._selected_equipment_id()
        if equipment_id is None:
            return
        record = next((item for item in self.equipment_records if item.id == equipment_id), None)
        if record is None:
            return
        self.selected_equipment_id = record.id
        self.name.setText(record.name)
        self.equipment_type.setText(record.equipment_type or "")
        self.manufacturer.setText(record.manufacturer or "")
        self.model.setText(record.model or "")
        self.serial_number.setText(record.serial_number or "")
        self.location.setText(record.location or "")
        index = self.status.findData(record.status)
        self.status.setCurrentIndex(index if index >= 0 else 0)
        self.last_maintenance_date.setText(record.last_maintenance_date or "")
        self.next_maintenance_date.setText(record.next_maintenance_date or "")
        self.notes.setPlainText(record.notes or "")
        self._fill_mapping_context(record)

    def new_equipment(self) -> None:
        self.selected_equipment_id = None
        self.name.clear()
        self.equipment_type.clear()
        self.manufacturer.clear()
        self.model.clear()
        self.serial_number.clear()
        self.location.clear()
        self.status.setCurrentIndex(0)
        self.last_maintenance_date.clear()
        self.next_maintenance_date.clear()
        self.notes.clear()

    def apply_setup_to_form(self) -> None:
        mode = self.connection_mode.currentData()
        ip = self.setup_ip.text().strip()
        port = self.setup_port.text().strip()
        serial = self.setup_serial.text().strip()
        profile = self.setup_profile.text().strip()
        notes = []
        if mode in {"network_inbound", "network_outbound"}:
            self.equipment_type.setText("Analyzer")
            if ip:
                self.location.setText(ip)
                self.scan_cidrs.setText(self._cidr_from_ip(ip))
            if port:
                self.scan_ports.setText(self._merge_csv(self.scan_ports.text(), port))
            endpoint = f"{ip}:{port}" if ip and port else port
            if mode == "network_inbound":
                notes.append(f"Connectivity: analyzer sends results to this PC on 0.0.0.0:{port or '<port>'}.")
            else:
                notes.append(f"Connectivity: this PC connects to analyzer at {endpoint or '<ip:port>'}.")
        elif mode == "serial":
            self.equipment_type.setText("Analyzer")
            if serial:
                self.location.setText(serial)
                self.serial_number.setText(self.serial_number.text() or serial)
            notes.append(f"Connectivity: serial port {serial or '<COM port>'}, common start 9600 8N1.")
        else:
            self.equipment_type.setText("Analyzer")
            notes.append("Connectivity: file drop / watched folder.")
        if profile:
            self.mapping_profile.setCurrentText(profile)
            notes.append(f"Instrument profile: {profile}.")
        self._append_notes(notes)
        self.setup_summary.setText(" ".join(notes) if notes else tr("Setup hints applied."))

    def scan_equipment(self) -> None:
        params = {
            "mode": str(self.scan_mode.currentData() or "quick"),
            "cidrs": self.scan_cidrs.text().strip(),
            "ports": self.scan_ports.text().strip(),
            "host_limit": self.scan_host_limit.text().strip(),
        }
        query = urllib.parse.urlencode({key: value for key, value in params.items() if value})
        try:
            payload = self._engine_get_json(f"/api/v1/ports/scan?{query}")
        except RuntimeError as exc:
            QMessageBox.warning(self, tr("Instrument Connectivity"), str(exc))
            return
        if not isinstance(payload, dict):
            self.scan_status.setText(tr("Instrument engine returned invalid JSON."))
            return
        self.discovery_rows = self._scan_rows(payload)
        self._render_discovery_rows()
        diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
        self.scan_status.setText(self._format_scan_status(diagnostics, len(self.discovery_rows)))

    def fill_form_from_discovery(self) -> None:
        row = self.discovery_table.currentRow()
        if row < 0 or row >= len(self.discovery_rows):
            QMessageBox.information(self, tr("Missing Selection"), tr("Select a discovered device first."))
            return
        device = self.discovery_rows[row]
        source = str(device.get("source") or "")
        address = str(device.get("address") or "")
        profile = str(device.get("profile") or "")
        if not self.name.text().strip():
            self.name.setText(str(device.get("name") or address))
        self.equipment_type.setText("Analyzer" if source in {"network", "serial"} else source.title())
        self.location.setText(address)
        if source == "serial":
            self.serial_number.setText(str(device.get("serial") or address))
        if profile:
            self.mapping_profile.setCurrentText(profile)
        self.mapping_device.setText(address)
        self._append_notes([str(device.get("note") or "")])
        self.tabs.setCurrentWidget(self.form_tab)

    def save_test_mapping(self) -> None:
        profile = self.mapping_profile.currentText().strip()
        code = self._mapping_raw_code_text()
        test_id = self.mapping_test.currentData()
        if not profile or not code or test_id is None:
            QMessageBox.warning(self, tr("Missing Data"), tr("Profile, analyzer code, and LIMS test are required."))
            return
        def _parse_int(text: str) -> int | None:
            t = text.strip()
            return int(t) if t.isdigit() else None

        def _parse_float(text: str) -> float | None:
            t = text.strip().replace(",", "")
            try:
                return float(t) if t else None
            except ValueError:
                return None

        try:
            self.database.save_instrument_result_mapping(
                instrument_profile=profile,
                device_id=self.mapping_device.text().strip(),
                raw_code=code,
                raw_name=self.mapping_raw_name.text().strip(),
                test_id=int(test_id),
                unit_override=self.mapping_unit.text().strip(),
                value_slice_start=_parse_int(self.mapping_slice_start.text()),
                value_slice_end=_parse_int(self.mapping_slice_end.text()),
                value_formula=self.mapping_multiplier.text().strip() or None,
                decimal_places=_parse_int(self.mapping_decimal_places.text()),
            )
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        self.mapping_status.setText(tr("Saved mapping for analyzer code {code}.", code=code))
        self.refresh_mappings()
        self.notify_data_changed()

    def open_connectivity_console(self) -> None:
        window = self.window()
        show_page = getattr(window, "_show_page", None)
        set_workspace = getattr(window, "_set_workspace", None)
        if callable(set_workspace):
            set_workspace("equipment", preferred_page_key="instrument_connectivity")
        elif callable(show_page):
            show_page("instrument_connectivity")

    def _launch_setup_wizard(self) -> None:
        wizard = MachineSetupWizard(self.database, parent=self)
        if wizard.exec():
            self.refresh_on_show()
            self.notify_data_changed()

    def _equipment_payload(self) -> dict[str, str]:
        return {
            "name": self.name.text(),
            "equipment_type": self.equipment_type.text(),
            "manufacturer": self.manufacturer.text(),
            "model": self.model.text(),
            "serial_number": self.serial_number.text(),
            "location": self.location.text(),
            "status": self.status.currentData(),
            "last_maintenance_date": self.last_maintenance_date.text(),
            "next_maintenance_date": self.next_maintenance_date.text(),
            "notes": self.notes.toPlainText(),
        }

    def _selected_equipment_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return self.selected_equipment_id
        item = self.table.item(row, 0)
        value = item.data(Qt.UserRole) if item is not None else None
        return int(value) if value is not None else None

    def _fill_mapping_context(self, record: EquipmentRecord) -> None:
        profile = self._profile_id_for_record(record)
        self.mapping_profile.setCurrentText(profile)
        self.mapping_device.setText(record.location or record.serial_number or record.name)

    def _clear_mapping_fields(self) -> None:
        self.mapping_device.clear()
        self.mapping_raw_name.clear()
        self.mapping_unit.clear()
        self.mapping_slice_start.clear()
        self.mapping_slice_end.clear()
        self.mapping_multiplier.clear()
        self.mapping_decimal_places.clear()
        self.mapping_test.setCurrentIndex(-1)
        self.mapping_test.lineEdit().clear()

    def _apply_selected_analyzer_code(self) -> None:
        data = self.mapping_raw_code.currentData()
        if data is None:
            return
        # Clear all fields before populating
        self.mapping_raw_name.clear()
        self.mapping_unit.clear()
        self.mapping_slice_start.clear()
        self.mapping_slice_end.clear()
        self.mapping_multiplier.clear()
        self.mapping_decimal_places.clear()
        self.mapping_test.setCurrentIndex(-1)
        self.mapping_test.lineEdit().clear()
        # Apply predefined defaults from ANALYZER_CODE_CHOICES
        if isinstance(data, dict):
            self.mapping_raw_name.setText(str(data.get("name") or ""))
            self.mapping_unit.setText(str(data.get("unit") or ""))
            test_code = str(data.get("test_code") or "")
            if test_code:
                self._select_mapping_test_by_code(test_code)
        # Look up existing saved mapping and override with its values
        profile = self.mapping_profile.currentText().strip()
        code = self._mapping_raw_code_text()
        if not profile or not code:
            return
        existing = self.database.resolve_instrument_result_mapping(
            instrument_profile=profile,
            device_id=self.mapping_device.text().strip(),
            raw_code=code,
        )
        if existing is None:
            return
        self.mapping_raw_name.setText(existing.raw_name or "")
        self.mapping_unit.setText(existing.unit_override or "")
        idx = self.mapping_test.findData(existing.test_id)
        if idx >= 0:
            self.mapping_test.setCurrentIndex(idx)
        if existing.value_slice_start is not None:
            self.mapping_slice_start.setText(str(existing.value_slice_start))
        if existing.value_slice_end is not None:
            self.mapping_slice_end.setText(str(existing.value_slice_end))
        formula = existing.value_formula or (str(existing.value_multiplier) if existing.value_multiplier is not None else "")
        self.mapping_multiplier.setText(formula)
        if existing.decimal_places is not None:
            self.mapping_decimal_places.setText(str(existing.decimal_places))

    def _select_mapping_test_by_code(self, test_code: str) -> None:
        suffix = f"({test_code})"
        for index in range(self.mapping_test.count()):
            if self.mapping_test.itemText(index).endswith(suffix):
                self.mapping_test.setCurrentIndex(index)
                return

    def _mapping_raw_code_text(self) -> str:
        text = self.mapping_raw_code.currentText().strip()
        data = self.mapping_raw_code.currentData()
        if (
            isinstance(data, dict)
            and data.get("code")
            and text in {self.mapping_raw_code.itemText(self.mapping_raw_code.currentIndex()), str(data["code"]).strip()}
        ):
            return str(data["code"]).strip()
        if " - " in text:
            text = text.split(" - ", 1)[0].strip()
        return text

    def _scan_rows(self, payload: dict[str, object]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for device in payload.get("network_devices") or []:
            if not isinstance(device, dict):
                continue
            profiles = device.get("correlated_profile_ids") if isinstance(device.get("correlated_profile_ids"), list) else []
            ip = str(device.get("ip") or "")
            ports = ", ".join(str(port) for port in device.get("open_ports") or [])
            rows.append(
                {
                    "source": "network",
                    "name": str(device.get("host") or ip),
                    "address": ip,
                    "ports": ports,
                    "profile": str(profiles[0]) if profiles else "",
                    "note": f"Discovered network endpoint {ip}; open ports: {ports or 'n/a'}.",
                }
            )
        for port in payload.get("ports") or []:
            if not isinstance(port, dict):
                continue
            port_name = str(port.get("port_name") or port.get("port_path") or "")
            rows.append(
                {
                    "source": "serial",
                    "name": str(port.get("product") or port_name),
                    "address": port_name,
                    "ports": "",
                    "profile": "",
                    "serial": str(port.get("serial_number") or ""),
                    "note": f"Discovered serial port {port_name}; {port.get('product') or 'serial device'}.",
                }
            )
        return rows

    def _render_discovery_rows(self) -> None:
        self.discovery_table.setRowCount(len(self.discovery_rows))
        for row_index, row in enumerate(self.discovery_rows):
            values = [
                str(row.get("source") or ""),
                str(row.get("name") or ""),
                str(row.get("address") or ""),
                str(row.get("ports") or ""),
                str(row.get("profile") or ""),
            ]
            for column_index, value in enumerate(values):
                self.discovery_table.setItem(row_index, column_index, QTableWidgetItem(value))
        if self.discovery_rows:
            self.discovery_table.selectRow(0)

    def _format_scan_status(self, diagnostics: dict[str, object], visible_count: int) -> str:
        warnings = diagnostics.get("warnings") if isinstance(diagnostics.get("warnings"), list) else []
        recommendations = diagnostics.get("recommendations") if isinstance(diagnostics.get("recommendations"), list) else []
        parts = [
            tr(
                "Found {count} devices. Checked {hosts} hosts on ports {ports}.",
                count=visible_count,
                hosts=diagnostics.get("candidate_hosts", 0),
                ports=", ".join(str(port) for port in diagnostics.get("ports") or []) or "n/a",
            )
        ]
        if warnings:
            parts.append(" ".join(str(item) for item in warnings))
        if recommendations:
            parts.append(" ".join(str(item) for item in recommendations))
        return " ".join(parts)

    def _engine_get_json(self, path: str) -> object:
        try:
            with urllib.request.urlopen(self.ENGINE_URL + path, timeout=45) as response:
                raw = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(tr("Instrument engine is offline or unavailable: {error}", error=str(exc))) from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(tr("Instrument engine returned invalid JSON.")) from exc

    def _append_notes(self, lines: list[str]) -> None:
        clean = [line.strip() for line in lines if line and line.strip()]
        if not clean:
            return
        existing = self.notes.toPlainText().strip()
        joined = "\n".join(clean)
        self.notes.setPlainText(f"{existing}\n{joined}".strip() if existing else joined)

    def _profile_id_for_record(self, record: EquipmentRecord) -> str:
        raw = " ".join(part for part in [record.manufacturer, record.model, record.name] if part).lower()
        if "mindray" in raw:
            return "mindray-bc30s"
        if "cor" in raw and "50" in raw:
            return "cor50-lis"
        if "urinalysis" in raw or "urine" in raw:
            return "urinalysis-com6"
        if "cm250" in raw or ("cm" in raw and "250" in raw):
            return "cm250"
        return ""

    @staticmethod
    def _cidr_from_ip(ip: str) -> str:
        parts = ip.split(".")
        if len(parts) == 4 and all(part.isdigit() for part in parts):
            return ".".join(parts[:3] + ["0/24"])
        return ""

    def _build_order_match_tab(self) -> None:
        outer = QHBoxLayout(self.order_match_tab)
        outer.setSpacing(12)

        # --- left card: order matching config ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        form_group = QGroupBox()
        self._order_match_form_group = form_group
        form_layout = QFormLayout(form_group)

        self.order_match_profile = QComboBox()
        self.order_match_profile.setEditable(True)
        self.order_match_profile.setInsertPolicy(QComboBox.NoInsert)
        self.order_match_profile.lineEdit().setPlaceholderText("mindray-bc30s")
        self.order_match_profile.currentTextChanged.connect(self._on_order_match_profile_changed)

        self.order_match_instrument_field = QComboBox()
        self.order_match_instrument_field.addItem("Sample ID — Número de muestra (OBR-3)", "sample_id")
        self.order_match_instrument_field.addItem("Accession ID (OBR-2)", "accession_id")
        self.order_match_instrument_field.addItem("Run ID / Código de barras", "analyzer_run_id")
        self.order_match_instrument_field.addItem("Patient ID", "patient_id")

        self.order_match_order_field = QComboBox()
        self.order_match_order_field.addItem("Número de orden (order_number)", "order_number")
        self.order_match_order_field.addItem("Sample ID", "sample_id")
        self.order_match_order_field.addItem("Accession ID", "accession_id")

        self.order_match_auto_import = QCheckBox("Importar resultados automáticamente")
        self.order_match_auto_import.setChecked(True)

        self.save_order_match_button = QPushButton("Guardar")
        self.save_order_match_button.clicked.connect(self.save_order_match_config)

        self.broadcast_enabled = QCheckBox("Habilitado")
        self.broadcast_enabled.setChecked(False)

        self.broadcast_enabled_left = QCheckBox("Bidireccional — enviar orden al instrumento")
        self.broadcast_enabled_left.setChecked(False)
        self.broadcast_enabled_left.toggled.connect(self.broadcast_enabled.setChecked)
        self.broadcast_enabled.toggled.connect(self.broadcast_enabled_left.setChecked)

        form_layout.addRow(QLabel(tr("Profile ID")), self.order_match_profile)
        form_layout.addRow(QLabel("El instrumento envía"), self.order_match_instrument_field)
        form_layout.addRow(QLabel("Buscar en campo de orden"), self.order_match_order_field)
        form_layout.addRow(QLabel("Auto-importar"), self.order_match_auto_import)
        form_layout.addRow(QLabel(""), self.broadcast_enabled_left)
        form_layout.addRow(self.save_order_match_button)

        self.order_match_status = QLabel()
        self.order_match_status.setWordWrap(True)

        self.order_match_table = QTableWidget(0, 4)
        self.order_match_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.order_match_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.order_match_table.horizontalHeader().setStretchLastSection(True)
        self.order_match_table.setHorizontalHeaderLabels(["Perfil", "El instrumento envía", "Campo en orden", "Auto-importar"])
        self.order_match_table.itemSelectionChanged.connect(self._load_selected_order_match)

        left_layout.addWidget(form_group)
        left_layout.addWidget(self.order_match_status)
        left_layout.addWidget(self.order_match_table, 1)

        # --- right card: bidirectional send configuration ---
        self.broadcast_group = QGroupBox('Bidireccional - Envío al instrumento')
        broadcast_layout = QFormLayout(self.broadcast_group)

        self.broadcast_protocol = QComboBox()
        self.broadcast_protocol.addItem("HL7 v2 — ORM^O01 (Orden de trabajo)", "hl7_orm")
        self.broadcast_protocol.addItem("HL7 v2 — QRY/QCK (Consulta de lista de trabajo)", "hl7_worklist")
        self.broadcast_protocol.addItem("ASTM E1394 (LIS1-A)", "astm")
        self.broadcast_protocol.addItem("ASTM LIS2-A2", "astm_lis2")

        self.broadcast_encoding = QComboBox()
        self.broadcast_encoding.addItem("ASCII (estándar)", "ascii")
        self.broadcast_encoding.addItem("ISO-8859-1 / Latin-1 (acentos)", "latin1")
        self.broadcast_encoding.addItem("UTF-8", "utf8")

        self.broadcast_patient_id = QCheckBox("ID del paciente")
        self.broadcast_patient_id.setChecked(True)
        self.broadcast_patient_name = QCheckBox("Nombre del paciente")
        self.broadcast_patient_name.setChecked(True)
        self.broadcast_dob = QCheckBox("Fecha de nacimiento")
        self.broadcast_dob.setChecked(True)
        self.broadcast_age = QCheckBox("Edad")
        self.broadcast_age.setChecked(True)
        self.broadcast_sex = QCheckBox("Sexo")
        self.broadcast_sex.setChecked(True)
        self.broadcast_doctor = QCheckBox("Médico")
        self.broadcast_doctor.setChecked(True)

        fields_widget = QWidget()
        fields_layout = QVBoxLayout(fields_widget)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.setSpacing(4)
        for cb in [
            self.broadcast_patient_id,
            self.broadcast_patient_name,
            self.broadcast_dob,
            self.broadcast_age,
            self.broadcast_sex,
            self.broadcast_doctor,
        ]:
            fields_layout.addWidget(cb)

        self.save_broadcast_button = QPushButton("Guardar configuración bidireccional")
        self.save_broadcast_button.clicked.connect(self.save_broadcast_config)

        broadcast_layout.addRow(QLabel("Estado"), self.broadcast_enabled)
        broadcast_layout.addRow(QLabel("Protocolo"), self.broadcast_protocol)
        broadcast_layout.addRow(QLabel("Codificación"), self.broadcast_encoding)
        broadcast_layout.addRow(QLabel("Campos a enviar"), fields_widget)
        broadcast_layout.addRow(self.save_broadcast_button)

        self.broadcast_status = QLabel()
        self.broadcast_status.setWordWrap(True)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.broadcast_group)
        right_layout.addWidget(self.broadcast_status)
        right_layout.addStretch(1)

        outer.addWidget(left_widget, 3)
        outer.addWidget(right_widget, 2)

    def save_order_match_config(self) -> None:
        profile = self.order_match_profile.currentText().strip()
        if not profile:
            QMessageBox.warning(self, tr("Missing Data"), "Se requiere el Profile ID.")
            return
        instrument_field = str(self.order_match_instrument_field.currentData() or "sample_id")
        order_field = str(self.order_match_order_field.currentData() or "order_number")
        self.database.save_instrument_order_match(
            profile, instrument_field, order_field,
            auto_import=self.order_match_auto_import.isChecked(),
            broadcast_enabled=self.broadcast_enabled.isChecked(),
            broadcast_protocol=str(self.broadcast_protocol.currentData() or "hl7_orm"), broadcast_encoding=str(self.broadcast_encoding.currentData() or "ascii"),
            broadcast_patient_id=self.broadcast_patient_id.isChecked(),
            broadcast_patient_name=self.broadcast_patient_name.isChecked(),
            broadcast_dob=self.broadcast_dob.isChecked(),
            broadcast_age=self.broadcast_age.isChecked(),
            broadcast_sex=self.broadcast_sex.isChecked(),
            broadcast_doctor=self.broadcast_doctor.isChecked(),
        )
        self.order_match_status.setText(f"Guardado: '{profile}' envía {instrument_field} → buscar en {order_field}.")
        self.refresh_order_match_configs()

    def save_broadcast_config(self) -> None:
        profile = self.order_match_profile.currentText().strip()
        if not profile:
            QMessageBox.warning(self, tr("Missing Data"), "Se requiere el Profile ID.")
            return
        instrument_field = str(self.order_match_instrument_field.currentData() or "sample_id")
        order_field = str(self.order_match_order_field.currentData() or "order_number")
        self.database.save_instrument_order_match(
            profile, instrument_field, order_field,
            auto_import=self.order_match_auto_import.isChecked(),
            broadcast_enabled=self.broadcast_enabled.isChecked(),
            broadcast_protocol=str(self.broadcast_protocol.currentData() or "hl7_orm"), broadcast_encoding=str(self.broadcast_encoding.currentData() or "ascii"),
            broadcast_patient_id=self.broadcast_patient_id.isChecked(),
            broadcast_patient_name=self.broadcast_patient_name.isChecked(),
            broadcast_dob=self.broadcast_dob.isChecked(),
            broadcast_age=self.broadcast_age.isChecked(),
            broadcast_sex=self.broadcast_sex.isChecked(),
            broadcast_doctor=self.broadcast_doctor.isChecked(),
        )
        status = "habilitado" if self.broadcast_enabled.isChecked() else "deshabilitado"
        self.broadcast_status.setText(f"Bidireccional {status} para '{profile}'.")
        self.refresh_order_match_configs()

    def refresh_order_match_configs(self) -> None:
        configs = self.database.list_instrument_order_match_configs()
        self._order_match_configs = configs
        _instrument_labels = {
            "sample_id": "Sample ID",
            "accession_id": "Accession ID",
            "analyzer_run_id": "Run ID / Barcode",
            "patient_id": "Patient ID",
        }
        _order_labels = {
            "order_number": "Número de orden",
            "sample_id": "Sample ID",
            "accession_id": "Accession ID",
        }
        self.order_match_table.setRowCount(len(configs))
        for row_index, cfg in enumerate(configs):
            values = [
                cfg.instrument_profile,
                _instrument_labels.get(cfg.instrument_field, cfg.instrument_field),
                _order_labels.get(cfg.order_field, cfg.order_field),
                "Sí" if cfg.auto_import else "No",
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, cfg.instrument_profile)
                self.order_match_table.setItem(row_index, col_index, item)

    def _load_selected_order_match(self) -> None:
        row = self.order_match_table.currentRow()
        configs = getattr(self, "_order_match_configs", [])
        if row < 0 or row >= len(configs):
            return
        cfg = configs[row]
        self.order_match_profile.blockSignals(True)
        self.order_match_profile.setCurrentText(cfg.instrument_profile)
        self.order_match_profile.blockSignals(False)
        index = self.order_match_instrument_field.findData(cfg.instrument_field)
        if index >= 0:
            self.order_match_instrument_field.setCurrentIndex(index)
        index = self.order_match_order_field.findData(cfg.order_field)
        if index >= 0:
            self.order_match_order_field.setCurrentIndex(index)
        self.order_match_auto_import.setChecked(bool(cfg.auto_import))
        self.broadcast_enabled.setChecked(bool(cfg.broadcast_enabled))
        self.broadcast_enabled_left.setChecked(bool(cfg.broadcast_enabled))
        lang_idx = self.broadcast_protocol.findData(cfg.broadcast_protocol or "hl7_orm")
        if lang_idx >= 0:
            self.broadcast_protocol.setCurrentIndex(lang_idx if lang_idx >= 0 else 0); enc_idx = self.broadcast_encoding.findData(cfg.broadcast_encoding or "ascii"); self.broadcast_encoding.setCurrentIndex(enc_idx if enc_idx >= 0 else 0)
        self.broadcast_patient_id.setChecked(bool(cfg.broadcast_patient_id))
        self.broadcast_patient_name.setChecked(bool(cfg.broadcast_patient_name))
        self.broadcast_dob.setChecked(bool(cfg.broadcast_dob))
        self.broadcast_age.setChecked(bool(cfg.broadcast_age))
        self.broadcast_sex.setChecked(bool(cfg.broadcast_sex))
        self.broadcast_doctor.setChecked(bool(cfg.broadcast_doctor))

    def _on_order_match_profile_changed(self, text: str) -> None:
        profile_id = text.strip()
        cfg = self.database.get_instrument_order_match(profile_id) if profile_id else None
        if cfg is None:
            self.order_match_instrument_field.setCurrentIndex(0)
            self.order_match_order_field.setCurrentIndex(0)
            self.order_match_auto_import.setChecked(True)
            self.broadcast_enabled.setChecked(False)
            self.broadcast_enabled_left.setChecked(False)
            self.broadcast_protocol.setCurrentIndex(0)
            self.broadcast_encoding.setCurrentIndex(0)
            self.broadcast_patient_id.setChecked(True)
            self.broadcast_patient_name.setChecked(True)
            self.broadcast_dob.setChecked(True)
            self.broadcast_age.setChecked(True)
            self.broadcast_sex.setChecked(True)
            self.broadcast_doctor.setChecked(True)
            return
        idx = self.order_match_instrument_field.findData(cfg.instrument_field)
        if idx >= 0:
            self.order_match_instrument_field.setCurrentIndex(idx)
        idx = self.order_match_order_field.findData(cfg.order_field)
        if idx >= 0:
            self.order_match_order_field.setCurrentIndex(idx)
        self.order_match_auto_import.setChecked(bool(cfg.auto_import))
        self.broadcast_enabled.setChecked(bool(cfg.broadcast_enabled))
        self.broadcast_enabled_left.setChecked(bool(cfg.broadcast_enabled))
        lang_idx = self.broadcast_protocol.findData(cfg.broadcast_protocol or "hl7_orm")
        if lang_idx >= 0:
            self.broadcast_protocol.setCurrentIndex(lang_idx)
        enc_idx = self.broadcast_encoding.findData(cfg.broadcast_encoding or "ascii")
        if enc_idx >= 0:
            self.broadcast_encoding.setCurrentIndex(enc_idx)
        self.broadcast_patient_id.setChecked(bool(cfg.broadcast_patient_id))
        self.broadcast_patient_name.setChecked(bool(cfg.broadcast_patient_name))
        self.broadcast_dob.setChecked(bool(cfg.broadcast_dob))
        self.broadcast_age.setChecked(bool(cfg.broadcast_age))
        self.broadcast_sex.setChecked(bool(cfg.broadcast_sex))
        self.broadcast_doctor.setChecked(bool(cfg.broadcast_doctor))

    @staticmethod
    def _merge_csv(existing: str, value: str) -> str:
        values = [item.strip() for item in existing.split(",") if item.strip()]
        if value and value not in values:
            values.append(value)
        return ", ".join(values)

    @staticmethod
    def _format_model(manufacturer: str | None, model: str | None) -> str:
        parts = [part for part in [manufacturer, model] if part]
        return " / ".join(parts)

    @staticmethod
    def _format_status(status: str) -> str:
        return tr(
            {
                "active": "Active",
                "maintenance": "Maintenance",
                "out_of_service": "Out of Service",
                "retired": "Retired",
            }.get(status, status)
        )

