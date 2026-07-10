from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database
from spdxlims.deployment import DeploymentService
from spdxlims.i18n import get_language, tr
from spdxlims.outsourced_service import OutsourcedService
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.pdf_table_extractor_library import (
    DetectedTable,
    ManualGridProposal,
    PdfLibrary,
)

EXTERNAL_PDF_APP_ROOT = Path(r"C:\SDXPDFTableExtractor")
_ZOOM_LEVELS = [50, 75, 100, 125, 150, 200]
_RENDER_BASE_WIDTH = 1200
_REQUIRED_COLUMNS = 5


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


class DropZoneFrame(QFrame):
    files_dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("DropZone")
        self.setStyleSheet(
            "#DropZone {"
            "  border: 2px dashed #7840b8;"
            "  border-radius: 12px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignCenter)

        self._title_label = QLabel()
        self._title_label.setAlignment(Qt.AlignCenter)
        self._title_label.setStyleSheet("font-weight: bold; font-size: 15px; border: none;")

        self._subtitle_label = QLabel()
        self._subtitle_label.setAlignment(Qt.AlignCenter)
        self._subtitle_label.setStyleSheet("border: none;")

        self._browse_button = QPushButton()
        self._browse_button.setFixedWidth(160)
        self._browse_button.clicked.connect(self._browse)

        layout.addWidget(self._title_label)
        layout.addWidget(self._subtitle_label)
        layout.addWidget(self._browse_button, 0, Qt.AlignCenter)

        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self._title_label.setText(tr("Drop PDF files here"))
        self._subtitle_label.setText(tr("Drag PDF files here or browse for them below."))
        self._browse_button.setText(tr("Select PDF Files"))

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            if any(url.toLocalFile().lower().endswith(".pdf") for url in event.mimeData().urls()):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event) -> None:
        files = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.toLocalFile().lower().endswith(".pdf")
        ]
        if files:
            self.files_dropped.emit(files)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Choose PDF"), "", tr("PDF File (*.pdf)")
        )
        if path:
            self.files_dropped.emit([path])


class PageCanvas(QLabel):
    """PDF page preview widget with optional drag-to-select region mode."""

    region_committed = Signal(tuple)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setMouseTracking(True)
        self._draw_mode = False
        self._drag_start: tuple[int, int] | None = None
        self._drag_current: tuple[int, int] | None = None
        self._base_pixmap: QPixmap | None = None
        self._pdf_width: float = 1.0
        self._zoom: float = 1.0
        self._region: tuple[float, float, float, float] | None = None

    def load_page(self, image_bytes: bytes, pdf_size: tuple[float, float], zoom: float = 1.0) -> None:
        px = QPixmap()
        px.loadFromData(image_bytes, "PNG")
        self._base_pixmap = px
        self._pdf_width = max(pdf_size[0], 1.0)
        self._zoom = zoom
        self._region = None
        self._drag_start = None
        self._drag_current = None
        self._repaint()

    def update_zoom(self, zoom: float) -> None:
        self._zoom = zoom
        self._repaint()

    def set_draw_mode(self, enabled: bool) -> None:
        self._draw_mode = enabled
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
        if not enabled:
            self._drag_start = None
            self._drag_current = None
            self._repaint()

    def clear_region(self) -> None:
        self._region = None
        self._drag_start = None
        self._drag_current = None
        self._repaint()

    def current_region(self) -> tuple[float, float, float, float] | None:
        return self._region

    def mousePressEvent(self, event) -> None:
        if self._draw_mode and event.button() == Qt.LeftButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            self._drag_start = (pos.x(), pos.y())
            self._drag_current = (pos.x(), pos.y())
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._draw_mode and self._drag_start is not None:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            self._drag_current = (pos.x(), pos.y())
            self._repaint()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._draw_mode and self._drag_start is not None and event.button() == Qt.LeftButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            self._drag_current = (pos.x(), pos.y())
            self._commit_region()
            self._drag_start = None
            self._drag_current = None
        else:
            super().mouseReleaseEvent(event)

    def _commit_region(self) -> None:
        if self._base_pixmap is None or self._drag_start is None or self._drag_current is None:
            return
        x0 = min(self._drag_start[0], self._drag_current[0])
        y0 = min(self._drag_start[1], self._drag_current[1])
        x1 = max(self._drag_start[0], self._drag_current[0])
        y1 = max(self._drag_start[1], self._drag_current[1])
        if x1 - x0 < 5 or y1 - y0 < 5:
            return
        display_scale = (self._base_pixmap.width() * self._zoom) / self._pdf_width
        if display_scale <= 0:
            return
        self._region = (
            x0 / display_scale,
            y0 / display_scale,
            x1 / display_scale,
            y1 / display_scale,
        )
        self._repaint()
        self.region_committed.emit(self._region)

    def _repaint(self) -> None:
        if self._base_pixmap is None:
            self.clear()
            return
        w = max(1, int(self._base_pixmap.width() * self._zoom))
        h = max(1, int(self._base_pixmap.height() * self._zoom))
        scaled = self._base_pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.resize(scaled.size())

        draw_region = self._region is not None
        draw_drag = self._drag_start is not None and self._drag_current is not None
        if draw_region or draw_drag:
            combined = QPixmap(scaled)
            painter = QPainter(combined)
            display_scale = scaled.width() / self._pdf_width

            if draw_region:
                rx0, ry0, rx1, ry1 = (int(v * display_scale) for v in self._region)
                painter.setPen(QPen(QColor("#bd93f9"), 2))
                painter.setBrush(QColor(189, 147, 249, 40))
                painter.drawRect(rx0, ry0, rx1 - rx0, ry1 - ry0)

            if draw_drag:
                dx0 = min(self._drag_start[0], self._drag_current[0])
                dy0 = min(self._drag_start[1], self._drag_current[1])
                dx1 = max(self._drag_start[0], self._drag_current[0])
                dy1 = max(self._drag_start[1], self._drag_current[1])
                painter.setPen(QPen(QColor("#a855f7"), 2, Qt.DashLine))
                painter.setBrush(QColor(168, 85, 247, 30))
                painter.drawRect(dx0, dy0, dx1 - dx0, dy1 - dy0)

            painter.end()
            self.setPixmap(combined)
        else:
            self.setPixmap(scaled)


