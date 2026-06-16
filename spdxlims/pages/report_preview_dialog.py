from __future__ import annotations

import ast as _ast
import importlib
import operator as _operator
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spdxlims.i18n import tr


_FORMULA_OPS: dict = {
    _ast.Add: _operator.add,
    _ast.Sub: _operator.sub,
    _ast.Mult: _operator.mul,
    _ast.Div: _operator.truediv,
    _ast.USub: _operator.neg,
    _ast.UAdd: _operator.pos,
}


def _safe_eval_formula(formula: str, x: float) -> float:
    """Evaluate a simple arithmetic formula with variable x.
    If the formula starts with an operator (e.g. *1000, /10, +5, -2) x is implied."""
    normalized = formula.strip()
    if normalized and normalized[0] in ("*", "/", "+", "-") and "x" not in normalized:
        normalized = "x " + normalized
    def _eval(node: _ast.AST) -> float:
        if isinstance(node, _ast.Expression):
            return _eval(node.body)
        if isinstance(node, _ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, _ast.Name) and node.id == "x":
            return x
        if isinstance(node, _ast.BinOp) and type(node.op) in _FORMULA_OPS:
            return _FORMULA_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, _ast.UnaryOp) and type(node.op) in _FORMULA_OPS:
            return _FORMULA_OPS[type(node.op)](_eval(node.operand))
        raise ValueError(f"Unsupported expression: {type(node).__name__}")
    return _eval(_ast.parse(normalized, mode="eval"))


