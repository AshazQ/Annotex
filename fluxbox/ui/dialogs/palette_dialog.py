"""The command palette and the printable shortcut sheet, for any tool.

Both read a tool's action registry, so a command added to the registry shows
up in the palette and on the sheet with no extra wiring.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QLineEdit, QListWidget,
                               QListWidgetItem)

from .. import icons
from .. import shortcuts as sc
from .common import Dialog, hint


class CommandPalette(Dialog):
    """Ctrl+K: type a few letters, run any command."""

    commandChosen = Signal(str)

    def __init__(self, parent, actions, keys, enabled=None, theme=None):
        super().__init__(parent, "Command palette",
                         "Type to filter; Enter runs the highlighted command.",
                         width=580)
        self._actions = list(actions)
        self._keys = dict(keys or {})
        self._enabled = dict(enabled or {})
        self._theme = dict(theme or {})

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search commands…")
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._run_current)
        self.body.addWidget(self.search)

        self.list = QListWidget()
        self.list.setMinimumHeight(340)
        self.list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemActivated.connect(lambda _i: self._run_current())
        self.list.itemClicked.connect(lambda _i: self._run_current())
        self.body.addWidget(self.list, 1)

        self.empty = hint("No command matches that.")
        self.empty.setVisible(False)
        self.body.addWidget(self.empty)

        self.add_close_button("Cancel")
        self._populate()
        self.search.setFocus()

    def _populate(self, needle="") -> None:
        self.list.clear()
        needle = needle.strip().lower()
        colour = self._theme.get("sub", "#8b93a1")
        shown = 0
        for action_id, label, _default, category, icon_name, desc in self._actions:
            if self._enabled.get(action_id) is False:
                continue
            haystack = " ".join((label, category, desc, action_id)).lower()
            if needle and not all(part in haystack for part in needle.split()):
                continue
            key = self._keys.get(action_id, "")
            text = "%s   ·   %s" % (label, category)
            if key:
                text += "        %s" % key
            item = QListWidgetItem(icons.icon(icon_name, colour, 16), text)
            item.setData(Qt.ItemDataRole.UserRole, action_id)
            if desc:
                item.setToolTip(desc)
            self.list.addItem(item)
            shown += 1
        self.empty.setVisible(shown == 0)
        if shown:
            self.list.setCurrentRow(0)

    def _filter(self, text) -> None:
        self._populate(text)

    def _run_current(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        action_id = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        self.commandChosen.emit(action_id)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            row = self.list.currentRow()
            step = 1 if event.key() == Qt.Key.Key_Down else -1
            self.list.setCurrentRow(max(0, min(self.list.count() - 1,
                                               row + step)))
            return
        super().keyPressEvent(event)


class ShortcutSheet(Dialog):
    """Every binding, grouped, in one scrollable sheet.

    `extra` is [(category, [(label, key, description)])] for bindings that are
    not in the registry because they cannot be rebound - digit class hotkeys,
    arrow-key nudges and the like."""

    def __init__(self, parent, actions, keys, theme=None, mouse_hint="",
                 extra=None):
        super().__init__(parent, "Keyboard shortcuts",
                         "Rebind any of these in Settings → Shortcuts.",
                         width=640, height=600)
        keys = dict(keys or {})

        self.list = QListWidget()
        self.list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.list.setSpacing(1)
        self.body.addWidget(self.list, 1)

        groups = [(category, [(label, keys.get(action_id, ""), desc)
                              for action_id, label, _d, _c, _i, desc in rows])
                  for category, rows in sc.grouped(actions)]
        groups.extend(extra or [])

        for category, rows in groups:
            header = QListWidgetItem(category.upper())
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = header.font()
            font.setBold(True)
            font.setPointSizeF(max(8.0, font.pointSizeF() - 1))
            header.setFont(font)
            header.setSizeHint(QSize(0, 30))
            self.list.addItem(header)
            for label, key, desc in rows:
                text = "    %s" % label
                if key:
                    text += "\t\t%s" % key
                item = QListWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                if desc:
                    item.setToolTip(desc)
                self.list.addItem(item)

        if mouse_hint:
            self.body.addWidget(hint(mouse_hint))
        self.add_close_button()
