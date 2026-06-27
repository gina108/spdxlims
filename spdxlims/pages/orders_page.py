from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from typing import Iterator

import sqlite3
from datetime import datetime

from spdxlims import instrument_broadcast

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QTextDocument
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QSizePolicy,
    QWidget,
)

from spdxlims.database import Database, OrderSummaryRecord, ResultEntryRecord
from spdxlims.deployment import DeploymentService
from spdxlims.label_printer_client import LabelPrinterClient, LabelPrinterError
from spdxlims.patient_dialog import PatientDialog as SharedPatientDialog
from spdxlims.patient_service import PatientService
from spdxlims.order_service import OrderService
from spdxlims.order_excel import read_order_workbook_rows, write_order_import_template
from spdxlims.result_service import ResultService
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.sat_catalogs import REGIMEN_FISCAL_OPTIONS, USO_CFDI_OPTIONS

from spdxlims.pages.order_patient_dialog import PatientDialog
from spdxlims.pages.order_doctor_dialog import DoctorDialog
from spdxlims.pages.order_client_dialog import ClientDialog
from spdxlims.pages.order_results_dialog import OrderResultsDialog
from spdxlims.pages.order_labels_dialog import OrderLabelsDialog


ORDER_ACTION_BUTTON_WIDTH = 110
ORDER_LIST_COLUMNS: list[tuple[str, str]] = [
    ("order_number", "Number"),
    ("patient_name", "Patient"),
    ("status", "Status"),
    ("created_at", "Created"),
]


