from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QDate, QEventLoop, QMarginsF, QTimer, QUrl
from PySide6.QtGui import QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database
from spdxlims.deployment import DeploymentService
from spdxlims.i18n import tr
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.report_export import build_pdf_export_path
from spdxlims.report_layout import build_report_html
from spdxlims.report_service import ReportService

try:
    from PySide6.QtWebEngineCore import QWebEnginePage
except ImportError:  # pragma: no cover
    QWebEnginePage = None


class ReportsPage(DataAwarePage):
    FILTER_DATE_MIN = QDate(2000, 1, 1)

    def __init__(self, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__()
        self.database = database
        self.deployment_service = deployment_service
        self.report_service = ReportService(database, deployment_service)
        self.current_preview: dict[str, object] | None = None
        self._loading_branding_controls = False
        self._web_view_class: type[QWidget] | None | bool = False
        self.preview: QWidget
        self._preview_html_setter: Callable[..., None] | None = None

        root = QHBoxLayout(self)
        root.addWidget(self._build_selector_group(), 1)
        root.addWidget(self._build_preview_group(), 7)

        self.retranslate_ui()
        self.refresh_orders()
        self.load_branding_options()
        self._update_actions()

    def _build_selector_group(self) -> QWidget:
        self.selector_group = QGroupBox()
        layout = QVBoxLayout(self.selector_group)

        self.selector_form = QFormLayout()
        self.selector_labels: dict[str, QLabel] = {}
        self.report_client_filter = QComboBox()
        self.report_test_filter = QComboBox()
        self.report_date_from = QDateEdit()
        self.report_date_to = QDateEdit()
        self.filter_button = QPushButton()
        self.filter_button.clicked.connect(self.apply_report_filters)
        self.clear_filter_button = QPushButton()
        self.clear_filter_button.clicked.connect(self.clear_report_filters)
        self.bulk_finalize_button = QPushButton()
        self.bulk_finalize_button.clicked.connect(self.finalize_filtered_reports)
        self.order_combo = QComboBox()
        self.load_button = QPushButton()
        self.load_button.clicked.connect(self.load_saved_or_live_preview)
        self.barcode_input = QLineEdit()
        self.barcode_button = QPushButton()
        self.barcode_button.clicked.connect(self.load_report_by_barcode)
        self.barcode_input.returnPressed.connect(self.load_report_by_barcode)
        self.header_combo = QComboBox()
        self.header_combo.currentIndexChanged.connect(self._branding_selection_changed)
        self.add_header_button = QPushButton()
        self.add_header_button.clicked.connect(self.add_header_image)
        self.footer_combo = QComboBox()
        self.footer_combo.currentIndexChanged.connect(self._branding_selection_changed)
        self.add_footer_button = QPushButton()
        self.add_footer_button.clicked.connect(self.add_footer_image)
        self.filter_status = QLabel()
        self.filter_status.setWordWrap(True)
        for widget in (self.report_date_from, self.report_date_to):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd")
            widget.setMinimumDate(self.FILTER_DATE_MIN)
            widget.setSpecialValueText(" ")
            widget.setDate(self.FILTER_DATE_MIN)

        filter_actions_row = QWidget()
        filter_actions_layout = QHBoxLayout(filter_actions_row)
        filter_actions_layout.setContentsMargins(0, 0, 0, 0)
        filter_actions_layout.addWidget(self.filter_button)
        filter_actions_layout.addWidget(self.clear_filter_button)
        filter_actions_layout.addWidget(self.bulk_finalize_button)

        report_date_row = QWidget()
        report_date_layout = QHBoxLayout(report_date_row)
        report_date_layout.setContentsMargins(0, 0, 0, 0)
        report_date_layout.addWidget(QLabel(tr("From")))
        report_date_layout.addWidget(self.report_date_from, 1)
        report_date_layout.addWidget(QLabel(tr("To")))
        report_date_layout.addWidget(self.report_date_to, 1)

        order_row = QWidget()
        order_layout = QHBoxLayout(order_row)
        order_layout.setContentsMargins(0, 0, 0, 0)
        order_layout.addWidget(self.order_combo, 1)
        order_layout.addWidget(self.load_button)

        barcode_row = QWidget()
        barcode_layout = QHBoxLayout(barcode_row)
        barcode_layout.setContentsMargins(0, 0, 0, 0)
        barcode_layout.addWidget(self.barcode_input, 1)
        barcode_layout.addWidget(self.barcode_button)

        header_row = QWidget()
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(self.header_combo, 1)
        header_layout.addWidget(self.add_header_button)

        footer_row = QWidget()
        footer_layout = QHBoxLayout(footer_row)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.addWidget(self.footer_combo, 1)
        footer_layout.addWidget(self.add_footer_button)

        report_client_label = QLabel()
        report_test_label = QLabel()
        report_date_range_label = QLabel()
        order_label = QLabel()
        barcode_label = QLabel()
        header_label = QLabel()
        footer_label = QLabel()
        self.selector_labels['report_client'] = report_client_label
        self.selector_labels['report_test'] = report_test_label
        self.selector_labels['report_date_range'] = report_date_range_label
        self.selector_labels['order'] = order_label
        self.selector_labels['barcode'] = barcode_label
        self.selector_labels['header'] = header_label
        self.selector_labels['footer'] = footer_label
        self.selector_form.addRow(report_client_label, self.report_client_filter)
        self.selector_form.addRow(report_test_label, self.report_test_filter)
        self.selector_form.addRow(report_date_range_label, report_date_row)
        self.selector_form.addRow(QLabel(), filter_actions_row)
        self.selector_form.addRow(order_label, order_row)
        self.selector_form.addRow(barcode_label, barcode_row)
        self.selector_form.addRow(header_label, header_row)
        self.selector_form.addRow(footer_label, footer_row)
        layout.addLayout(self.selector_form)
        layout.addWidget(self.filter_status)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.source_label = QLabel()
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)

        self.refresh_live_button = QPushButton()
        self.refresh_live_button.clicked.connect(self.load_live_preview)
        self.finalize_button = QPushButton()
        self.finalize_button.clicked.connect(self.finalize_report)
        self.print_button = QPushButton()
        self.print_button.clicked.connect(self.print_report)
        self.export_pdf_button = QPushButton()
        self.export_pdf_button.clicked.connect(self.export_pdf)

        layout.addWidget(self.refresh_live_button)
        layout.addWidget(self.finalize_button)
        layout.addWidget(self.print_button)
        layout.addWidget(self.export_pdf_button)
        layout.addStretch(1)
        return self.selector_group

    def _build_preview_group(self) -> QWidget:
        self.preview_group = QGroupBox()
        layout = QVBoxLayout(self.preview_group)
        web_view_class = self._get_web_view_class()
        if web_view_class is not None:
            self.preview = web_view_class()
            self.preview.setStyleSheet('background:#ffffff; border:1px solid #c9d1dc;')
            settings = getattr(self.preview, 'settings', None)
            if callable(settings):
                preview_settings = settings()
                web_attribute = getattr(preview_settings, 'WebAttribute', None)
                if web_attribute is not None:
                    local_access = getattr(web_attribute, 'LocalContentCanAccessFileUrls', None)
                    remote_access = getattr(web_attribute, 'LocalContentCanAccessRemoteUrls', None)
                    if local_access is not None:
                        preview_settings.setAttribute(local_access, True)
                    if remote_access is not None:
                        preview_settings.setAttribute(remote_access, True)
            self._preview_html_setter = self.preview.setHtml
        else:
            self.preview = QTextEdit()
            self.preview.setReadOnly(True)
            self.preview.setStyleSheet('background:#ffffff; color:#111111; border:1px solid #c9d1dc;')
            self._preview_html_setter = self.preview.setHtml
        layout.addWidget(self.preview)
        return self.preview_group

    def _get_web_view_class(self) -> type[QWidget] | None:
        if self._web_view_class is not False:
            return self._web_view_class if self._web_view_class is not True else None
        try:
            module = importlib.import_module("PySide6.QtWebEngineWidgets")
        except ImportError:  # pragma: no cover
            self._web_view_class = True
            return None
        self._web_view_class = getattr(module, "QWebEngineView", None) or True
        return self._web_view_class if self._web_view_class is not True else None

    def _set_preview_html(self, html: str) -> None:
        if self._preview_html_setter is None:
            return
        if QWebEnginePage is not None and self._get_web_view_class() is not None:
            self._preview_html_setter(html, QUrl.fromLocalFile(str(Path.cwd())))
            return
        self._preview_html_setter(html)

    def retranslate_ui(self) -> None:
        self.selector_group.setTitle(tr('Report Workflow'))
        self.preview_group.setTitle(tr('Report Preview'))
        self.selector_labels['report_client'].setText(tr('Client Filter'))
        self.selector_labels['report_test'].setText(tr('Test Filter'))
        self.selector_labels['report_date_range'].setText(tr('Date Range'))
        self.selector_labels['order'].setText(tr('Order'))
        self.selector_labels['barcode'].setText(tr('Barcode'))
        self.selector_labels['header'].setText(tr('Header Image'))
        self.selector_labels['footer'].setText(tr('Footer Image'))
        self.filter_button.setText(tr('Apply Filters'))
        self.clear_filter_button.setText(tr('Clear Filters'))
        self.bulk_finalize_button.setText(tr('Finalize Filtered Reports'))
        self.barcode_input.setPlaceholderText(tr('Enter or scan an order barcode'))
        self.barcode_button.setText(tr('Load Barcode Report'))
        self.add_header_button.setText(tr('Add Header'))
        self.add_footer_button.setText(tr('Add Footer'))
        self.load_button.setText(tr('Load Report'))
        self.refresh_live_button.setText(tr('Refresh Live Preview'))
        self.finalize_button.setText(tr('Finalize Report'))
        self.print_button.setText(tr('Print Report'))
        self.export_pdf_button.setText(tr('Export PDF'))
        if self.current_preview is None:
            self.summary.setText(tr('Select an order to preview or finalize its report.'))
            self.source_label.setText(tr('No report loaded.'))
            self._set_preview_html(self._empty_html())
        else:
            self._render_preview(self.current_preview)
        self.refresh_filter_choices()
        self.refresh_orders()
        self.load_branding_options()
        self._update_actions()

    def refresh_on_show(self) -> None:
        current_order_id = self.order_combo.currentData()
        self.refresh_filter_choices()
        self.refresh_orders()
        self.load_branding_options()
        if current_order_id is not None:
            self._set_combo_value(current_order_id)
            self._load_preview_for_order(current_order_id)

    def refresh_filter_choices(self) -> None:
        self.set_combo_items(
            self.report_client_filter,
            [(label, client_id) for client_id, label in self.database.list_client_choices(active_only=True)],
            placeholder=tr('All clients'),
            selected_data=self.report_client_filter.currentData(),
        )
        self.set_combo_items(
            self.report_test_filter,
            [(label, test_id) for test_id, label in self.database.list_test_choices()],
            placeholder=tr('All tests'),
            selected_data=self.report_test_filter.currentData(),
        )

    def refresh_orders(self) -> None:
        try:
            choices = self.report_service.list_filtered_report_order_choices(
                client_id=self.report_client_filter.currentData(),
                test_id=self.report_test_filter.currentData(),
                date_from=self._filter_date_value(self.report_date_from),
                date_to=self._filter_date_value(self.report_date_to),
            )
        except RuntimeError as exc:
            self.filter_status.setText(str(exc))
            choices = self.report_service.list_report_order_choices()
        else:
            self.filter_status.setText(tr('Matching report orders: {count}', count=str(len(choices))))
        self.set_combo_items(
            self.order_combo,
            [(label, order_id) for order_id, label in choices],
            placeholder=tr('Select order'),
            selected_data=self.order_combo.currentData(),
        )

    def load_branding_options(self) -> None:
        branding = self.database.get_report_branding_options()
        self._loading_branding_controls = True
        self.set_combo_items(
            self.header_combo,
            [(self._report_asset_label(path), path) for path in branding['headers']],
            placeholder=tr('No Header Image'),
            placeholder_data='',
            selected_data=branding['selected_header'],
        )
        self.set_combo_items(
            self.footer_combo,
            [(self._report_asset_label(path), path) for path in branding['footers']],
            placeholder=tr('No Footer Image'),
            placeholder_data='',
            selected_data=branding['selected_footer'],
        )
        self._loading_branding_controls = False
        if self.current_preview is not None:
            self.current_preview = self._override_preview_branding(self.current_preview)
            self._render_preview(self.current_preview)

    def _report_asset_label(self, raw_path: object) -> str:
        value = str(raw_path or '').strip()
        if not value:
            return ''
        candidate = Path(value)
        return candidate.name or value

    def _combo_paths(self, combo: QComboBox) -> list[str]:
        values: list[str] = []
        for index in range(1, combo.count()):
            value = str(combo.itemData(index) or '').strip()
            if value and value not in values:
                values.append(value)
        return values

    def _selected_header_path(self) -> str:
        return str(self.header_combo.currentData() or '').strip()

    def _selected_footer_path(self) -> str:
        return str(self.footer_combo.currentData() or '').strip()

    def _save_branding_options(self) -> None:
        self.database.save_report_branding_options(
            self._combo_paths(self.header_combo),
            self._combo_paths(self.footer_combo),
            self._selected_header_path(),
            self._selected_footer_path(),
        )

    def _branding_selection_changed(self, *_args: object) -> None:
        if self._loading_branding_controls:
            return
        self._save_branding_options()
        if self.current_preview is None:
            return
        self.current_preview = self._override_preview_branding(self.current_preview)
        self._render_preview(self.current_preview)

    def _pick_report_image(self, title: str) -> str:
        path, _ = QFileDialog.getOpenFileName(
            self,
            title,
            '',
            tr('Images (*.png *.jpg *.jpeg)'),
        )
        return path

    def add_header_image(self) -> None:
        path = self._pick_report_image(tr('Choose Report Header Image'))
        if not path:
            return
        saved_path = self.database.add_report_branding_asset(path, 'header')
        self.load_branding_options()
        if saved_path:
            index = self.header_combo.findData(saved_path)
            if index >= 0:
                self.header_combo.setCurrentIndex(index)

    def add_footer_image(self) -> None:
        path = self._pick_report_image(tr('Choose Report Footer Image'))
        if not path:
            return
        saved_path = self.database.add_report_branding_asset(path, 'footer')
        self.load_branding_options()
        if saved_path:
            index = self.footer_combo.findData(saved_path)
            if index >= 0:
                self.footer_combo.setCurrentIndex(index)

    def _set_combo_value(self, order_id: int | str | None) -> None:
        index = self.order_combo.findData(order_id)
        if index >= 0:
            self.order_combo.setCurrentIndex(index)

    def _override_preview_branding(self, preview: dict[str, object]) -> dict[str, object]:
        merged = dict(preview)
        merged['header_image_path'] = self._selected_header_path()
        merged['footer_signature_image_path'] = self._selected_footer_path()
        return merged

    def _load_preview_for_order(self, order_id: int | str | None) -> bool:
        if order_id is None:
            return False
        preview = self.report_service.get_saved_report_preview(order_id) or self.report_service.get_live_report_preview(order_id)
        if preview is None:
            return False
        self.current_preview = self._override_preview_branding(preview)
        self._render_preview(self.current_preview)
        self._update_actions()
        return True

    def load_saved_or_live_preview(self) -> None:
        order_id = self.order_combo.currentData()
        if order_id is None:
            QMessageBox.warning(self, tr('Missing Data'), tr('Select an order first.'))
            return
        if not self._load_preview_for_order(order_id):
            QMessageBox.warning(self, tr('Missing Selection'), tr('The selected order could not be loaded.'))
            return

    def load_report_by_barcode(self) -> None:
        barcode = self.barcode_input.text().strip()
        if not barcode:
            QMessageBox.warning(self, tr('Missing Data'), tr('Enter or scan an order barcode.'))
            return
        try:
            order_id = self.report_service.find_report_order_id_by_barcode(barcode)
        except Exception as exc:
            QMessageBox.warning(self, tr('Missing Selection'), str(exc))
            return
        if order_id is None:
            QMessageBox.warning(self, tr('Missing Selection'), tr('Barcode order not found.'))
            return
        self.refresh_orders()
        self._set_combo_value(order_id)
        if not self._load_preview_for_order(order_id):
            QMessageBox.warning(self, tr('Missing Selection'), tr('Barcode order not found.'))
            return
        self.barcode_input.clear()

    def apply_report_filters(self) -> None:
        self.refresh_orders()
        self._update_actions()

    def clear_report_filters(self) -> None:
        self.report_client_filter.setCurrentIndex(0)
        self.report_test_filter.setCurrentIndex(0)
        self.report_date_from.setDate(self.FILTER_DATE_MIN)
        self.report_date_to.setDate(self.FILTER_DATE_MIN)
        self.refresh_orders()
        self._update_actions()

    def load_live_preview(self) -> None:
        order_id = self.order_combo.currentData()
        if order_id is None:
            QMessageBox.warning(self, tr('Missing Data'), tr('Select an order first.'))
            return
        preview = self.report_service.get_live_report_preview(order_id)
        if preview is None:
            QMessageBox.warning(self, tr('Missing Selection'), tr('The selected order could not be loaded.'))
            return
        self.current_preview = self._override_preview_branding(preview)
        self._render_preview(self.current_preview)
        self._update_actions()

    def finalize_report(self) -> None:
        order_id = self.order_combo.currentData()
        if order_id is None:
            QMessageBox.warning(self, tr('Missing Data'), tr('Select an order first.'))
            return
        try:
            self.report_service.finalize_report(
                order_id,
                header_image_path=self._selected_header_path(),
                footer_signature_image_path=self._selected_footer_path(),
            )
        except Exception as exc:
            QMessageBox.critical(self, tr('Save Failed'), str(exc))
            return
        self.refresh_orders()
        saved_preview = self.report_service.get_saved_report_preview(order_id)
        self.current_preview = self._override_preview_branding(saved_preview) if saved_preview is not None else None
        if self.current_preview is not None:
            self._render_preview(self.current_preview)
        self._set_combo_value(order_id)
        self.notify_data_changed()
        QMessageBox.information(self, tr('Saved'), tr('Report finalized.'))
        self._update_actions()

    def finalize_filtered_reports(self) -> None:
        try:
            choices = self.report_service.list_filtered_report_order_choices(
                client_id=self.report_client_filter.currentData(),
                test_id=self.report_test_filter.currentData(),
                date_from=self._filter_date_value(self.report_date_from),
                date_to=self._filter_date_value(self.report_date_to),
            )
        except RuntimeError as exc:
            QMessageBox.warning(self, tr('Unavailable'), str(exc))
            return
        if not choices:
            QMessageBox.information(self, tr('No Matches'), tr('No orders matched the selected report filters.'))
            return
        created = 0
        failures = 0
        for order_id, _label in choices:
            try:
                self.report_service.finalize_report(
                    order_id,
                    header_image_path=self._selected_header_path(),
                    footer_signature_image_path=self._selected_footer_path(),
                )
                created += 1
            except Exception:  # noqa: BLE001
                failures += 1
        self.refresh_orders()
        self.notify_data_changed()
        if failures:
            QMessageBox.warning(
                self,
                tr('Completed With Errors'),
                tr('Finalized {created} reports and skipped {failed}.', created=str(created), failed=str(failures)),
            )
            return
        QMessageBox.information(self, tr('Saved'), tr('Finalized {count} reports.', count=str(created)))

    def _filter_date_value(self, widget: QDateEdit) -> str:
        if widget.date() <= self.FILTER_DATE_MIN:
            return ''
        return widget.date().toString('yyyy-MM-dd')

    def print_report(self) -> None:
        if self.current_preview is None:
            return
        printer = QPrinter(QPrinter.HighResolution)
        preview = QPrintPreviewDialog(printer, self)
        document = QTextDocument()
        document.setHtml(self._build_report_html(self.current_preview))
        preview.paintRequested.connect(document.print)
        preview.exec()

    def export_pdf(self) -> None:
        if self.current_preview is None:
            return
        report_version = int(self.current_preview.get("report_version") or 0)
        path = build_pdf_export_path(
            self.database,
            self.current_preview,
            suffix=f"_v{report_version}" if report_version > 0 else "",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        html = self._build_report_html(self.current_preview)
        webengine_pdf = self._export_pdf_with_webengine(html, path)
        if webengine_pdf is not None:
            QMessageBox.information(self, tr('Saved'), tr('Report PDF saved: {path}', path=str(path)))
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
        QMessageBox.information(self, tr('Saved'), tr('Report PDF saved: {path}', path=str(path)))

    def _update_actions(self) -> None:
        has_order = self.order_combo.currentData() is not None
        has_preview = self.current_preview is not None
        self.refresh_live_button.setEnabled(has_order)
        self.finalize_button.setEnabled(has_order)
        self.print_button.setEnabled(has_preview)
        self.export_pdf_button.setEnabled(has_preview)

    def _render_preview(self, preview: dict[str, object]) -> None:
        self.summary.setText(
            tr(
                'Order {order_number} for {patient_name}',
                order_number=str(preview.get('order_number') or ''),
                patient_name=str(preview.get('patient_name') or ''),
            )
        )
        source = tr('Final Snapshot') if preview.get('source') == 'saved' else tr('Live Preview')
        status = str(preview.get('order_status') or '')
        version = preview.get('report_version')
        finalized_at = preview.get('finalized_at') or ''
        version_text = f' | v{version}' if version else ''
        finalized_text = f' | {finalized_at}' if finalized_at else ''
        self.source_label.setText(f'{source}{version_text} | {status}{finalized_text}')
        self._set_preview_html(self._build_report_html(preview))

    def _build_report_html(self, preview: dict[str, object]) -> str:
        return build_report_html({**self.database.get_report_layout_settings(), **preview})

    def _export_pdf_with_webengine(self, html: str, pdf_path: Path) -> Path | None:
        if QWebEnginePage is None:
            return None
        page = QWebEnginePage(self)
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
    def _empty_html() -> str:
        return '<html><body style="font-family:Segoe UI, Arial, sans-serif;color:#dfe5ec;">Select an order to preview a report.</body></html>'
