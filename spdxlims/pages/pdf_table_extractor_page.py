from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database
from spdxlims.i18n import get_language, tr
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.pdf_table_extractor_library import (
    DetectedTable,
    PdfLibrary,
)

EXTERNAL_PDF_APP_ROOT = Path(r"C:\SDXPDFTableExtractor")


def _ensure_qtawesome_stub() -> None:
    if "qtawesome" in sys.modules:
        return
    module = types.ModuleType("qtawesome")
    module.icon = lambda *args, **kwargs: QIcon()
    sys.modules["qtawesome"] = module


def _load_external_workspace_page():
    if not EXTERNAL_PDF_APP_ROOT.exists():
        return None
    project_root = str(EXTERNAL_PDF_APP_ROOT)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    _ensure_qtawesome_stub()
    try:
        module = importlib.import_module("ui.pages.page_workspace")
    except Exception:  # noqa: BLE001
        return None
    return getattr(module, "WorkspacePage", None)


def _load_external_main_window_class():
    if not EXTERNAL_PDF_APP_ROOT.exists():
        return None
    project_root = str(EXTERNAL_PDF_APP_ROOT)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    _ensure_qtawesome_stub()
    try:
        module = importlib.import_module("ui.main_window")
    except Exception:  # noqa: BLE001
        return None
    return getattr(module, "MainWindow", None)


