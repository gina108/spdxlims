from __future__ import annotations

from html import escape
import base64
import mimetypes
import sqlite3
from datetime import date
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QDate, QMarginsF, QSize, Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QLayout,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spdxlims.admin_cfdi import write_cfdi_preview_xml
from spdxlims.admin_excel import build_admin_export_sheets, build_invoice_excel_sheet, write_admin_export_workbook
from spdxlims.database import (
    BillingCustomerRecord,
    ClientRecord,
    Database,
    DoctorRecord,
    InventoryItemRecord,
    InventoryMovementRecord,
    InvoiceRecord,
    ReceiptRecord,
    SupplierRecord,
)
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.pages.orders_page import ClientDialog, DoctorDialog
from spdxlims.sat_catalogs import FORMA_PAGO_OPTIONS, METODO_PAGO_OPTIONS, USO_CFDI_OPTIONS
from spdxlims.whatsapp_phone import normalize_whatsapp_phone


class AdministrativePage(DataAwarePage):
    FILTER_DATE_MIN = QDate(2000, 1, 1)

    def minimumSizeHint(self) -> QSize:
        return QSize(1, 1)

    def __init__(self, database: Database, *, section_mode: str = 'full') -> None:
        super().__init__()
        self.database = database
        self.section_mode = section_mode
        self.billing_records: list[BillingCustomerRecord] = []
        self.filtered_billing_records: list[BillingCustomerRecord] = []
        self.billing_status_filter = 'active'
        self.doctor_records: list[DoctorRecord] = []
        self.filtered_doctor_records: list[DoctorRecord] = []
        self.doctor_status_filter = 'active'
        self.inventory_records: list[InventoryItemRecord] = []
        self.filtered_inventory_records: list[InventoryItemRecord] = []
        self.editing_inventory_id: int | None = None
        self.filtered_supplier_records: list[SupplierRecord] = []
        self.editing_supplier_id: int | None = None
        self.invoice_records: list[InvoiceRecord] = []
        self.receipt_records: list[ReceiptRecord] = []
        self.supplier_records: list[SupplierRecord] = []
        self.movement_records: list[InventoryMovementRecord] = []

        root = QVBoxLayout(self)
        root.setSizeConstraint(QLayout.SetNoConstraint)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        if self.section_mode == 'inventory':
            grid.addWidget(self._build_inventory_group(), 0, 0)
            grid.addWidget(self._build_supplier_group(), 0, 1)
            grid.addWidget(self._build_movement_group(), 1, 0, 1, 2)
            grid.addWidget(self._build_export_group(), 2, 0, 1, 2)
            root.addLayout(grid)
        elif self.section_mode == 'collections':
            top_split = QSplitter(Qt.Horizontal)
            top_split.setChildrenCollapsible(False)
            _left_scroll = QScrollArea()
            _left_scroll.setWidgetResizable(True)
            _left_scroll.setFrameShape(QScrollArea.NoFrame)
            _left_scroll.setWidget(self._build_invoice_group())
            top_split.addWidget(_left_scroll)
            top_split.addWidget(self._build_invoice_preview_group())
            top_split.setSizes([5000, 5000])
            root.addWidget(top_split, 1)
            self.invoice_table.itemSelectionChanged.connect(self._update_invoice_preview)
        else:
            grid.addWidget(self._build_billing_group(), 0, 0)
            grid.addWidget(self._build_doctor_group(), 0, 1)
            grid.addWidget(self._build_inventory_group(), 1, 0)
            grid.addWidget(self._build_supplier_group(), 1, 1)
            grid.addWidget(self._build_movement_group(), 2, 0)
            grid.addWidget(self._build_invoice_group(), 2, 1)
            grid.addWidget(self._build_export_group(), 3, 0, 1, 2)
            root.addLayout(grid)

        self.retranslate_ui()
        self.refresh_data()
        self.setMinimumWidth(1)

    def _styled_group(self, title: str = '') -> tuple[QGroupBox, QVBoxLayout]:
        group = QGroupBox(title)
        group.setObjectName('recentPatientsGroup')
        layout = QVBoxLayout(group)
        return group, layout

    def _build_billing_group(self) -> QWidget:
        self.billing_group, layout = self._styled_group()
        self.billing_info = QLabel()
        self.billing_info.setWordWrap(True)
        self.billing_search = QLineEdit()
        self.billing_search.textChanged.connect(self.refresh_billing_table)
        self.billing_filter_label = QLabel()
        self.billing_filter_combo = QComboBox()
        self.billing_filter_combo.currentIndexChanged.connect(self._change_billing_filter)
        self.new_customer_button = QPushButton()
        self.new_customer_button.clicked.connect(self.open_client_dialog)
        self.edit_customer_button = QPushButton()
        self.edit_customer_button.clicked.connect(self.edit_selected_client)
        self.billing_table = QTableWidget(0, 6)
        self.billing_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.billing_table.setSelectionMode(QTableWidget.SingleSelection)
        self.billing_table.cellDoubleClicked.connect(lambda _row, _col: self.edit_selected_client())
        self.billing_table.setObjectName('recentPatientsTable')
        self.billing_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.billing_info)
        filter_row = QHBoxLayout()
        filter_row.addWidget(self.billing_search, 1)
        filter_row.addWidget(self.billing_filter_label)
        filter_row.addWidget(self.billing_filter_combo)
        layout.addLayout(filter_row)
        button_row = QHBoxLayout()
        button_row.addWidget(self.new_customer_button)
        button_row.addWidget(self.edit_customer_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        layout.addWidget(self.billing_table)
        return self.billing_group


    def _build_doctor_group(self) -> QWidget:
        self.doctor_group, layout = self._styled_group()
        self.doctor_info = QLabel()
        self.doctor_info.setWordWrap(True)
        self.doctor_search = QLineEdit()
        self.doctor_search.textChanged.connect(self.refresh_doctor_table)
        self.doctor_filter_label = QLabel()
        self.doctor_filter_combo = QComboBox()
        self.doctor_filter_combo.currentIndexChanged.connect(self._change_doctor_filter)
        self.new_doctor_button = QPushButton()
        self.new_doctor_button.clicked.connect(self.open_doctor_dialog)
        self.edit_doctor_button = QPushButton()
        self.edit_doctor_button.clicked.connect(self.edit_selected_doctor)
        self.doctor_table = QTableWidget(0, 5)
        self.doctor_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.doctor_table.setSelectionMode(QTableWidget.SingleSelection)
        self.doctor_table.cellDoubleClicked.connect(lambda _row, _col: self.edit_selected_doctor())
        self.doctor_table.setObjectName('recentPatientsTable')
        self.doctor_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.doctor_info)
        filter_row = QHBoxLayout()
        filter_row.addWidget(self.doctor_search, 1)
        filter_row.addWidget(self.doctor_filter_label)
        filter_row.addWidget(self.doctor_filter_combo)
        layout.addLayout(filter_row)
        button_row = QHBoxLayout()
        button_row.addWidget(self.new_doctor_button)
        button_row.addWidget(self.edit_doctor_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        layout.addWidget(self.doctor_table)
        return self.doctor_group

    def _build_inventory_group(self) -> QWidget:
        self.inventory_group, layout = self._styled_group()
        self.inventory_info = QLabel()
        self.inventory_info.setWordWrap(True)
        layout.addWidget(self.inventory_info)
        self.inventory_search = QLineEdit()
        self.inventory_search.textChanged.connect(self.refresh_inventory_table)
        layout.addWidget(self.inventory_search)
        self.inventory_summary_label = QLabel()
        self.inventory_summary_label.setWordWrap(True)
        layout.addWidget(self.inventory_summary_label)
        form = QFormLayout()
        self.inventory_labels: dict[str, QLabel] = {}
        self.inventory_sku = QLineEdit()
        self.inventory_name = QLineEdit()
        self.inventory_unit = QLineEdit()
        self.inventory_on_hand = QLineEdit('0')
        self.inventory_reorder = QLineEdit('0')
        self.inventory_cost = QLineEdit('0')
        for key, field in [('inventory_sku', self.inventory_sku), ('inventory_name', self.inventory_name), ('inventory_unit', self.inventory_unit), ('inventory_on_hand', self.inventory_on_hand), ('inventory_reorder', self.inventory_reorder), ('inventory_cost', self.inventory_cost)]:
            label = QLabel()
            self.inventory_labels[key] = label
            form.addRow(label, field)
        layout.addLayout(form)
        button_row = QHBoxLayout()
        self.save_inventory_button = QPushButton()
        self.save_inventory_button.clicked.connect(self.save_inventory_item)
        self.clear_inventory_button = QPushButton()
        self.clear_inventory_button.clicked.connect(self.clear_inventory_form)
        self.delete_inventory_button = QPushButton()
        self.delete_inventory_button.clicked.connect(self.delete_selected_inventory_item)
        self.delete_inventory_button.setVisible(False)
        button_row.addStretch(1)
        button_row.addWidget(self.delete_inventory_button)
        button_row.addWidget(self.clear_inventory_button)
        button_row.addWidget(self.save_inventory_button)
        layout.addLayout(button_row)
        self.inventory_table = QTableWidget(0, 6)
        self.inventory_table.setObjectName('recentPatientsTable')
        self.inventory_table.horizontalHeader().setStretchLastSection(True)
        self.inventory_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.inventory_table.setSelectionMode(QTableWidget.SingleSelection)
        self.inventory_table.cellDoubleClicked.connect(lambda row, _col: self.load_inventory_item_for_edit(row))
        layout.addWidget(self.inventory_table)
        return self.inventory_group

    def _build_supplier_group(self) -> QWidget:
        self.supplier_group, layout = self._styled_group()
        self.supplier_info = QLabel()
        self.supplier_info.setWordWrap(True)
        layout.addWidget(self.supplier_info)
        form = QFormLayout()
        self.supplier_labels: dict[str, QLabel] = {}
        self.supplier_name = QLineEdit()
        self.supplier_tax_id = QLineEdit()
        self.supplier_phone = QLineEdit()
        self.supplier_email = QLineEdit()
        for key, field in [('supplier_name', self.supplier_name), ('supplier_tax_id', self.supplier_tax_id), ('supplier_phone', self.supplier_phone), ('supplier_email', self.supplier_email)]:
            label = QLabel()
            self.supplier_labels[key] = label
            form.addRow(label, field)
        layout.addLayout(form)
        supplier_button_row = QHBoxLayout()
        self.save_supplier_button = QPushButton()
        self.save_supplier_button.clicked.connect(self.save_supplier)
        self.clear_supplier_button = QPushButton()
        self.clear_supplier_button.clicked.connect(self.clear_supplier_form)
        self.delete_supplier_button = QPushButton()
        self.delete_supplier_button.clicked.connect(self.delete_selected_supplier)
        self.delete_supplier_button.setVisible(False)
        supplier_button_row.addStretch(1)
        supplier_button_row.addWidget(self.delete_supplier_button)
        supplier_button_row.addWidget(self.clear_supplier_button)
        supplier_button_row.addWidget(self.save_supplier_button)
        layout.addLayout(supplier_button_row)
        self.supplier_table = QTableWidget(0, 4)
        self.supplier_table.setObjectName('recentPatientsTable')
        self.supplier_table.horizontalHeader().setStretchLastSection(True)
        self.supplier_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.supplier_table.setSelectionMode(QTableWidget.SingleSelection)
        self.supplier_table.cellDoubleClicked.connect(lambda row, _col: self.load_supplier_for_edit(row))
        layout.addWidget(self.supplier_table)
        return self.supplier_group

    def _build_movement_group(self) -> QWidget:
        self.movement_group, layout = self._styled_group()
        self.movement_info = QLabel()
        self.movement_info.setWordWrap(True)
        layout.addWidget(self.movement_info)
        form = QFormLayout()
        self.movement_labels: dict[str, QLabel] = {}
        self.movement_inventory = QComboBox()
        self.movement_supplier = QComboBox()
        self.movement_type = QComboBox()
        self.movement_quantity = QLineEdit('0')
        self.movement_cost = QLineEdit('0')
        self.movement_date = QDateEdit(QDate.currentDate())
        self.movement_date.setCalendarPopup(True)
        self.movement_date.setDisplayFormat('yyyy-MM-dd')
        self.movement_notes = QLineEdit()
        for key, field in [('movement_inventory', self.movement_inventory), ('movement_supplier', self.movement_supplier), ('movement_type', self.movement_type), ('movement_quantity', self.movement_quantity), ('movement_cost', self.movement_cost), ('movement_date', self.movement_date), ('movement_notes', self.movement_notes)]:
            label = QLabel()
            self.movement_labels[key] = label
            form.addRow(label, field)
        layout.addLayout(form)
        self.save_movement_button = QPushButton()
        self.save_movement_button.clicked.connect(self.save_inventory_movement)
        layout.addWidget(self.save_movement_button, alignment=Qt.AlignRight)
        self.movement_table = QTableWidget(0, 6)
        self.movement_table.setObjectName('recentPatientsTable')
        self.movement_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.movement_table)
        return self.movement_group

    def _build_invoice_group(self) -> QWidget:
        self.invoice_group, layout = self._styled_group()
        self.invoice_info = QLabel()
        self.invoice_info.setWordWrap(True)
        layout.addWidget(self.invoice_info)
        button_row = QGridLayout()
        button_row.setSpacing(4)
        self.clear_invoice_filter_button = QPushButton()
        self.clear_invoice_filter_button.clicked.connect(self.clear_invoice_filters)
        self.save_invoice_button = QPushButton()
        self.save_invoice_button.clicked.connect(self.save_invoice)
        self.batch_invoice_button = QPushButton()
        self.batch_invoice_button.clicked.connect(self.create_filtered_invoices)
        self.create_receipt_button = QPushButton()
        self.create_receipt_button.clicked.connect(self.create_receipt_for_selected_order)
        self.export_cfdi_button = QPushButton()
        self.export_cfdi_button.clicked.connect(self.export_selected_invoice_cfdi)
        self.print_invoice_button = QPushButton()
        self.print_invoice_button.clicked.connect(self.print_selected_invoice)
        self.export_invoice_pdf_button = QPushButton()
        self.export_invoice_pdf_button.clicked.connect(self.export_selected_invoice_pdf)
        self.export_invoice_excel_button = QPushButton()
        self.export_invoice_excel_button.clicked.connect(self.export_selected_invoice_excel)
        self.send_invoice_whatsapp_button = QPushButton()
        self.send_invoice_whatsapp_button.clicked.connect(self.send_selected_invoice_whatsapp)
        self.delete_invoice_button = QPushButton()
        self.delete_invoice_button.clicked.connect(self.delete_selected_invoice)
        self._invoice_buttons = [
            self.clear_invoice_filter_button,
            self.save_invoice_button,
            self.batch_invoice_button,
            self.create_receipt_button,
            self.print_invoice_button,
            self.export_invoice_pdf_button,
            self.export_invoice_excel_button,
            self.send_invoice_whatsapp_button,
            self.export_cfdi_button,
            self.delete_invoice_button,
        ]
        self._invoice_button_grid = button_row
        # Place every button once so they get parented to the group; isHidden()
        # only reports explicit hides after this. update_invoice_mode() then calls
        # _relayout_invoice_buttons() to reflow just the visible ones (rows of 4).
        for _index, _button in enumerate(self._invoice_buttons):
            button_row.addWidget(_button, _index // 4, _index % 4)
        layout.addLayout(button_row)
        form = QFormLayout()
        self.invoice_labels: dict[str, QLabel] = {}
        self.invoice_mode = QComboBox()
        self.invoice_mode.currentIndexChanged.connect(self.update_invoice_mode)
        self.invoice_number = QLineEdit()
        self.invoice_number.setReadOnly(True)
        self.invoice_date = QLineEdit(date.today().isoformat())
        self.invoice_client = QComboBox()
        self.invoice_client.currentIndexChanged.connect(self.sync_invoice_client_defaults)
        self.invoice_order = QComboBox()
        self.invoice_order.currentIndexChanged.connect(self.sync_invoice_total_from_order)
        self.receipt_order = QComboBox()
        self.receipt_order.currentIndexChanged.connect(self.sync_receipt_total_from_order)
        self.invoice_filter_client = QComboBox()
        _today = QDate.currentDate()
        self.invoice_filter_date_from = QDateEdit(_today.addMonths(-1))
        self.invoice_filter_date_to = QDateEdit(_today)
        self.invoice_status = QComboBox()
        self.invoice_total = QLineEdit('0.00')
        self.invoice_cfdi_use = QComboBox()
        self.invoice_cfdi_use.addItem('', '')
        for code, label in USO_CFDI_OPTIONS:
            self.invoice_cfdi_use.addItem(label, code)
        self.invoice_payment_form = QComboBox()
        for code, label in FORMA_PAGO_OPTIONS:
            self.invoice_payment_form.addItem(label, code)
        self.invoice_payment_method = QComboBox()
        for code, label in METODO_PAGO_OPTIONS:
            self.invoice_payment_method.addItem(label, code)
        self.invoice_currency = QLineEdit('MXN')
        self.invoice_notes = QTextEdit()
        self.invoice_notes.setMinimumHeight(72)
        self.invoice_filter_status = QLabel()
        self.invoice_filter_status.setWordWrap(True)
        for widget in (self.invoice_filter_date_from, self.invoice_filter_date_to):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd")
            widget.setMinimumDate(self.FILTER_DATE_MIN)
        # Filters auto-apply on change (replaces the former "Apply filters" button).
        # refresh_choices() is guarded against re-entrancy because it also
        # repopulates invoice_filter_client.
        self.invoice_filter_client.currentIndexChanged.connect(self.refresh_choices)
        self.invoice_filter_date_from.dateChanged.connect(self.refresh_choices)
        self.invoice_filter_date_to.dateChanged.connect(self.refresh_choices)
        for key, field in [('invoice_mode', self.invoice_mode), ('invoice_number', self.invoice_number), ('invoice_date', self.invoice_date), ('invoice_client', self.invoice_client), ('invoice_order', self.invoice_order), ('receipt_order', self.receipt_order), ('invoice_status', self.invoice_status), ('invoice_total', self.invoice_total), ('invoice_cfdi_use', self.invoice_cfdi_use), ('invoice_payment_form', self.invoice_payment_form), ('invoice_payment_method', self.invoice_payment_method), ('invoice_currency', self.invoice_currency), ('invoice_notes', self.invoice_notes)]:
            label = QLabel()
            self.invoice_labels[key] = label
            form.addRow(label, field)
        self.invoice_filter_labels: dict[str, QLabel] = {}
        filter_form = QFormLayout()
        self.invoice_date_range_row = QWidget()
        invoice_date_range_layout = QHBoxLayout(self.invoice_date_range_row)
        invoice_date_range_layout.setContentsMargins(0, 0, 0, 0)
        invoice_date_range_layout.addWidget(QLabel(tr("From")))
        invoice_date_range_layout.addWidget(self.invoice_filter_date_from, 1)
        invoice_date_range_layout.addWidget(QLabel(tr("To")))
        invoice_date_range_layout.addWidget(self.invoice_filter_date_to, 1)
        for key, field in [('invoice_filter_date_range', self.invoice_date_range_row), ('invoice_filter_client', self.invoice_filter_client)]:
            label = QLabel()
            self.invoice_filter_labels[key] = label
            filter_form.addRow(label, field)
        # Periodo + Cliente sit directly under the buttons, above the rest of the form.
        layout.addLayout(filter_form)
        layout.addLayout(form)
        layout.addWidget(self.invoice_filter_status)
        self.invoice_table = QTableWidget(0, 6)
        self.invoice_table.setObjectName('recentPatientsTable')
        self.invoice_table.horizontalHeader().setStretchLastSection(True)
        self.invoice_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.invoice_table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.invoice_table)
        self.receipt_table = QTableWidget(0, 6)
        self.receipt_table.setObjectName('recentPatientsTable')
        self.receipt_table.horizontalHeader().setStretchLastSection(True)
        self.receipt_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.receipt_table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.receipt_table)
        return self.invoice_group

    def _build_export_group(self) -> QWidget:
        self.export_group, layout = self._styled_group()
        self.export_info = QLabel()
        self.export_info.setWordWrap(True)
        self.export_button = QPushButton()
        self.export_button.clicked.connect(self.export_admin_workbook)
        self.export_status = QLabel()
        self.export_status.setWordWrap(True)
        layout.addWidget(self.export_info)
        layout.addWidget(self.export_button, alignment=Qt.AlignRight)
        layout.addWidget(self.export_status)
        return self.export_group

    def _build_invoice_preview_group(self) -> QWidget:
        self.invoice_preview_group, layout = self._styled_group()
        self.invoice_preview = QTextEdit()
        self.invoice_preview.setReadOnly(True)
        self.invoice_preview.setStyleSheet('background:#ffffff; color:#111827;')
        layout.addWidget(self.invoice_preview)
        return self.invoice_preview_group

    def retranslate_ui(self) -> None:
        self.summary.setText(
            tr('Inventory, suppliers, stock movements, and Excel exports.')
            if self.section_mode == 'inventory'
            else tr('Cobranza de clientes y seguimiento de facturacion.')
            if self.section_mode == 'collections'
            else tr('Administrative addon for billing, inventory, invoicing, and Excel exports.')
        )
        if hasattr(self, 'billing_group'):
            self.billing_group.setTitle(tr('Customer Billing'))
            self.billing_info.setText(tr('Review customers and outstanding balances for administrative follow-up.'))
            self.billing_search.setPlaceholderText(tr('Search customers'))
            self.billing_filter_label.setText(tr('Show'))
            current_filter = self.billing_filter_combo.currentData()
            self.billing_filter_combo.clear()
            self.billing_filter_combo.addItem(tr('Active Only'), 'active')
            self.billing_filter_combo.addItem(tr('Archived Only'), 'archived')
            self.billing_filter_combo.addItem(tr('All'), 'all')
            filter_index = self.billing_filter_combo.findData(current_filter or self.billing_status_filter)
            self.billing_filter_combo.setCurrentIndex(filter_index if filter_index >= 0 else 0)
            self.new_customer_button.setText(tr('New Customer'))
            self.edit_customer_button.setText(tr('Edit Customer'))
            self.billing_table.setHorizontalHeaderLabels([tr('Customer'), tr('Phone'), tr('Email'), tr('Status'), tr('Open Balance'), tr('Invoice Count')])

            if self.section_mode != 'collections':
                self.doctor_group.setTitle(tr('Doctors'))
                self.doctor_info.setText(tr('Maintain active and archived doctors used during order entry.'))
                self.doctor_search.setPlaceholderText(tr('Search doctors'))
                self.doctor_filter_label.setText(tr('Show'))
                current_doctor_filter = self.doctor_filter_combo.currentData()
                self.doctor_filter_combo.clear()
                self.doctor_filter_combo.addItem(tr('Active Only'), 'active')
                self.doctor_filter_combo.addItem(tr('Archived Only'), 'archived')
                self.doctor_filter_combo.addItem(tr('All'), 'all')
                doctor_filter_index = self.doctor_filter_combo.findData(current_doctor_filter or self.doctor_status_filter)
                self.doctor_filter_combo.setCurrentIndex(doctor_filter_index if doctor_filter_index >= 0 else 0)
                self.new_doctor_button.setText(tr('New Doctor'))
                self.edit_doctor_button.setText(tr('Edit Doctor'))
                self.doctor_table.setHorizontalHeaderLabels([tr('Doctor'), tr('License'), tr('Phone'), tr('Email'), tr('Status')])

        if hasattr(self, 'inventory_group'):
            self.inventory_group.setTitle(tr('Inventory'))
            self.inventory_info.setText(tr('Track stock, reorder thresholds, and unit cost for consumables. Double-click an item to edit it.'))
            self.inventory_search.setPlaceholderText(tr('Search inventory'))
            for key, label in [('inventory_sku','SKU'),('inventory_name','Name'),('inventory_unit','Unit'),('inventory_on_hand','On Hand'),('inventory_reorder','Reorder Level'),('inventory_cost','Unit Cost')]:
                self.inventory_labels[key].setText(tr(label))
            self.clear_inventory_button.setText(tr('Clear'))
            self.delete_inventory_button.setText(tr('Delete Inventory Item'))
            self._update_inventory_form_mode()
            self.inventory_table.setHorizontalHeaderLabels([tr('SKU'), tr('Name'), tr('Unit'), tr('On Hand'), tr('Reorder Level'), tr('Unit Cost')])

            self.supplier_group.setTitle(tr('Suppliers'))
            self.supplier_info.setText(tr('Maintain supplier records for purchases and stock movements. Double-click a supplier to edit it.'))
            for key, label in [('supplier_name','Supplier Name'),('supplier_tax_id','Tax ID (RFC)'),('supplier_phone','Phone'),('supplier_email','Email')]:
                self.supplier_labels[key].setText(tr(label))
            self.clear_supplier_button.setText(tr('Clear'))
            self.delete_supplier_button.setText(tr('Delete Supplier'))
            self._update_supplier_form_mode()
            self.supplier_table.setHorizontalHeaderLabels([tr('Supplier Name'), tr('Tax ID (RFC)'), tr('Phone'), tr('Email')])

            self.movement_group.setTitle(tr('Stock Movements'))
            self.movement_info.setText(tr('Register purchases, consumption, and inventory adjustments.'))
            for key, label in [('movement_inventory','Inventory Item'),('movement_supplier','Supplier'),('movement_type','Movement Type'),('movement_quantity','Quantity'),('movement_cost','Unit Cost'),('movement_date','Movement Date'),('movement_notes','Notes')]:
                self.movement_labels[key].setText(tr(label))
            self.save_movement_button.setText(tr('Save Movement'))
            self.movement_table.setHorizontalHeaderLabels([tr('Inventory Item'), tr('Supplier'), tr('Movement Type'), tr('Quantity'), tr('Unit Cost'), tr('Movement Date')])

        if self.section_mode != 'inventory':
            self.invoice_group.setTitle(tr('Cobranza de clientes') if self.section_mode == 'collections' else tr('Invoicing'))
            if hasattr(self, 'invoice_preview_group'):
                self.invoice_preview_group.setTitle(tr('Vista Previa de Factura'))
            self.invoice_info.setText(
                tr('Create cobranza records and customer invoice entries.')
                if self.section_mode == 'collections'
                else tr('Create billing records and factura-ready invoice entries for customers.')
            )
            for key, label in [('invoice_mode','Mode'),('invoice_number','Invoice Number'),('invoice_date','Invoice/Receipt Date'),('invoice_client','Customer'),('invoice_order','Order for Invoice'),('receipt_order','Order for Receipt'),('invoice_status','Invoice Status'),('invoice_total','Total Amount'),('invoice_cfdi_use','CFDI Use'),('invoice_payment_form','Payment Form'),('invoice_payment_method','Payment Method'),('invoice_currency','Currency'),('invoice_notes','Notes')]:
                self.invoice_labels[key].setText(tr(label))
            current_mode = self.invoice_mode.currentData()
            self.invoice_mode.clear()
            self.invoice_mode.addItem(tr('Invoice by Client'), 'client')
            self.invoice_mode.addItem(tr('Invoice / Receipt by Order'), 'order')
            mode_index = self.invoice_mode.findData(current_mode or 'client')
            self.invoice_mode.setCurrentIndex(mode_index if mode_index >= 0 else 0)
            self.invoice_filter_labels['invoice_filter_client'].setText(tr('Client Filter'))
            date_range_label = tr('Periodo (Desde — Hasta)') if self.section_mode == 'collections' else tr('Date Range')
            self.invoice_filter_labels['invoice_filter_date_range'].setText(date_range_label)
            self.clear_invoice_filter_button.setText(tr('Clear Invoice Filters'))
            self.save_invoice_button.setText(tr('Save Invoice'))
            self.batch_invoice_button.setText(
                tr('Create Client Invoices From Filters')
                if self.section_mode == 'collections'
                else tr('Create Invoices From Filters')
            )
            self.create_receipt_button.setText(tr('Create Receipt for Selected Order'))
            self.print_invoice_button.setText(tr('Print Invoice'))
            self.export_invoice_pdf_button.setText(tr('Export Invoice PDF'))
            self.export_invoice_excel_button.setText(tr('Export Invoice Excel'))
            self.send_invoice_whatsapp_button.setText(tr('Send via WhatsApp'))
            self.export_cfdi_button.setText(tr('Export CFDI Preview XML'))
            self.delete_invoice_button.setText(tr('Delete Invoice'))
            self.invoice_table.setHorizontalHeaderLabels([tr('Invoice Number'), tr('Customer'), tr('Invoice Date'), tr('Status'), tr('Total Amount'), tr('Orders')])
            self.receipt_table.setHorizontalHeaderLabels([tr('Receipt Number'), tr('Order Number'), tr('Customer'), tr('Patient'), tr('Receipt Date'), tr('Total Amount')])
            current_status = self.invoice_status.currentData()
            self.invoice_status.clear()
            for label, value in [('Draft','draft'),('Issued','issued'),('Paid','paid'),('Cancelled','cancelled')]:
                self.invoice_status.addItem(tr(label), value)
            index = self.invoice_status.findData(current_status)
            self.invoice_status.setCurrentIndex(index if index >= 0 else 1)
            self.update_invoice_mode()
        if hasattr(self, 'movement_type'):
            current_movement = self.movement_type.currentData()
            self.movement_type.clear()
            for label, value in [('Purchase','purchase'),('Adjustment In','adjustment_in'),('Adjustment Out','adjustment_out'),('Consumption','consumption')]:
                self.movement_type.addItem(tr(label), value)
            index = self.movement_type.findData(current_movement)
            self.movement_type.setCurrentIndex(index if index >= 0 else 0)

        if self.section_mode == 'inventory':
            self.export_group.setTitle(tr('Excel Export'))
            self.export_info.setText(tr('Export customers, inventory, invoices, suppliers, and stock movements to Excel.'))
            self.export_button.setText(tr('Export Administrative Workbook'))

        self.refresh_choices()

    def refresh_on_show(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        if hasattr(self, 'billing_group'):
            self.billing_records = self.database.list_billing_customers()
            if self.section_mode != 'collections':
                self.doctor_records = self.database.list_doctors(status_filter='all')
        if hasattr(self, 'inventory_group'):
            self.inventory_records = self.database.list_inventory_items()
        if self.section_mode != 'inventory':
            self.invoice_records = self.database.list_invoices()
            self.receipt_records = self.database.list_receipts()
        if hasattr(self, 'supplier_group'):
            self.supplier_records = self.database.list_suppliers()
        if hasattr(self, 'movement_group'):
            self.movement_records = self.database.list_inventory_movements()
        if self.section_mode != 'inventory':
            self.invoice_number.setText(self.database.next_invoice_number())
        self.refresh_choices()
        if hasattr(self, 'billing_group'):
            self.refresh_billing_table()
            if self.section_mode != 'collections':
                self.refresh_doctor_table()
        if hasattr(self, 'inventory_table'):
            self.refresh_inventory_table()
        if hasattr(self, 'supplier_table'):
            self.refresh_supplier_table()
        if hasattr(self, 'movement_table'):
            self.refresh_movement_table()
        if self.section_mode != 'inventory':
            self.refresh_invoice_table()
            self.refresh_receipt_table()

    def refresh_choices(self, *_args) -> None:
        # Guard against re-entrancy: this repopulates invoice_filter_client, whose
        # currentIndexChanged is wired back here for auto-apply of the filters.
        if getattr(self, '_refreshing_choices', False):
            return
        self._refreshing_choices = True
        try:
            self._refresh_choices_impl()
        finally:
            self._refreshing_choices = False

    def _refresh_choices_impl(self) -> None:
        if self.section_mode != 'inventory':
            self.set_combo_items(self.invoice_client, [(label, client_id) for client_id, label in self.database.list_client_choices(active_only=True, include_ids=[self.invoice_client.currentData()] if self.invoice_client.currentData() is not None else None)], placeholder=tr('Select client'), selected_data=self.invoice_client.currentData())
            self.set_combo_items(self.invoice_filter_client, [(label, client_id) for client_id, label in self.database.list_client_choices(active_only=True)], placeholder=tr('All clients'), selected_data=self.invoice_filter_client.currentData())
            self.set_combo_items(self.invoice_order, [(label, order_id) for order_id, label in self.database.list_filtered_invoice_order_choices(client_id=self.invoice_filter_client.currentData(), date_from=self._filter_date_value(self.invoice_filter_date_from), date_to=self._filter_date_value(self.invoice_filter_date_to))], placeholder=tr('Select order'), selected_data=self.invoice_order.currentData())
            self.set_combo_items(self.receipt_order, [(label, order_id) for order_id, label in self.database.list_receipt_order_choices(client_id=self.invoice_filter_client.currentData(), date_from=self._filter_date_value(self.invoice_filter_date_from), date_to=self._filter_date_value(self.invoice_filter_date_to))], placeholder=tr('Select order for receipt'), selected_data=self.receipt_order.currentData())
        if hasattr(self, 'movement_inventory'):
            self.set_combo_items(self.movement_inventory, [(label, item_id) for item_id, label in self.database.list_inventory_item_choices()], placeholder=tr('Select inventory item'), selected_data=self.movement_inventory.currentData())
        if hasattr(self, 'movement_supplier'):
            self.set_combo_items(self.movement_supplier, [(label, supplier_id) for supplier_id, label in self.database.list_supplier_choices()], placeholder=tr('Select supplier'), selected_data=self.movement_supplier.currentData())
        if self.section_mode != 'inventory':
            invoice_order_count = max(self.invoice_order.count() - 1, 0)
            receipt_order_count = max(self.receipt_order.count() - 1, 0)
            self.invoice_filter_status.setText(tr('Matching invoice orders: {invoice_count}. Matching receipt orders: {receipt_count}.', invoice_count=str(invoice_order_count), receipt_count=str(receipt_order_count)))

    def update_invoice_mode(self) -> None:
        if self.section_mode == 'inventory' or not hasattr(self, 'invoice_mode'):
            return
        mode = str(self.invoice_mode.currentData() or 'client')
        client_mode = mode == 'client'
        collections_mode = self.section_mode == 'collections'
        for key in ('invoice_client', 'invoice_order', 'receipt_order'):
            self.invoice_labels[key].setVisible(not client_mode)
            getattr(self, key).setVisible(not client_mode)
        self.save_invoice_button.setVisible(not client_mode)
        self.create_receipt_button.setVisible(not client_mode)
        self.batch_invoice_button.setVisible(client_mode)
        # In collections client mode hide secondary fields so date pickers are prominent
        hide_in_collections = collections_mode and client_mode
        for key in ('invoice_mode', 'invoice_number', 'invoice_total', 'invoice_cfdi_use',
                    'invoice_payment_form', 'invoice_payment_method', 'invoice_currency'):
            self.invoice_labels[key].setVisible(not hide_in_collections)
            getattr(self, key).setVisible(not hide_in_collections)
        self.invoice_filter_labels['invoice_filter_client'].setText(tr('Client') if client_mode else tr('Client Filter'))
        self.invoice_info.setText(
            tr('Select a client and date range, then create a printable invoice that can be exported as PDF or sent through WhatsApp.')
            if client_mode
            else tr('Create invoice or receipt records for individual orders.')
        )
        self._relayout_invoice_buttons()

    def _relayout_invoice_buttons(self) -> None:
        """Lay out only the visible action buttons in rows of four.

        Mode toggles hide some buttons (e.g. Save Invoice / Create Receipt in
        client mode). Re-adding just the visible ones keeps the grid gap-free
        instead of leaving empty cells where hidden buttons would sit.
        """
        grid = self._invoice_button_grid
        while grid.count():
            grid.takeAt(0)
        columns = 4
        visible = [button for button in self._invoice_buttons if not button.isHidden()]
        for index, button in enumerate(visible):
            grid.addWidget(button, index // columns, index % columns)

    def refresh_billing_table(self) -> None:
        query = self.billing_search.text().strip().lower()
        rows = []
        self.filtered_billing_records = []
        for record in self.billing_records:
            if self.billing_status_filter == 'active' and not record.is_active:
                continue
            if self.billing_status_filter == 'archived' and record.is_active:
                continue
            haystack = ' '.join([record.name, record.phone or '', record.email or '']).lower()
            if query and query not in haystack:
                continue
            self.filtered_billing_records.append(record)
            rows.append((record.name, record.phone or '', record.email or '', tr('Active') if record.is_active else tr('Archived'), f'{record.outstanding_balance:.2f}', str(record.invoice_count)))
        self.set_table_rows(self.billing_table, rows)

    def _change_billing_filter(self) -> None:
        self.billing_status_filter = str(self.billing_filter_combo.currentData() or 'active')
        self.refresh_billing_table()

    def refresh_doctor_table(self) -> None:
        query = self.doctor_search.text().strip().lower()
        rows = []
        self.filtered_doctor_records = []
        for record in self.doctor_records:
            if self.doctor_status_filter == 'active' and not record.is_active:
                continue
            if self.doctor_status_filter == 'archived' and record.is_active:
                continue
            haystack = ' '.join([record.full_name, record.license_number or '', record.phone or '', record.email or '']).lower()
            if query and query not in haystack:
                continue
            self.filtered_doctor_records.append(record)
            rows.append((record.full_name, record.license_number or '', record.phone or '', record.email or '', tr('Active') if record.is_active else tr('Archived')))
        self.set_table_rows(self.doctor_table, rows)

    def _change_doctor_filter(self) -> None:
        self.doctor_status_filter = str(self.doctor_filter_combo.currentData() or 'active')
        self.refresh_doctor_table()

    @staticmethod
    def _is_low_stock(record: InventoryItemRecord) -> bool:
        return float(record.reorder_level) > 0 and float(record.on_hand) <= float(record.reorder_level)

    def refresh_inventory_table(self) -> None:
        query = self.inventory_search.text().strip().lower()
        self.filtered_inventory_records = [
            record for record in self.inventory_records
            if not query or query in ' '.join([record.sku, record.name, record.unit or '']).lower()
        ]
        self.set_table_rows(self.inventory_table, [
            (r.sku, r.name, r.unit or '', self._format_decimal(r.on_hand), self._format_decimal(r.reorder_level), self._format_decimal(r.unit_cost))
            for r in self.filtered_inventory_records
        ])
        low_background = QBrush(QColor('#7a3030'))
        low_foreground = QBrush(QColor('#ffffff'))
        for row_index, record in enumerate(self.filtered_inventory_records):
            if not self._is_low_stock(record):
                continue
            for column in range(self.inventory_table.columnCount()):
                cell = self.inventory_table.item(row_index, column)
                if cell is not None:
                    cell.setBackground(low_background)
                    cell.setForeground(low_foreground)
        total_value = sum(float(r.on_hand) * float(r.unit_cost) for r in self.inventory_records)
        low_count = sum(1 for r in self.inventory_records if self._is_low_stock(r))
        reorder_text = (
            tr('{count} items need reordering', count=str(low_count))
            if low_count
            else tr('All items above reorder level')
        )
        self.inventory_summary_label.setText(
            tr('Total inventory value: {value}', value=self._format_decimal(total_value)) + '  •  ' + reorder_text
        )

    def refresh_supplier_table(self) -> None:
        self.filtered_supplier_records = list(self.supplier_records)
        self.set_table_rows(self.supplier_table, [(r.name, r.tax_id or '', r.phone or '', r.email or '') for r in self.filtered_supplier_records])

    def refresh_movement_table(self) -> None:
        self.set_table_rows(self.movement_table, [(r.inventory_name, r.supplier_name or '', self._format_movement_type(r.movement_type), self._format_decimal(r.quantity), self._format_decimal(r.unit_cost), r.movement_date) for r in self.movement_records[:25]])

    def refresh_invoice_table(self) -> None:
        self.set_table_rows(self.invoice_table, [(r.invoice_number, r.client_name or '', r.invoice_date, self._format_invoice_status(r.status), self._format_decimal(r.total_amount), r.order_number or '') for r in self.invoice_records[:25]])

    def refresh_receipt_table(self) -> None:
        self.set_table_rows(self.receipt_table, [(r.receipt_number, r.order_number, r.client_name or '', r.patient_name, r.receipt_date, self._format_decimal(r.total_amount)) for r in self.receipt_records[:25]])

    def _update_invoice_preview(self) -> None:
        if not hasattr(self, 'invoice_preview'):
            return
        row = self.invoice_table.currentRow()
        if row < 0 or row >= min(25, len(self.invoice_records)):
            self.invoice_preview.clear()
            return
        self.invoice_preview.setHtml(self._build_invoice_html(self.invoice_records[row]))

    def open_client_dialog(self) -> None:
        dialog = ClientDialog(self.database, self)
        if dialog.exec() == QDialog.Accepted and dialog.client_id is not None:
            self.refresh_data()
            self.notify_data_changed()

    def edit_selected_client(self) -> None:
        row = self.billing_table.currentRow()
        if row < 0 or row >= len(self.filtered_billing_records):
            QMessageBox.warning(self, tr('Missing Selection'), tr('Select a customer first.'))
            return
        client_id = self.filtered_billing_records[row].id
        dialog = ClientDialog(self.database, self, client_id=client_id)
        if dialog.exec() == QDialog.Accepted and dialog.client_id is not None:
            self.refresh_data()
            self.notify_data_changed()

    def open_doctor_dialog(self) -> None:
        dialog = DoctorDialog(self.database, self)
        if dialog.exec() == QDialog.Accepted and dialog.doctor_id is not None:
            self.refresh_data()
            self.notify_data_changed()

    def edit_selected_doctor(self) -> None:
        row = self.doctor_table.currentRow()
        if row < 0 or row >= len(self.filtered_doctor_records):
            QMessageBox.warning(self, tr('Missing Selection'), tr('Select a doctor first.'))
            return
        doctor_id = self.filtered_doctor_records[row].id
        dialog = DoctorDialog(self.database, self, doctor_id=doctor_id)
        if dialog.exec() == QDialog.Accepted and dialog.doctor_id is not None:
            self.refresh_data()
            self.notify_data_changed()

    def save_inventory_item(self) -> None:
        if not self.inventory_sku.text().strip() or not self.inventory_name.text().strip():
            QMessageBox.warning(self, tr('Missing Data'), tr('SKU and inventory name are required.'))
            return
        try:
            payload = {
                'sku': self.inventory_sku.text(),
                'name': self.inventory_name.text(),
                'unit': self.inventory_unit.text(),
                'on_hand': self._parse_decimal(self.inventory_on_hand.text()),
                'reorder_level': self._parse_decimal(self.inventory_reorder.text()),
                'unit_cost': self._parse_decimal(self.inventory_cost.text()),
            }
            if self.editing_inventory_id is not None:
                self.database.update_inventory_item(self.editing_inventory_id, payload)
            else:
                self.database.create_inventory_item(payload)
        except ValueError:
            QMessageBox.warning(self, tr('Invalid Data'), tr('Inventory quantities and cost must be numeric.'))
            return
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr('Save Failed'), str(exc))
            return
        self.clear_inventory_form()
        self.refresh_data()
        self.notify_data_changed()

    def load_inventory_item_for_edit(self, row: int) -> None:
        if row < 0 or row >= len(self.filtered_inventory_records):
            return
        record = self.filtered_inventory_records[row]
        self.editing_inventory_id = record.id
        self.inventory_sku.setText(record.sku)
        self.inventory_name.setText(record.name)
        self.inventory_unit.setText(record.unit or '')
        self.inventory_on_hand.setText(self._format_decimal(record.on_hand))
        self.inventory_reorder.setText(self._format_decimal(record.reorder_level))
        self.inventory_cost.setText(self._format_decimal(record.unit_cost))
        self._update_inventory_form_mode()

    def clear_inventory_form(self) -> None:
        self.editing_inventory_id = None
        for field, value in [(self.inventory_sku, ''), (self.inventory_name, ''), (self.inventory_unit, ''), (self.inventory_on_hand, '0'), (self.inventory_reorder, '0'), (self.inventory_cost, '0')]:
            field.setText(value)
        self.inventory_table.clearSelection()
        self._update_inventory_form_mode()

    def delete_selected_inventory_item(self) -> None:
        if self.editing_inventory_id is None:
            QMessageBox.warning(self, tr('Missing Selection'), tr('Select an inventory item first.'))
            return
        if self.database.inventory_item_has_movements(self.editing_inventory_id):
            QMessageBox.warning(self, tr('Delete Failed'), tr('This item has stock movements and cannot be deleted.'))
            return
        confirm = QMessageBox.question(self, tr('Delete Inventory Item'), tr('Delete this inventory item?'), QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        self.database.delete_inventory_item(self.editing_inventory_id)
        self.clear_inventory_form()
        self.refresh_data()
        self.notify_data_changed()

    def _update_inventory_form_mode(self) -> None:
        editing = self.editing_inventory_id is not None
        self.save_inventory_button.setText(tr('Update Inventory Item') if editing else tr('Save Inventory Item'))
        self.delete_inventory_button.setVisible(editing)

    def save_supplier(self) -> None:
        if not self.supplier_name.text().strip():
            QMessageBox.warning(self, tr('Missing Data'), tr('Supplier name is required.'))
            return
        try:
            payload = {'name': self.supplier_name.text(), 'tax_id': self.supplier_tax_id.text(), 'phone': self.supplier_phone.text(), 'email': self.supplier_email.text()}
            if self.editing_supplier_id is not None:
                self.database.update_supplier(self.editing_supplier_id, payload)
            else:
                self.database.create_supplier(payload)
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr('Save Failed'), str(exc))
            return
        self.clear_supplier_form()
        self.refresh_data()
        self.notify_data_changed()

    def load_supplier_for_edit(self, row: int) -> None:
        if row < 0 or row >= len(self.filtered_supplier_records):
            return
        record = self.filtered_supplier_records[row]
        self.editing_supplier_id = record.id
        self.supplier_name.setText(record.name)
        self.supplier_tax_id.setText(record.tax_id or '')
        self.supplier_phone.setText(record.phone or '')
        self.supplier_email.setText(record.email or '')
        self._update_supplier_form_mode()

    def clear_supplier_form(self) -> None:
        self.editing_supplier_id = None
        for field in [self.supplier_name, self.supplier_tax_id, self.supplier_phone, self.supplier_email]:
            field.clear()
        self.supplier_table.clearSelection()
        self._update_supplier_form_mode()

    def delete_selected_supplier(self) -> None:
        if self.editing_supplier_id is None:
            QMessageBox.warning(self, tr('Missing Selection'), tr('Select a supplier first.'))
            return
        if self.database.supplier_has_movements(self.editing_supplier_id):
            QMessageBox.warning(self, tr('Delete Failed'), tr('This supplier is used by stock movements and cannot be deleted.'))
            return
        confirm = QMessageBox.question(self, tr('Delete Supplier'), tr('Delete this supplier?'), QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        self.database.delete_supplier(self.editing_supplier_id)
        self.clear_supplier_form()
        self.refresh_data()
        self.notify_data_changed()

    def _update_supplier_form_mode(self) -> None:
        editing = self.editing_supplier_id is not None
        self.save_supplier_button.setText(tr('Update Supplier') if editing else tr('Save Supplier'))
        self.delete_supplier_button.setVisible(editing)

    def save_inventory_movement(self) -> None:
        if self.movement_inventory.currentData() is None:
            QMessageBox.warning(self, tr('Missing Data'), tr('Select inventory item'))
            return
        try:
            self.database.create_inventory_movement({'inventory_item_id': self.movement_inventory.currentData(), 'supplier_id': self.movement_supplier.currentData(), 'movement_type': self.movement_type.currentData(), 'quantity': self._parse_decimal(self.movement_quantity.text()), 'unit_cost': self._parse_decimal(self.movement_cost.text()), 'movement_date': self.movement_date.date().toString('yyyy-MM-dd'), 'notes': self.movement_notes.text()})
        except ValueError:
            QMessageBox.warning(self, tr('Invalid Data'), tr('Inventory quantities and cost must be numeric.'))
            return
        self.movement_quantity.setText('0')
        self.movement_cost.setText('0')
        self.movement_notes.clear()
        self.refresh_data()
        self.notify_data_changed()

    def sync_invoice_client_defaults(self) -> None:
        client_id = self.invoice_client.currentData()
        if client_id is None:
            return
        client = self.database.get_client(client_id)
        if client is None:
            return
        if client.cfdi_use:
            cfdi_index = self.invoice_cfdi_use.findData(client.cfdi_use)
            if cfdi_index >= 0:
                self.invoice_cfdi_use.setCurrentIndex(cfdi_index)

    def sync_invoice_total_from_order(self) -> None:
        order_id = self.invoice_order.currentData()
        if order_id is None:
            return
        self.invoice_total.setText(self._format_decimal(self.database.calculate_order_total(order_id)))
        client_id = self.database.get_order_client_id(int(order_id))
        if client_id is not None:
            client_index = self.invoice_client.findData(client_id)
            if client_index >= 0:
                self.invoice_client.setCurrentIndex(client_index)

    def sync_receipt_total_from_order(self) -> None:
        order_id = self.receipt_order.currentData()
        if order_id is None:
            return
        self.invoice_total.setText(self._format_decimal(self.database.calculate_order_total(order_id)))

    def clear_invoice_filters(self) -> None:
        today = QDate.currentDate()
        filter_widgets = (self.invoice_filter_client, self.invoice_filter_date_from, self.invoice_filter_date_to)
        for widget in filter_widgets:
            widget.blockSignals(True)
        self.invoice_filter_client.setCurrentIndex(0)
        self.invoice_filter_date_from.setDate(today.addMonths(-1))
        self.invoice_filter_date_to.setDate(today)
        for widget in filter_widgets:
            widget.blockSignals(False)
        self.refresh_choices()

    def save_invoice(self) -> None:
        if self.invoice_client.currentData() is None:
            QMessageBox.warning(self, tr('Missing Data'), tr('Select client'))
            return
        if self.invoice_order.currentData() is None:
            QMessageBox.warning(self, tr('Missing Data'), tr('Select an order for the invoice.'))
            return
        try:
            total_amount = self._parse_decimal(self.invoice_total.text())
        except ValueError:
            QMessageBox.warning(self, tr('Invalid Data'), tr('Invoice total must be numeric.'))
            return
        try:
            self.database.create_invoice({'client_id': self.invoice_client.currentData(), 'order_id': self.invoice_order.currentData(), 'invoice_date': self.invoice_date.text().strip(), 'status': self.invoice_status.currentData(), 'total_amount': total_amount, 'notes': self.invoice_notes.toPlainText(), 'cfdi_use': self.invoice_cfdi_use.currentData(), 'payment_form': self.invoice_payment_form.currentData(), 'payment_method': self.invoice_payment_method.currentData(), 'currency': self.invoice_currency.text().strip() or 'MXN'})
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr('Save Failed'), str(exc))
            return
        self.invoice_date.setText(date.today().isoformat())
        self.invoice_notes.clear()
        self.invoice_total.setText('0.00')
        self.invoice_order.setCurrentIndex(0)
        self.receipt_order.setCurrentIndex(0)
        self.invoice_client.setCurrentIndex(0)
        self.invoice_cfdi_use.setCurrentIndex(0)
        self.invoice_payment_form.setCurrentIndex(0)
        self.invoice_payment_method.setCurrentIndex(0)
        self.invoice_currency.setText('MXN')
        self.refresh_data()
        self.notify_data_changed()

    def create_filtered_invoices(self) -> None:
        if self.invoice_filter_client.currentData() is None:
            QMessageBox.warning(self, tr('Missing Data'), tr('Select a client before creating a client invoice.'))
            return
        client_id = self.invoice_filter_client.currentData()
        date_from = self._filter_date_value(self.invoice_filter_date_from)
        date_to = self._filter_date_value(self.invoice_filter_date_to)
        choices = self.database.list_filtered_invoice_order_choices(
            client_id=client_id,
            date_from=date_from,
            date_to=date_to,
        )
        if not choices:
            all_choices = self.database.list_filtered_invoice_order_choices(
                client_id=client_id,
                date_from=date_from,
                date_to=date_to,
                exclude_invoiced=False,
            )
            if all_choices:
                QMessageBox.information(self, tr('No Matches'), tr('All orders for this client in the selected date range already have invoices.'))
            else:
                QMessageBox.information(self, tr('No Matches'), tr('No orders found for this client in the selected date range. Make sure orders have the correct client assigned.'))
            return
        created, linked_orders, skipped = self.database.create_client_invoices_for_orders(
            [int(order_id) for order_id, _label in choices],
            invoice_date=self.invoice_date.text().strip(),
            status=str(self.invoice_status.currentData() or 'issued'),
            notes=self.invoice_notes.toPlainText(),
            payment_form=str(self.invoice_payment_form.currentData() or ''),
            payment_method=str(self.invoice_payment_method.currentData() or ''),
            currency=self.invoice_currency.text().strip() or 'MXN',
        )
        self.refresh_data()
        if created and self.invoice_table.rowCount() > 0:
            self.invoice_table.selectRow(0)
        self.notify_data_changed()
        if skipped:
            QMessageBox.information(
                self,
                tr('Completed'),
                tr('Created {created} client invoices for {orders} orders and skipped {skipped}.', created=str(created), orders=str(linked_orders), skipped=str(skipped)),
            )
            return
        QMessageBox.information(self, tr('Saved'), tr('Created {created} client invoices for {orders} orders.', created=str(created), orders=str(linked_orders)))

    def create_receipt_for_selected_order(self) -> None:
        order_id = self.receipt_order.currentData()
        if order_id is None:
            QMessageBox.warning(self, tr('Missing Selection'), tr('Select an order for the receipt.'))
            return
        try:
            self.database.create_receipt_for_order(
                int(order_id),
                receipt_date=self.invoice_date.text().strip(),
                notes=self.invoice_notes.toPlainText(),
                payment_form=str(self.invoice_payment_form.currentData() or ''),
                payment_method=str(self.invoice_payment_method.currentData() or ''),
                currency=self.invoice_currency.text().strip() or 'MXN',
            )
        except (sqlite3.IntegrityError, ValueError) as exc:
            QMessageBox.critical(self, tr('Save Failed'), str(exc))
            return
        self.receipt_order.setCurrentIndex(0)
        self.invoice_notes.clear()
        self.invoice_total.setText('0.00')
        self.refresh_data()
        self.notify_data_changed()
        QMessageBox.information(self, tr('Saved'), tr('Receipt created for the selected order.'))

    def export_selected_invoice_cfdi(self) -> None:
        row = self.invoice_table.currentRow()
        if row < 0 or row >= min(25, len(self.invoice_records)):
            QMessageBox.warning(self, tr('Missing Selection'), tr('Select an invoice to export.'))
            return
        invoice = self.invoice_records[row]
        if invoice.client_id is None:
            QMessageBox.warning(self, tr('Missing Data'), tr('The selected invoice does not have a customer.'))
            return
        client = self.database.get_client(invoice.client_id)
        if client is None:
            QMessageBox.warning(self, tr('Missing Data'), tr('The selected invoice customer could not be loaded.'))
            return
        path, _ = QFileDialog.getSaveFileName(self, tr('Save CFDI Preview XML'), f'{invoice.invoice_number}.xml', tr('XML File (*.xml)'))
        if not path:
            return
        target = write_cfdi_preview_xml(path, settings=self.database.get_lab_settings(), client=client, invoice=invoice)
        QMessageBox.information(self, tr('Saved'), tr('CFDI preview saved: {path}', path=str(target)))

    def print_selected_invoice(self) -> None:
        invoice = self._selected_invoice()
        if invoice is None:
            return
        document = QTextDocument()
        document.setHtml(self._build_invoice_html(invoice))
        printer = QPrinter(QPrinter.ScreenResolution)
        preview = QPrintPreviewDialog(printer, self)
        preview.paintRequested.connect(getattr(document, 'print', None) or document.print_)
        preview.exec()

    def export_selected_invoice_pdf(self) -> None:
        invoice = self._selected_invoice()
        if invoice is None:
            return
        default_name = self._invoice_pdf_path(invoice).name
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Save Invoice PDF'), default_name, tr('PDF File (*.pdf)')
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != '.pdf':
            target = target.with_suffix('.pdf')
        try:
            target = self._export_invoice_pdf(invoice, target)
        except Exception as exc:  # noqa: BLE001 - surface any export failure to the user
            QMessageBox.critical(self, tr('Export Failed'), tr('Could not export the invoice PDF: {error}', error=str(exc)))
            return
        QMessageBox.information(self, tr('Saved'), tr('Invoice PDF saved: {path}', path=str(target)))

    def send_selected_invoice_whatsapp(self) -> None:
        invoice = self._selected_invoice()
        if invoice is None:
            return
        if invoice.client_id is None:
            QMessageBox.warning(self, tr('Missing Data'), tr('The selected invoice does not have a customer.'))
            return
        client = self.database.get_client(invoice.client_id)
        if client is None or not (client.phone or '').strip():
            QMessageBox.warning(self, tr('Missing Data'), tr('The selected customer does not have a phone number.'))
            return
        path = self._export_invoice_pdf(invoice)
        message = tr(
            'Hello {name}, here is invoice {invoice_number} for {amount} {currency}. PDF: {path}',
            name=client.name,
            invoice_number=invoice.invoice_number,
            amount=self._format_decimal(invoice.total_amount),
            currency=invoice.currency or 'MXN',
            path=str(path),
        )
        phone = normalize_whatsapp_phone(client.phone, self.database.get_whatsapp_country_code())
        if not phone:
            QMessageBox.warning(self, tr('Missing Data'), tr('The selected customer phone number is not valid for WhatsApp.'))
            return
        if not QDesktopServices.openUrl(QUrl(f'https://wa.me/{phone}?text={quote(message)}')):
            QMessageBox.warning(self, tr('Open Failed'), tr('Could not open WhatsApp.'))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def export_selected_invoice_excel(self) -> None:
        invoice = self._selected_invoice()
        if invoice is None:
            return
        order_panels = self.database.list_invoice_order_panels(invoice.id)
        safe_number = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in invoice.invoice_number)
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Save Invoice Excel'), f'{safe_number}.xlsx', tr('Excel Workbook (*.xlsx)')
        )
        if not path:
            return
        sheets = build_invoice_excel_sheet(
            invoice_number=invoice.invoice_number,
            client_name=invoice.client_name or '',
            invoice_date=invoice.invoice_date,
            status=self._format_invoice_status(invoice.status),
            total=self._format_decimal(invoice.total_amount),
            orders=order_panels,
        )
        target = write_admin_export_workbook(path, sheets)
        QMessageBox.information(self, tr('Saved'), tr('Invoice exported: {path}', path=str(target)))

    def delete_selected_invoice(self) -> None:
        invoice = self._selected_invoice()
        if invoice is None:
            return
        confirm = QMessageBox.question(
            self,
            tr('Delete Invoice'),
            tr(
                'Permanently delete invoice {number}? Its orders will become available to '
                'invoice again. This cannot be undone.',
                number=invoice.invoice_number,
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        if not self.database.delete_invoice(invoice.id):
            QMessageBox.warning(self, tr('Delete Failed'), tr('The invoice could not be found.'))
            return
        self.refresh_data()
        self.notify_data_changed()
        QMessageBox.information(self, tr('Deleted'), tr('Invoice {number} deleted.', number=invoice.invoice_number))

    def _selected_invoice(self) -> InvoiceRecord | None:
        row = self.invoice_table.currentRow()
        if row < 0 or row >= min(25, len(self.invoice_records)):
            QMessageBox.warning(self, tr('Missing Selection'), tr('Select an invoice first.'))
            return None
        return self.invoice_records[row]

    def _export_invoice_pdf(self, invoice: InvoiceRecord, target: Path | None = None) -> Path:
        path = target if target is not None else self._invoice_pdf_path(invoice)
        path.parent.mkdir(parents=True, exist_ok=True)
        # ScreenResolution (96 DPI) renders the HTML's px units at their intended
        # CSS size. HighResolution makes QTextDocument emit px values verbatim as
        # point sizes and then scale the page by ~0.06, collapsing fonts to ~0.7pt.
        printer = QPrinter(QPrinter.ScreenResolution)
        printer.setPageSize(QPageSize(QPageSize.A4))
        printer.setPageMargins(QMarginsF(8, 8, 8, 8), QPageLayout.Millimeter)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(str(path))
        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setHtml(self._build_invoice_html(invoice))
        print_document = getattr(document, 'print', None) or document.print_
        print_document(printer)
        return path

    def _invoice_pdf_path(self, invoice: InvoiceRecord) -> Path:
        safe_invoice = ''.join(character if character.isalnum() or character in ('-', '_') else '_' for character in invoice.invoice_number)
        safe_client = ''.join(character if character.isalnum() or character in ('-', '_') else '_' for character in (invoice.client_name or 'client'))
        return self.database.db_path.parent / 'exports' / 'invoices' / f'{safe_invoice}_{safe_client}.pdf'

    def _invoice_logo_html(self, logo_path: str) -> str:
        """Return an <img> for the report logo as a base64 data URI.

        Falls back to the bundled brand logo when the lab profile has no logo
        configured. Embedding the bytes keeps the image visible when the HTML is
        rendered by QTextDocument for PDF export.
        """
        candidates: list[Path] = []
        if logo_path:
            value = str(logo_path).strip()
            if value.startswith("file:///"):
                value = value.removeprefix("file:///")
            if value and not value.startswith(("http://", "https://")):
                candidates.append(Path(value))
        candidates.append(Path(__file__).resolve().parent.parent / "assets" / "SDXpurple.png")
        for candidate in candidates:
            if not candidate.exists():
                continue
            mime = mimetypes.guess_type(candidate.name)[0] or "image/png"
            data = base64.b64encode(candidate.read_bytes()).decode("ascii")
            return f'<img class="logo" height="56" src="data:{mime};base64,{data}">'
        return ""

    def _build_invoice_html(self, invoice: InvoiceRecord) -> str:
        settings = self.database.get_lab_settings()
        currency = escape(invoice.currency or "MXN")
        logo_html = self._invoice_logo_html(getattr(settings, "logo_path", "") or "")

        # --- Page 1: breakdown by panel ---------------------------------
        # Pricing is per panel. Group the per-order panel prices into one line
        # per (panel, price): "BH  29 x $price = subtotal".
        panel_rows = self.database.list_invoice_order_panels(invoice.id)
        summary: dict[tuple[str, float], int] = {}
        for row in panel_rows:
            name = str(row.get('panel') or tr('Panel'))
            price = float(row.get('panel_total') or 0)
            summary[(name, price)] = summary.get((name, price), 0) + 1

        breakdown_rows = ''.join(
            '<tr>'
            f'<td>{escape(name)}</td>'
            f'<td style="text-align:right;">{count}</td>'
            f'<td style="text-align:right;">{self._format_decimal(price)}</td>'
            f'<td style="text-align:right;">{self._format_decimal(price * count)}</td>'
            '</tr>'
            for (name, price), count in sorted(summary.items(), key=lambda item: item[0][0].lower())
        )
        if not breakdown_rows:
            breakdown_rows = f'<tr><td colspan="4">{escape(tr("No linked orders found."))}</td></tr>'

        # Grand total = sum of the panel breakdown lines (kept consistent with
        # what is printed on the page, independent of the stored total).
        grand_total = sum(price * count for (_name, price), count in summary.items())

        # --- Detail pages: every single test (informational listing) -----
        tests = self.database.list_invoice_tests(invoice.id)
        panel_details: list[tuple[str, str, str, str]] = []
        seen_panels: set[tuple[str, str, str, str]] = set()
        for test in tests:
            row = (
                str(test.get("order_number") or ""),
                str(test.get("order_date") or ""),
                str(test.get("patient_name") or ""),
                str(test.get("panel") or ""),
            )
            if row in seen_panels:
                continue
            seen_panels.add(row)
            panel_details.append(row)
        detail_rows = ''.join(
            '<tr>'
            f'<td>{escape(order_number)}</td>'
            f'<td>{escape(order_date)}</td>'
            f'<td>{escape(patient_name)}</td>'
            f'<td>{escape(panel)}</td>'
            '</tr>'
            for order_number, order_date, patient_name, panel in panel_details
        )
        if not detail_rows:
            detail_rows = f'<tr><td colspan="4">{escape(tr("No linked orders found."))}</td></tr>'

        return f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; color: #111827; }}
                .header {{ border-bottom: 2px solid #7c3aed; padding-bottom: 12px; margin-bottom: 18px; }}
                .logo {{ height: 56px; margin-bottom: 6px; }}
                .brand {{ font-size: 26px; font-weight: 700; color: #111827; }}
                .meta {{ color: #4b5563; font-size: 11px; }}
                .grid {{ display: table; width: 100%; margin-bottom: 16px; }}
                .cell {{ display: table-cell; width: 50%; vertical-align: top; }}
                h1 {{ font-size: 20px; margin: 0 0 8px 0; }}
                h2 {{ font-size: 15px; margin: 18px 0 4px 0; color: #374151; }}
                table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
                th {{ background: #ede9fe; text-align: left; }}
                th, td {{ border: 1px solid #d1d5db; padding: 7px; font-size: 11px; }}
                .total {{ font-size: 20px; font-weight: 700; color: #111827; margin: 6px 0 4px 0; }}
                .detail {{ page-break-before: always; }}
                .notes {{ margin-top: 18px; white-space: pre-wrap; color: #374151; }}
            </style>
        </head>
        <body>
            <div class="header">
                {logo_html}
                <div class="brand">{escape(settings.lab_name or "SDX")}</div>
                <div class="meta">{escape(settings.address or "")}</div>
                <div class="meta">{escape(settings.phone or "")} {escape(settings.email or "")}</div>
            </div>
            <div class="grid">
                <div class="cell">
                    <h1>{escape(tr("Invoice"))} {escape(invoice.invoice_number)}</h1>
                    <div>{escape(tr("Customer"))}: {escape(invoice.client_name or "")}</div>
                    <div>{escape(tr("Date"))}: {escape(invoice.invoice_date or "")}</div>
                    <div>{escape(tr("Status"))}: {escape(self._format_invoice_status(invoice.status))}</div>
                </div>
                <div class="cell">
                    <div>{escape(tr("Currency"))}: {currency}</div>
                    <div>{escape(tr("Payment Form"))}: {escape(invoice.payment_form or "")}</div>
                    <div>{escape(tr("Payment Method"))}: {escape(invoice.payment_method or "")}</div>
                    <div>{escape(tr("CFDI Use"))}: {escape(invoice.cfdi_use or "")}</div>
                </div>
            </div>
            <div class="total">{escape(tr("Total"))}: {self._format_decimal(grand_total)} {currency}</div>
            <h2>{escape(tr("Breakdown by Panel"))}</h2>
            <table width="100%" cellspacing="0">
                <thead>
                    <tr>
                        <th>{escape(tr("Panel"))}</th>
                        <th style="text-align:right;">{escape(tr("Quantity"))}</th>
                        <th style="text-align:right;">{escape(tr("Unit Price"))}</th>
                        <th style="text-align:right;">{escape(tr("Subtotal"))}</th>
                    </tr>
                </thead>
                <tbody>{breakdown_rows}</tbody>
            </table>
            <div class="detail">
                <h2>{escape(tr("Test Detail"))}</h2>
                <table width="100%" cellspacing="0">
                    <thead>
                        <tr>
                            <th>{escape(tr("Order"))}</th>
                            <th>{escape(tr("Date"))}</th>
                            <th>{escape(tr("Patient"))}</th>
                            <th>{escape(tr("Panel"))}</th>
                        </tr>
                    </thead>
                    <tbody>{detail_rows}</tbody>
                </table>
            </div>
            <div class="notes">{escape(invoice.notes or "")}</div>
        </body>
        </html>
        """

    def export_admin_workbook(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr('Save Administrative Export'), 'administrative_export.xlsx', tr('Excel Workbook (*.xlsx)'))
        if not path:
            return
        sheets = build_admin_export_sheets(
            [(r.name, r.phone or '', r.email or '', f'{r.outstanding_balance:.2f}', str(r.invoice_count)) for r in self.billing_records],
            [(r.sku, r.name, r.unit or '', self._format_decimal(r.on_hand), self._format_decimal(r.reorder_level), self._format_decimal(r.unit_cost)) for r in self.inventory_records],
            [(r.invoice_number, r.client_name or '', r.invoice_date, self._format_invoice_status(r.status), self._format_decimal(r.total_amount), r.order_number or '', r.notes or '') for r in self.invoice_records],
            [(r.name, r.tax_id or '', r.phone or '', r.email or '') for r in self.supplier_records],
            [(r.inventory_name, r.supplier_name or '', self._format_movement_type(r.movement_type), self._format_decimal(r.quantity), self._format_decimal(r.unit_cost), r.movement_date) for r in self.movement_records],
        )
        target = write_admin_export_workbook(path, sheets)
        self.export_status.setText(tr('Administrative export saved: {path}', path=str(target)))
        QMessageBox.information(self, tr('Saved'), tr('Administrative export saved: {path}', path=str(target)))

    @staticmethod
    def _parse_decimal(value: str) -> float:
        cleaned = value.strip().replace(',', '.')
        return float(cleaned) if cleaned else 0.0

    @staticmethod
    def _format_decimal(value: float) -> str:
        return f'{value:.2f}'

    @staticmethod
    def _format_invoice_status(status: str) -> str:
        return tr({'draft': 'Draft', 'issued': 'Issued', 'paid': 'Paid', 'cancelled': 'Cancelled'}.get(status, status))

    @staticmethod
    def _format_movement_type(status: str) -> str:
        return tr({'purchase': 'Purchase', 'adjustment_in': 'Adjustment In', 'adjustment_out': 'Adjustment Out', 'consumption': 'Consumption'}.get(status, status))

    def _filter_date_value(self, widget: QDateEdit) -> str:
        if widget.date() <= self.FILTER_DATE_MIN:
            return ''
        return widget.date().toString('yyyy-MM-dd')
