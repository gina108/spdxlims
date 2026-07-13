from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEventLoop, QMarginsF, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database, OrderBrowserRecord
from spdxlims.deployment import DeploymentService
from spdxlims.i18n import tr
from spdxlims.order_service import OrderService
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.pages.report_editor_dialog import ReportEditorDialog
from spdxlims.report_export import build_pdf_export_path
from spdxlims.report_layout import build_report_html
from spdxlims.report_service import ReportService

try:
    from PySide6.QtWebEngineCore import QWebEnginePage
except ImportError:
    QWebEnginePage = None


class OrdersBrowserPage(DataAwarePage):
    def __init__(self, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__()
        self.database = database
        self.order_service = OrderService(database, deployment_service)
        self.report_service = ReportService(database, deployment_service)
        self.current_records: list[OrderBrowserRecord] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        self.group = QGroupBox()
        layout = QVBoxLayout(self.group)

        self.helper = QLabel()
        self.helper.setWordWrap(True)
        layout.addWidget(self.helper)

        search_row = QWidget()
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(10)
        self.search_label = QLabel()
        self.search_input = QLineEdit()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self.refresh_on_show)
        self.search_input.textChanged.connect(lambda _: self._search_timer.start())
        # Live refresh: while this page is the visible one, re-poll so status
        # changes from other sources (results entered, reports finalized, portal
        # imports) appear without having to navigate away and back.
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(5000)
        self._auto_refresh_timer.timeout.connect(self._auto_refresh_tick)
        self.show_archived_checkbox = QCheckBox()
        self.show_archived_checkbox.stateChanged.connect(lambda _: self.refresh_on_show())
        search_layout.addWidget(self.search_label)
        search_layout.addWidget(self.search_input, 1)
        search_layout.addWidget(self.show_archived_checkbox)
        layout.addWidget(search_row)

        self.table = QTableWidget(0, 6)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.itemSelectionChanged.connect(self._update_report_buttons)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.archive_button = QPushButton()
        self.archive_button.setProperty("class", "secondaryButton")
        self.archive_button.setEnabled(False)
        self.archive_button.clicked.connect(self._archive_selected)
        self.edit_report_button = QPushButton()
        self.edit_report_button.setProperty("class", "secondaryButton")
        self.edit_report_button.setEnabled(False)
        self.edit_report_button.clicked.connect(self._edit_selected_report)
        self.export_pdf_button = QPushButton()
        self.export_pdf_button.setProperty("class", "primaryButton")
        self.export_pdf_button.setEnabled(False)
        self.export_pdf_button.clicked.connect(self._export_selected_pdf)
        action_row.addWidget(self.archive_button)
        action_row.addStretch(1)
        action_row.addWidget(self.edit_report_button)
        action_row.addWidget(self.export_pdf_button)
        layout.addLayout(action_row)

        root.addWidget(self.group, 1)

        self.retranslate_ui()
        self.refresh_on_show()

    def retranslate_ui(self) -> None:
        self.group.setTitle(tr("Orders"))
        self.helper.setText(tr("Search orders by patient name, order number, or client."))
        self.search_label.setText(tr("Search"))
        self.search_input.setPlaceholderText(tr("Search by patient, order number, or client"))
        self.table.setHorizontalHeaderLabels(
            [
                tr("Number"),
                tr("Patient"),
                tr("Client"),
                tr("Doctor"),
                tr("Status"),
                tr("Created"),
            ]
        )
        self.archive_button.setText(tr("Archive Order"))
        self.edit_report_button.setText(tr("Edit Report"))
        self.export_pdf_button.setText(tr("Export PDF"))
        self.show_archived_checkbox.setText(tr("Show archived"))
        self._update_report_buttons()
        self._refresh_table()

    def refresh_on_show(self) -> None:
        selected = self._selected_order()
        selected_id = selected.id if selected is not None else None
        include_archived = self.show_archived_checkbox.isChecked()
        try:
            self.current_records = self.order_service.search_orders(
                self.search_input.text(), include_archived=include_archived
            )
        except RuntimeError:
            self.current_records = []
        self._refresh_table()
        if selected_id is not None:
            for row_index, record in enumerate(self.current_records):
                if record.id == selected_id:
                    self.table.selectRow(row_index)
                    break

    def _auto_refresh_tick(self) -> None:
        # Skip while a menu or modal dialog is open so the table isn't rebuilt
        # out from under the user mid-interaction.
        if not self.isVisible():
            return
        if QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None:
            return
        self.refresh_on_show()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self._auto_refresh_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().hideEvent(event)
        self._auto_refresh_timer.stop()

    def _refresh_table(self) -> None:
        self.table.clearContents()
        self.table.setRowCount(len(self.current_records))
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 250)
        self.table.setColumnWidth(2, 220)
        self.table.setColumnWidth(3, 220)
        self.table.setColumnWidth(4, 52)
        self.table.setColumnWidth(5, 150)

        muted = QColor("#7f8a98")
        for row_index, record in enumerate(self.current_records):
            archived = bool(record.is_archived)
            self._set_item(row_index, 0, record.order_number, muted if archived else None)
            self._set_item(row_index, 1, record.patient_name, muted if archived else None)
            self._set_item(row_index, 2, record.client_name or "", muted if archived else None)
            self._set_item(row_index, 3, record.doctor_name or "", muted if archived else None)
            self.table.setCellWidget(row_index, 4, self.build_order_status_indicator(record.status, all_results_entered=record.all_results_entered))
            self._set_item(row_index, 5, self._format_order_date(record.order_date), muted if archived else None)

    def _set_item(self, row: int, column: int, value: str, color: QColor | None = None) -> None:
        item = QTableWidgetItem(value)
        item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        if color is not None:
            item.setForeground(color)
        self.table.setItem(row, column, item)

    def _show_context_menu(self, pos: object) -> None:
        record = self._selected_order()
        if record is None:
            return
        menu = QMenu(self)
        if record.is_archived:
            action = menu.addAction(tr("Unarchive Order"))
        else:
            action = menu.addAction(tr("Archive Order"))
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen != action:
            return
        self.order_service.set_order_archived(record.id, not record.is_archived)
        self.refresh_on_show()

    def _update_report_buttons(self) -> None:
        record = self._selected_order()
        has_selection = record is not None
        self.edit_report_button.setEnabled(has_selection)
        self.export_pdf_button.setEnabled(has_selection)
        self.archive_button.setEnabled(has_selection)
        if record is not None and record.is_archived:
            self.archive_button.setText(tr("Unarchive Order"))
        else:
            self.archive_button.setText(tr("Archive Order"))

    def _archive_selected(self) -> None:
        record = self._selected_order()
        if record is None:
            return
        self.order_service.set_order_archived(record.id, not record.is_archived)
        self.refresh_on_show()

    def _selected_order(self) -> OrderBrowserRecord | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.current_records):
            return None
        return self.current_records[row]

    def _edit_selected_report(self) -> None:
        record = self._selected_order()
        if record is None:
            return
        preview = self.report_service.get_saved_report_preview(record.id)
        if preview is None:
            QMessageBox.warning(self, tr("No Report"), tr("No finalized report for this order."))
            return
        preview_with_layout = {**self.database.get_report_layout_settings(), **preview}
        dialog = ReportEditorDialog(preview_with_layout, parent=self)
        if dialog.exec() != ReportEditorDialog.Accepted:
            return
        edited = dialog.edited_preview
        self.report_service.finalize_report(
            record.id,
            header_image_path=str(preview.get("header_image_path") or "") or None,
            footer_signature_image_path=str(preview.get("footer_signature_image_path") or "") or None,
            preview_override=edited,
        )
        QMessageBox.information(self, tr("Saved"), tr("Report finalized."))

    def _export_selected_pdf(self) -> None:
        record = self._selected_order()
        if record is None:
            return
        preview = self.report_service.get_saved_report_preview(record.id)
        if preview is None:
            QMessageBox.warning(self, tr("No Report"), tr("No finalized report for this order."))
            return
        report_version = int(preview.get("report_version") or 0)
        path = build_pdf_export_path(
            self.database,
            preview,
            suffix=f"_v{report_version}" if report_version > 0 else "",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        preview_with_layout = {**self.database.get_report_layout_settings(), **preview}
        html = build_report_html(preview_with_layout)
        if self._export_pdf_with_webengine(html, path) is not None:
            QMessageBox.information(self, tr("Saved"), tr("Report PDF saved: {path}", path=str(path)))
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.A4))
        printer.setPageMargins(QMarginsF(4, 4, 4, 4), QPageLayout.Millimeter)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(str(path))
        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setHtml(html)
        document.print(printer)
        QMessageBox.information(self, tr("Saved"), tr("Report PDF saved: {path}", path=str(path)))

    def _export_pdf_with_webengine(self, html: str, pdf_path: Path) -> Path | None:
        if QWebEnginePage is None:
            return None
        page = QWebEnginePage(self)
        settings = page.settings()
        web_attribute = getattr(settings, 'WebAttribute', None)
        if web_attribute is not None:
            local_access = getattr(web_attribute, 'LocalContentCanAccessFileUrls', None)
            remote_access = getattr(web_attribute, 'LocalContentCanAccessRemoteUrls', None)
            if local_access is not None:
                settings.setAttribute(local_access, True)
            if remote_access is not None:
                settings.setAttribute(remote_access, True)
        loop = QEventLoop(self)
        timeout = QTimer(self)
        timeout.setSingleShot(True)
        state = {"loaded": False, "printed": False, "success": False}
        layout = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(4, 4, 4, 4), QPageLayout.Millimeter)

        def finish() -> None:
            if loop.isRunning():
                loop.quit()

        def handle_load_finished(ok: bool) -> None:
            state["loaded"] = ok
            if not ok:
                finish()
                return
            try:
                page.printToPdf(str(pdf_path), layout)
            except TypeError:
                page.printToPdf(str(pdf_path))

        def handle_pdf_finished(_file_path: str, success: bool) -> None:
            state["printed"] = True
            state["success"] = success
            finish()

        timeout.timeout.connect(finish)
        page.loadFinished.connect(handle_load_finished)
        page.pdfPrintingFinished.connect(handle_pdf_finished)
        page.setHtml(html, QUrl.fromLocalFile(str(Path.cwd())))
        timeout.start(15000)
        loop.exec()
        timeout.stop()
        page.deleteLater()
        if state["loaded"] and state["printed"] and state["success"] and pdf_path.exists():
            return pdf_path
        return None

    @staticmethod
    def _format_order_date(raw_value: str | None) -> str:
        value = str(raw_value or "").strip()
        if not value:
            return ""
        date_part = value.replace("T", " ").split(" ", 1)[0]
        chunks = date_part.split("-")
        if len(chunks) == 3:
            year, month, day = chunks
            return f"{day}-{month}-{year}"
        return date_part
