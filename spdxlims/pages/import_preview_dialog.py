from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from spdxlims.i18n import tr


class ImportPreviewDialog(QDialog):
    def __init__(self, title: str, summary_lines: list[str], detail_lines: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.resize(640, 460)
        self.setWindowTitle(title)

        root = QVBoxLayout(self)
        summary = QLabel("\n".join(summary_lines))
        summary.setWordWrap(True)
        root.addWidget(summary)

        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlainText("\n".join(detail_lines) if detail_lines else tr("No row issues were found."))
        root.addWidget(self.details)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setText(tr("Import"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
