"""LabelImg Shapes' side panel: the shapes on the current image."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QToolButton, QVBoxLayout, QWidget)

from annotex.ui import icons
from annotex.ui.widgets import section_label

KIND_ICONS = {"polygon": "polygon", "obb": "obb", "circle": "circle",
              "ellipse": "ellipse", "freehand": "freehand"}


class ShapeListPanel(QWidget):
    selectionRequested = Signal(object)          # [index]
    editRequested = Signal()
    duplicateRequested = Signal()
    deleteRequested = Signal()
    lockToggled = Signal(object, bool)
    visibilityToggled = Signal(object, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = {}
        self._shapes = []
        self._colour_for = None
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(section_label("Shapes on this image"))
        header.addStretch(1)
        self.count_label = QLabel("0")
        self.count_label.setObjectName("Subtitle")
        header.addWidget(self.count_label)
        layout.addLayout(header)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setUniformItemSizes(True)      # the list may hold hundreds
        self.list.setMinimumHeight(120)
        self.list.setIconSize(QSize(16, 16))
        self.list.itemSelectionChanged.connect(self._emit_selection)
        self.list.itemDoubleClicked.connect(lambda _item: self.editRequested.emit())
        layout.addWidget(self.list, 1)

        self.empty_hint = QLabel("Nothing drawn yet - pick a shape tool above and draw.")
        self.empty_hint.setObjectName("Hint")
        self.empty_hint.setWordWrap(True)
        layout.addWidget(self.empty_hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        self.buttons = {}
        for key, icon, tip in (("edit", "tag", "Change the class  [Ctrl+E]"),
                               ("duplicate", "copy", "Duplicate  [Ctrl+D]"),
                               ("lock", "lock", "Lock or unlock"),
                               ("hide", "eye", "Hide or show"),
                               ("delete", "trash", "Delete  [Del]")):
            button = QToolButton()
            button.setObjectName("Tool")
            button.setToolTip(tip)
            button.setIconSize(QSize(17, 17))
            buttons.addWidget(button)
            self.buttons[key] = (button, icon)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.buttons["edit"][0].clicked.connect(self.editRequested.emit)
        self.buttons["duplicate"][0].clicked.connect(self.duplicateRequested.emit)
        self.buttons["delete"][0].clicked.connect(self.deleteRequested.emit)
        self.buttons["lock"][0].clicked.connect(self._toggle_lock)
        self.buttons["hide"][0].clicked.connect(self._toggle_hidden)
        self._sync_buttons()

    def set_theme(self, theme) -> None:
        self._theme = dict(theme)
        for button, icon in self.buttons.values():
            colour = theme.get("danger" if icon == "trash" else "text", "#c8cdd6")
            button.setIcon(icons.icon(icon, colour, 17))
        self._rebuild(self.selected_rows())

    def set_shapes(self, shapes, colour_for, selection=()) -> None:
        self._shapes = list(shapes)
        self._colour_for = colour_for
        self._rebuild(selection)

    def selected_rows(self):
        """Every selected row.

        The row is read back off the item rather than looked up with
        QListWidget.row(), which walks the list: with a few hundred shapes
        selected that turns one selection change into a visible pause."""
        rows = []
        for item in self.list.selectedItems():
            row = item.data(Qt.ItemDataRole.UserRole)
            rows.append(self.list.row(item) if row is None else int(row))
        return sorted(rows)

    def set_selection(self, indices) -> None:
        self._updating = True
        blocked = self.list.blockSignals(True)
        self.list.setUpdatesEnabled(False)
        try:
            wanted = set(indices)
            for row in range(self.list.count()):
                item = self.list.item(row)
                if item is not None:
                    item.setSelected(row in wanted)
            if wanted:
                first = self.list.item(min(wanted))
                if first is not None:
                    self.list.scrollToItem(first)
        finally:
            self.list.setUpdatesEnabled(True)
            self.list.blockSignals(blocked)
            self._updating = False
        self._sync_buttons()

    def _rebuild(self, selection) -> None:
        self._updating = True
        wanted = set(selection or ())
        blocked = self.list.blockSignals(True)
        self.list.setUpdatesEnabled(False)
        try:
            self.list.clear()
            for index, shape in enumerate(self._shapes):
                colour = self._colour_for(shape.label) if self._colour_for else "#f0a33d"
                flags = []
                if shape.locked:
                    flags.append("locked")
                if not shape.visible:
                    flags.append("hidden")
                text = "%s   ·   %s  %s%s" % (shape.label or "no class", shape.kind_label,
                                              shape.describe(),
                                              ("   (%s)" % ", ".join(flags)) if flags else "")
                item = QListWidgetItem(icons.icon(KIND_ICONS.get(shape.kind, "polygon"),
                                                  colour, 16), text)
                item.setToolTip("Shape %d  ·  double-click to change the class" % (index + 1))
                item.setData(Qt.ItemDataRole.UserRole, index)
                self.list.addItem(item)
                item.setSelected(index in wanted)
        finally:
            self.list.setUpdatesEnabled(True)
            self.list.blockSignals(blocked)
            self._updating = False
        count = len(self._shapes)
        self.count_label.setText(str(count))
        self.list.setVisible(bool(count))
        self.empty_hint.setVisible(not count)
        self._sync_buttons()

    def _emit_selection(self) -> None:
        self._sync_buttons()
        if not self._updating:
            self.selectionRequested.emit(self.selected_rows())

    def _sync_buttons(self) -> None:
        has = bool(self.list.selectedItems())
        for button, _icon in self.buttons.values():
            button.setEnabled(has)

    def _toggle_lock(self) -> None:
        rows = self.selected_rows()
        if rows:
            value = not all(self._shapes[r].locked for r in rows if r < len(self._shapes))
            self.lockToggled.emit(rows, value)

    def _toggle_hidden(self) -> None:
        rows = self.selected_rows()
        if rows:
            visible = not all(self._shapes[r].visible for r in rows if r < len(self._shapes))
            self.visibilityToggled.emit(rows, visible)