class OrdersPage(DataAwarePage):
    def __init__(self, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__()
        self.database = database
        self.deployment_service = deployment_service
        self.patient_service = PatientService(database, deployment_service)
        self.order_service = OrderService(database, deployment_service)
        self.selected_items: list[dict[str, object]] = []
        self.recent_order_records: list[OrderSummaryRecord] = []
        self.edit_order_id: int | str | None = None

        self.setObjectName("ordersPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self.top_controls = self._build_top_controls()
        root.addWidget(self.top_controls)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.order_form_panel = self._build_order_form()
        self.order_form_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.recent_orders_panel = self._build_recent_orders()
        self.recent_orders_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cards.addWidget(self.order_form_panel, 5)
        cards.addWidget(self.recent_orders_panel, 4)
        root.addLayout(cards, 1)
        self._doctor_choices: list[tuple[int | str, str]] = []
        self._client_choices: list[tuple[int | str, str]] = []

        self.retranslate_ui()
        self.refresh_page_data()
        self.populate_next_order_number()

    def _build_card(self, object_name: str, title: str) -> tuple[QFrame, QVBoxLayout, QLabel]:
        card = QFrame()
        card.setObjectName(object_name)
        card.setProperty("class", "orderCard")
        card.setFrameShape(QFrame.NoFrame)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("orderCardTitle")
        layout.addWidget(title_label)
        return card, layout, title_label

    def _build_field_block(self, label_widget: QLabel, field: QWidget) -> QWidget:
        block = QWidget()
        block.setProperty("class", "fieldBlock")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        layout.addWidget(label_widget)
        layout.addWidget(field)
        return block

    def _build_top_controls(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("orderTopControls")
        bar.setProperty("class", "orderCard")
        layout = QGridLayout(bar)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(6)

        self.form_labels: dict[str, QLabel] = {}
        self.order_number = QLineEdit()
        self.order_number.setReadOnly(True)
        self.status = QComboBox()
        self.status.setMinimumWidth(150)
        self.scan_input = QLineEdit()
        self.scan_input.returnPressed.connect(self.open_scanned_order)

        for key, field in (
            ("order_number", self.order_number),
            ("status", self.status),
            ("scan", self.scan_input),
        ):
            label = QLabel()
            self.form_labels[key] = label
            layout.addWidget(self._build_field_block(label, field), 0, len(self.form_labels) - 1)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 2)
        return bar

    def _build_order_form(self) -> QWidget:
        self.form_group, layout, self.current_order_title = self._build_card("orderCurrentCard", "Orden actual")
        self.form_group.setObjectName('orderFormShell')

        self.form = QFormLayout()
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(8)
        self.form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        _BTN_W = 130

        self.patient_combo = QComboBox()
        self.patient_combo.setMinimumWidth(210)
        self.add_patient_button = QPushButton()
        self.add_patient_button.setProperty("class", "secondaryButton")
        self.add_patient_button.setFixedWidth(_BTN_W)
        self.add_patient_button.clicked.connect(self.open_patient_dialog)
        patient_row = QWidget()
        patient_row.setStyleSheet("background: transparent;")
        patient_row_layout = QHBoxLayout(patient_row)
        patient_row_layout.setContentsMargins(0, 0, 0, 0)
        patient_row_layout.setSpacing(12)
        patient_row_layout.addWidget(self.patient_combo, 1)
        patient_row_layout.addWidget(self.add_patient_button, 0)

        self.doctor_input = QLineEdit()
        self.doctor_input.setMinimumWidth(210)
        doctor_row = QWidget()
        doctor_row.setStyleSheet("background: transparent;")
        doctor_row_layout = QHBoxLayout(doctor_row)
        doctor_row_layout.setContentsMargins(0, 0, 0, 0)
        doctor_row_layout.setSpacing(0)
        doctor_row_layout.addWidget(self.doctor_input, 1)
        doctor_row_layout.addSpacing(_BTN_W + 12)

        self.client_combo = QComboBox()
        self.client_combo.setMinimumWidth(210)
        client_row = QWidget()
        client_row.setStyleSheet("background: transparent;")
        client_row_layout = QHBoxLayout(client_row)
        client_row_layout.setContentsMargins(0, 0, 0, 0)
        client_row_layout.setSpacing(0)
        client_row_layout.addWidget(self.client_combo, 1)
        client_row_layout.addSpacing(_BTN_W + 12)

        self.test_combo = QComboBox()
        self.panel_combo = QComboBox()
        self.test_combo.setMinimumWidth(210)
        self.panel_combo.setMinimumWidth(210)
        self._configure_searchable_combo(self.test_combo)
        self._configure_searchable_combo(self.panel_combo)
        self.add_test_button = QPushButton()
        self.add_test_button.setProperty("class", "secondaryButton")
        self.add_test_button.setFixedWidth(_BTN_W)
        self.add_test_button.clicked.connect(self.add_selected_test)
        self.add_panel_button = QPushButton()
        self.add_panel_button.setProperty("class", "secondaryButton")
        self.add_panel_button.setFixedWidth(_BTN_W)
        self.add_panel_button.clicked.connect(self.add_selected_panel)
        self.test_row = QWidget()
        self.test_row.setStyleSheet("background: transparent;")
        test_row_layout = QHBoxLayout(self.test_row)
        test_row_layout.setContentsMargins(0, 0, 0, 0)
        test_row_layout.setSpacing(12)
        test_row_layout.addWidget(self.test_combo, 1)
        test_row_layout.addWidget(self.add_test_button, 0)
        panel_row = QWidget()
        panel_row.setStyleSheet("background: transparent;")
        panel_row_layout = QHBoxLayout(panel_row)
        panel_row_layout.setContentsMargins(0, 0, 0, 0)
        panel_row_layout.setSpacing(12)
        panel_row_layout.addWidget(self.panel_combo, 1)
        panel_row_layout.addWidget(self.add_panel_button, 0)
        self.remove_button = QPushButton()
        self.remove_button.setProperty("class", "secondaryButton")
        self.remove_button.clicked.connect(self.remove_selected_test)

        self._add_form_row("patient", patient_row)
        self._add_form_row("doctor", doctor_row)
        self._add_form_row("client", client_row)
        self._add_form_row("test", self.test_row)
        self._add_form_row("panel", panel_row)
        layout.addLayout(self.form)

        self.selected_group = QWidget()
        self.selected_group.setObjectName('orderSelectedShell')
        selected_layout = QVBoxLayout(self.selected_group)
        selected_layout.setContentsMargins(0, 0, 0, 0)
        selected_layout.setSpacing(0)
        self.selected_stack = QStackedWidget()
        self.selected_stack.setObjectName("selectedPanelsStack")
        self.empty_panels_state = self._build_empty_panels_state()
        self.selected_table = QTableWidget(0, 2)
        self.selected_table.setObjectName("selectedPanelsTable")
        self.selected_panels: list[dict[str, object]] = []
        self.selected_table.itemChanged.connect(self._handle_selected_table_item_changed)
        self.selected_table.horizontalHeader().setStretchLastSection(False)
        self.selected_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.selected_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.selected_table.setMinimumHeight(170)
        self.selected_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.selected_stack.addWidget(self.empty_panels_state)
        self.selected_stack.addWidget(self.selected_table)
        selected_layout.addWidget(self.selected_stack)
        layout.addWidget(self.selected_group, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.save_button = QPushButton()
        self.save_button.setProperty("class", "primaryButton")
        self.save_button.clicked.connect(self.save_order)
        self.save_and_print_labels_button = QPushButton()
        self.save_and_print_labels_button.setProperty("class", "secondaryButton")
        self.save_and_print_labels_button.clicked.connect(self.save_and_print_labels)
        self.print_receipt_button = QPushButton()
        self.print_receipt_button.setProperty("class", "secondaryButton")
        self.print_receipt_button.clicked.connect(self.print_order_receipt)
        self.cancel_edit_button = QPushButton()
        self.cancel_edit_button.setProperty("class", "secondaryButton")
        self.cancel_edit_button.clicked.connect(self.clear_order_form)
        self.cancel_edit_button.setVisible(False)
        actions.addStretch(1)
        actions.addWidget(self.cancel_edit_button)
        actions.addWidget(self.remove_button)
        actions.addWidget(self.save_and_print_labels_button)
        actions.addWidget(self.print_receipt_button)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)

        return self.form_group

    def _build_recent_orders(self) -> QWidget:
        self.recent_group, layout, self.recent_orders_title = self._build_card("recentOrdersGroup", "Órdenes recientes")
        self.recent_group.setObjectName("recentOrdersGroup")
        self.helper = QLabel()
        self.helper.setObjectName("ordersHelper")
        self.helper.setWordWrap(True)
        self.scan_button = QPushButton()
        self.scan_button.setProperty("class", "secondaryButton")
        self.scan_button.clicked.connect(self.open_scanned_order)
        self.orders_table = QTableWidget(0, len(ORDER_LIST_COLUMNS))
        self.orders_table.setObjectName("recentOrdersTable")
        self.orders_table.horizontalHeader().setStretchLastSection(True)
        self.orders_table.setMinimumHeight(230)
        self.orders_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.orders_table.setSelectionMode(QTableWidget.SingleSelection)
        self.orders_table.cellDoubleClicked.connect(self.handle_recent_order_double_click)
        layout.addWidget(self.helper)
        layout.addWidget(self.orders_table)

        actions = QGridLayout()
        actions.setHorizontalSpacing(8)
        actions.setVerticalSpacing(8)
        self.edit_order_button = QPushButton()
        self.edit_order_button.setProperty("class", "secondaryButton")
        self.edit_order_button.clicked.connect(self.open_selected_order_for_edit)
        self.label_button = QPushButton()
        self.label_button.setProperty("class", "secondaryButton")
        self.label_button.clicked.connect(self.open_order_labels_dialog)
        self.result_button = QPushButton()
        self.result_button.setProperty("class", "primaryButton")
        self.result_button.clicked.connect(self.open_order_results_dialog)
        self.order_template_button = QPushButton()
        self.order_template_button.setProperty("class", "secondaryButton")
        self.order_template_button.clicked.connect(self.save_order_import_template)
        self.import_orders_button = QPushButton()
        self.import_orders_button.setProperty("class", "secondaryButton")
        self.import_orders_button.clicked.connect(self.import_orders_from_excel)
        self.import_and_print_button = QPushButton()
        self.import_and_print_button.setProperty("class", "primaryButton")
        self.import_and_print_button.setStyleSheet(
            "QPushButton { background-color: #bd93f9; color: #1a1a1a; border: none; font-weight: 800; }"
            "QPushButton:hover { background-color: #caa9fa; }"
            "QPushButton:pressed { background-color: #a77de6; }"
        )
        self.import_and_print_button.clicked.connect(self.import_and_print_from_excel)
        actions.addWidget(self.result_button, 0, 0, 1, 2)
        actions.addWidget(self.edit_order_button, 1, 0, 1, 2)
        actions.addWidget(self.label_button, 2, 0, 1, 2)
        actions.addWidget(self.order_template_button, 3, 0, 1, 2)
        actions.addWidget(self.import_orders_button, 4, 0)
        actions.addWidget(self.import_and_print_button, 4, 1)
        actions.setColumnStretch(0, 1)
        actions.setColumnStretch(1, 1)
        layout.addLayout(actions)
        return self.recent_group

    def _add_form_row(self, key: str, field: QWidget) -> None:
        label = QLabel()
        self.form_labels[key] = label
        self.form.addRow(label, field)

    def _build_empty_panels_state(self) -> QWidget:
        empty = QWidget()
        empty.setObjectName("emptyPanelsState")
        layout = QVBoxLayout(empty)
        layout.setContentsMargins(18, 22, 18, 22)
        layout.setSpacing(6)
        layout.addStretch(1)
        icon = QLabel("+")
        icon.setObjectName("emptyPanelsIcon")
        icon.setAlignment(Qt.AlignCenter)
        title = QLabel("No hay paneles agregados")
        title.setObjectName("emptyPanelsTitle")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel("Agregue un panel para comenzar")
        subtitle.setObjectName("emptyPanelsSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon, 0, Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)
        return empty

    def retranslate_ui(self) -> None:

        if self.order_service.uses_server_backend():
            self.helper.setText(tr("Scan or select a shared order to edit it from the server. Double-click a recent order to load it into the form."))
        else:
            self.helper.setText(tr("Enter or scan an order barcode, or double-click an order to enter results."))
        self.current_order_title.setText("Orden actual")
        self.recent_orders_title.setText("Órdenes recientes")
        self.form_labels["scan"].setText("Escanear Código")
        self.scan_input.setPlaceholderText(tr("Scan barcode or search by order number / patient name"))
        self.scan_button.setText("Abrir Código")
        self.add_patient_button.setText(tr("New Patient"))
        self.add_test_button.setText(tr("Add Test"))
        self.add_panel_button.setText(tr("Add Panel"))
        self.remove_button.setText("Quitar Panel")
        self.save_and_print_labels_button.setText("Guardar e imprimir etiquetas")
        self.print_receipt_button.setText("Imprimir recibo")
        self.selected_table.setHorizontalHeaderLabels([tr("Panel"), tr("Outsourced")])
        self.edit_order_button.setText("Editar Orden Seleccionada")
        self.label_button.setText("Imprimir Etiquetas")
        self.result_button.setText("Agregar Resultado")
        self.order_template_button.setText(tr("Order Template"))
        self.import_orders_button.setText(tr("Import Orders"))
        self.import_and_print_button.setText("Importar y imprimir etiquetas")
        self.form_labels["order_number"].setText("Número de Orden")
        self.form_labels["status"].setText("Estado")
        self.form_labels["patient"].setText(tr("Patient"))
        self.form_labels["doctor"].setText(tr("Doctor"))
        self.form_labels["client"].setText(tr("Client"))
        self.form_labels["test"].setText(tr("Individual Test"))
        self.form_labels["panel"].setText(tr("Panel"))
        self._set_test_row_visible(False)
        current_status = self.status.currentData()
        self.status.clear()
        if self.order_service.uses_server_backend():
            self.status.addItem(tr("Registered"), "registered")
            self.status.addItem(tr("Collected"), "collected")
            self.status.addItem(tr("In Lab"), "in_lab")
            self.status.addItem(tr("Completed"), "completed")
            self.status.addItem(tr("Reported"), "reported")
            self.status.addItem(tr("Amended"), "amended")
        else:
            self.status.addItem("Borrador", "draft")
            self.status.addItem(tr("In Progress"), "in_progress")
        status_index = self.status.findData(current_status)
        self.status.setCurrentIndex(status_index if status_index >= 0 else 0)
        self.selected_table.setHorizontalHeaderLabels([tr("Panel"), tr("Outsourced")])
        self.orders_table.setHorizontalHeaderLabels(["Número", "Paciente", "Estado", "Fecha"])
        self._apply_orders_table_column_visibility()
        self.refresh_choices()
        self.refresh_recent_orders()
        self._refresh_selected_table()
        self._update_form_mode()

    def refresh_on_show(self) -> None:
        self.refresh_page_data()
        QTimer.singleShot(0, self.scan_input.setFocus)

    def refresh_page_data(self) -> None:
        self.refresh_choices()
        self._apply_orders_table_column_visibility()
        self.refresh_recent_orders()

    def refresh_choices(self) -> None:
        self.set_combo_items(
            self.patient_combo,
            [(label, patient_id) for patient_id, label in self.patient_service.list_patient_choices()],
            placeholder=tr("Select patient"),
            selected_data=self.patient_combo.currentData(),
        )
        self._doctor_choices = [(doctor_id, label) for doctor_id, label in self.order_service.list_doctor_choices()]
        _doctor_names = [label for _, label in self._doctor_choices]
        _doctor_completer = QCompleter(_doctor_names, self.doctor_input)
        _doctor_completer.setCaseSensitivity(Qt.CaseInsensitive)
        _doctor_completer.setFilterMode(Qt.MatchContains)
        self.doctor_input.setCompleter(_doctor_completer)
        self._client_choices = [(client_id, label) for client_id, label in self.order_service.list_client_choices()]
        selected_client_id = self.client_combo.currentData()
        self.set_combo_items(
            self.client_combo,
            [(label, client_id) for client_id, label in self._client_choices],
            placeholder=tr("Select client"),
            selected_data=selected_client_id,
        )
        self._set_searchable_combo_items(
            self.test_combo,
            [(label, test_id) for test_id, label in self.order_service.list_test_choices()],
            placeholder=tr("Select test"),
            selected_data=self.test_combo.currentData(),
        )
        self._set_searchable_combo_items(
            self.panel_combo,
            [(label, panel_id) for panel_id, label in self.order_service.list_panel_choices()],
            placeholder=tr("Select panel"),
            selected_data=self.panel_combo.currentData(),
        )

    def _configure_searchable_combo(self, combo: QComboBox) -> None:
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.completer().setCompletionMode(QCompleter.PopupCompletion)
        combo.completer().setFilterMode(Qt.MatchContains)
        combo.completer().setCaseSensitivity(Qt.CaseInsensitive)
        combo.completer().activated.connect(lambda text, target=combo: self._sync_searchable_combo_text(target, text))
        combo.lineEdit().editingFinished.connect(lambda target=combo: self._sync_searchable_combo_text(target, target.currentText()))

    def _set_searchable_combo_items(
        self,
        combo: QComboBox,
        items: list[tuple[str, int | str]],
        *,
        placeholder: str,
        selected_data: int | str | None,
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        for label, data in items:
            combo.addItem(label, data)
        combo.lineEdit().setPlaceholderText(placeholder)
        selected_index = combo.findData(selected_data) if selected_data is not None else -1
        combo.setCurrentIndex(selected_index if selected_index >= 0 else -1)
        if selected_index < 0:
            combo.lineEdit().clear()
        combo.blockSignals(False)

    def _sync_searchable_combo_text(self, combo: QComboBox, text: str) -> None:
        match_index = combo.findText(text, Qt.MatchFixedString)
        combo.setCurrentIndex(match_index if match_index >= 0 else -1)

    def refresh_recent_orders(self) -> None:
        self.recent_order_records = self.order_service.list_recent_orders()
        rows = [
            (
                record.order_number,
                record.patient_name,
                "",
                self._format_recent_order_date(record.created_at),
            )
            for record in self.recent_order_records
        ]
        self.set_table_rows(self.orders_table, rows)
        for row_index, record in enumerate(self.recent_order_records):
            self.orders_table.setCellWidget(row_index, 2, self.build_order_status_indicator(record.status, all_results_entered=record.all_results_entered))
            date_item = self.orders_table.item(row_index, 3)
            if date_item is not None:
                date_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.orders_table.setColumnWidth(0, 92)
        self.orders_table.setColumnWidth(1, 170)
        self.orders_table.setColumnWidth(2, 52)
        self.orders_table.setColumnWidth(3, 88)
        self._apply_orders_table_column_visibility()

    @staticmethod
    def _display_status(status: str | None) -> str:
        labels = {
            "draft": "Borrador",
            "in_progress": "En progreso",
            "registered": "Registrada",
            "collected": "Recolectada",
            "in_lab": "En laboratorio",
            "completed": "Completada",
            "reported": "Reportada",
            "amended": "Corregida",
        }
        return labels.get(str(status or "").strip(), str(status or ""))

    def _visible_orders_list_columns(self) -> list[str]:
        ui_state = self.database.get_ui_state()
        stored = ui_state.get("orders_list_visible_columns")
        default_columns = [key for key, _label in ORDER_LIST_COLUMNS]
        visible = [
            key for key in stored
            if isinstance(key, str) and key in default_columns
        ] if isinstance(stored, list) else default_columns
        return visible or [default_columns[0]]

    def _apply_orders_table_column_visibility(self) -> None:
        visible = set(self._visible_orders_list_columns())
        for column_index, (key, _label) in enumerate(ORDER_LIST_COLUMNS):
            self.orders_table.setColumnHidden(column_index, key not in visible)

    @staticmethod
    def _format_recent_order_date(raw_value: str | None) -> str:
        value = str(raw_value or "").strip()
        if not value:
            return ""
        date_part = value.replace("T", " ").split(" ", 1)[0]
        chunks = date_part.split("-")
        if len(chunks) == 3:
            year, month, day = chunks
            return f"{day}-{month}-{year}"
        return date_part

    def open_patient_dialog(self) -> None:
        dialog = SharedPatientDialog(self.patient_service, self)
        if dialog.exec() == QDialog.Accepted and dialog.patient_id is not None:
            self.refresh_page_data()
            index = self.patient_combo.findData(dialog.patient_id)
            if index >= 0:
                self.patient_combo.setCurrentIndex(index)
            self.notify_data_changed()

    def open_doctor_dialog(self) -> None:
        if self.order_service.uses_server_backend():
            QMessageBox.information(
                self,
                tr("Not Available Yet"),
                tr("Doctor maintenance is not available in server mode yet. Use the server admin tools for shared providers."),
            )
            return
        dialog = DoctorDialog(self.database, self)
        if dialog.exec() == QDialog.Accepted and dialog.doctor_id is not None:
            self.refresh_page_data()
            doctor = self.database.get_doctor(dialog.doctor_id)
            self.doctor_input.setText(doctor.full_name if doctor is not None else dialog.full_name.text().strip())
            self.notify_data_changed()

    def edit_selected_doctor(self) -> None:
        if self.order_service.uses_server_backend():
            QMessageBox.information(
                self,
                tr("Not Available Yet"),
                tr("Doctor maintenance is not available in server mode yet. Use the server admin tools for shared providers."),
            )
            return
        doctor_id = self._resolve_doctor_id_from_input(create_if_missing=False)
        if doctor_id is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a doctor first."))
            return
        dialog = DoctorDialog(self.database, self, doctor_id=doctor_id)
        if dialog.exec() == QDialog.Accepted and dialog.doctor_id is not None:
            self.refresh_page_data()
            doctor = self.database.get_doctor(dialog.doctor_id)
            self.doctor_input.setText(doctor.full_name if doctor is not None else dialog.full_name.text().strip())
            self.notify_data_changed()

    def open_client_dialog(self) -> None:
        if self.order_service.uses_server_backend():
            QMessageBox.information(
                self,
                tr("Not Available Yet"),
                tr("Client maintenance is not available in server mode yet. Use the server admin tools for shared providers."),
            )
            return
        dialog = ClientDialog(self.database, self)
        if dialog.exec() == QDialog.Accepted and dialog.client_id is not None:
            self.refresh_page_data()
            index = self.client_combo.findData(dialog.client_id)
            if index >= 0:
                self.client_combo.setCurrentIndex(index)
            self.notify_data_changed()

    def edit_selected_client(self) -> None:
        if self.order_service.uses_server_backend():
            QMessageBox.information(
                self,
                tr("Not Available Yet"),
                tr("Client maintenance is not available in server mode yet. Use the server admin tools for shared providers."),
            )
            return
        client_id = self.client_combo.currentData()
        if client_id is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a client first."))
            return
        dialog = ClientDialog(self.database, self, client_id=client_id)
        if dialog.exec() == QDialog.Accepted and dialog.client_id is not None:
            self.refresh_page_data()
            index = self.client_combo.findData(dialog.client_id)
            if index >= 0:
                self.client_combo.setCurrentIndex(index)
            self.notify_data_changed()

    def open_scanned_order(self) -> None:
        query = self.scan_input.text().strip()
        if not query:
            QMessageBox.warning(self, tr("Missing Data"), tr("Enter or scan an order barcode."))
            return
        if self.order_service.uses_server_backend():
            try:
                record = self.order_service.get_order_detail_by_number(query)
            except RuntimeError as exc:
                QMessageBox.warning(self, tr("Missing Selection"), str(exc))
                return
            self._load_order_record(record)
            self.scan_input.clear()
            QMessageBox.information(self, tr("Order"), tr("Shared order loaded for editing."))
            return
        lookup = self.database.find_order_by_number(query)
        if lookup is not None:
            if lookup.is_preallocated:
                record = self.database.get_order_edit_record(lookup.id)
                if record is None:
                    QMessageBox.warning(self, tr("Missing Selection"), tr("Barcode order not found."))
                    return
                self._load_order_record(record)
                self.scan_input.clear()
                QMessageBox.information(self, tr("Saved"), tr("Barcode order loaded. Assign the patient and tests, then save."))
                return
            self._highlight_order_in_table(lookup.id)
            return
        matches = self.database.search_orders(query)
        if not matches:
            QMessageBox.warning(self, tr("Missing Selection"), tr("No orders found matching that number or name."))
            return
        if len(matches) == 1:
            order_id = matches[0].id
        else:
            order_id = self._pick_order_from_list(matches)
            if order_id is None:
                return
        self._highlight_order_in_table(order_id)

    def _highlight_order_in_table(self, order_id: int) -> None:
        self.scan_input.clear()
        self.refresh_recent_orders()
        self._select_recent_order(order_id)
        row = self.orders_table.currentRow()
        if row >= 0:
            item = self.orders_table.item(row, 0)
            if item is not None:
                self.orders_table.scrollToItem(item)

    def _pick_order_from_list(self, matches: list) -> int | None:
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Select Order"))
        dialog.setModal(True)
        dialog.resize(500, 320)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(tr("Multiple orders found. Select one:")))
        list_widget = QListWidget()
        for order in matches:
            label = f"{order.order_number}  —  {order.patient_name}  ({order.order_date[:10] if order.order_date else ''})"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, order.id)
            list_widget.addItem(item)
        list_widget.itemDoubleClicked.connect(lambda _: dialog.accept())
        layout.addWidget(list_widget, 1)
        buttons = QHBoxLayout()
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.clicked.connect(dialog.reject)
        select_btn = QPushButton(tr("Select"))
        select_btn.setProperty("class", "primaryButton")
        select_btn.clicked.connect(dialog.accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(select_btn)
        layout.addLayout(buttons)
        if list_widget.count() > 0:
            list_widget.setCurrentRow(0)
        if dialog.exec() != QDialog.Accepted:
            return None
        item = list_widget.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def generate_preallocated_batch(self) -> None:
        try:
            count = int((self.batch_count_input.text() or '0').strip())
        except ValueError:
            QMessageBox.warning(self, tr("Invalid Data"), tr("Batch size must be a whole number."))
            return
        if count <= 0:
            QMessageBox.warning(self, tr("Invalid Data"), tr("Batch size must be a whole number."))
            return
        batch_prefix = (self.batch_prefix_input.text() or '').strip().upper()
        if batch_prefix and (len(batch_prefix) != 1 or not batch_prefix.isalpha()):
            QMessageBox.warning(self, tr("Invalid Data"), tr("Batch letter must be a single letter."))
            return
        label_rows = self.database.create_preallocated_order_batch(count, self.client_combo.currentData(), batch_prefix=batch_prefix)
        self.populate_next_order_number()
        dialog = OrderLabelsDialog(self.database, label_rows=label_rows, parent=self)
        dialog.exec()

    def open_order_labels_dialog(self) -> None:
        order_id = self._selected_recent_order_id()
        if order_id is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a recent order first."))
            return
        prefs = self.database.get_label_print_preferences()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._print_order_label_silent(order_id, prefs, LabelPrinterClient(), str(prefs.get("printer") or "niimbot:B1"))
        except LabelPrinterError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, tr("Print Failed"), str(exc))
            return
        QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "Listo", "Etiqueta impresa.")

    def open_order_results_dialog(self) -> None:
        order_id = self._selected_recent_order_id()
        if order_id is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a recent order first."))
            return
        dialog = OrderResultsDialog(self.database, order_id, self.deployment_service, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_recent_orders()
            self.notify_data_changed()

    def save_order_import_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Save Order Template"),
            "order_import_template.xlsx",
            tr("Excel Workbook (*.xlsx)"),
        )
        if not path:
            return
        try:
            target = write_order_import_template(
                path,
                clients=self.database.list_client_choices(active_only=True),
                panels=self.database.list_panels(status_filter="active"),
            )
        except OSError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        QMessageBox.information(self, tr("Saved"), tr("Order template saved: {path}", path=str(target)))

    def import_orders_from_excel(self) -> None:
        if self.order_service.uses_server_backend():
            QMessageBox.information(self, tr("Not Available Yet"), tr("Order Excel import is not available yet in server mode."))
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("Import Orders"), "", tr("Excel Workbook (*.xlsx)"))
        if not path:
            return
        try:
            rows = read_order_workbook_rows(path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, tr("Import Failed"), str(exc))
            return
        try:
            plan, errors = self._build_order_import_plan(rows)
        except Exception as exc:
            QMessageBox.critical(self, tr("Import Failed"), str(exc))
            return
        if errors:
            QMessageBox.critical(self, tr("Import Failed"), "\n".join(errors[:20]))
            return
        if not plan:
            QMessageBox.information(self, tr("No Matches"), tr("No valid orders were found in the workbook."))
            return
        preview_lines = [
            f"{item['patient_name']} - {len(item['order_items'])} tests"
            for item in plan[:12]
        ]
        if len(plan) > 12:
            preview_lines.append(f"... +{len(plan) - 12} more")
        confirm = QMessageBox.question(
            self,
            tr("Preview Order Import"),
            tr("Create {count} orders?", count=str(len(plan))) + "\n\n" + "\n".join(preview_lines),
        )
        if confirm != QMessageBox.Yes:
            return
        created = 0
        try:
            for item in plan:
                order_id = self.database.create_order(
                    order_number=str(item.get("order_number") or "") or None,
                    accession_id=str(item.get("accession_id") or "") or None,
                    sample_id=str(item.get("sample_id") or "") or None,
                    patient_id=int(item["patient_id"]),
                    doctor_id=item.get("doctor_id"),
                    client_id=item.get("client_id"),
                    order_items=list(item["order_items"]),
                    status=str(item.get("status") or "draft"),
                    notes=str(item.get("notes") or ""),
                )
                created += 1
                self._maybe_broadcast_order(
                    int(item["patient_id"]),
                    order_id,
                    order_items=list(item["order_items"]),
                    doctor_name_override="",
                )
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        self.refresh_page_data()
        self.notify_data_changed()
        QMessageBox.information(self, tr("Saved"), tr("Created {count} orders.", count=str(created)))

    def import_and_print_from_excel(self) -> None:
        if self.order_service.uses_server_backend():
            QMessageBox.information(self, tr("Not Available Yet"), tr("Order Excel import is not available yet in server mode."))
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("Import Orders"), "", tr("Excel Workbook (*.xlsx)"))
        if not path:
            return
        try:
            rows = read_order_workbook_rows(path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, tr("Import Failed"), str(exc))
            return
        try:
            plan, errors = self._build_order_import_plan(rows)
        except Exception as exc:
            QMessageBox.critical(self, tr("Import Failed"), str(exc))
            return
        if errors:
            QMessageBox.critical(self, tr("Import Failed"), "\n".join(errors[:20]))
            return
        if not plan:
            QMessageBox.information(self, tr("No Matches"), tr("No valid orders were found in the workbook."))
            return
        preview_lines = [
            f"{item['patient_name']} - {len(item['order_items'])} tests"
            for item in plan[:12]
        ]
        if len(plan) > 12:
            preview_lines.append(f"... +{len(plan) - 12} more")
        confirm = QMessageBox.question(
            self,
            tr("Preview Order Import"),
            "¿Crear " + str(len(plan)) + " órdenes e imprimir etiquetas?\n\n" + "\n".join(preview_lines),
        )
        if confirm != QMessageBox.Yes:
            return
        created_orders: list[tuple[int, int | None]] = []
        try:
            for item in plan:
                order_id = self.database.create_order(
                    order_number=str(item.get("order_number") or "") or None,
                    accession_id=str(item.get("accession_id") or "") or None,
                    sample_id=str(item.get("sample_id") or "") or None,
                    patient_id=int(item["patient_id"]),
                    doctor_id=item.get("doctor_id"),
                    client_id=item.get("client_id"),
                    order_items=list(item["order_items"]),
                    status=str(item.get("status") or "draft"),
                    notes=str(item.get("notes") or ""),
                )
                created_orders.append((order_id, item.get("client_id")))
                self._maybe_broadcast_order(
                    int(item["patient_id"]),
                    order_id,
                    order_items=list(item["order_items"]),
                    doctor_name_override="",
                )
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return
        self.refresh_page_data()
        self.notify_data_changed()
        _label_client = LabelPrinterClient()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        printed = 0
        first_error: str = ""
        try:
            for order_id, client_id in created_orders:
                prefs = self.database.get_label_print_preferences(client_id)
                printer_pref = str(prefs.get("printer") or "niimbot:B1")
                try:
                    self._print_order_label_silent(order_id, prefs, _label_client, printer_pref)
                    printed += 1
                except LabelPrinterError as exc:
                    first_error = str(exc)
                    break
        finally:
            QApplication.restoreOverrideCursor()
        if first_error:
            QMessageBox.warning(
                self,
                tr("Print Failed"),
                "Se crearon " + str(len(created_orders)) + " órdenes. "
                + str(printed) + " etiqueta(s) impresas. Error: " + first_error,
            )
        else:
            QMessageBox.information(
                self,
                "Listo",
                "Se crearon " + str(len(created_orders)) + " órdenes y se imprimieron "
                + str(printed) + " etiqueta(s).",
            )

    def _silent_print_labels_niimbot(self, order_id: int, prefs: dict[str, str]) -> None:
        client = LabelPrinterClient()
        printer_pref = str(prefs.get("printer") or "niimbot:B1")
        try:
            self._print_order_label_silent(order_id, prefs, client, printer_pref)
        except LabelPrinterError as exc:
            QMessageBox.warning(self, tr("Print Failed"), str(exc))

    def _silent_print_labels_system(self, order_id: int, prefs: dict[str, str], printer_pref: str) -> None:
        label_rows = self.database.get_order_label_entries(order_id)
        if not label_rows:
            return
        size_key = str(prefs.get("size") or "small_tall")
        payload_key = str(prefs.get("payload") or "order_only")
        template_key = str(prefs.get("template") or "general")
        show_barcode = str(prefs.get("show_barcode") or "1") == "1"
        show_patient_name = str(prefs.get("show_patient_name") or "1") == "1"
        show_order_number_text = str(prefs.get("show_order_number_text") or "0") == "1"
        show_datetime = str(prefs.get("show_datetime") or "0") == "1"
        copies = max(1, int(str(prefs.get("copies") or "1")))
        base_row = dict(label_rows[0])
        base_row["test_name"] = ""
        base_row["specimen_type"] = ""
        base_row["group_label"] = ""
        rows_to_print = [base_row] * copies
        html = OrderLabelsDialog._build_label_html(
            rows_to_print,
            size_key,
            template_key,
            payload_key,
            show_barcode=show_barcode,
            show_patient_name=show_patient_name,
            show_order_number_text=show_order_number_text,
            show_datetime=show_datetime,
        )
        printer = QPrinter(QPrinter.HighResolution)
        if printer_pref.startswith("system:"):
            printer_name = printer_pref[len("system:"):]
            if printer_name:
                printer.setPrinterName(printer_name)
        document = QTextDocument()
        document.setHtml(html)
        document.print(printer)

    def _print_order_label_silent(
        self,
        order_id: int,
        prefs: dict[str, str],
        client: LabelPrinterClient,
        printer_id: str,
    ) -> None:
        label_rows = self.database.get_order_label_entries(order_id)
        if not label_rows:
            return
        base_row = dict(label_rows[0])
        base_row["test_name"] = ""
        base_row["specimen_type"] = ""
        base_row["group_label"] = ""
        size_key = str(prefs.get("size") or "small_tall")
        payload_key = str(prefs.get("payload") or "order_only")
        copies = max(1, int(str(prefs.get("copies") or "1")))
        density = max(1, min(5, int(str(prefs.get("density") or "4"))))
        panel_codes = self.database.get_order_panel_codes(order_id)
        if panel_codes:
            panel_extra_copies = self.database.get_panel_extra_copies()
            copies += sum(panel_extra_copies.get(code, 0) for code in panel_codes)
        show_barcode = str(prefs.get("show_barcode") or "1") == "1"
        show_patient_name = str(prefs.get("show_patient_name") or "1") == "1"
        show_order_number_text = str(prefs.get("show_order_number_text") or "0") == "1"
        show_datetime = str(prefs.get("show_datetime") or "0") == "1"
        width_mm, height_mm = OrderLabelsDialog._niimbot_label_size(size_key)
        token = OrderLabelsDialog._build_token(base_row, payload_key)
        safe_token = "".join(c if c.isalnum() else "" for c in token.upper()) or token.upper()
        text_lines: list[str] = []
        if show_order_number_text:
            order_number = str(base_row.get("order_number") or "").strip()
            if order_number:
                text_lines.append(order_number)
        if show_patient_name:
            patient_name = str(base_row.get("patient_name") or "").strip()
            if patient_name:
                text_lines.append(patient_name)
        if show_datetime:
            created_at = str(base_row.get("created_at") or "").strip()
            if created_at:
                text_lines.append(created_at)
        client.print_label(
            printer_id=printer_id,
            width_mm=width_mm,
            height_mm=height_mm,
            barcode_value=safe_token,
            human_text=safe_token,
            text_lines=text_lines,
            show_barcode=show_barcode,
            copies=copies,
            density=density,
        )

    def _build_order_import_plan(self, rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], list[str]]:
        plan: list[dict[str, object]] = []
        errors: list[str] = []
        for index, row in enumerate(rows, start=1):
            row_label = self._order_import_row_label(row, index)
            first_name = str(row.get("first_name") or "").strip()
            last_name = str(row.get("last_name") or "").strip()
            if not first_name:
                errors.append(f"{row_label}: first_name is required.")
                continue
            order_items, item_errors = self._order_import_items(row)
            if item_errors:
                errors.extend(f"{row_label}: {message}" for message in item_errors)
                continue
            if not order_items:
                errors.append(f"{row_label}: add at least one panel_codes value.")
                continue
            patient_id = self._resolve_import_patient(row)
            doctor_id = self._resolve_import_doctor(str(row.get("doctor") or ""))
            client_id = self._resolve_import_client(str(row.get("client") or ""))
            status = str(row.get("status") or "draft").strip() or "draft"
            if status not in {"draft", "in_progress"}:
                errors.append(f"{row_label}: status must be draft or in_progress.")
                continue
            plan.append(
                {
                    "order_number": str(row.get("order_number") or "").strip(),
                    "accession_id": str(row.get("accession_id") or "").strip(),
                    "sample_id": str(row.get("sample_id") or "").strip(),
                    "patient_id": patient_id,
                    "patient_name": " ".join(part for part in [first_name, last_name] if part),
                    "doctor_id": doctor_id,
                    "client_id": client_id,
                    "order_items": order_items,
                    "status": status,
                    "notes": str(row.get("notes") or "").strip(),
                }
            )
        return plan, errors

    def _order_import_items(self, row: dict[str, str]) -> tuple[list[dict[str, object]], list[str]]:
        items: list[dict[str, object]] = []
        errors: list[str] = []
        test_labels = {int(test_id): label for test_id, label in self.database.list_test_choices()}
        for code in self._split_import_codes(str(row.get("test_codes") or "")):
            test_id = self.database.get_test_id_by_code(code)
            if test_id is None:
                errors.append(f"unknown test code {code}")
                continue
            items.append({"item_type": "test", "test_id": test_id, "label": test_labels.get(test_id, code), "source": tr("Test"), "is_outsourced": 0})
        for code in self._split_import_codes(str(row.get("panel_codes") or "")):
            panel_id = self.database.get_panel_id_by_code(code)
            if panel_id is None:
                errors.append(f"unknown panel code {code}")
                continue
            for panel_item in self.order_service.get_panel_order_items(panel_id):
                item_type = self._import_item_value(panel_item, "item_type", "")
                test_id = self._import_item_value(panel_item, "test_id", None)
                if item_type != "test" or test_id is None:
                    continue
                items.append(
                    {
                        "item_type": "test",
                        "test_id": int(test_id),
                        "label": str(self._import_item_value(panel_item, "label", "")),
                        "source": code,
                        "is_outsourced": 0,
                    }
                )
        return items, errors

    @staticmethod
    def _import_item_value(item: object, key: str, default: object = None) -> object:
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    def _resolve_import_patient(self, row: dict[str, str]) -> int:
        patient_code = str(row.get("patient_code") or "").strip()
        first_name = str(row.get("first_name") or "").strip()
        last_name = str(row.get("last_name") or "").strip()
        middle_name = str(row.get("middle_name") or "").strip()
        date_of_birth = str(row.get("date_of_birth") or "").strip()
        with self.database.connect() as connection:
            if patient_code:
                existing = connection.execute("SELECT id FROM patients WHERE patient_code = ? AND is_active = 1", (patient_code,)).fetchone()
                if existing is not None:
                    return int(existing["id"])
            existing = connection.execute(
                """
                SELECT id FROM patients
                WHERE lower(first_name) = lower(?)
                  AND lower(last_name) = lower(?)
                  AND lower(COALESCE(middle_name, '')) = lower(?)
                  AND COALESCE(date_of_birth, '') = ?
                  AND is_active = 1
                """,
                (first_name, last_name, middle_name, date_of_birth),
            ).fetchone()
            if existing is not None:
                return int(existing["id"])
        return self.database.create_patient(
            {
                "patient_code": patient_code,
                "first_name": first_name,
                "last_name": last_name,
                "middle_name": middle_name,
                "sex": self._normalize_import_sex(str(row.get("sex") or "")),
                "date_of_birth": date_of_birth,
                "age_value": self._parse_optional_int(str(row.get("age_value") or "")),
                "age_unit": self._normalize_import_age_unit(str(row.get("age_unit") or "")),
                "phone": str(row.get("phone") or "").strip(),
                "email": str(row.get("email") or "").strip(),
                "address": str(row.get("address") or "").strip(),
                "national_id": str(row.get("national_id") or "").strip(),
            }
        )

    def _resolve_import_doctor(self, doctor_name: str) -> int | None:
        normalized = doctor_name.strip()
        if not normalized:
            return None
        for doctor_id, label in self._doctor_choices:
            if str(label).strip().casefold() == normalized.casefold():
                return int(doctor_id)
        return self.database.create_doctor({"full_name": normalized, "license_number": "", "phone": "", "email": ""})

    def _resolve_import_client(self, client_name: str) -> int | None:
        normalized = client_name.strip()
        if not normalized:
            return None
        for client_id, label in self._client_choices:
            label_str = str(label).strip()
            if label_str.casefold() == normalized.casefold():
                return int(client_id)
            # label may be "Name (phone)" — also try matching against name only
            name_part = label_str.split(" (")[0].strip()
            if name_part.casefold() == normalized.casefold():
                return int(client_id)
        return None

    @staticmethod
    def _split_import_codes(value: str) -> list[str]:
        normalized = value.replace("\n", ",").replace(";", ",").replace("|", ",")
        return [chunk.strip() for chunk in normalized.split(",") if chunk.strip()]

    @staticmethod
    def _parse_optional_int(value: str) -> int | None:
        text = value.strip()
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            return None

    @staticmethod
    def _normalize_import_sex(value: str) -> str | None:
        text = value.strip().casefold()
        male = {"m", "male", "masculino", "masc", "hombre", "h"}
        female = {"f", "female", "femenino", "fem", "mujer"}
        other = {"o", "other", "otro", "otra"}
        if text in male:
            return "M"
        if text in female:
            return "F"
        if text in other:
            return "O"
        return None

    @staticmethod
    def _normalize_import_age_unit(value: str) -> str:
        text = value.strip().casefold()
        return {
            "day": "days",
            "days": "days",
            "dia": "days",
            "dias": "days",
            "día": "days",
            "días": "days",
            "month": "months",
            "months": "months",
            "mes": "months",
            "meses": "months",
            "year": "years",
            "years": "years",
            "ano": "years",
            "anos": "years",
            "año": "years",
            "años": "years",
        }.get(text, text)

    @staticmethod
    def _order_import_row_label(row: dict[str, str], default_row_number: int) -> str:
        sheet = str(row.get("__sheet_name__") or "").strip()
        row_number = str(row.get("__row_number__") or default_row_number).strip()
        return f"{sheet} row {row_number}" if sheet else f"Row {row_number}"

    def handle_recent_order_double_click(self, _row: int, _col: int) -> None:
        if self.order_service.uses_server_backend():
            self.open_selected_order_for_edit()
            return
        self.open_order_results_dialog()

    def open_selected_order_for_edit(self) -> None:
        order_id = self._selected_recent_order_id()
        self._open_order_for_edit(order_id)

    def open_active_order_for_edit(self) -> None:
        self._open_order_for_edit(self._active_order_id())

    def _open_order_for_edit(self, order_id: int | str | None) -> None:
        if order_id is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a recent order first."))
            return
        if self.order_service.uses_server_backend():
            try:
                record = self.order_service.get_order_detail(order_id)
            except RuntimeError as exc:
                QMessageBox.warning(self, tr("Missing Selection"), str(exc))
                return
            self._load_order_record(record)
            QMessageBox.information(self, tr("Order"), tr("Shared order loaded for editing."))
            return
        record = self.database.get_order_edit_record(int(order_id))
        if record is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Order not found."))
            return
        self._load_order_record(record)
        QMessageBox.information(self, tr("Order"), tr("Order loaded for editing."))

    def _active_order_id(self) -> int | str | None:
        if self.edit_order_id is not None:
            return self.edit_order_id
        return self._selected_recent_order_id()

    def _selected_recent_order_id(self) -> int | str | None:
        row = self.orders_table.currentRow()
        if row < 0 or row >= len(self.recent_order_records):
            return None
        return self.recent_order_records[row].id

    def _select_recent_order(self, order_id: int | str) -> None:
        for row_index, record in enumerate(self.recent_order_records):
            if record.id == order_id:
                self.orders_table.setCurrentCell(row_index, 0)
                self.orders_table.selectRow(row_index)
                return

    def _set_combo_value(self, combo: QComboBox, value: int | str | None) -> None:
        if value is None:
            combo.setCurrentIndex(0)
            return
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _doctor_label_from_id(self, doctor_id: int | str | None) -> str:
        if doctor_id is None:
            return ""
        for choice_id, label in self._doctor_choices:
            if str(choice_id) == str(doctor_id):
                return label
        if not self.order_service.uses_server_backend():
            doctor = self.database.get_doctor(int(doctor_id))
            if doctor is not None:
                return doctor.full_name
        return ""

    def _resolve_doctor_id_from_input(self, *, create_if_missing: bool) -> int | str | None:
        doctor_name = self.doctor_input.text().strip()
        if not doctor_name:
            return None
        for doctor_id, label in self._doctor_choices:
            if label.strip().casefold() == doctor_name.casefold():
                return doctor_id
        if self.order_service.uses_server_backend():
            raise RuntimeError("Enter an existing doctor name exactly as configured on the server.")
        if not create_if_missing:
            return None
        doctor_id = self.database.create_doctor(
            {
                "full_name": doctor_name,
                "license_number": "",
                "phone": "",
                "email": "",
            }
        )
        self.refresh_choices()
        self.doctor_input.setText(doctor_name)
        return doctor_id

    def _update_form_mode(self) -> None:
        editing = self.edit_order_id is not None
        if editing:
            self.save_button.setText(tr("Update Order"))
            self.cancel_edit_button.setText(tr("Cancel Edit"))
        else:
            self.save_button.setText(tr("Save Order"))
        self.cancel_edit_button.setVisible(editing)

    def _load_order_record(self, record) -> None:
        self.edit_order_id = record.id
        self.order_number.setText(record.order_number)
        self._set_combo_value(self.patient_combo, record.patient_id if not record.is_preallocated else None)
        self.doctor_input.setText(self._doctor_label_from_id(record.doctor_id))
        self._set_combo_value(self.client_combo, record.client_id)
        status_value = record.status if not record.is_preallocated else 'draft'
        status_index = self.status.findData(status_value)
        self.status.setCurrentIndex(status_index if status_index >= 0 else 0)
        self.selected_items = [dict(item) for item in record.items]
        self._load_selected_panels_from_items()
        self._refresh_selected_table()
        self._update_form_mode()

    def add_selected_test(self) -> None:
        test_id = self.test_combo.currentData()
        label = self.test_combo.currentText()
        if test_id is None:
            QMessageBox.warning(self, tr("Missing Data"), tr("Select a test first."))
            return
        self._add_test_item(test_id, label, tr("Test"))
        self.test_combo.setCurrentIndex(0)

    def add_selected_panel(self) -> None:
        panel_id = self.panel_combo.currentData()
        panel_label = self.panel_combo.currentText()
        if panel_id is None:
            QMessageBox.warning(self, tr("Missing Data"), tr("Select a panel first."))
            return
        if any(panel.get("panel_id") == panel_id for panel in self.selected_panels):
            QMessageBox.information(self, tr("Panel Already Added"), tr("This panel is already on the order."))
            return
        panel_items = self.order_service.get_panel_order_items(panel_id)
        panel_detail = self.database.get_panel_detail(int(panel_id), include_inactive=True) if not self.order_service.uses_server_backend() else None
        panel_name = str((panel_detail or {}).get("name") or panel_label).strip()
        if not panel_items:
            QMessageBox.warning(self, tr("Empty Panel"), tr("This panel does not have any tests."))
            return
        panel_tests: list[dict[str, object]] = []
        for item in panel_items:
            item_type = str(item.get("item_type") or "test")
            if item_type in {"heading", "comment"}:
                panel_tests.append(
                    {
                        "item_type": item_type,
                        "label": str(item.get("heading_text") or item.get("label") or ""),
                        "source": panel_name,
                        "is_outsourced": 0,
                    }
                )
                continue
            test_id = item.get("test_id")
            if test_id is None:
                continue
            panel_tests.append(
                {
                    "item_type": "test",
                    "test_id": test_id,
                    "label": str(item.get("label") or ""),
                    "source": panel_name,
                    "is_outsourced": 0,
                }
            )
        if not panel_tests:
            QMessageBox.warning(self, tr("Empty Panel"), tr("This panel does not have any tests."))
            return
        self.selected_panels.append({"panel_id": panel_id, "label": panel_name, "items": panel_tests, "is_outsourced": 0})
        self._rebuild_selected_items_from_panels()
        self._refresh_selected_table()
        self.panel_combo.setCurrentIndex(-1)
        self.panel_combo.lineEdit().clear()

    def remove_selected_test(self) -> None:
        row = self.selected_table.currentRow()
        if row < 0 or row >= len(self.selected_panels):
            return
        self.selected_panels.pop(row)
        self._rebuild_selected_items_from_panels()
        self._refresh_selected_table()

    def _save_current_order(self) -> tuple[int, int | None, str] | None:
        """Validate and persist the current form.

        Returns (patient_id, order_id, message) on success.
        order_id is None for server-created orders where no local ID is available.
        Returns None and shows an error dialog on failure.
        """
        patient_id = self.patient_combo.currentData()
        if patient_id is None:
            QMessageBox.warning(self, tr("Missing Data"), tr("Select a patient for the order."))
            return None
        if not self.selected_items:
            QMessageBox.warning(self, tr("Missing Data"), tr("Add at least one test or panel."))
            return None

        if self.order_service.uses_server_backend():
            unsupported_items = [item for item in self.selected_items if item.get("item_type") != "test"]
            if unsupported_items:
                QMessageBox.information(
                    self,
                    tr("Not Available Yet"),
                    tr("Server mode currently supports direct test orders only."),
                )
                return None
            try:
                doctor_id = self._resolve_doctor_id_from_input(create_if_missing=False)
            except RuntimeError as exc:
                QMessageBox.warning(self, tr("Missing Data"), str(exc))
                return None
            try:
                if self.edit_order_id is not None:
                    updated = self.order_service.update_simple_order(
                        self.edit_order_id,
                        patient_id=patient_id,
                        test_ids=[item.get("test_id") for item in self.selected_items],
                        items=self.selected_items,
                        accession_id=None,
                        sample_id=None,
                        status=str(self.status.currentData() or "pending"),
                        notes="",
                        doctor_id=doctor_id,
                        client_id=self.client_combo.currentData(),
                    )
                    message = tr("Order updated: {order_number}").format(order_number=updated.order_number)
                    return (patient_id, int(self.edit_order_id), message)
                else:
                    created = self.order_service.create_simple_order(
                        patient_id=patient_id,
                        test_ids=[item.get("test_id") for item in self.selected_items],
                        items=self.selected_items,
                        accession_id=None,
                        sample_id=None,
                        status=str(self.status.currentData() or "pending"),
                        notes="",
                        doctor_id=doctor_id,
                        client_id=self.client_combo.currentData(),
                    )
                    message = tr("Order created: {order_number}").format(order_number=created.get("order_number") or "")
                    return (patient_id, None, message)
            except RuntimeError as exc:
                QMessageBox.critical(self, tr("Save Failed"), str(exc))
                return None

        try:
            doctor_id = self._resolve_doctor_id_from_input(create_if_missing=True)
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return None

        try:
            if self.edit_order_id is not None:
                record = self.database.get_order_edit_record(int(self.edit_order_id))
                if record is not None and int(record.is_preallocated) == 1:
                    self.database.assign_preallocated_order(
                        order_id=int(self.edit_order_id),
                        accession_id=None,
                        sample_id=None,
                        patient_id=patient_id,
                        doctor_id=doctor_id,
                        client_id=self.client_combo.currentData(),
                        order_items=self.selected_items,
                        status=self.status.currentData(),
                        notes="",
                    )
                    message = tr("Order assigned.")
                else:
                    self.database.update_order(
                        order_id=int(self.edit_order_id),
                        accession_id=None,
                        sample_id=None,
                        patient_id=patient_id,
                        doctor_id=doctor_id,
                        client_id=self.client_combo.currentData(),
                        order_items=self.selected_items,
                        status=self.status.currentData(),
                        notes="",
                    )
                    message = tr("Order updated.")
                return (patient_id, int(self.edit_order_id), message)
            else:
                order_id = self.database.create_order(
                    order_number=None,
                    accession_id=None,
                    sample_id=None,
                    patient_id=patient_id,
                    doctor_id=doctor_id,
                    client_id=self.client_combo.currentData(),
                    order_items=self.selected_items,
                    status=self.status.currentData(),
                    notes="",
                )
                return (patient_id, order_id, tr("Order created."))
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return None

    @contextmanager
    def _busy(self, button: QPushButton, busy_text: str) -> Iterator[None]:
        """Show a wait cursor and a disabled '…' button while a slow op runs.

        Saving an order blocks the UI thread (DB writes plus, in server mode,
        network calls), so without this the window looks frozen. We repaint the
        busy state before yielding so the user sees it before the blocking work.
        """
        original_text = button.text()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        button.setEnabled(False)
        button.setText(busy_text)
        QApplication.processEvents()
        try:
            yield
        finally:
            # Only restore our label if nothing else changed it meanwhile —
            # a successful save clears the form and _update_form_mode() may have
            # already set the correct ("Save Order" vs "Update Order") text.
            if button.text() == busy_text:
                button.setText(original_text)
            button.setEnabled(True)
            QApplication.restoreOverrideCursor()

    def save_order(self) -> None:
        with self._busy(self.save_button, tr("Saving…")):
            result = self._save_current_order()
            if result is None:
                return
            patient_id, order_id, message = result
            self._maybe_broadcast_order(patient_id, order_id)
            self.clear_order_form()
            self.refresh_recent_orders()
            self.notify_data_changed()
        QMessageBox.information(self, tr("Saved"), message)

    def save_and_print_labels(self) -> None:
        with self._busy(self.save_and_print_labels_button, tr("Saving…")):
            result = self._save_current_order()
            if result is None:
                return
            patient_id, order_id, _message = result
            self._maybe_broadcast_order(patient_id, order_id)
            self.clear_order_form()
            self.refresh_recent_orders()
            self.notify_data_changed()
            if order_id is None:
                return
            prefs = self.database.get_label_print_preferences()
            self._silent_print_labels_niimbot(order_id, prefs)

    def print_order_receipt(self) -> None:
        if self.edit_order_id is not None:
            order_id = int(self.edit_order_id)
        else:
            result = self._save_current_order()
            if result is None:
                return
            patient_id, order_id, _message = result
            if order_id is None:
                QMessageBox.warning(self, tr("Not Available"), tr("Receipt printing is not available for server-mode orders."))
                return
            self._maybe_broadcast_order(patient_id, order_id)
            self.clear_order_form()
            self.refresh_recent_orders()
            self.notify_data_changed()
        html = self._build_receipt_html(order_id)
        document = QTextDocument()
        document.setHtml(html)
        printer = QPrinter(QPrinter.HighResolution)
        preview = QPrintPreviewDialog(printer, self)
        preview.paintRequested.connect(document.print)
        preview.exec()

    def _build_receipt_html(self, order_id: int) -> str:
        from html import escape
        lines = self.database.get_order_receipt_lines(order_id)
        settings = self.database.get_lab_settings()
        if not lines:
            return f"<html><body><p>{escape(tr('No tests found for this order.'))}</p></body></html>"
        first = lines[0]
        order_number = str(first.get("order_number") or "")
        patient_name = str(first.get("patient_name") or "")
        order_date = str(first.get("order_date") or "")[:10]
        total = sum(float(row.get("price") or 0) for row in lines)
        rows_html = "".join(
            f"<tr><td>{escape(str(row.get('test_name') or ''))}</td>"
            f"<td style='text-align:right;'>${float(row.get('price') or 0):,.2f}</td></tr>"
            for row in lines
        )
        return f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; font-size: 11px; color: #111827; margin: 20px; }}
                .header {{ text-align: center; border-bottom: 2px solid #7c3aed; padding-bottom: 10px; margin-bottom: 14px; }}
                .brand {{ font-size: 20px; font-weight: 700; color: #6d28d9; }}
                .meta {{ color: #4b5563; font-size: 10px; }}
                .info {{ margin-bottom: 12px; }}
                .info span {{ display: inline-block; min-width: 110px; color: #6b7280; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th {{ background: #ede9fe; text-align: left; padding: 5px 7px; font-size: 10px; }}
                td {{ border-bottom: 1px solid #e5e7eb; padding: 5px 7px; }}
                .total {{ text-align: right; font-size: 14px; font-weight: 700; margin-top: 10px; }}
                .footer {{ text-align: center; color: #9ca3af; font-size: 9px; margin-top: 18px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <div class="brand">{escape(settings.lab_name or "SDX LIMS")}</div>
                <div class="meta">{escape(settings.address or "")}</div>
                <div class="meta">{escape(settings.phone or "")}{"  " if settings.phone and settings.email else ""}{escape(settings.email or "")}</div>
                <div style="font-size:13px;font-weight:700;margin-top:6px;">RECIBO</div>
            </div>
            <div class="info">
                <div><span>Orden:</span> {escape(order_number)}</div>
                <div><span>Paciente:</span> {escape(patient_name)}</div>
                <div><span>Fecha:</span> {escape(order_date)}</div>
            </div>
            <table>
                <thead><tr><th>Estudio</th><th style="text-align:right;">Precio</th></tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
            <div class="total">Total: ${total:,.2f} MXN</div>
            <div class="footer">Conserve este recibo como comprobante de pago.</div>
        </body>
        </html>
        """

    def _maybe_broadcast_order(
        self,
        patient_id: int,
        order_id: int | None = None,
        *,
        order_items: list | None = None,
        doctor_name_override: str | None = None,
    ) -> None:
        """Send order to any bidirectional-enabled instrument profiles, silently on error.

        By default the order's tests and doctor are read from the live form state
        (self.selected_items / self.doctor_input). The Excel-import paths pass
        order_items and doctor_name_override explicitly so imported orders are
        broadcast with their own tests rather than whatever is in the form.
        """
        try:
            configs = self.database.list_instrument_order_match_configs()
            enabled = [c for c in configs if c.broadcast_enabled]
            if not enabled:
                return
            patient = next(
                (p for p in self.database.list_patients() if p.id == patient_id), None
            )
            patient_name = f"{patient.first_name} {patient.last_name}".strip() if patient else ""
            dob = str(patient.date_of_birth or "") if patient else ""
            sex = str(patient.sex or "") if patient else ""
            doctor_name = (
                self.doctor_input.text().strip()
                if doctor_name_override is None
                else doctor_name_override
            )

            # Resolve the order number — used as sample_id for ASTM analyzers.
            order_number = ""
            if order_id is not None:
                try:
                    rec = self.database.get_order_edit_record(order_id)
                    if rec:
                        order_number = str(rec.order_number or "")
                except Exception:
                    pass

            order_data: dict[str, object] = {
                "patient_id": str(patient_id),
                "patient_name": patient_name,
                "patient_dob": dob,
                "patient_age_value": str(patient.age_value or "") if patient else "",
                "patient_age_unit": str(patient.age_unit or "a") if patient else "a",
                "patient_sex": sex,
                "doctor_name": doctor_name,
                "order_number": order_number,
                "sample_id": order_number,
                "accession_id": "",
            }

            for cfg in enabled:
                try:
                    protocol = (cfg.broadcast_protocol or "hl7_orm").lower()
                    # File-drop analyzers (e.g. CM250) have no TCP transport; the Go
                    # engine writes their order file (.ANA) when a pending order is
                    # pushed, so route them through the same engine endpoint as ASTM.
                    writes_order_file = instrument_broadcast.profile_writes_order_files(
                        cfg.instrument_profile
                    )
                    if protocol == "astm" or writes_order_file:
                        # Push pending order to the Go engine's in-memory store so it
                        # can respond to ASTM Q record queries from the analyzer and/or
                        # write an order file for file-drop analyzers.
                        if not order_number:
                            continue
                        mappings = self.database.list_instrument_result_mappings(
                            instrument_profile=cfg.instrument_profile
                        )
                        code_by_test_id: dict[int, tuple[str, str]] = {
                            m.test_id: (m.raw_code, m.raw_name or m.test_name or m.raw_code)
                            for m in mappings
                        }
                        tests = []
                        for item in (self.selected_items if order_items is None else order_items):
                            if item.get("item_type") != "test":
                                continue
                            tid = item.get("test_id")
                            if tid and tid in code_by_test_id:
                                code, name = code_by_test_id[tid]
                                tests.append({"test_code": code, "test_name": name})
                        instrument_broadcast.push_pending_order_to_engine(
                            sample_id=order_number,
                            tests=tests,
                            patient_id=str(patient_id) if bool(cfg.broadcast_patient_id) else "",
                            patient_name=patient_name if bool(cfg.broadcast_patient_name) else "",
                            dob=dob if bool(cfg.broadcast_dob) else "",
                            sex=sex if bool(cfg.broadcast_sex) else "",
                            doctor_name=doctor_name if bool(cfg.broadcast_doctor) else "",
                            profile_id=cfg.instrument_profile,
                        )
                    else:
                        instrument_broadcast.broadcast_order(
                            cfg.instrument_profile,
                            order_data,
                            send_patient_id=bool(cfg.broadcast_patient_id),
                            send_patient_name=bool(cfg.broadcast_patient_name),
                            send_dob=bool(cfg.broadcast_dob),
                            send_age=bool(cfg.broadcast_age),
                            send_sex=bool(cfg.broadcast_sex),
                            send_doctor=bool(cfg.broadcast_doctor),
                            protocol=protocol,
                            encoding=cfg.broadcast_encoding or "ascii",
                        )
                except RuntimeError:
                    pass
        except Exception:
            pass

    def clear_order_form(self) -> None:
        self.edit_order_id = None
        self.populate_next_order_number()
        self.status.setCurrentIndex(0)
        self.patient_combo.setCurrentIndex(0)
        self.doctor_input.clear()
        self.client_combo.setCurrentIndex(0)
        self.test_combo.setCurrentIndex(0)
        self.panel_combo.setCurrentIndex(-1)
        self.panel_combo.lineEdit().clear()
        self.selected_panels = []
        self.selected_items = []
        self._refresh_selected_table()
        self._update_form_mode()

    def _add_test_item(self, test_id: int, label: str, source: str) -> None:
        if any(item.get("item_type") == "test" and item.get("test_id") == test_id for item in self.selected_items):
            return
        self.selected_items.append({"item_type": "test", "test_id": test_id, "label": label, "source": source, "is_outsourced": 0})
        self._refresh_selected_table()

    def _add_heading_item(self, label: str, source: str) -> None:
        heading = label.strip()
        if not heading:
            return
        self.selected_items.append({"item_type": "heading", "label": heading, "source": source, "is_outsourced": 0})
        self._refresh_selected_table()

    def _add_comment_item(self, label: str, source: str) -> None:
        comment_label = label.strip()
        if not comment_label:
            return
        self.selected_items.append({"item_type": "comment", "label": comment_label, "source": source, "is_outsourced": 0})
        self._refresh_selected_table()

    def _refresh_selected_table(self, labels_override: dict[int, str] | None = None) -> None:
        _ = labels_override
        self.selected_table.blockSignals(True)
        self.selected_table.setRowCount(len(self.selected_panels))
        for row_index, panel in enumerate(self.selected_panels):
            self.selected_table.setItem(row_index, 0, QTableWidgetItem(str(panel.get("label") or "")))
            outsourced_item = QTableWidgetItem()
            outsourced_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            outsourced_item.setCheckState(Qt.Checked if panel.get("is_outsourced") else Qt.Unchecked)
            self.selected_table.setItem(row_index, 1, outsourced_item)
        self.selected_table.blockSignals(False)
        self.selected_stack.setCurrentIndex(1 if self.selected_panels else 0)

    def populate_next_order_number(self) -> None:
        self.order_number.setText(self.order_service.next_order_number())
        self.order_number.setPlaceholderText(tr("Assigned automatically when saved."))

    def _set_test_row_visible(self, visible: bool) -> None:
        self.test_row.setVisible(visible)
        self.form_labels["test"].setVisible(visible)
        set_row_visible = getattr(self.form, "setRowVisible", None)
        if callable(set_row_visible):
            set_row_visible(self.form_labels["test"], visible)

    def _rebuild_selected_items_from_panels(self) -> None:
        items: list[dict[str, object]] = []
        seen_test_ids: set[object] = set()
        for panel in self.selected_panels:
            is_outsourced = 1 if panel.get("is_outsourced") else 0
            for item in panel.get("items") or []:
                if not isinstance(item, dict):
                    continue
                test_id = item.get("test_id")
                if test_id is None or test_id in seen_test_ids:
                    continue
                seen_test_ids.add(test_id)
                item_payload = dict(item)
                item_payload["is_outsourced"] = is_outsourced
                items.append(item_payload)
        self.selected_items = items

    def _load_selected_panels_from_items(self) -> None:
        grouped_panels: dict[str, dict[str, object]] = {}
        for item in self.selected_items:
            if str(item.get("item_type") or "test") != "test":
                continue
            source = str(item.get("source") or "").strip()
            if not source or source == tr("Test"):
                continue
            panel = grouped_panels.setdefault(
                source,
                {
                    "panel_id": None,
                    "label": source,
                    "items": [],
                    "is_outsourced": 0,
                },
            )
            panel["items"].append(dict(item))
            if item.get("is_outsourced"):
                panel["is_outsourced"] = 1
        self.selected_panels = [
            {
                "panel_id": panel.get("panel_id"),
                "label": panel.get("label"),
                "items": list(panel.get("items") or []),
                "is_outsourced": 1 if panel.get("is_outsourced") else 0,
            }
            for panel in grouped_panels.values()
        ]
        self._rebuild_selected_items_from_panels()

    def _handle_selected_table_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 1:
            return
        row = item.row()
        if row < 0 or row >= len(self.selected_panels):
            return
        self.selected_panels[row]["is_outsourced"] = 1 if item.checkState() == Qt.Checked else 0
        self._rebuild_selected_items_from_panels()
