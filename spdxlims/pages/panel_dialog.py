from __future__ import annotations

import re
import sqlite3
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spdxlims.database import Database
from spdxlims.i18n import tr
from spdxlims.panel_service import PanelService


class PanelDialog(QDialog):
    def __init__(self, database: Database, panel_service: PanelService | None = None, panel_id: int | str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.panel_service = panel_service
        self.panel_id = panel_id
        self._editing = panel_id is not None
        self.pending_items: list[dict[str, Any]] = []
        self._all_test_choices: list[tuple[str, str]] | list[tuple[int, str]] = []

        self.setModal(True)
        self.resize(760, 560)
        self.setWindowTitle(tr("Edit Panel") if panel_id is not None else tr("Add Panel"))

        root = QVBoxLayout(self)
        form_row = QHBoxLayout()
        form_row.setSpacing(12)
        self.panel_code = QLineEdit()
        self.panel_name = QLineEdit()
        self.panel_specimen_type = QLineEdit()
        self.panel_method = QLineEdit()
        panel_code_label = QLabel(tr("Panel Code"))
        panel_name_label = QLabel(tr("Panel Name"))
        form_row.addWidget(panel_code_label)
        form_row.addWidget(self.panel_code, 1)
        form_row.addWidget(panel_name_label)
        form_row.addWidget(self.panel_name, 3)
        root.addLayout(form_row)
        meta_row = QHBoxLayout()
        meta_row.setSpacing(12)
        meta_row.addWidget(QLabel(tr("Specimen Type")))
        meta_row.addWidget(self.panel_specimen_type, 1)
        meta_row.addWidget(QLabel(tr("Methodology")))
        meta_row.addWidget(self.panel_method, 1)
        root.addLayout(meta_row)

        content = QHBoxLayout()

        available_group = QGroupBox(tr("Available Tests"))
        available_group.setMinimumWidth(300)
        available_layout = QVBoxLayout(available_group)
        available_helper = QLabel(tr("Double click on a test to add it to the panel."))
        available_helper.setWordWrap(True)
        available_layout.addWidget(available_helper)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(tr("Search")))
        self.test_search = QLineEdit()
        self.test_search.setPlaceholderText(tr("Filter available tests"))
        self.test_search.textChanged.connect(self._filter_test_choices)
        search_row.addWidget(self.test_search, 1)
        available_layout.addLayout(search_row)
        self.available_tests = QListWidget()
        self.available_tests.setMinimumWidth(280)
        self.available_tests.setSelectionMode(QAbstractItemView.SingleSelection)
        self.available_tests.itemDoubleClicked.connect(lambda _item: self.add_selected_test())
        available_layout.addWidget(self.available_tests)
        content.addWidget(available_group, 4)

        items_group = QGroupBox(tr("Panel Items"))
        items_layout = QVBoxLayout(items_group)
        items_helper = QLabel(tr("Add tests, subheadings, and panel comments, then arrange them in the order they should appear."))
        items_helper.setWordWrap(True)
        items_layout.addWidget(items_helper)

        buttons = QHBoxLayout()
        add_test_button = QPushButton(tr("Add Selected Test"))
        add_test_button.clicked.connect(self.add_selected_test)
        add_heading_button = QPushButton(tr("Add Subheading"))
        add_heading_button.clicked.connect(self.add_subheading)
        add_comment_button = QPushButton(tr("Add Comment Section"))
        add_comment_button.clicked.connect(self.add_comment_section)
        buttons.addWidget(add_test_button)
        buttons.addWidget(add_heading_button)
        buttons.addWidget(add_comment_button)
        buttons.addStretch(1)
        items_layout.addLayout(buttons)

        self.panel_items = QListWidget()
        self.panel_items.setSelectionMode(QAbstractItemView.SingleSelection)
        items_layout.addWidget(self.panel_items)

        item_actions = QHBoxLayout()
        move_up_button = QPushButton(tr("Move Up"))
        move_up_button.clicked.connect(lambda: self._move_item(-1))
        move_down_button = QPushButton(tr("Move Down"))
        move_down_button.clicked.connect(lambda: self._move_item(1))
        remove_button = QPushButton(tr("Remove Selected Item"))
        remove_button.clicked.connect(self.remove_selected_item)
        item_actions.addWidget(move_up_button)
        item_actions.addWidget(move_down_button)
        item_actions.addStretch(1)
        item_actions.addWidget(remove_button)
        items_layout.addLayout(item_actions)
        content.addWidget(items_group, 5)

        root.addLayout(content)

        buttons = QHBoxLayout()
        cancel_button = QPushButton(tr("Cancel"))
        cancel_button.clicked.connect(self.reject)
        self.archive_panel_button = QPushButton()
        self.archive_panel_button.clicked.connect(self.toggle_panel_archive)
        save_button = QPushButton(tr("Update Panel") if self._editing else tr("Save Panel"))
        save_button.clicked.connect(self.save_panel)
        buttons.addStretch(1)
        if self._editing:
            buttons.addWidget(self.archive_panel_button)
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        root.addLayout(buttons)

        detail = self._get_panel_detail(self.panel_id, include_inactive=True) if self.panel_id is not None else None
        if self.panel_id is not None:
            if detail is None:
                QMessageBox.warning(self, tr("Missing Selection"), tr("The selected panel could not be loaded."))
                self.reject()
                return
            self.panel_code.setText(detail["code"])
            self.panel_name.setText(detail["name"])
            self.panel_specimen_type.setText(detail.get("specimen_type") or "")
            self.panel_method.setText(detail.get("method") or "")
            self.pending_items = [dict(item) for item in detail.get("items", [])]
            self.archive_panel_button.setText(tr("Unarchive Panel") if not detail.get("is_active") else tr("Archive Panel"))

        self._load_test_choices()
        self._refresh_panel_items()

    def _list_test_choices(self) -> list[tuple[str, str]] | list[tuple[int, str]]:
        if self.panel_service is not None:
            return self.panel_service.list_test_choices()
        return self.database.list_test_choices()

    def _get_panel_detail(self, panel_id: int | str | None, *, include_inactive: bool = False) -> dict[str, Any] | None:
        if panel_id is None:
            return None
        if self.panel_service is not None:
            return self.panel_service.get_panel_detail(panel_id, include_inactive=include_inactive)
        return self.database.get_panel_detail(int(panel_id), include_inactive=include_inactive)

    def _create_panel(self, code: str, name: str, panel_items: list[dict[str, Any]], specimen_type: str, method: str) -> None:
        if self.panel_service is not None:
            self.panel_service.create_panel(code, name, panel_items, specimen_type=specimen_type, method=method)
            return
        self.database.create_panel(code, name, panel_items, specimen_type=specimen_type, method=method)

    def _update_panel(self, panel_id: int | str | None, code: str, name: str, panel_items: list[dict[str, Any]], specimen_type: str, method: str) -> None:
        if panel_id is None:
            return
        if self.panel_service is not None:
            self.panel_service.update_panel(panel_id, code, name, panel_items, specimen_type=specimen_type, method=method)
            return
        self.database.update_panel(int(panel_id), code, name, panel_items, specimen_type=specimen_type, method=method)

    def _archive_panel(self, panel_id: int | str | None) -> None:
        if panel_id is None:
            return
        if self.panel_service is not None:
            self.panel_service.archive_panel(panel_id)
            return
        self.database.archive_panel(int(panel_id))

    def _unarchive_panel(self, panel_id: int | str | None) -> None:
        if panel_id is None:
            return
        if self.panel_service is not None:
            self.panel_service.unarchive_panel(panel_id)
            return
        self.database.unarchive_panel(int(panel_id))

    def _load_test_choices(self) -> None:
        self._all_test_choices = list(self._list_test_choices())
        self._filter_test_choices()

    def _filter_test_choices(self) -> None:
        self.available_tests.clear()
        query = self.test_search.text().strip().lower() if hasattr(self, "test_search") else ""
        for test_id, label in self._all_test_choices:
            if query and query not in str(label).lower():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, test_id)
            self.available_tests.addItem(item)

    def _refresh_panel_items(self) -> None:
        self.panel_items.clear()
        for item in self.pending_items:
            if item.get("item_type") == "heading":
                label = f'{tr("Heading")}: {item.get("heading_text") or item.get("label") or ""}'
            elif item.get("item_type") == "comment":
                label = f'{tr("Comment")}: {item.get("heading_text") or item.get("label") or ""}'
            else:
                label = self._display_test_label(str(item.get("label") or ""))
            list_item = QListWidgetItem(label)
            list_item.setData(Qt.UserRole, dict(item))
            self.panel_items.addItem(list_item)

    def add_selected_test(self) -> None:
        item = self.available_tests.currentItem()
        if item is None:
            QMessageBox.warning(self, tr("Missing Selection"), tr("Select a test to add."))
            return
        test_id = item.data(Qt.UserRole)
        if any(existing.get("item_type") == "test" and existing.get("test_id") == test_id for existing in self.pending_items):
            return
        self.pending_items.append({"item_type": "test", "test_id": test_id, "label": self._display_test_label(item.text())})
        self._refresh_panel_items()
        self.panel_items.setCurrentRow(self.panel_items.count() - 1)

    @staticmethod
    def _display_test_label(label: str) -> str:
        return re.sub(r"\s+\([A-Z0-9_-]{1,20}\)$", "", label.strip()).strip()

    def add_subheading(self) -> None:
        heading_text, accepted = QInputDialog.getText(self, tr("Add Subheading"), tr("Enter Subheading"))
        if not accepted:
            return
        heading_text = heading_text.strip()
        if not heading_text:
            QMessageBox.warning(self, tr("Missing Data"), tr("Subheading text is required."))
            return
        self.pending_items.append({"item_type": "heading", "heading_text": heading_text, "label": heading_text})
        self._refresh_panel_items()
        self.panel_items.setCurrentRow(self.panel_items.count() - 1)

    def add_comment_section(self) -> None:
        comment_text, accepted = QInputDialog.getText(self, tr("Add Comment Section"), tr("Enter Comment Section Label"), text=tr("Comments"))
        if not accepted:
            return
        comment_text = comment_text.strip()
        if not comment_text:
            QMessageBox.warning(self, tr("Missing Data"), tr("Comment section label is required."))
            return
        self.pending_items.append({"item_type": "comment", "heading_text": comment_text, "label": comment_text})
        self._refresh_panel_items()
        self.panel_items.setCurrentRow(self.panel_items.count() - 1)

    def remove_selected_item(self) -> None:
        row = self.panel_items.currentRow()
        if row < 0 or row >= len(self.pending_items):
            return
        self.pending_items.pop(row)
        self._refresh_panel_items()
        if self.panel_items.count() > 0:
            self.panel_items.setCurrentRow(min(row, self.panel_items.count() - 1))

    def _move_item(self, offset: int) -> None:
        row = self.panel_items.currentRow()
        new_row = row + offset
        if row < 0 or new_row < 0 or new_row >= len(self.pending_items):
            return
        self.pending_items[row], self.pending_items[new_row] = self.pending_items[new_row], self.pending_items[row]
        self._refresh_panel_items()
        self.panel_items.setCurrentRow(new_row)

    def toggle_panel_archive(self) -> None:
        if not self._editing or self.panel_id is None:
            return
        detail = self._get_panel_detail(self.panel_id, include_inactive=True)
        if detail is None:
            return
        if detail.get("is_active"):
            if QMessageBox.question(self, tr("Archive Panel"), tr("Archive this panel?")) != QMessageBox.Yes:
                return
            self._archive_panel(self.panel_id)
        else:
            self._unarchive_panel(self.panel_id)
        self.accept()

    def save_panel(self) -> None:
        if not self.panel_code.text().strip() or not self.panel_name.text().strip():
            QMessageBox.warning(self, tr("Missing Data"), tr("Panel code and panel name are required."))
            return
        if not self.pending_items:
            QMessageBox.warning(self, tr("Missing Data"), tr("Select at least one item for the panel."))
            return

        try:
            if self.panel_id is None:
                self._create_panel(self.panel_code.text(), self.panel_name.text(), self.pending_items, self.panel_specimen_type.text(), self.panel_method.text())
            else:
                self._update_panel(self.panel_id, self.panel_code.text(), self.panel_name.text(), self.pending_items, self.panel_specimen_type.text(), self.panel_method.text())
        except sqlite3.IntegrityError as exc:
            QMessageBox.critical(self, tr("Save Failed"), str(exc))
            return

        self.accept()
