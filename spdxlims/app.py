from __future__ import annotations

import sys
from pathlib import Path


def _acquire_single_instance_lock(mutex_name: str) -> bool:
    """Return True if this is the first running instance (lock acquired).

    The mutex is named per installation, so the local install and the server
    checkout each guard themselves without blocking each other.
    """
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        _handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        return ctypes.windll.kernel32.GetLastError() != 183  # 183 = ERROR_ALREADY_EXISTS
    except Exception:
        return True

from PySide6.QtCore import QEvent, QLocale, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QComboBox, QDateEdit, QDateTimeEdit, QDoubleSpinBox, QMessageBox, QSpinBox, QTimeEdit

from spdxlims.addons import AddonManager
from spdxlims.auto_invoicing import run_auto_invoicing
from spdxlims.database import Database
from spdxlims.deployment import DeploymentConfig, DeploymentService
from spdxlims.i18n import set_language, tr
from spdxlims.instance import app_instance, apply_windows_identity, icon_path as instance_icon_path
from spdxlims.log import get_logger, setup_logging
from spdxlims.main_window import MainWindow
from spdxlims.theme import recolor, rgb as accent_rgb


class _App(QApplication):
    """QApplication subclass that prevents scroll wheel from changing combo/spin values."""

    def notify(self, obj, event):
        if event.type() == QEvent.Type.Wheel and isinstance(
            obj, (QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit, QTimeEdit)
        ):
            return False
        return super().notify(obj, event)


def _apply_dark_theme(app: QApplication) -> None:
    app_font = QFont("Segoe UI", 12)
    app.setFont(app_font)

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(31, 35, 42))           # #1f232a
    palette.setColor(QPalette.WindowText, QColor(195, 204, 223))    # #c3ccdf
    palette.setColor(QPalette.Base, QColor(31, 35, 42))             # #1f232a
    palette.setColor(QPalette.AlternateBase, QColor(32, 36, 43))    # #20242b
    palette.setColor(QPalette.ToolTipBase, QColor(32, 36, 43))      # #20242b
    palette.setColor(QPalette.ToolTipText, QColor(195, 204, 223))   # #c3ccdf
    palette.setColor(QPalette.Text, QColor(195, 204, 223))          # #c3ccdf
    palette.setColor(QPalette.Button, QColor(32, 36, 43))            # #20242b — neutral, QSS handles button purple
    palette.setColor(QPalette.ButtonText, QColor(195, 204, 223))    # #c3ccdf
    palette.setColor(QPalette.BrightText, QColor(255, 107, 107))    # #FF6B6B
    # Accent-coloured, so a second install wearing another accent takes its
    # links and selections with it. See spdxlims/theme.py.
    palette.setColor(QPalette.Link, QColor(*accent_rgb("#bd93f9")))
    palette.setColor(QPalette.Highlight, QColor(*accent_rgb("#634b8a")))  # selection
    palette.setColor(QPalette.HighlightedText, QColor(195, 204, 223))
    palette.setColor(QPalette.PlaceholderText, QColor(139, 149, 170)) # #8b95aa

    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(74, 86, 104))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(74, 86, 104))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(74, 86, 104))

    app.setPalette(palette)
    app.setStyleSheet(
        recolor(
            """
        QWidget {
            background-color: #1f232a;
            color: #c3ccdf;
            font-family: "Segoe UI";
            font-size: 12pt;
        }
        QMainWindow, QDialog {
            background-color: #1f232a;
        }
        QDialog {
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 14px;
        }
        QGroupBox {
            background-color: #20242b;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px;
            margin-top: 14px;
            padding: 14px;
            font-weight: 600;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
            color: #c3ccdf;
            font-size: 12pt;
        }
        QLineEdit, QTextEdit, QComboBox {
            background-color: #1f232a;
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: 7px;
            padding: 6px 10px;
            color: #c3ccdf;
            font-size: 11pt;
            selection-background-color: #bd93f9;
            selection-color: #1a1a1a;
        }
        QListWidget, QTableWidget {
            background-color: #1f232a;
            border: none;
            border-radius: 10px;
            color: #c3ccdf;
            font-size: 12pt;
            selection-background-color: transparent;
            selection-color: #c3ccdf;
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
            background-color: #20242b;
            alternate-background-color: #252930;
            gridline-color: transparent;
            selection-background-color: #392c4b;
            selection-color: #c3ccdf;
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
            background-color: #392c4b;
            color: #c3ccdf;
            border: none;
            border-radius: 0px;
        }
        QTableWidget {
            alternate-background-color: transparent;
        }
        QTableWidget::item {
            background-color: #20242b;
            border-top: 2px solid #1f232a;
            border-bottom: 2px solid #1f232a;
            padding: 8px 10px;
        }
        QTableWidget::item:selected {
            background-color: #634b8a;
            color: #c3ccdf;
        }
        QTableCornerButton::section, QHeaderView::section {
            background-color: #252930;
            color: #8b95aa;
            padding: 7px 6px;
            border: none;
            border-bottom: 1px solid rgba(255,255,255,0.08);
            font-size: 12pt;
        }
        QToolTip {
            background-color: #20242b;
            color: #c3ccdf;
            border: 1px solid rgba(255,255,255,0.08);
            padding: 4px 6px;
        }
        QPushButton {
            background: #392c4b;
            color: #c3ccdf;
            border: 1px solid #392c4b;
            border-radius: 7px;
            padding: 6px 10px;
            font-size: 10pt;
            font-weight: 700;
        }
        QPushButton:hover { background: #43365a; }
        QPushButton:pressed { background: #342744; }
        QPushButton:disabled {
            background: #252930;
            border-color: rgba(255,255,255,0.06);
            color: #4a5568;
        }
        QDialog QGroupBox {
            background-color: #20242b;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px;
            margin-top: 16px;
            padding: 16px;
        }
        QDialog QLabel { color: #c3ccdf; }
        QDialog QLineEdit,
        QDialog QTextEdit,
        QDialog QComboBox,
        QDialog QListWidget,
        QDialog QTableWidget {
            background-color: #1f232a;
            border: 1px solid rgba(255,255,255,0.12);
        }
        QDialog QPushButton { min-height: 18px; }
        QScrollArea {
            border: none;
            background: transparent;
        }
        QStatusBar {
            background-color: #191d24;
            color: #8b95aa;
            border-top: 1px solid rgba(255,255,255,0.06);
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
            background-color: #20242b;
            border-top: 3px solid #1f232a;
            border-bottom: 3px solid #1f232a;
            padding: 9px 12px;
        }
        QTableWidget#recentOrdersTable::item:selected {
            background-color: #634b8a;
            color: #c3ccdf;
        }
        QGroupBox#recentPatientsGroup,
        QGroupBox#catalogTestsGroup,
        QGroupBox#catalogPanelsGroup {
            background-color: #20242b;
            border: 1px solid rgba(255,255,255,0.08);
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
            background-color: #20242b;
            border-top: 3px solid #1f232a;
            border-bottom: 3px solid #1f232a;
            padding: 9px 12px;
        }
        QTableWidget#recentPatientsTable::item:selected,
        QTableWidget#catalogTestsTable::item:selected,
        QTableWidget#catalogPanelsTable::item:selected {
            background-color: #634b8a;
            color: #c3ccdf;
        }
        QLabel {
            background: transparent;
            font-size: 12pt;
        }
        QLabel#workspaceLabel {
            background-color: #252930;
            color: #c3ccdf;
            font-size: 12pt;
            font-weight: 700;
            letter-spacing: 0.5px;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px;
            padding: 10px 12px;
            margin-top: 2px;
        }
        QPushButton#workspaceSelector {
            background-color: #20242b;
            color: #8b95aa;
            border: 1px solid #20242b;
            border-radius: 10px;
            padding: 5px 0;
            font-size: 10pt;
            font-weight: 700;
            min-width: 0;
        }
        QPushButton#workspaceSelector:hover {
            background-color: #252930;
            color: #c3ccdf;
        }
        QPushButton#workspaceSelector:checked {
            background-color: #392c4b;
            border-color: #392c4b;
            color: #c3ccdf;
        }
        QWidget#navSidebar {
            background-color: #191d24;
            border: none;
        }
        QListWidget#navDrawer {
            background-color: #191d24;
            font-family: "Segoe UI";
            font-size: 12pt;
            font-weight: 600;
            padding: 2px;
            border: none;
            outline: 0;
        }
        QListWidget#navDrawer:focus {
            border: none;
            outline: 0;
        }
        """
        )
    )
    theme_path = Path(__file__).resolve().parent / "styles" / "dark_theme.qss"
    if theme_path.exists():
        app.setStyleSheet(app.styleSheet() + "\n" + recolor(theme_path.read_text(encoding="utf-8")))


