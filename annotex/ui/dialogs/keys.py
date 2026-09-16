"""A shortcut editor any tool's settings dialog can drop in as a tab."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView,
                               QKeySequenceEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from .. import design
from . import messages
from .. import shortcuts as sc
from .common import Dialog, hint


class KeyBindingsEditor(QWidget):
    """The rebindable commands of one tool, double-click to change."""

    def __init__(self, actions, overrides=None, reserved=(), parent=None):
        super().__init__(parent)
        self.actions = list(actions)
        self.reserved = set(reserved or ())
        self.keys = sc.resolve(self.actions, overrides or {})

        layout = QVBoxLayout(self)
        layout.setSpacing(design.SPACE["s"])
        layout.addWidget(hint("Double-click a shortcut to change it. Clearing "
                              "one leaves that command available from the "
                              "menus and the command palette."))

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Command", "Category", "Key"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        head = self.table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft
                                 | Qt.AlignmentFlag.AlignVCenter)
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(self._edit_key)

        for action_id, label, _default, category, _icon, _desc in self.actions:
            index = self.table.rowCount()
            self.table.insertRow(index)
            name = QTableWidgetItem(label)
            name.setData(Qt.ItemDataRole.UserRole, action_id)
            self.table.setItem(index, 0, name)
            self.table.setItem(index, 1, QTableWidgetItem(category))
            self.table.setItem(index, 2,
                               QTableWidgetItem(self.keys.get(action_id, "")))
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        clear = QPushButton("Clear shortcut")
        clear.clicked.connect(self._clear_key)
        reset = QPushButton("Reset all to defaults")
        reset.clicked.connect(self.reset)
        buttons.addWidget(clear)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def overrides(self) -> dict:
        return sc.overrides_from(self.actions, self.keys)

    def _current_action(self):
        index = self.table.currentRow()
        if index < 0:
            return None, None
        item = self.table.item(index, 0)
        return index, item.data(Qt.ItemDataRole.UserRole)

    def _edit_key(self) -> None:
        index, action_id = self._current_action()
        if action_id is None:
            return
        dialog = KeyCapture(self, sc.label(self.actions, action_id),
                            self.keys.get(action_id, ""))
        if dialog.exec() != Dialog.DialogCode.Accepted:
            return
        self.assign(action_id, dialog.value(), ask=True)

    @staticmethod
    def _same_key(a, b) -> bool:
        """Two spellings of one key - Del and Delete, Shift+Ctrl and Ctrl+Shift -
        are the same key, and only one command can have it."""
        if not a or not b:
            return False
        fmt = QKeySequence.SequenceFormat.PortableText
        return QKeySequence(a).toString(fmt) == QKeySequence(b).toString(fmt)

    def assign(self, action_id, chosen, ask=False) -> bool:
        if chosen and any(self._same_key(chosen, key) for key in self.reserved):
            if ask:
                messages.inform(self, "Reserved key",
                                        "%s is used by the canvas itself."
                                        % chosen)
            return False
        for other_id, key in self.keys.items():
            if other_id != action_id and self._same_key(key, chosen):
                if ask:
                    answer = messages.ask(
                        self, "Already used",
                        "%s is already bound to \"%s\".\n\nMove it to \"%s\"?"
                        % (chosen, sc.label(self.actions, other_id),
                           sc.label(self.actions, action_id)))
                    if not answer:
                        return False
                self.keys[other_id] = ""
                self._refresh_row(other_id)
                break
        self.keys[action_id] = chosen
        self._refresh_row(action_id)
        return True

    def _refresh_row(self, action_id) -> None:
        for index in range(self.table.rowCount()):
            item = self.table.item(index, 0)
            if item.data(Qt.ItemDataRole.UserRole) == action_id:
                self.table.item(index, 2).setText(self.keys.get(action_id, ""))
                return

    def _clear_key(self) -> None:
        index, action_id = self._current_action()
        if action_id is None:
            return
        self.keys[action_id] = ""
        self.table.item(index, 2).setText("")

    def reset(self) -> None:
        self.keys = sc.resolve(self.actions, {})
        for index in range(self.table.rowCount()):
            action_id = self.table.item(index, 0).data(Qt.ItemDataRole.UserRole)
            self.table.item(index, 2).setText(self.keys.get(action_id, ""))


class KeyCapture(Dialog):
    """Press the key you want."""

    def __init__(self, parent, label, current):
        super().__init__(parent, "Set shortcut",
                         "Press the key combination for \"%s\"." % label,
                         width=420)
        self.editor = QKeySequenceEdit()
        if current:
            self.editor.setKeySequence(QKeySequence(current))
        self.body.addWidget(self.editor)
        self.body.addWidget(hint("Press Escape to clear it."))
        self.add_button("Cancel", slot=self.reject)
        self.add_button("Set", primary=True, slot=self.accept)

    def value(self) -> str:
        return self.editor.keySequence().toString(
            QKeySequence.SequenceFormat.PortableText)