class LegacyPdfTableExtractorPage(DataAwarePage):
    def __init__(self, data_root: Path) -> None:
        super().__init__()
        self.library = PdfLibrary(data_root)
        self.current_document_path: str | None = None
        self.detected_tables: list[DetectedTable] = []

        root = QVBoxLayout(self)
        self.current_pdf_group = QGroupBox()
        current_pdf_layout = QFormLayout(self.current_pdf_group)
        self.current_pdf_name = QLabel()
        self.current_pdf_name.setWordWrap(True)
        self.current_pdf_pages = QLabel()
        self.current_pdf_source = QLabel()
        self.page_picker = QSpinBox()
        self.page_picker.setMinimum(1)
        self.page_picker.setMaximum(1)
        self.page_picker.valueChanged.connect(self._render_selected_page)
        current_pdf_layout.addRow(tr("Current PDF"), self.current_pdf_name)
        current_pdf_layout.addRow(tr("Pages"), self.current_pdf_pages)
        current_pdf_layout.addRow(tr("Source"), self.current_pdf_source)
        current_pdf_layout.addRow(tr("Preview Page"), self.page_picker)
        root.addWidget(self.current_pdf_group)

        actions_row = QHBoxLayout()
        self.import_button = QPushButton()
        self.import_button.clicked.connect(self._import_pdf)
        self.remove_button = QPushButton()
        self.remove_button.clicked.connect(self._remove_pdf)
        actions_row.addWidget(self.import_button)
        actions_row.addWidget(self.remove_button)
        actions_row.addStretch(1)
        root.addLayout(actions_row)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        self.preview_label = QLabel()
        self.preview_label.setObjectName("SectionTitle")
        preview_layout.addWidget(self.preview_label)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_image = QLabel()
        self.preview_image.setAlignment(Qt.AlignCenter)
        self.preview_scroll.setWidget(self.preview_image)
        preview_layout.addWidget(self.preview_scroll, 1)
        splitter.addWidget(preview_panel)

        results_panel = QWidget()
        results_layout = QVBoxLayout(results_panel)
        self.detected_label = QLabel()
        self.detected_label.setObjectName("SectionTitle")
        results_layout.addWidget(self.detected_label)
        self.tables_table = QTableWidget(0, 5)
        self.tables_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.tables_table.setSelectionMode(QTableWidget.SingleSelection)
        self.tables_table.itemSelectionChanged.connect(self._refresh_selected_table)
        self.tables_table.verticalHeader().setVisible(False)
        self.tables_table.horizontalHeader().setStretchLastSection(True)
        results_layout.addWidget(self.tables_table)
        self.table_data_label = QLabel()
        self.table_data_label.setObjectName("SectionTitle")
        results_layout.addWidget(self.table_data_label)
        self.table_data = QTableWidget(0, 0)
        self.table_data.verticalHeader().setVisible(False)
        self.table_data.horizontalHeader().setStretchLastSection(True)
        results_layout.addWidget(self.table_data, 1)
        splitter.addWidget(results_panel)
        splitter.setSizes([600, 700])
        root.addWidget(splitter, 1)

        self.retranslate_ui()
        self._load_current_document()

    def retranslate_ui(self) -> None:
        self.current_pdf_group.setTitle(tr("PDF Workspace"))
        self.import_button.setText(tr("Import PDF"))
        self.remove_button.setText(tr("Remove PDF"))
        self.preview_label.setText(tr("PDF Preview"))
        self.detected_label.setText(tr("Detected Tables"))
        self.table_data_label.setText(tr("Selected Table Data"))
        self.tables_table.setHorizontalHeaderLabels(
            [
                tr("Page"),
                tr("Table"),
                tr("Rows"),
                tr("Columns"),
                tr("Origin"),
            ]
        )

    def refresh_on_show(self) -> None:
        self._load_current_document()

    def _import_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Choose PDF"),
            "",
            tr("PDF File (*.pdf)"),
        )
        if not path:
            return
        imported = self.library.import_files([path])
        if not imported:
            QMessageBox.warning(self, tr("Import Failed"), tr("No valid PDF file was selected."))
            return
        self.detected_tables = []
        self._load_current_document()

    def _remove_pdf(self) -> None:
        if not self.current_document_path:
            return
        answer = QMessageBox.question(
            self,
            tr("Remove PDF"),
            tr("Remove the current PDF from the extractor workspace?"),
        )
        if answer != QMessageBox.Yes:
            return
        self.library.delete_document(self.current_document_path)
        self.detected_tables = []
        self._load_current_document()

    def _detect_tables(self) -> None:
        if not self.current_document_path:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Import a PDF first."))
            return
        try:
            self.detected_tables = self.library.detect_tables(self.current_document_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("Detection Failed"), str(exc))
            return
        self._refresh_table_list()
        self.library.append_extraction_log(
            "detect_tables",
            self.current_document_path,
            rows=sum(table.rows for table in self.detected_tables),
            columns=max((table.columns for table in self.detected_tables), default=0),
            detail=f"Detected {len(self.detected_tables)} table(s)",
        )

    def _load_current_document(self) -> None:
        records = self.library.list_documents()
        record = records[0] if records else None
        self.current_document_path = record.full_path if record is not None else None
        self.current_pdf_name.setText(Path(record.full_path).name if record is not None else tr("No PDF loaded."))
        self.current_pdf_pages.setText(str(record.page_count) if record is not None else "0")
        self.current_pdf_source.setText(record.original_source if record is not None else tr("No source"))
        self.page_picker.blockSignals(True)
        self.page_picker.setMaximum(max(1, record.page_count if record is not None else 1))
        self.page_picker.setValue(1)
        self.page_picker.blockSignals(False)
        self._refresh_table_list()
        self._render_selected_page()

    def _render_selected_page(self) -> None:
        if not self.current_document_path:
            self.preview_image.clear()
            self.preview_image.setText(tr("Import a PDF to preview it here."))
            return
        page_index = self.page_picker.value() - 1
        try:
            image_bytes, _page_size = self.library.render_page(self.current_document_path, page_index)
        except Exception as exc:  # noqa: BLE001
            self.preview_image.setText(str(exc))
            return
        pixmap = QPixmap()
        pixmap.loadFromData(image_bytes, "PNG")
        self.preview_image.setPixmap(
            pixmap.scaledToWidth(560, Qt.SmoothTransformation) if not pixmap.isNull() else QPixmap()
        )

    def _refresh_table_list(self) -> None:
        self.tables_table.setRowCount(len(self.detected_tables))
        for row_index, table in enumerate(self.detected_tables):
            values = [
                str(table.page_index + 1),
                str(table.table_index),
                str(table.rows),
                str(table.columns),
                table.method,
            ]
            for column_index, value in enumerate(values):
                self.tables_table.setItem(row_index, column_index, QTableWidgetItem(value))
        if self.detected_tables:
            self.tables_table.selectRow(0)
        else:
            self.table_data.clear()
            self.table_data.setRowCount(0)
            self.table_data.setColumnCount(0)

    def _selected_table(self) -> DetectedTable | None:
        row = self.tables_table.currentRow()
        if row < 0 or row >= len(self.detected_tables):
            return None
        return self.detected_tables[row]

    def _refresh_selected_table(self) -> None:
        table = self._selected_table()
        if table is None:
            self.table_data.clear()
            self.table_data.setRowCount(0)
            self.table_data.setColumnCount(0)
            return
        rows = table.data
        column_count = max((len(row) for row in rows), default=0)
        self.table_data.clear()
        self.table_data.setRowCount(len(rows))
        self.table_data.setColumnCount(column_count)
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                self.table_data.setItem(row_index, column_index, QTableWidgetItem(value))
        self.page_picker.blockSignals(True)
        self.page_picker.setValue(table.page_index + 1)
        self.page_picker.blockSignals(False)
        self._render_selected_page()

    def _export_selected_table(self, kind: str) -> None:
        table = self._selected_table()
        if table is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a detected table first."))
            return
        suffix = {"csv": ".csv", "xlsx": ".xlsx", "docx": ".docx"}[kind]
        filter_label = {
            "csv": tr("CSV File (*.csv)"),
            "xlsx": tr("Excel Workbook (*.xlsx)"),
            "docx": tr("Word File (*.docx)"),
        }[kind]
        destination, _ = QFileDialog.getSaveFileName(
            self,
            tr("Save Export"),
            str(self._default_export_path(table, suffix)),
            filter_label,
        )
        if not destination:
            return
        try:
            if kind == "csv":
                self.library.export_table_csv(table, destination)
            elif kind == "xlsx":
                self.library.export_table_xlsx(table, destination)
            else:
                self.library.export_table_docx(table, destination)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("Export Failed"), str(exc))
            return
        self.library.append_extraction_log(
            f"export_{kind}",
            table.document_path,
            page_label=str(table.page_index + 1),
            rows=table.rows,
            columns=table.columns,
            method=table.method,
            destination=destination,
        )
        QMessageBox.information(self, tr("Saved"), tr("Export saved: {path}", path=destination))

    def _default_export_path(self, table: DetectedTable, suffix: str) -> Path:
        return (
            self.library.root_dir
            / f"{Path(table.document_path).stem}_page_{table.page_index + 1}_table_{table.table_index}{suffix}"
        )


