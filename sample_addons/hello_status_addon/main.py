from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


def create_page(context) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    title = QLabel("Hello from an addon")
    title.setStyleSheet("font-size: 18px; font-weight: 700;")
    layout.addWidget(title)
    layout.addWidget(
        QLabel(
            "This page was loaded from a downloadable addon bundle.\n"
            f"Addon files live in: {context.addon_dir}"
        )
    )
    layout.addStretch(1)
    return page