_REVIEW_BTN_STYLE = (
    "QPushButton {"
    "  background-color: #bd93f9; color: #1a1a1a; border: none;"
    "  border-radius: 6px; padding: 8px; font-weight: 800;"
    "}"
    "QPushButton:hover { background-color: #caa9fa; }"
    "QPushButton:pressed { background-color: #a77de6; }"
)


class GridCanvas(QLabel):
    """Renders a PDF region with draggable row/column guide lines."""

    guides_changed = Signal()

    _GUIDE_COLOR = QColor("#4da6ff")
    _SELECT_COLOR = QColor("#ff9f43")
    _SNAP_PX = 8

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self._base_pixmap: QPixmap | None = None
        self._region_width: float = 1.0
        self._region_height: float = 1.0
        self._row_guides: list[float] = []
        self._col_guides: list[float] = []
        self._selected: tuple[str, int] | None = None
        self._mode: str = "select"
        self._dragging: bool = False
        self._col_guides_locked: bool = False

    def load(self, image_bytes: bytes, region_size: tuple[float, float]) -> None:
        px = QPixmap()
        px.loadFromData(image_bytes, "PNG")
        self._base_pixmap = px
        self._region_width, self._region_height = region_size
        self.resize(px.size())
        self._repaint()

    def set_guides(self, row_guides: list[float], col_guides: list[float]) -> None:
        rh, rw = self._region_height, self._region_width
        self._row_guides = [g for g in row_guides if 0 < g < rh]
        self._col_guides = [g for g in col_guides if 0 < g < rw]
        self._selected = None
        self._repaint()

    def get_row_guides(self) -> list[float]:
        return sorted(self._row_guides)

    def get_col_guides(self) -> list[float]:
        return sorted(self._col_guides)

    def selected_label(self) -> str:
        if self._selected is None:
            return "none"
        kind, idx = self._selected
        guides = self._row_guides if kind == "row" else self._col_guides
        if 0 <= idx < len(guides):
            return f"{'Row' if kind == 'row' else 'Column'} {idx + 1}"
        return "none"

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._selected = None
        cursors = {"add_row": Qt.SplitVCursor, "add_col": Qt.SplitHCursor}
        self.setCursor(cursors.get(mode, Qt.ArrowCursor))
        self._repaint()

    def set_col_guides_locked(self, locked: bool) -> None:
        self._col_guides_locked = locked

    def delete_selected(self) -> bool:
        if self._selected is None:
            return False
        kind, idx = self._selected
        if kind == "col" and self._col_guides_locked:
            return False
        target = self._row_guides if kind == "row" else self._col_guides
        if 0 <= idx < len(target):
            target.pop(idx)
            self._selected = None
            self._repaint()
            self.guides_changed.emit()
            return True
        return False

    def reset_guides(self, row_guides: list[float], col_guides: list[float]) -> None:
        self.set_guides(row_guides, col_guides)
        self.guides_changed.emit()

    def mousePressEvent(self, event) -> None:
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        px, py = pos.x(), pos.y()
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)

        if self._mode == "add_row":
            pdf_y = self._px_to_pdf_y(py)
            self._row_guides.append(max(0.001, min(self._region_height - 0.001, pdf_y)))
            self._selected = ("row", len(self._row_guides) - 1)
            self._mode = "select"
            self.setCursor(Qt.ArrowCursor)
            self._repaint()
            self.guides_changed.emit()
            return

        if self._mode == "add_col":
            pdf_x = self._px_to_pdf_x(px)
            self._col_guides.append(max(0.001, min(self._region_width - 0.001, pdf_x)))
            self._selected = ("col", len(self._col_guides) - 1)
            self._mode = "select"
            self.setCursor(Qt.ArrowCursor)
            self._repaint()
            self.guides_changed.emit()
            return

        hit = self._hit_test(px, py)
        self._selected = hit
        if hit is not None:
            self._dragging = True
            self.setCursor(Qt.ClosedHandCursor)
        self._repaint()
        self.guides_changed.emit()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        px, py = pos.x(), pos.y()

        if self._dragging and self._selected is not None:
            kind, idx = self._selected
            if kind == "row" and 0 <= idx < len(self._row_guides):
                self._row_guides[idx] = max(0.001, min(self._region_height - 0.001, self._px_to_pdf_y(py)))
            elif kind == "col" and 0 <= idx < len(self._col_guides):
                self._col_guides[idx] = max(0.001, min(self._region_width - 0.001, self._px_to_pdf_x(px)))
            self._repaint()
            return

        if self._mode == "select":
            hit = self._hit_test(px, py)
            if hit is not None:
                self.setCursor(Qt.SizeVerCursor if hit[0] == "row" else Qt.SizeHorCursor)
            else:
                self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging and event.button() == Qt.LeftButton:
            self._dragging = False
            self.setCursor(Qt.ArrowCursor)
            self.guides_changed.emit()
        else:
            super().mouseReleaseEvent(event)

    def _hit_test(self, px: int, py: int) -> tuple[str, int] | None:
        for idx, g in enumerate(self._row_guides):
            if abs(py - self._pdf_y_to_px(g)) <= self._SNAP_PX:
                return ("row", idx)
        for idx, g in enumerate(self._col_guides):
            if abs(px - self._pdf_x_to_px(g)) <= self._SNAP_PX:
                return ("col", idx)
        return None

    def _pdf_x_to_px(self, x: float) -> int:
        if self._base_pixmap is None or self._region_width == 0:
            return 0
        return int(x / self._region_width * self._base_pixmap.width())

    def _pdf_y_to_px(self, y: float) -> int:
        if self._base_pixmap is None or self._region_height == 0:
            return 0
        return int(y / self._region_height * self._base_pixmap.height())

    def _px_to_pdf_x(self, px: int) -> float:
        if self._base_pixmap is None or self._base_pixmap.width() == 0:
            return 0.0
        return px / self._base_pixmap.width() * self._region_width

    def _px_to_pdf_y(self, py: int) -> float:
        if self._base_pixmap is None or self._base_pixmap.height() == 0:
            return 0.0
        return py / self._base_pixmap.height() * self._region_height

    def _repaint(self) -> None:
        if self._base_pixmap is None:
            return
        combined = QPixmap(self._base_pixmap)
        painter = QPainter(combined)
        w, h = combined.width(), combined.height()

        for idx, g in enumerate(self._row_guides):
            py = self._pdf_y_to_px(g)
            is_sel = self._selected == ("row", idx)
            painter.setPen(QPen(self._SELECT_COLOR if is_sel else self._GUIDE_COLOR, 2 if is_sel else 1))
            painter.drawLine(0, py, w, py)

        for idx, g in enumerate(self._col_guides):
            px = self._pdf_x_to_px(g)
            is_sel = self._selected == ("col", idx)
            painter.setPen(QPen(self._SELECT_COLOR if is_sel else self._GUIDE_COLOR, 2 if is_sel else 1))
            painter.drawLine(px, 0, px, h)

        painter.end()
        self.setPixmap(combined)


