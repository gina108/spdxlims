from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QLocale, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QComboBox, QMessageBox, QSpinBox

from spdxlims.addons import AddonManager
from spdxlims.database import Database
from spdxlims.deployment import DeploymentConfig, DeploymentService
from spdxlims.i18n import set_language, tr
from spdxlims.main_window import MainWindow


class _App(QApplication):
    """QApplication subclass that prevents scroll wheel from changing combo/spin values."""

    def notify(self, obj, event):
        if event.type() == QEvent.Type.Wheel and isinstance(obj, (QComboBox, QSpinBox)):
            return False
        return super().notify(obj, event)


def _apply_dark_theme(app: QApplication) -> None:
    app_font = QFont("Segoe UI", 12)
    app.setFont(app_font)

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(24, 28, 34))
    palette.setColor(QPalette.WindowText, QColor(232, 236, 241))
    palette.setColor(QPalette.Base, QColor(18, 22, 27))
    palette.setColor(QPalette.AlternateBase, QColor(31, 36, 44))
    palette.setColor(QPalette.ToolTipBase, QColor(232, 236, 241))
    palette.setColor(QPalette.ToolTipText, QColor(18, 22, 27))
    palette.setColor(QPalette.Text, QColor(232, 236, 241))
    palette.setColor(QPalette.Button, QColor(38, 44, 52))
    palette.setColor(QPalette.ButtonText, QColor(232, 236, 241))
    palette.setColor(QPalette.BrightText, QColor(255, 107, 107))
    palette.setColor(QPalette.Link, QColor(189, 147, 249))
    palette.setColor(QPalette.Highlight, QColor(189, 147, 249))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.PlaceholderText, QColor(145, 152, 161))

    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(120, 127, 136))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 127, 136))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(120, 127, 136))

    app.setPalette(palette)
    app.setStyleSheet(
        """
        QWidget {
            background-color: #181c22;
            color: #e8ecf1;
            font-size: 12pt;
        }
        QMainWindow, QDialog {
            background-color: #181c22;
        }
        QDialog {
            border: 1px solid #465364;
            border-radius: 14px;
        }
        QGroupBox {
            background-color: #1d2229;
            border: 1px solid #3c4652;
            border-radius: 12px;
            margin-top: 14px;
            padding: 14px;
            font-weight: 600;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
            color: #f5f7fa;
            font-size: 12pt;
        }
        QLineEdit, QTextEdit, QComboBox {
            background-color: #101419;
            border: 1px solid #3c4652;
            border-radius: 8px;
            padding: 6px 8px;
            color: #e8ecf1;
            font-size: 12pt;
            selection-background-color: #bd93f9;
            selection-color: #ffffff;
        }
        QListWidget, QTableWidget {
            background-color: #181c22;
            border: none;
            border-radius: 10px;
            color: #e8ecf1;
            font-size: 12pt;
            selection-background-color: transparent;
            selection-color: #ffffff;
        }
        QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QListWidget:focus, QTableWidget:focus {
            border: 1px solid #bd93f9;
        }
        QComboBox {
            padding-right: 24px;
        }
        QComboBox::drop-down {
            border: none;
            width: 22px;
        }
        QComboBox QAbstractItemView, QListWidget, QTableWidget {
            background-color: #101419;
            alternate-background-color: #1a2028;
            gridline-color: transparent;
            selection-background-color: #bd93f9;
            selection-color: #ffffff;
            outline: 0;
        }
        QComboBox QAbstractItemView::item,
        QListWidget::item {
            border: none;
            border-radius: 0px;
            margin: 0px;
            padding: 6px 8px;
            background: transparent;
        }
        QComboBox QAbstractItemView::item:selected,
        QListWidget::item:selected {
            background-color: #bd93f9;
            color: #14171c;
            border: none;
            border-radius: 0px;
        }
        QTableWidget {
            alternate-background-color: transparent;
        }
        QTableWidget::item {
            background-color: #1f2630;
            border-top: 2px solid #181c22;
            border-bottom: 2px solid #181c22;
            padding: 8px 10px;
        }
        QTableWidget::item:selected {
            background-color: #bd93f9;
            color: #14171c;
        }
        QTableCornerButton::section, QHeaderView::section {
            background-color: #232a33;
            color: #eef2f6;
            padding: 7px 6px;
            border: none;
            border-bottom: 1px solid #3c4652;
            font-size: 12pt;
        }
        QToolTip {
            background-color: #232a33;
            color: #eef2f6;
            border: 1px solid #465160;
            padding: 4px 6px;
        }
        QPushButton {
            background-color: #bd93f9;
            color: #14171c;
            border: 1px solid #bd93f9;
            border-radius: 8px;
            padding: 7px 10px;
            font-size: 10pt;
            font-weight: 600;
        }
        QPushButton:hover {
            background-color: #caa8fb;
            border-color: #caa8fb;
        }
        QPushButton:pressed {
            background-color: #a97cf2;
            border-color: #a97cf2;
        }
        QPushButton:disabled {
            background-color: #39424d;
            border-color: #39424d;
            color: #98a0a8;
        }
        QPushButton[text^="Clear"],
        QPushButton[text^="Cancel"],
        QPushButton[text^="Close"],
        QPushButton[text^="Browse"],
        QPushButton[text^="Remove"],
        QPushButton[text^="Edit Selected"] {
            background-color: #232a33;
            border: 1px solid #465160;
            color: #e8ecf1;
        }
        QDialog QGroupBox {
            background-color: #1b2128;
            border: 1px solid #465364;
            border-radius: 12px;
            margin-top: 16px;
            padding: 16px;
        }
        QDialog QLabel {
            color: #dfe5ec;
        }
        QDialog QLineEdit,
        QDialog QTextEdit,
        QDialog QComboBox,
        QDialog QListWidget,
        QDialog QTableWidget {
            background-color: #0f1318;
            border: 1px solid #4a5667;
        }
        QDialog QPushButton {
            min-height: 18px;
        }
        QDialog QPushButton[text^="Cancel"],
        QDialog QPushButton[text^="Close"],
        QDialog QPushButton[text^="Browse"],
        QDialog QPushButton[text^="Remove"],
        QDialog QPushButton[text^="Edit Selected"] {
            background-color: #262e39;
            border-color: #556274;
        }
        QPushButton[text^="Clear"]:hover,
        QPushButton[text^="Cancel"]:hover,
        QPushButton[text^="Close"]:hover,
        QPushButton[text^="Browse"]:hover,
        QPushButton[text^="Remove"]:hover,
        QPushButton[text^="Edit Selected"]:hover {
            background-color: #2b3340;
            border-color: #5a6677;
        }
        QListWidget {
            padding: 6px;
        }
        QWidget#navSidebar {
            background-color: #181c22;
            border: none;
        }
        QListWidget#navDrawer {
            background-color: #181c22;
            font-family: "Segoe UI";
            font-size: 12pt;
            font-weight: 600;
            letter-spacing: 0px;
            padding: 2px;
            border: none;
            outline: 0;
        }
        QListWidget#navDrawer:focus {
            border: none;
            outline: 0;
        }
        QScrollArea {
            border: none;
            background: transparent;
        }
        QStatusBar {
            background-color: #1f242c;
            color: #d9dee4;
            border-top: 1px solid #39424d;
        }
        QWidget#recentOrdersGroup {
            background-color: transparent;
            border: none;
        }
        QTableWidget#recentOrdersTable {
            background-color: transparent;
            border: none;
            padding: 4px;
        }
        QTableWidget#recentOrdersTable::item {
            background-color: #202833;
            border-top: 3px solid #171b21;
            border-bottom: 3px solid #171b21;
            padding: 9px 12px;
        }
        QTableWidget#recentOrdersTable::item:selected {
            background-color: #bd93f9;
            color: #14171c;
        }
        QGroupBox#recentPatientsGroup,
        QGroupBox#catalogTestsGroup,
        QGroupBox#catalogPanelsGroup {
            background-color: #171b21;
            border: 1px solid #465364;
        }
        QTableWidget#recentPatientsTable,
        QTableWidget#catalogTestsTable,
        QTableWidget#catalogPanelsTable {
            background-color: transparent;
            border: none;
            padding: 4px;
        }
        QTableWidget#recentPatientsTable::item,
        QTableWidget#catalogTestsTable::item,
        QTableWidget#catalogPanelsTable::item {
            background-color: #202833;
            border-top: 3px solid #171b21;
            border-bottom: 3px solid #171b21;
            padding: 9px 12px;
        }
        QTableWidget#recentPatientsTable::item:selected,
        QTableWidget#catalogTestsTable::item:selected,
        QTableWidget#catalogPanelsTable::item:selected {
            background-color: #bd93f9;
            color: #14171c;
        }
        QLabel {
            background: transparent;
            font-size: 12pt;
        }
        QLabel#workspaceLabel {
            background-color: #202833;
            color: #f5f7fa;
            font-size: 12pt;
            font-weight: 700;
            letter-spacing: 0.5px;
            border: 1px solid #465364;
            border-radius: 12px;
            padding: 10px 12px;
            margin-top: 2px;
        }
        QPushButton#workspaceSelector {
            background-color: #232a33;
            color: #d9dee4;
            border: 1px solid #465160;
            border-radius: 10px;
            padding: 5px 0;
            font-size: 10pt;
            font-weight: 700;
            min-width: 0;
        }
        QPushButton#workspaceSelector:hover {
            background-color: #2b3340;
            border-color: #5a6677;
            color: #f5f7fa;
        }
        QPushButton#workspaceSelector:checked {
            background-color: #bd93f9;
            border-color: #bd93f9;
            color: #14171c;
        }
        """
    )
    theme_path = Path(__file__).resolve().parent / "styles" / "dark_theme.qss"
    if theme_path.exists():
        app.setStyleSheet(app.styleSheet() + "\n" + theme_path.read_text(encoding="utf-8"))


