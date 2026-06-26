"""PORTAL catalog page — manage the client portal's test catalog from the LIS.

Add tests to the portal (POST /lis/tests), edit them, and link each portal test
to a LIS test. Links are stored in the SAME local PortalStore mapping the order
-import flow reads, so a link set here pre-fills future order imports.

Talks to the portal directly via PortalClient (shared secret in PortalStore),
matching spdxlims/pages/portal_page.py. LIS tests are read/created through
TestService so it works in both local (SQLite) and server (API) modes.
"""
from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database
from spdxlims.deployment import DeploymentService
from spdxlims.pages.base_page import DataAwarePage
from spdxlims.portal.client import PortalClient, PortalError
from spdxlims.portal.settings import PortalStore
from spdxlims.test_service import TestService

_RESULT_KINDS = [("Texto", "text"), ("Numérico", "numeric"), ("Selección", "select")]
_CREATE_NEW = "__create_new__"


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.lower().split())


class AddPortalTestDialog(QDialog):
    """Create a test on the portal, and either link it to an existing LIS test
    or create a matching LIS test (create-in-both)."""

    def __init__(self, lis_choices: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Agregar examen al portal")
        self.setMinimumWidth(480)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.category = QLineEdit()
        self.turnaround = QSpinBox()
        self.turnaround.setRange(0, 8760)
        self.turnaround.setSuffix(" h")
        self.turnaround.setSpecialValueText("(sin definir)")
        self.result_kind = QComboBox()
        for label, value in _RESULT_KINDS:
            self.result_kind.addItem(label, value)
        self.lis_link = QComboBox()
        self.lis_link.addItem("(crear examen nuevo en el LIS)", _CREATE_NEW)
        for test_id, label in lis_choices:
            self.lis_link.addItem(label, test_id)
        self.lis_link.currentIndexChanged.connect(self._toggle_result_kind)

        form.addRow("Nombre", self.name)
        form.addRow("Categoría", self.category)
        form.addRow("Tiempo de entrega", self.turnaround)
        form.addRow("Examen del LIS", self.lis_link)
        form.addRow("Tipo de resultado (LIS)", self.result_kind)
        root.addLayout(form)

        hint = QLabel(
            "Si eliges «crear examen nuevo en el LIS», se creará el examen en ambos catálogos y se vincularán."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Agregar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.accepted_data: dict[str, Any] | None = None
        self._toggle_result_kind()

    def _toggle_result_kind(self) -> None:
        self.result_kind.setEnabled(self.lis_link.currentData() == _CREATE_NEW)

    def _on_accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Datos incompletos", "El nombre del examen es obligatorio.")
            return
        turnaround = self.turnaround.value() or None
        self.accepted_data = {
            "name": self.name.text().strip(),
            "category": self.category.text().strip(),
            "turnaround_hours": turnaround,
            "lis_test_id": str(self.lis_link.currentData() or ""),
            "result_kind": str(self.result_kind.currentData() or "text"),
        }
        self.accept()


class EditPortalTestDialog(QDialog):
    """Edit a portal test's fields and its link to a LIS test."""

    def __init__(self, test: dict[str, Any], current_link: str, lis_choices: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Editar examen del portal #{test.get('id')}")
        self.setMinimumWidth(480)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(str(test.get("name") or ""))
        self.category = QLineEdit(str(test.get("category") or ""))
        self.turnaround = QSpinBox()
        self.turnaround.setRange(0, 8760)
        self.turnaround.setSuffix(" h")
        self.turnaround.setSpecialValueText("(sin definir)")
        self.turnaround.setValue(int(test.get("turnaround_hours") or 0))
        self.active = QCheckBox("Activo")
        self.active.setChecked(bool(test.get("is_active", 1)))
        self.lis_link = QComboBox()
        self.lis_link.addItem("— sin vincular —", "")
        selected_index = 0
        for test_id, label in lis_choices:
            self.lis_link.addItem(label, test_id)
            if test_id == current_link:
                selected_index = self.lis_link.count() - 1
        self.lis_link.setCurrentIndex(selected_index)

        form.addRow("Nombre", self.name)
        form.addRow("Categoría", self.category)
        form.addRow("Tiempo de entrega", self.turnaround)
        form.addRow("", self.active)
        form.addRow("Examen del LIS", self.lis_link)
        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Guardar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.accepted_data: dict[str, Any] | None = None

    def _on_accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Datos incompletos", "El nombre del examen es obligatorio.")
            return
        self.accepted_data = {
            "name": self.name.text().strip(),
            "category": self.category.text().strip(),
            "turnaround_hours": self.turnaround.value() or None,
            "is_active": self.active.isChecked(),
            "lis_test_id": str(self.lis_link.currentData() or ""),
        }
        self.accept()


class PortalCatalogPage(DataAwarePage):
    def __init__(self, data_dir: Path, database: Database, deployment_service: DeploymentService) -> None:
        super().__init__()
        self.store = PortalStore(data_dir)
        self.test_service = TestService(database, deployment_service)
        self._portal_tests: list[dict[str, Any]] = []
        self._mapping: dict[str, str] = {}
        self._lis_choices: list[tuple[str, str]] = []   # (id, "name (code)") active only
        self._lis_label_by_id: dict[str, str] = {}      # all tests, for display
        self._lis_name_index: dict[str, str] = {}       # normalized name -> id, active only
        self.unlinked_only = False

        root = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("Catálogo del portal")
        title.setObjectName("SectionTitle")
        self.connection_label = QLabel()
        self.connection_label.setWordWrap(True)
        self.refresh_button = QPushButton("Actualizar")
        self.refresh_button.clicked.connect(self.refresh_on_show)
        header.addWidget(title)
        header.addWidget(self.connection_label, 1)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        self.group = QGroupBox("Exámenes del portal")
        layout = QVBoxLayout(self.group)
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar exámenes")
        self.search.textChanged.connect(self._refresh_table)
        self.all_button = QPushButton("Todos")
        self.all_button.clicked.connect(lambda: self._set_unlinked(False))
        self.unlinked_button = QPushButton("Solo sin vincular")
        self.unlinked_button.clicked.connect(lambda: self._set_unlinked(True))
        self.auto_button = QPushButton("Vincular por nombre")
        self.auto_button.clicked.connect(self._auto_match)
        self.add_button = QPushButton("Agregar examen")
        self.add_button.clicked.connect(self._add_test)
        self.edit_button = QPushButton("Editar")
        self.edit_button.clicked.connect(self._edit_selected)
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.all_button)
        toolbar.addWidget(self.unlinked_button)
        toolbar.addWidget(self.auto_button)
        toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.edit_button)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Examen del portal", "Categoría", "Activo", "Examen del LIS vinculado", "Estado"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self._edit_selected())
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 320)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(3, 300)
        layout.addWidget(self.table)
        root.addWidget(self.group, 1)

        self.refresh_on_show()

    # -- connection --------------------------------------------------------
    def _client(self) -> PortalClient | None:
        settings = self.store.load_settings()
        if not settings.is_configured():
            return None
        return PortalClient(settings.base_url, settings.shared_secret)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (self.search, self.all_button, self.unlinked_button, self.auto_button, self.add_button, self.edit_button, self.table):
            widget.setEnabled(enabled)

    def refresh_on_show(self) -> None:
        client = self._client()
        if client is None:
            self.connection_label.setText("● sin configurar — configura la conexión en la página PORTAL")
            self.connection_label.setStyleSheet("color: #7f8a98;")
            self._set_enabled(False)
            self._portal_tests = []
            self._refresh_table()
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._load_lis_tests()
            self._portal_tests = client.tests()
            self._mapping = self.store.load_mapping()
        except PortalError as exc:
            QApplication.restoreOverrideCursor()
            self.connection_label.setText(f"● sin conexión — {exc}")
            self.connection_label.setStyleSheet("color: #e05260;")
            self._set_enabled(False)
            self._portal_tests = []
            self._refresh_table()
            return
        except RuntimeError as exc:
            QApplication.restoreOverrideCursor()
            self.connection_label.setText(f"● error del LIS — {exc}")
            self.connection_label.setStyleSheet("color: #e05260;")
            self._set_enabled(False)
            self._refresh_table()
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.connection_label.setText("● conectado")
        self.connection_label.setStyleSheet("color: #3ddc84;")
        self._set_enabled(True)
        self._refresh_table()

    def _load_lis_tests(self) -> None:
        records = self.test_service.list_tests(status_filter="all")
        self._lis_choices = []
        self._lis_label_by_id = {}
        self._lis_name_index = {}
        for record in records:
            label = f"{record.name} ({record.code})" if record.code else record.name
            self._lis_label_by_id[str(record.id)] = label
            if record.is_active:
                self._lis_choices.append((str(record.id), label))
                self._lis_name_index.setdefault(_normalize(record.name), str(record.id))

    # -- table -------------------------------------------------------------
    def _set_unlinked(self, value: bool) -> None:
        self.unlinked_only = value
        self._refresh_table()

    def _visible_tests(self) -> list[dict[str, Any]]:
        query = self.search.text().strip().lower()
        result: list[dict[str, Any]] = []
        for test in self._portal_tests:
            linked = bool(self._mapping.get(str(test.get("id"))))
            if self.unlinked_only and linked:
                continue
            haystack = f"{test.get('name') or ''} {test.get('category') or ''}".lower()
            if query and query not in haystack:
                continue
            result.append(test)
        return result

    def _refresh_table(self) -> None:
        visible = self._visible_tests()
        self.table.setRowCount(len(visible))
        linked_total = sum(1 for t in self._portal_tests if self._mapping.get(str(t.get("id"))))
        for row, test in enumerate(visible):
            link_id = self._mapping.get(str(test.get("id")), "")
            link_label = self._lis_label_by_id.get(link_id, "") if link_id else ""
            is_active = bool(test.get("is_active", 1))
            values = [
                str(test.get("name") or ""),
                str(test.get("category") or ""),
                "Sí" if is_active else "No",
                link_label or ("(LIS desconocido)" if link_id else ""),
                "" if link_id else "Sin vincular",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.UserRole, int(test.get("id")))
                self.table.setItem(row, col, item)
        total = len(self._portal_tests)
        self.group.setTitle(
            f"Exámenes del portal — {total} en total, {total - linked_total} sin vincular" if total else "Exámenes del portal"
        )

    def _selected_test(self) -> dict[str, Any] | None:
        row = self.table.currentRow()
        visible = self._visible_tests()
        if row < 0 or row >= len(visible):
            return None
        return visible[row]

    # -- actions -----------------------------------------------------------
    def _add_test(self) -> None:
        client = self._client()
        if client is None:
            return
        dialog = AddPortalTestDialog(self._lis_choices, self)
        if dialog.exec() != QDialog.Accepted or dialog.accepted_data is None:
            return
        data = dialog.accepted_data
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            created = client.create_test(data["name"], data["category"] or None, data["turnaround_hours"])
            portal_id = int(created.get("id"))
            lis_test_id = self._resolve_lis_link(portal_id, data)
        except PortalError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Error del portal", str(exc))
            return
        except RuntimeError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(
                self,
                "Examen creado en el portal",
                f"El examen se creó en el portal, pero no se pudo crear/vincular en el LIS:\n{exc}",
            )
            self.refresh_on_show()
            return
        finally:
            QApplication.restoreOverrideCursor()
        if lis_test_id:
            self.store.update_mapping({str(portal_id): lis_test_id})
        self.notify_data_changed()
        self.refresh_on_show()

    def _resolve_lis_link(self, portal_id: int, data: dict[str, Any]) -> str:
        """Return the LIS test id to link, creating the LIS test if requested."""
        choice = data.get("lis_test_id") or ""
        if choice and choice != _CREATE_NEW:
            return choice
        if choice != _CREATE_NEW:
            return ""
        code = f"PRT-{portal_id}"
        self.test_service.create_test(
            {
                "code": code,
                "name": data["name"],
                "category_name": data["category"],
                "result_kind": data.get("result_kind") or "text",
            },
            [],
        )
        # create_test does not return the id; find it back by its unique code.
        for record in self.test_service.list_tests(status_filter="all"):
            if record.code == code:
                return str(record.id)
        return ""

    def _edit_selected(self) -> None:
        client = self._client()
        if client is None:
            return
        test = self._selected_test()
        if test is None:
            QMessageBox.information(self, "Selecciona un examen", "Elige un examen del portal de la lista.")
            return
        portal_id = int(test.get("id"))
        current_link = self._mapping.get(str(portal_id), "")
        dialog = EditPortalTestDialog(test, current_link, self._lis_choices, self)
        if dialog.exec() != QDialog.Accepted or dialog.accepted_data is None:
            return
        data = dialog.accepted_data
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            client.update_test(
                portal_id,
                name=data["name"],
                category=data["category"],
                turnaround_hours=data["turnaround_hours"],
                is_active=data["is_active"],
            )
        except PortalError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Error del portal", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        new_link = data.get("lis_test_id") or ""
        if new_link:
            self.store.update_mapping({str(portal_id): new_link})
        elif current_link:
            self._clear_mapping(portal_id)
        self.notify_data_changed()
        self.refresh_on_show()

    def _clear_mapping(self, portal_id: int) -> None:
        mapping = self.store.load_mapping()
        mapping.pop(str(portal_id), None)
        self.store.save_mapping(mapping)

    def _auto_match(self) -> None:
        if self._client() is None:
            return
        additions: dict[str, str] = {}
        unmatched: list[str] = []
        for test in self._portal_tests:
            portal_id = str(test.get("id"))
            if self._mapping.get(portal_id):
                continue
            match = self._lis_name_index.get(_normalize(str(test.get("name") or "")))
            if match:
                additions[portal_id] = match
            else:
                unmatched.append(str(test.get("name") or ""))
        if additions:
            self.store.update_mapping(additions)
        message = f"Se vincularon {len(additions)} examen(es) por nombre."
        if unmatched:
            preview = "\n".join(f"• {name}" for name in unmatched[:15])
            extra = f"\n…y {len(unmatched) - 15} más" if len(unmatched) > 15 else ""
            message += f"\n\nSin coincidencia ({len(unmatched)}):\n{preview}{extra}"
        QMessageBox.information(self, "Vincular por nombre", message)
        self.notify_data_changed()
        self.refresh_on_show()