class PdfTableExtractorPage(DataAwarePage):
    def __init__(self, data_root: Path) -> None:
        super().__init__()
        self.data_root = data_root
        self.database = Database(data_root.parent.parent / "spdxlims.db")
        self._pending_target_selection: tuple[int, str] | None = None
        self._external_window = None
        self._external_workspace = None
        self._fallback_page = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        selector_group = QGroupBox()
        selector_layout = QFormLayout(selector_group)
        selector_group.setContentsMargins(0, 0, 0, 0)
        self.order_combo = QComboBox()
        self.order_combo.currentIndexChanged.connect(self._load_outsourced_panels_for_selected_order)
        self.outsourced_panel_combo = QComboBox()
        self.outsourced_panel_combo.setEnabled(False)
        selector_layout.addRow(tr("Order"), self.order_combo)
        selector_layout.addRow(tr("Outsourced Panel"), self.outsourced_panel_combo)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.save_to_outsourced_panel_button = QPushButton()
        self.save_to_outsourced_panel_button.clicked.connect(self._save_selected_table_to_outsourced_panel)
        button_row.addWidget(self.save_to_outsourced_panel_button)
        selector_layout.addRow("", button_row)
        selector_layout.setContentsMargins(12, 10, 12, 8)
        selector_layout.setVerticalSpacing(8)
        selector_layout.setHorizontalSpacing(10)
        self.selector_group = selector_group

        main_window_class = _load_external_main_window_class()
        if main_window_class is not None:
            self._external_window = main_window_class()
            embedded_drawer = getattr(self._external_window, "drawer", None)
            if embedded_drawer is not None:
                embedded_drawer.hide()
            embedded_root = self._external_window.takeCentralWidget()
            if embedded_root is not None:
                embedded_root.setParent(self)
                self._insert_selector_into_workspace(getattr(self._external_window, "workspace_page", None))
                root.addWidget(embedded_root)
                self.retranslate_ui()
                self._load_outsourced_orders()
                return

        workspace_page_class = _load_external_workspace_page()
        if workspace_page_class is not None:
            app_data_dir = EXTERNAL_PDF_APP_ROOT / "app_data"
            self._external_workspace = workspace_page_class(app_data_dir)
            self._insert_selector_into_workspace(self._external_workspace)
            root.addWidget(self._external_workspace)
        else:
            root.addWidget(selector_group)
            self._fallback_page = LegacyPdfTableExtractorPage(data_root)
            root.addWidget(self._fallback_page)

        self.retranslate_ui()
        self._load_outsourced_orders()

    def retranslate_ui(self) -> None:
        self.selector_group.setTitle(tr("Outsourced Report Target"))
        self.save_to_outsourced_panel_button.setText(tr("Save To Outsourced Panel"))
        if self._external_window is not None:
            language = "es" if get_language() == "es" else "en"
            apply_language = getattr(self._external_window, "apply_language", None)
            workspace_page = getattr(self._external_window, "workspace_page", None)
            set_language = getattr(workspace_page, "set_language", None) if workspace_page is not None else None
            if callable(set_language):
                set_language(language)
            if callable(apply_language):
                apply_language(language)
            self._hide_external_workspace_controls()
            QTimer.singleShot(0, self._hide_external_workspace_controls)
            QTimer.singleShot(150, self._hide_external_workspace_controls)
            return
        if self._external_workspace is not None:
            language = "es" if get_language() == "es" else "en"
            set_language = getattr(self._external_workspace, "set_language", None)
            apply_language = getattr(self._external_workspace, "apply_language", None)
            if callable(set_language):
                set_language(language)
            elif callable(apply_language):
                apply_language(language)
            self._hide_external_workspace_controls()
            QTimer.singleShot(0, self._hide_external_workspace_controls)
            QTimer.singleShot(150, self._hide_external_workspace_controls)
            return
        if self._fallback_page is not None:
            self._fallback_page.retranslate_ui()

    def refresh_on_show(self) -> None:
        self._load_outsourced_orders()
        self._apply_pending_target_selection()
        if self._external_window is not None:
            language = "es" if get_language() == "es" else "en"
            apply_language = getattr(self._external_window, "apply_language", None)
            workspace_page = getattr(self._external_window, "workspace_page", None)
            set_language = getattr(workspace_page, "set_language", None) if workspace_page is not None else None
            load_records = getattr(workspace_page, "load_records", None) if workspace_page is not None else None
            if callable(set_language):
                set_language(language)
            if callable(apply_language):
                apply_language(language)
            if callable(load_records):
                load_records()
            self._hide_external_workspace_controls()
            QTimer.singleShot(0, self._hide_external_workspace_controls)
            QTimer.singleShot(150, self._hide_external_workspace_controls)
            return
        if self._external_workspace is not None:
            language = "es" if get_language() == "es" else "en"
            set_language = getattr(self._external_workspace, "set_language", None)
            if callable(set_language):
                set_language(language)
            load_records = getattr(self._external_workspace, "load_records", None)
            if callable(load_records):
                load_records()
            self._hide_external_workspace_controls()
            QTimer.singleShot(0, self._hide_external_workspace_controls)
            QTimer.singleShot(150, self._hide_external_workspace_controls)
            return
        if self._fallback_page is not None:
            self._fallback_page.refresh_on_show()

    def set_target_selection(self, order_id: int, panel_label: str) -> None:
        self._pending_target_selection = (int(order_id), str(panel_label))
        self._load_outsourced_orders()
        self._apply_pending_target_selection()

    def _load_outsourced_orders(self) -> None:
        current_order_id = self.order_combo.currentData()
        self.order_combo.blockSignals(True)
        self.order_combo.clear()
        self.order_combo.addItem(tr("Select order"), None)
        for order_id, label in self.database.list_outsourced_order_choices():
            self.order_combo.addItem(label, order_id)
        if current_order_id is not None:
            index = self.order_combo.findData(current_order_id)
            if index >= 0:
                self.order_combo.setCurrentIndex(index)
        self.order_combo.blockSignals(False)
        self._load_outsourced_panels_for_selected_order()
        self._apply_pending_target_selection()

    def _load_outsourced_panels_for_selected_order(self) -> None:
        order_id = self.order_combo.currentData()
        self.outsourced_panel_combo.clear()
        self.outsourced_panel_combo.addItem(tr("Select outsourced panel"), None)
        if order_id is None:
            self.outsourced_panel_combo.setEnabled(False)
            self.save_to_outsourced_panel_button.setEnabled(False)
            return
        panel_labels = self.database.list_outsourced_panels_for_order(int(order_id))
        for label in panel_labels:
            self.outsourced_panel_combo.addItem(label, label)
        self.outsourced_panel_combo.setEnabled(bool(panel_labels))
        self.save_to_outsourced_panel_button.setEnabled(bool(panel_labels))
        self._apply_pending_target_selection()

    def _apply_pending_target_selection(self) -> None:
        if self._pending_target_selection is None:
            return
        order_id, panel_label = self._pending_target_selection
        order_index = self.order_combo.findData(order_id)
        if order_index < 0:
            return
        if self.order_combo.currentIndex() != order_index:
            self.order_combo.setCurrentIndex(order_index)
        panel_index = self._find_outsourced_panel_index(panel_label)
        if panel_index < 0:
            return
        self.outsourced_panel_combo.setCurrentIndex(panel_index)
        self._pending_target_selection = None

    def _find_outsourced_panel_index(self, panel_label: str) -> int:
        direct_index = self.outsourced_panel_combo.findData(panel_label)
        if direct_index >= 0:
            return direct_index
        target = str(panel_label or "").strip().casefold()
        if not target:
            return -1
        for index in range(self.outsourced_panel_combo.count()):
            value = str(self.outsourced_panel_combo.itemData(index) or "").strip()
            normalized = value.casefold()
            if normalized == target:
                return index
            if normalized.startswith(target) or target.startswith(normalized):
                return index
        return -1

    def _save_selected_table_to_outsourced_panel(self) -> None:
        order_id = self.order_combo.currentData()
        panel_label = self.outsourced_panel_combo.currentData()
        if order_id is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select order"))
            return
        if not panel_label:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select outsourced panel"))
            return
        rows = self._current_selected_table_rows()
        if not rows:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a detected table first."))
            return
        source_pdf_path = self._current_source_pdf_path()
        if not source_pdf_path:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Import a PDF first."))
            return
        try:
            self.database.save_outsourced_panel_table(int(order_id), str(panel_label), source_pdf_path, rows)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("Save Failed"), str(exc))
            return
        QMessageBox.information(self, tr("Saved"), tr("Outsourced table saved to selected panel."))

    def _active_workspace(self) -> QWidget | None:
        if self._external_window is not None:
            return getattr(self._external_window, "workspace_page", None)
        if self._external_workspace is not None:
            return self._external_workspace
        return self._fallback_page

    def _current_selected_table_rows(self) -> list[list[str]]:
        workspace = self._active_workspace()
        if workspace is None:
            return []
        selected_table = getattr(workspace, "_selected_table", None)
        if not callable(selected_table):
            return []
        table = selected_table()
        if table is None:
            return []
        table_data = getattr(workspace, "_table_data", None)
        if callable(table_data):
            raw_rows = table_data(table)
        else:
            raw_rows = getattr(table, "data", [])
        return [
            [str(value or "").strip() for value in list(row)]
            for row in list(raw_rows or [])
        ]

    def _current_source_pdf_path(self) -> str:
        workspace = self._active_workspace()
        if workspace is None:
            return ""
        selected_record = getattr(workspace, "_selected_record", None)
        if callable(selected_record):
            record = selected_record()
            if record is not None:
                source = getattr(record, "original_source", None) or getattr(record, "full_path", None)
                if source:
                    return str(source)
        current_document_path = getattr(workspace, "current_document_path", None)
        return str(current_document_path or "")

    def _hide_external_workspace_controls(self) -> None:
        root = None
        if self._external_window is not None:
            top_language_btn = getattr(self._external_window, "top_language_btn", None)
            if top_language_btn is not None:
                top_language_btn.hide()
            root = getattr(self._external_window, "workspace_page", None) or self._external_window
        elif self._external_workspace is not None:
            root = self._external_workspace
        if root is None:
            return

        for attr_name in ("header", "subheader"):
            widget = getattr(root, attr_name, None)
            if isinstance(widget, QLabel):
                widget.hide()

        button_texts = {
            "Detectar tablas",
            "Detect Tables",
            "Exportar Word",
            "Export Word",
            "Exportar Excel",
            "Export Excel",
            "Exportar CSV",
            "Export CSV",
        }
        label_fragments = (
            "Convertidor de Tablas PDF",
            "PDF Table Extractor",
            "Busca tablas en el PDF actual",
            "Search for tables in the current PDF",
            "Searches for tables in the current PDF",
            "Dibuja un recuadro sobre una tabla",
            "Draw a box over a table",
        )

        for button in root.findChildren(QPushButton):
            button_text = button.text().strip()
            if button_text in button_texts or "Detectar tablas" in button_text or "Detect Tables" in button_text:
                button.hide()

        for label in root.findChildren(QLabel):
            label_text = label.text().strip()
            if any(fragment in label_text for fragment in label_fragments):
                label.hide()

        for attr_name in ("actions_export_options", "auto_open_checkbox", "csv_options_label", "csv_export_combo"):
            widget = getattr(root, attr_name, None)
            if widget is not None:
                widget.hide()

    def _insert_selector_into_workspace(self, workspace: QWidget | None) -> None:
        if workspace is None:
            return
        outer_layout = workspace.layout()
        if outer_layout is None or outer_layout.count() == 0:
            return
        scroll = outer_layout.itemAt(0).widget()
        if not isinstance(scroll, QScrollArea):
            return
        container = scroll.widget()
        if container is None or container.layout() is None:
            return
        content_layout = container.layout()
        if self.selector_group.parent() is not container:
            self.selector_group.setParent(container)
        content_layout.insertWidget(1, self.selector_group)