def main() -> int:
    instance = app_instance()
    # Before any window exists, or Windows has already grouped this process
    # under the pythonw.exe taskbar button.
    apply_windows_identity()
    if not _acquire_single_instance_lock(instance.mutex_name):
        app = _App(sys.argv)
        QMessageBox.information(None, instance.display_name, f"{instance.display_name} ya está en ejecución.")
        return 0
    QLocale.setDefault(QLocale(QLocale.Language.Spanish, QLocale.Country.Mexico))
    app = _App(sys.argv)
    app.setApplicationName("SPDXLIMS")
    app.setOrganizationName("SPDXLIMS")
    icon_path = instance_icon_path()
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        app.setWindowIcon(icon)
    _apply_dark_theme(app)

    data_dir = Path.cwd() / "data"
    data_dir.mkdir(exist_ok=True)
    setup_logging(data_dir, debug="--debug" in sys.argv)
    _log = get_logger(__name__)

    database = Database(data_dir / "spdxlims.db")
    database.initialize()
    run_auto_invoicing(database)
    addon_manager = AddonManager(data_dir)
    deployment_service = DeploymentService(data_dir / "deployment.json")
    set_language(database.get_lab_settings().ui_language)
    deployment_config = deployment_service.load()

    if deployment_config.mode == "server":
        health = deployment_service.ping(deployment_config.server_url, deployment_config.api_timeout_seconds)
        if health.ok:
            deployment_service.try_auto_login()
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
    exit_code = app.exec()
    database.checkpoint()
    return exit_code