def main() -> int:
    QLocale.setDefault(QLocale(QLocale.Language.Spanish, QLocale.Country.Mexico))
    app = _App(sys.argv)
    app.setApplicationName("SPDXLIMS")
    app.setOrganizationName("SPDXLIMS")
    icon_path = Path(__file__).resolve().parent.parent / "assets" / "SDXSquarePurple.png"
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        app.setWindowIcon(icon)
    _apply_dark_theme(app)

    data_dir = Path.cwd() / "data"
    data_dir.mkdir(exist_ok=True)

    database = Database(data_dir / "spdxlims.db")
    database.initialize()
    addon_manager = AddonManager(data_dir)
    deployment_service = DeploymentService(data_dir / "deployment.json")
    set_language(database.get_lab_settings().ui_language)
    deployment_config = deployment_service.load()

    if deployment_config.mode == "server":
        health = deployment_service.ping(deployment_config.server_url, deployment_config.api_timeout_seconds)
        if not health.ok:
            message_box = QMessageBox()
            message_box.setIcon(QMessageBox.Warning)
            message_box.setWindowTitle(tr("Server Connection"))
            message_box.setText(tr("The configured server is unavailable."))
            message_box.setInformativeText(
                tr(
                    "Could not reach {server_url}.\n\n{error_message}\n\nWould you like to start in local mode instead?",
                    server_url=deployment_config.server_url,
                    error_message=health.message,
                )
            )
            start_local_button = message_box.addButton(tr("Start in Local Mode"), QMessageBox.AcceptRole)
            exit_button = message_box.addButton(tr("Exit"), QMessageBox.RejectRole)
            message_box.exec()
            if message_box.clickedButton() is start_local_button:
                deployment_service.save(
                    DeploymentConfig(
                        mode="local",
                        server_url=deployment_config.server_url,
                        api_timeout_seconds=deployment_config.api_timeout_seconds,
                    )
                )
            else:
                return 0

    window = MainWindow(database, deployment_service, addon_manager)
    if icon_path.exists():
        window.setWindowIcon(icon)
    screen = app.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        width = max(1100, available.width() - 24)
        height = min(760, max(640, available.height() - 40))
        window.resize(width, height)
    else:
        window.resize(1280, 760)
    window.show()
    return app.exec()