class ReportPreviewDialog(QDialog):
    def __init__(
        self,
        preview: dict[str, object],
        html_renderer,
        *,
        can_approve: bool,
        approved: bool,
        header_options: list[tuple[str, str]],
        selected_header: str,
        footer_options: list[tuple[str, str]] | None = None,
        selected_footer: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._approved_clicked = False
        self._approved = approved
        self._html_renderer = html_renderer
        self._preview = dict(preview)
        self._approved_preview: dict[str, object] | None = None
        self._preview_dirty = False
        self._web_view_class: type[QWidget] | None | bool = False
        self.preview_widget: QWidget
        self._preview_html_setter: Callable[..., None] | None = None
        self._preview_uses_webengine = False
        self.setModal(True)
        self.resize(1020, 760)

        layout = QVBoxLayout(self)

        summary = QLabel(
            tr(
                "Order {order_number} report preview",
                order_number=str(preview.get("order_number") or ""),
            )
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        help_label = QLabel(tr("Preview and approve the report before sending it."))
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        image_row = QHBoxLayout()
        header_label = QLabel(tr("Header Image"))
        self.header_combo = QComboBox()
        self.header_combo.addItem(tr("No Header Image"), "")
        for label, value in header_options:
            self.header_combo.addItem(label, value)
        selected_index = self.header_combo.findData(selected_header)
        self.header_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        self.header_combo.currentIndexChanged.connect(self._header_changed)
        footer_label = QLabel(tr("Footer Image"))
        self.footer_combo = QComboBox()
        self.footer_combo.addItem(tr("No Footer Image"), "")
        for label, value in (footer_options or []):
            self.footer_combo.addItem(label, value)
        selected_footer_index = self.footer_combo.findData(selected_footer)
        self.footer_combo.setCurrentIndex(selected_footer_index if selected_footer_index >= 0 else 0)
        self.footer_combo.currentIndexChanged.connect(self._footer_changed)
        image_row.addWidget(header_label)
        image_row.addWidget(self.header_combo, 1)
        image_row.addSpacing(16)
        image_row.addWidget(footer_label)
        image_row.addWidget(self.footer_combo, 1)
        layout.addLayout(image_row)

        fields_row = QHBoxLayout()
        fields_row.addWidget(QLabel(tr("Header Fields")))
        _field_defs = [
            ("report_show_doctor", tr("Doctor")),
            ("report_show_client", tr("Origin")),
            ("report_show_sex", tr("Sex")),
            ("report_show_age", tr("Age")),
            ("report_show_dob", tr("DOB")),
            ("report_show_ordered_at", tr("Appt. Date")),
            ("report_show_reported_at", tr("Print Date")),
        ]
        self._header_field_checkboxes: dict[str, QCheckBox] = {}
        for key, label in _field_defs:
            cb = QCheckBox(label)
            cb.setChecked(bool(self._preview.get(key, True)))
            cb.stateChanged.connect(lambda _state, k=key, c=cb: self._header_field_changed(k, c))
            self._header_field_checkboxes[key] = cb
            fields_row.addWidget(cb)
        fields_row.addStretch(1)
        layout.addLayout(fields_row)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        close_button = QPushButton(tr("Close Preview"))
        close_button.clicked.connect(self.reject)
        button_row.addWidget(close_button)

        self.edit_button = QPushButton(tr("Edit Report"))
        self.edit_button.setEnabled(can_approve)
        self.edit_button.clicked.connect(self._edit_report)
        button_row.addWidget(self.edit_button)

        self.approve_button = QPushButton(tr("Approved") if approved else tr("Approve and Export PDF"))
        self.approve_button.setEnabled(can_approve and not approved)
        self.approve_button.clicked.connect(self._approve_and_export)
        button_row.addWidget(self.approve_button)

        layout.addLayout(button_row)

        self.preview_widget = self._build_preview_widget()
        self._set_preview_html(self._render_preview_html())
        layout.addWidget(self.preview_widget, 1)

    @property
    def approved_clicked(self) -> bool:
        return self._approved_clicked

    @property
    def selected_header(self) -> str:
        return str(self.header_combo.currentData() or "")

    @property
    def selected_footer(self) -> str:
        return str(self.footer_combo.currentData() or "")

    @property
    def approved_preview(self) -> dict[str, object] | None:
        return None if self._approved_preview is None else dict(self._approved_preview)

    @property
    def preview_changed(self) -> bool:
        return self._preview_dirty

    @property
    def current_preview(self) -> dict[str, object]:
        return dict(self._preview)

    def _approve_and_export(self) -> None:
        self._approved_clicked = True
        self._approved_preview = dict(self._preview)
        self.accept()

    def _header_changed(self) -> None:
        self._preview["header_image_path"] = self.selected_header
        self._preview_dirty = True
        self._set_preview_html(self._render_preview_html())

    def _footer_changed(self) -> None:
        self._preview["footer_signature_image_path"] = self.selected_footer
        self._preview_dirty = True
        self._set_preview_html(self._render_preview_html())

    def _header_field_changed(self, key: str, checkbox: QCheckBox) -> None:
        self._preview[key] = checkbox.isChecked()
        self._preview_dirty = True
        self._set_preview_html(self._render_preview_html())

    def _edit_report(self) -> None:
        from spdxlims.pages.report_editor_dialog import ReportEditorDialog
        dialog = ReportEditorDialog(self._preview, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._preview = dialog.edited_preview
        self._preview["header_image_path"] = self.selected_header
        self._preview["footer_signature_image_path"] = self.selected_footer
        self._preview_dirty = True
        self._set_preview_html(self._render_preview_html())

    def _render_preview_html(self) -> str:
        return self._html_renderer(self._preview)

    def _build_preview_widget(self) -> QWidget:
        web_view_class = self._get_web_view_class()
        if web_view_class is not None:
            preview_widget = web_view_class()
            preview_widget.setStyleSheet("background:#ffffff; border:1px solid #c9d1dc;")
            self._configure_web_preview(preview_widget)
            self._preview_html_setter = preview_widget.setHtml
            self._preview_uses_webengine = True
            return preview_widget

        preview_widget = QTextEdit()
        preview_widget.setReadOnly(True)
        preview_widget.setStyleSheet("background:#ffffff; color:#111111; border:1px solid #c9d1dc;")
        self._preview_html_setter = preview_widget.setHtml
        self._preview_uses_webengine = False
        return preview_widget

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

    def _configure_web_preview(self, preview_widget: QWidget) -> None:
        settings = getattr(preview_widget, "settings", None)
        if not callable(settings):
            return
        preview_settings = settings()
        web_attribute = getattr(preview_settings, "WebAttribute", None)
        if web_attribute is None:
            return
        local_access = getattr(web_attribute, "LocalContentCanAccessFileUrls", None)
        remote_access = getattr(web_attribute, "LocalContentCanAccessRemoteUrls", None)
        if local_access is not None:
            preview_settings.setAttribute(local_access, True)
        if remote_access is not None:
            preview_settings.setAttribute(remote_access, True)

    def _set_preview_html(self, html: str) -> None:
        if self._preview_html_setter is None:
            return
        if self._preview_uses_webengine:
            self._preview_html_setter(html, QUrl.fromLocalFile(str(Path.cwd())))
            return
        self._preview_html_setter(html)