class ManualGridEditorDialog(QDialog):
    def __init__(
        self,
        library: PdfLibrary,
        full_path: str,
        page_index: int,
        bbox: tuple[float, float, float, float],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.library = library
        self.full_path = full_path
        self.page_index = page_index
        self.bbox = bbox
        self.extracted_table: DetectedTable | None = None
        self._original_row_guides: list[float] = []
        self._original_col_guides: list[float] = []
        self._region_size: tuple[float, float] = (1.0, 1.0)

        self.setWindowTitle(tr("Manual Grid Editor"))
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        self.resize(1100, 660)

        try:
            image_bytes, region_size = library.render_region(full_path, page_index, bbox, max_width=900)
            proposal = library.propose_manual_grid(full_path, page_index, bbox)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("Error"), str(exc))
            self._init_failed = True
            return
        self._init_failed = False
        self._region_size = proposal.region_size
        self._original_row_guides = list(proposal.row_guides)
        _rw = proposal.region_size[0]
        _n = _REQUIRED_COLUMNS - 1
        _proposed_cols = [g for g in proposal.column_guides if 0 < g < _rw]
        if len(_proposed_cols) != _n:
            _proposed_cols = [_rw * i / _REQUIRED_COLUMNS for i in range(1, _REQUIRED_COLUMNS)]
        self._original_col_guides = _proposed_cols

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # ── Header ────────────────────────────────────────────────────────
        header_row = QHBoxLayout()
        title_label = QLabel(tr("Manual Grid Editor"))
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        header_row.addWidget(title_label)
        header_row.addStretch(1)
        self._show_tools_btn = QPushButton(tr("Show Tools"))
        self._show_tools_btn.setCheckable(True)
        self._show_tools_btn.setChecked(True)
        self._show_tools_btn.toggled.connect(self._toggle_toolbar)
        self._show_preview_btn = QPushButton(tr("Show Preview"))
        self._show_preview_btn.setCheckable(True)
        self._show_preview_btn.setChecked(True)
        self._show_preview_btn.toggled.connect(self._toggle_preview)
        self._fill_btn = QPushButton("⛶")
        self._fill_btn.setFixedSize(32, 28)
        self._fill_btn.setToolTip(tr("Fill screen"))
        self._fill_btn.clicked.connect(self._toggle_fill)
        header_row.addWidget(self._show_tools_btn)
        header_row.addWidget(self._show_preview_btn)
        header_row.addWidget(self._fill_btn)
        root.addLayout(header_row)

        subtitle = QLabel(
            tr("Review the proposed row and column guides, drag them into place, "
               "or add and remove guides before applying the extraction.")
        )
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # ── Toolbar ───────────────────────────────────────────────────────
        self._toolbar = QFrame()
        tb_layout = QHBoxLayout(self._toolbar)
        tb_layout.setContentsMargins(0, 4, 0, 4)
        tb_layout.setSpacing(6)
        self._add_row_btn = QPushButton(tr("+ Add Row Line"))
        self._add_row_btn.clicked.connect(lambda: self._grid_canvas.set_mode("add_row"))
        self._delete_btn = QPushButton(tr("Delete Line"))
        self._delete_btn.clicked.connect(self._delete_selected)
        self._reset_btn = QPushButton(tr("Reset Grid"))
        self._reset_btn.clicked.connect(self._reset_grid)
        tb_layout.addWidget(self._add_row_btn)
        tb_layout.addWidget(self._delete_btn)
        tb_layout.addWidget(self._reset_btn)
        tb_layout.addStretch(1)
        self._cancel_btn = QPushButton(tr("Cancel"))
        self._cancel_btn.clicked.connect(self.reject)
        self._apply_btn = QPushButton(tr("Apply Extraction and Close"))
        self._apply_btn.setStyleSheet(
            "QPushButton { background-color: #bd93f9; color: #1a1a1a; border: none;"
            " border-radius: 4px; padding: 6px 14px; font-weight: 800; }"
            "QPushButton:hover { background-color: #caa9fa; }"
            "QPushButton:pressed { background-color: #a77de6; }"
        )
        self._apply_btn.clicked.connect(self._apply_extraction)
        self._selected_label = QLabel(f"{tr('Selected')}: none")
        tb_layout.addWidget(self._cancel_btn)
        tb_layout.addWidget(self._apply_btn)
        tb_layout.addWidget(self._selected_label)
        root.addWidget(self._toolbar)

        # ── Main splitter: canvas | preview ───────────────────────────────
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setChildrenCollapsible(False)

        canvas_scroll = QScrollArea()
        canvas_scroll.setWidgetResizable(False)
        self._grid_canvas = GridCanvas()
        self._grid_canvas.guides_changed.connect(self._on_guides_changed)
        canvas_scroll.setWidget(self._grid_canvas)
        self._splitter.addWidget(canvas_scroll)

        self._preview_panel = QWidget()
        preview_layout = QVBoxLayout(self._preview_panel)
        preview_layout.setContentsMargins(8, 0, 0, 0)
        preview_title = QLabel(tr("Live Table Preview"))
        preview_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        preview_layout.addWidget(preview_title)
        self._preview_info = QLabel()
        preview_layout.addWidget(self._preview_info)
        self._preview_table = QTableWidget(0, 0)
        self._preview_table.verticalHeader().setVisible(False)
        self._preview_table.horizontalHeader().setStretchLastSection(True)
        preview_layout.addWidget(self._preview_table, 1)
        self._preview_panel.setFixedWidth(380)
        self._splitter.addWidget(self._preview_panel)
        self._splitter.setSizes([700, 380])
        root.addWidget(self._splitter, 1)

        # Load initial data
        self._grid_canvas.load(image_bytes, proposal.region_size)
        self._grid_canvas.set_guides(proposal.row_guides, self._original_col_guides)
        self._grid_canvas.set_col_guides_locked(True)
        self._update_preview()

    def was_init_failed(self) -> bool:
        return getattr(self, "_init_failed", True)

    # ── Toolbar actions ────────────────────────────────────────────────────

    def _toggle_toolbar(self, visible: bool) -> None:
        self._toolbar.setVisible(visible)

    def _toggle_preview(self, visible: bool) -> None:
        self._preview_panel.setVisible(visible)

    def _toggle_fill(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _delete_selected(self) -> None:
        sel = self._grid_canvas.selected_label()
        if not self._grid_canvas.delete_selected():
            if sel.startswith("Column"):
                QMessageBox.information(self, tr("Locked"), tr("Column guides are fixed. Only row guides can be deleted."))
            else:
                QMessageBox.information(self, tr("No Selection"), tr("Click a guide line to select it first."))

    def _reset_grid(self) -> None:
        self._grid_canvas.reset_guides(self._original_row_guides, self._original_col_guides)

    # ── Guide changes / preview ────────────────────────────────────────────

    def _on_guides_changed(self) -> None:
        label = self._grid_canvas.selected_label()
        self._selected_label.setText(f"{tr('Selected')}: {label}")
        self._update_preview()

    def _update_preview(self) -> None:
        table = self._extract_current()
        if table is None:
            self._preview_info.setText(tr("No data extracted."))
            self._preview_info.setStyleSheet("")
            self._preview_table.setRowCount(0)
            self._preview_table.setColumnCount(0)
            self._apply_btn.setEnabled(False)
            return

        cols_ok = table.columns == _REQUIRED_COLUMNS
        color = "#3ddc84" if cols_ok else "#f5a742"
        self._preview_info.setText(
            tr("Previewing {rows} row(s) and {cols}/{req} column(s).",
               rows=table.rows, cols=table.columns, req=_REQUIRED_COLUMNS)
        )
        self._preview_info.setStyleSheet(f"color: {color};")
        self._apply_btn.setEnabled(True)
        self._preview_table.setRowCount(table.rows)
        self._preview_table.setColumnCount(table.columns)
        if table.columns == _REQUIRED_COLUMNS:
            self._preview_table.setHorizontalHeaderLabels([
                tr("Test"), tr("Flag"), tr("Result"), tr("Unit"), tr("Reference"),
            ])
        for r, row in enumerate(table.data):
            for c, val in enumerate(row):
                self._preview_table.setItem(r, c, QTableWidgetItem(val))

    def _extract_current(self) -> DetectedTable | None:
        try:
            return self.library.extract_table_with_guides(
                self.full_path,
                self.page_index,
                self.bbox,
                self._grid_canvas.get_row_guides(),
                self._grid_canvas.get_col_guides(),
            )
        except Exception:  # noqa: BLE001
            return None

    def _apply_extraction(self) -> None:
        try:
            table = self.library.extract_table_with_guides(
                self.full_path,
                self.page_index,
                self.bbox,
                self._grid_canvas.get_row_guides(),
                self._grid_canvas.get_col_guides(),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("Extraction Failed"), str(exc))
            return
        if table is None:
            QMessageBox.warning(self, tr("No Data"), tr("No data was extracted from the selected region."))
            return
        if table.columns != _REQUIRED_COLUMNS:
            QMessageBox.warning(
                self,
                tr("Column Count Mismatch"),
                tr(
                    "The extraction produced {cols} column(s) but exactly {req} are required. "
                    "Adjust the column guides until the Live Table Preview shows {req} columns.",
                    cols=table.columns,
                    req=_REQUIRED_COLUMNS,
                ),
            )
            return
        self.extracted_table = table
        self.accept()


class LegacyPdfTableExtractorPage(DataAwarePage):
    extraction_changed = Signal(bool)
    delete_saved_extraction_requested = Signal(int)  # extraction_id

    def __init__(self, data_root: Path) -> None:
        super().__init__()
        self.library = PdfLibrary(data_root)
        self.current_document_path: str | None = None
        self.detected_tables: list[DetectedTable] = []
        self._page_count: int = 0
        self._current_page: int = 0
        self._zoom_index: int = 2  # 100%
        self._render_bytes: bytes | None = None
        self._render_pdf_size: tuple[float, float] = (1.0, 1.0)
        self._stored_region: tuple[float, float, float, float] | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # ── Drop zone (+ optional side panel on the same row) ─────────────
        self._top_row = QHBoxLayout()
        self._top_row.setSpacing(10)
        self._drop_zone = DropZoneFrame()
        self._drop_zone.files_dropped.connect(self._on_files_dropped)
        self._top_row.addWidget(self._drop_zone, 1)
        root.addLayout(self._top_row)

        # ── Current PDF status row ─────────────────────────────────────────
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self._current_pdf_key = QLabel()
        self._current_pdf_key.setStyleSheet("font-weight: bold;")
        self._current_pdf_value = QLabel()
        self._current_pdf_value.setWordWrap(True)
        status_row.addWidget(self._current_pdf_key)
        status_row.addWidget(self._current_pdf_value, 1)
        root.addLayout(status_row)

        # ── Page Preview header ────────────────────────────────────────────
        preview_header = QHBoxLayout()
        preview_header.setSpacing(6)
        self._preview_section_label = QLabel()
        self._preview_section_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        preview_header.addWidget(self._preview_section_label)
        preview_header.addStretch(1)
        self._page_nav_label = QLabel()
        self._page_number_label = QLabel("1")
        self._page_number_label.setFixedWidth(26)
        self._page_number_label.setAlignment(Qt.AlignCenter)
        self._page_up_btn = QPushButton("∧")
        self._page_up_btn.setFixedSize(26, 22)
        self._page_up_btn.clicked.connect(self._page_up)
        self._page_down_btn = QPushButton("∨")
        self._page_down_btn.setFixedSize(26, 22)
        self._page_down_btn.clicked.connect(self._page_down)
        preview_header.addWidget(self._page_nav_label)
        preview_header.addWidget(self._page_number_label)
        preview_header.addWidget(self._page_up_btn)
        preview_header.addWidget(self._page_down_btn)
        root.addLayout(preview_header)

        # ── Preview splitter: canvas | actions ─────────────────────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        self._preview_scroll = QScrollArea()
        self._preview_scroll.setWidgetResizable(False)
        self._canvas = PageCanvas()
        self._canvas.setAlignment(Qt.AlignCenter)
        self._canvas.region_committed.connect(self._on_region_drawn)
        self._preview_scroll.setWidget(self._canvas)
        splitter.addWidget(self._preview_scroll)

        actions_frame = QFrame()
        actions_frame.setFrameShape(QFrame.StyledPanel)
        actions_layout = QVBoxLayout(actions_frame)
        actions_layout.setContentsMargins(12, 12, 12, 12)
        actions_layout.setSpacing(8)

        self._actions_group_label = QLabel()
        self._actions_group_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        actions_layout.addWidget(self._actions_group_label)

        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(6)
        self._zoom_out_btn = QPushButton()
        self._zoom_out_btn.clicked.connect(self._zoom_out)
        self._zoom_in_btn = QPushButton()
        self._zoom_in_btn.clicked.connect(self._zoom_in)
        zoom_row.addWidget(self._zoom_out_btn)
        zoom_row.addWidget(self._zoom_in_btn)
        zoom_row.addStretch(1)
        actions_layout.addLayout(zoom_row)

        self._zoom_pct_label = QLabel(f"{_ZOOM_LEVELS[self._zoom_index]}%")
        actions_layout.addWidget(self._zoom_pct_label)

        self._draw_region_btn = QPushButton()
        self._draw_region_btn.setCheckable(True)
        self._draw_region_btn.toggled.connect(self._on_draw_mode_toggled)
        actions_layout.addWidget(self._draw_region_btn)

        self._clear_region_btn = QPushButton()
        self._clear_region_btn.clicked.connect(self._clear_region)
        actions_layout.addWidget(self._clear_region_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333;")
        actions_layout.addWidget(sep)

        self._extractions_label = QLabel()
        self._extractions_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        actions_layout.addWidget(self._extractions_label)

        self._extractions_container = QWidget()
        self._extractions_vbox = QVBoxLayout(self._extractions_container)
        self._extractions_vbox.setContentsMargins(0, 0, 0, 0)
        self._extractions_vbox.setSpacing(3)
        actions_layout.addWidget(self._extractions_container)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #333;")
        actions_layout.addWidget(sep2)

        self._saved_extractions_label = QLabel()
        self._saved_extractions_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        actions_layout.addWidget(self._saved_extractions_label)

        self._saved_extractions_container = QWidget()
        self._saved_extractions_vbox = QVBoxLayout(self._saved_extractions_container)
        self._saved_extractions_vbox.setContentsMargins(0, 0, 0, 0)
        self._saved_extractions_vbox.setSpacing(3)
        actions_layout.addWidget(self._saved_extractions_container)

        actions_layout.addStretch(1)
        actions_frame.setFixedWidth(230)
        splitter.addWidget(actions_frame)
        splitter.setSizes([700, 230])
        root.addWidget(splitter, 1)

        self.retranslate_ui()
        self._current_pdf_value.setText(
            tr("Import a PDF to begin detection and extraction. "
               "The most recently imported file becomes the active document.")
        )
        self._page_up_btn.setEnabled(False)
        self._page_down_btn.setEnabled(False)

    def retranslate_ui(self) -> None:
        self._drop_zone.retranslate_ui()
        self._current_pdf_key.setText(tr("Current PDF"))
        self._preview_section_label.setText(tr("Page Preview"))
        self._page_nav_label.setText(tr("Page"))
        self._actions_group_label.setText(tr("Page Actions"))
        self._zoom_out_btn.setText(tr("Zoom Out"))
        self._zoom_in_btn.setText(tr("Zoom In"))
        self._draw_region_btn.setText(tr("Draw a Region to Review"))
        self._clear_region_btn.setText(tr("Clear Region"))
        self._refresh_extractions_panel()
        self._saved_extractions_label.setText(f"{tr('Saved')}: 0")

    def refresh_on_show(self) -> None:
        self._render_current_page()

    def set_drop_zone_side_panel(self, widget: QWidget) -> None:
        widget.setParent(self)
        self._top_row.addWidget(widget)

    # ── File handling ──────────────────────────────────────────────────────

    def _on_files_dropped(self, file_paths: list[str]) -> None:
        imported = self.library.import_files(file_paths)
        if not imported:
            QMessageBox.warning(self, tr("Import Failed"), tr("No valid PDF file was selected."))
            return
        self.detected_tables = []
        self._refresh_extractions_panel()
        self.extraction_changed.emit(False)
        self._load_current_document()

    def _load_current_document(self) -> None:
        records = self.library.list_documents()
        record = records[0] if records else None
        self.current_document_path = record.full_path if record is not None else None
        self._page_count = record.page_count if record is not None else 0
        self._current_page = 0

        if record is not None:
            name = Path(record.full_path).name
            self._current_pdf_value.setText(
                f"{name}  —  {tr('Page count')}: {record.page_count}"
            )
        else:
            self._current_pdf_value.setText(
                tr("Import a PDF to begin detection and extraction. "
                   "The most recently imported file becomes the active document.")
            )

        self._page_number_label.setText("1")
        # Start on page 1: "previous" (∧) is disabled, "next" (∨) is enabled when
        # the document has more than one page so the second page is reachable.
        self._page_up_btn.setEnabled(False)
        self._page_down_btn.setEnabled(self._page_count > 1)
        self._render_current_page()

    # ── Page navigation ────────────────────────────────────────────────────

    def _page_up(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._page_number_label.setText(str(self._current_page + 1))
            self._page_up_btn.setEnabled(self._current_page > 0)
            self._page_down_btn.setEnabled(self._current_page < self._page_count - 1)
            self._exit_review_mode()
            self._canvas.clear_region()
            self._render_current_page()

    def _page_down(self) -> None:
        if self._current_page < self._page_count - 1:
            self._current_page += 1
            self._page_number_label.setText(str(self._current_page + 1))
            self._page_up_btn.setEnabled(self._current_page > 0)
            self._page_down_btn.setEnabled(self._current_page < self._page_count - 1)
            self._exit_review_mode()
            self._canvas.clear_region()
            self._render_current_page()

    def _render_current_page(self) -> None:
        if not self.current_document_path:
            self._canvas.clear()
            return
        try:
            image_bytes, pdf_size = self.library.render_page(
                self.current_document_path, self._current_page, max_width=_RENDER_BASE_WIDTH
            )
        except Exception as exc:  # noqa: BLE001
            self._canvas.setText(str(exc))
            return
        self._render_bytes = image_bytes
        self._render_pdf_size = pdf_size
        zoom = _ZOOM_LEVELS[self._zoom_index] / 100.0
        self._canvas.load_page(image_bytes, pdf_size, zoom)

    # ── Zoom ───────────────────────────────────────────────────────────────

    def _zoom_out(self) -> None:
        if self._zoom_index > 0:
            self._zoom_index -= 1
            self._apply_zoom()

    def _zoom_in(self) -> None:
        if self._zoom_index < len(_ZOOM_LEVELS) - 1:
            self._zoom_index += 1
            self._apply_zoom()

    def _apply_zoom(self) -> None:
        pct = _ZOOM_LEVELS[self._zoom_index]
        self._zoom_pct_label.setText(f"{pct}%")
        self._zoom_out_btn.setEnabled(self._zoom_index > 0)
        self._zoom_in_btn.setEnabled(self._zoom_index < len(_ZOOM_LEVELS) - 1)
        self._canvas.update_zoom(pct / 100.0)

    # ── Region drawing ─────────────────────────────────────────────────────

    def _on_draw_mode_toggled(self, checked: bool) -> None:
        self._canvas.set_draw_mode(checked)

    def _on_region_drawn(self, region: tuple) -> None:
        self._draw_region_btn.setChecked(False)
        self._canvas.set_draw_mode(False)
        if not self.current_document_path:
            return
        self._stored_region = region
        self._enter_review_mode()

    def _enter_review_mode(self) -> None:
        self._draw_region_btn.toggled.disconnect(self._on_draw_mode_toggled)
        self._draw_region_btn.setChecked(False)
        self._draw_region_btn.setCheckable(False)
        self._draw_region_btn.setStyleSheet(_REVIEW_BTN_STYLE)
        self._draw_region_btn.setText(tr("Review Region"))
        self._draw_region_btn.clicked.connect(self._open_grid_editor)

    def _exit_review_mode(self) -> None:
        if self._stored_region is None:
            return
        try:
            self._draw_region_btn.clicked.disconnect(self._open_grid_editor)
        except RuntimeError:
            pass
        self._stored_region = None
        self._draw_region_btn.setStyleSheet("")
        self._draw_region_btn.setText(tr("Draw a Region to Review"))
        self._draw_region_btn.setCheckable(True)
        self._draw_region_btn.toggled.connect(self._on_draw_mode_toggled)

    def _open_grid_editor(self) -> None:
        if not self.current_document_path or self._stored_region is None:
            return
        dialog = ManualGridEditorDialog(
            self.library,
            self.current_document_path,
            self._current_page,
            self._stored_region,
            parent=self,
        )
        if dialog.was_init_failed():
            return
        if dialog.exec() == QDialog.Accepted and dialog.extracted_table is not None:
            self.detected_tables.append(dialog.extracted_table)
            self._refresh_extractions_panel()
            self.extraction_changed.emit(True)
            self.library.append_extraction_log(
                "extract_grid",
                self.current_document_path,
                page_label=str(self._current_page + 1),
                rows=dialog.extracted_table.rows,
                columns=dialog.extracted_table.columns,
                method="manual-grid",
                detail="Manual grid editor extraction",
            )
        self._exit_review_mode()
        self._canvas.clear_region()

    def _clear_region(self) -> None:
        self._exit_review_mode()
        self._canvas.clear_region()
        self._draw_region_btn.setChecked(False)
        self._canvas.set_draw_mode(False)

    # ── Table detection ────────────────────────────────────────────────────

    def _detect_tables(self) -> None:
        if not self.current_document_path:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Import a PDF first."))
            return
        try:
            self.detected_tables = self.library.detect_tables_on_page(
                self.current_document_path, self._current_page
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("Detection Failed"), str(exc))
            return
        self.library.append_extraction_log(
            "detect_tables",
            self.current_document_path,
            page_label=str(self._current_page + 1),
            rows=sum(t.rows for t in self.detected_tables),
            columns=max((t.columns for t in self.detected_tables), default=0),
            detail=f"Detected {len(self.detected_tables)} table(s) on page {self._current_page + 1}",
        )

    def _refresh_extractions_panel(self) -> None:
        n = len(self.detected_tables)
        self._extractions_label.setText(f"{tr('Extractions')}: {n}")
        while self._extractions_vbox.count():
            item = self._extractions_vbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, table in enumerate(self.detected_tables):
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            lbl = QLabel(f"#{i + 1}  {table.rows} {tr('Rows').lower()}")
            lbl.setStyleSheet("font-size: 11px;")
            remove_btn = QPushButton("✕")
            remove_btn.setFixedSize(22, 22)
            remove_btn.setStyleSheet(
                "QPushButton { border: none; color: #f87171; font-weight: bold; background: transparent; }"
                "QPushButton:hover { color: #ef4444; }"
            )
            remove_btn.clicked.connect(lambda _checked, idx=i: self._remove_extraction(idx))
            row_layout.addWidget(lbl)
            row_layout.addStretch(1)
            row_layout.addWidget(remove_btn)
            self._extractions_vbox.addWidget(row_widget)

    def _remove_extraction(self, idx: int) -> None:
        if 0 <= idx < len(self.detected_tables):
            self.detected_tables.pop(idx)
            self._refresh_extractions_panel()
            if not self.detected_tables:
                self.extraction_changed.emit(False)

    def set_saved_extractions(self, extractions: list[dict]) -> None:
        n = len(extractions)
        self._saved_extractions_label.setText(f"{tr('Saved')}: {n}")
        while self._saved_extractions_vbox.count():
            item = self._saved_extractions_vbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for ext in extractions:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            page = str(ext.get("page_label") or "").strip()
            count = int(ext.get("row_count") or 0)
            lbl_text = f"p.{page}  {count} {tr('Rows').lower()}" if page else f"{count} {tr('Rows').lower()}"
            lbl = QLabel(lbl_text)
            lbl.setStyleSheet("font-size: 11px;")
            trash_btn = QPushButton("🗑")
            trash_btn.setFixedSize(24, 22)
            trash_btn.setStyleSheet(
                "QPushButton { border: none; color: #f87171; background: transparent; font-size: 13px; }"
                "QPushButton:hover { color: #ef4444; }"
            )
            ext_id = int(ext["id"])
            trash_btn.clicked.connect(lambda _checked, eid=ext_id: self.delete_saved_extraction_requested.emit(eid))
            row_layout.addWidget(lbl)
            row_layout.addStretch(1)
            row_layout.addWidget(trash_btn)
            self._saved_extractions_vbox.addWidget(row_widget)

    def _selected_table(self) -> DetectedTable | None:
        if not self.detected_tables:
            return None
        if len(self.detected_tables) == 1:
            return self.detected_tables[0]
        combined_data: list[list[str]] = []
        for t in self.detected_tables:
            combined_data.extend(t.data)
        first = self.detected_tables[0]
        return DetectedTable(
            document_path=first.document_path,
            page_index=first.page_index,
            page_label=first.page_label,
            table_index=first.table_index,
            bbox=first.bbox,
            rows=len(combined_data),
            columns=first.columns,
            data=combined_data,
            method="manual-grid",
        )


class PdfTableExtractorPage(DataAwarePage):
    def __init__(
        self,
        data_root: Path,
        database: Database | None = None,
        deployment_service: DeploymentService | None = None,
    ) -> None:
        super().__init__()
        self.data_root = data_root
        self.database = database if database is not None else Database(data_root.parent.parent / "spdxlims.db")
        if deployment_service is None:
            deployment_service = DeploymentService(data_root.parent.parent / "deployment.json")
        self.deployment_service = deployment_service
        # Routes outsourced-panel reads/writes to local SQLite or the server API
        # depending on the configured mode, so the addon works in server mode too.
        self.outsourced_service = OutsourcedService(self.database, self.deployment_service)
        self._pending_target_selection: tuple[object, str] | None = None
        self._external_window = None
        self._external_workspace = None
        self._fallback_page = None
        self._extraction_ready: bool = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.order_combo = QComboBox()
        self.order_combo.currentIndexChanged.connect(self._load_outsourced_panels_for_selected_order)
        self.outsourced_panel_combo = QComboBox()
        self.outsourced_panel_combo.currentIndexChanged.connect(self._refresh_saved_extractions)
        self.outsourced_panel_combo.setEnabled(False)
        self.save_to_outsourced_panel_button = QPushButton()
        self.save_to_outsourced_panel_button.clicked.connect(self._save_selected_table_to_outsourced_panel)

        selector_group = QGroupBox()
        selector_layout = QFormLayout(selector_group)
        selector_layout.addRow(tr("Order"), self.order_combo)
        selector_layout.addRow(tr("Outsourced Panel"), self.outsourced_panel_combo)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
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
            self._fallback_page = LegacyPdfTableExtractorPage(data_root)
            self._fallback_page.extraction_changed.connect(self._on_extraction_changed)
            self._fallback_page.delete_saved_extraction_requested.connect(self._delete_saved_extraction)
            self._fallback_page.set_drop_zone_side_panel(self.selector_group)
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

    def set_target_selection(self, order_id: object, panel_label: str) -> None:
        self._pending_target_selection = (order_id, str(panel_label))
        self._load_outsourced_orders()
        self._apply_pending_target_selection()

    def _refresh_saved_extractions(self) -> None:
        if self._fallback_page is None:
            return
        order_id = self.order_combo.currentData()
        panel_label = self.outsourced_panel_combo.currentData()
        if order_id is None or not panel_label:
            self._fallback_page.set_saved_extractions([])
            return
        extractions = self.outsourced_service.list_outsourced_panel_extractions(order_id, str(panel_label))
        self._fallback_page.set_saved_extractions(extractions)

    def _delete_saved_extraction(self, extraction_id: object) -> None:
        try:
            self.outsourced_service.delete_outsourced_panel_extraction(extraction_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("Delete Failed"), str(exc))
            return
        self._refresh_saved_extractions()

    def _on_extraction_changed(self, ready: bool) -> None:
        self._extraction_ready = ready
        self._update_save_btn()

    def _update_save_btn(self) -> None:
        self.save_to_outsourced_panel_button.setEnabled(self._extraction_ready)

    def _load_outsourced_orders(self) -> None:
        current_order_id = self.order_combo.currentData()
        self.order_combo.blockSignals(True)
        self.order_combo.clear()
        self.order_combo.addItem(tr("Select order"), None)
        for order_id, label in self.outsourced_service.list_outsourced_order_choices():
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
            self._update_save_btn()
            return
        panel_labels = self.outsourced_service.list_outsourced_panels_for_order(order_id)
        for label in panel_labels:
            self.outsourced_panel_combo.addItem(label, label)
        self.outsourced_panel_combo.setEnabled(bool(panel_labels))
        self._update_save_btn()
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
        workspace = self._active_workspace()
        rows = self._current_selected_table_rows()
        if not rows:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a detected table first."))
            return
        source_pdf_path = self._current_source_pdf_path()
        if not source_pdf_path:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Import a PDF first."))
            return
        table = getattr(workspace, "_selected_table", lambda: None)() if workspace else None
        page_label = str(getattr(table, "page_label", "") or "")
        try:
            self.outsourced_service.append_outsourced_panel_extraction(
                order_id, str(panel_label), source_pdf_path, page_label, rows
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("Save Failed"), str(exc))
            return
        QMessageBox.information(self, tr("Saved"), tr("Outsourced table saved to selected panel."))
        self._refresh_saved_extractions()

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
