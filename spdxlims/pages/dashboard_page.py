from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from spdxlims.i18n import tr


class DashboardPage(QWidget):
    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 12pt; font-weight: 700;")

        self.body = QLabel()
        self.body.setWordWrap(True)

        layout.addWidget(self.title)
        layout.addWidget(self.body)
        layout.addStretch(1)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self.title.setText(tr("Clinical Lab LIMS MVP"))
        self.body.setText(
            tr("This first build is centered on manual workflow:\npatient registration, order/result entry, and final branded reports.")
        )
