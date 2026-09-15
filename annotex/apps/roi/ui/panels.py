"""Side panels: the ROI list and the vertex inspector.

The minimap, the batch counters and the comment box are the suite's shared
panels and are re-exported here so the window imports them from one place.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView,
                               QLabel, QListWidget, QListWidgetItem,
                               QTableWidget, QTableWidgetItem, QToolButton,
                               QVBoxLayout, QWidget)

from annotex.ui.widgets import (CommentBox, MiniMap, StatsPanel,  # noqa: F401
                                divider, section_label)

from ....ui import design
from ..config import SHAPE_CIRCLE, SHAPE_RECT
from . import icons
from .palette import qcolor


# ══════════════════════════════════════════════════════════════
class RoiListPanel(QWidget):
    """Every ROI on the current image, with per-row visibility and lock."""

    selectionRequested = Signal(int, bool)      # index, additive
    visibilityToggled = Signal(int, bool)
    lockToggled = Signal(int, bool)
    deleteRequested = Signal()
    duplicateRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = {}
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(design.SPACE["s"])
        header.addWidget(section_label("ROIs on this image"))
        header.addStretch(1)
        self.count_label = QLabel("0")
        self.count_label.setObjectName("Subtitle")
        header.addWidget(self.count_label)
        layout.addLayout(header)

        self.list = QListWidget()
        self.list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setUniformItemSizes(True)
        self.list.setMinimumHeight(120)
        self.list.itemSelectionChanged.connect(self._emit_selection)
        self.list.itemClicked.connect(self._maybe_toggle)
        layout.addWidget(self.list, 1)

        actions = QHBoxLayout()
        actions.setSpacing(design.SPACE["s"])
        self.btn_visible = self._action("eye", "Show or hide the selected ROI")
        self.btn_lock = self._action("lock", "Lock the selected ROI so it "
                                             "cannot be moved")
        self.btn_duplicate = self._action("copy", "Duplicate the selected ROI")
        self.btn_delete = self._action("trash", "Delete the selected ROI")
        self.btn_visible.clicked.connect(self._toggle_visible)
        self.btn_lock.clicked.connect(self._toggle_lock)
        self.btn_duplicate.clicked.connect(self.duplicateRequested.emit)
        self.btn_delete.clicked.connect(self.deleteRequested.emit)
        for button in (self.btn_visible, self.btn_lock, self.btn_duplicate,
                       self.btn_delete):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self._shapes = []

    def _action(self, name, tip) -> QToolButton:
        button = QToolButton()
        button.setObjectName("Tool")
        button.setToolTip(tip)
        button.setIconSize(QSize(design.ICON["s"], design.ICON["s"]))
        button.setProperty("iconName", name)
        button.setAutoRaise(True)
        return button

    def set_theme(self, theme: dict) -> None:
        self._theme = dict(theme)
        for button in (self.btn_visible, self.btn_lock, self.btn_duplicate,
                       self.btn_delete):
            colour = theme["danger"] if button is self.btn_delete else theme["sub"]
            button.setIcon(icons.icon(button.property("iconName"), colour, 17))
        self.refresh(self._shapes, set())

    # ── content ───────────────────────────────────────────
    def refresh(self, shapes, selection) -> None:
        self._shapes = list(shapes or [])
        selection = set(selection or ())
        self._updating = True
        try:
            self.list.clear()
            theme = self._theme or {}
            for index, shape in enumerate(self._shapes):
                marks = []
                if not shape.visible:
                    marks.append("hidden")
                if shape.locked:
                    marks.append("locked")
                suffix = ("  ·  " + ", ".join(marks)) if marks else ""
                item = QListWidgetItem("ROI %d   %s%s"
                                       % (index + 1, shape.describe(), suffix))
                item.setData(Qt.ItemDataRole.UserRole, index)
                kind_icon = {SHAPE_RECT: "rect", SHAPE_CIRCLE: "circle"}.get(
                    shape.kind, "polygon")
                colour = theme.get("muted" if (shape.locked or not shape.visible)
                                   else "text", "#c8cdd6")
                item.setIcon(icons.icon(kind_icon, colour, 15))
                if not shape.visible or shape.locked:
                    item.setForeground(QBrush(qcolor(theme.get("muted",
                                                               "#6f7784"))))
                self.list.addItem(item)
                item.setSelected(index in selection)
            self.count_label.setText(str(len(self._shapes)))
        finally:
            self._updating = False
        self._sync_buttons(selection)

    def _sync_buttons(self, selection) -> None:
        has = bool(selection)
        for button in (self.btn_visible, self.btn_lock, self.btn_duplicate,
                       self.btn_delete):
            button.setEnabled(has)
        if has:
            index = sorted(selection)[0]
            if 0 <= index < len(self._shapes):
                shape = self._shapes[index]
                theme = self._theme or {}
                self.btn_visible.setIcon(icons.icon(
                    "eye" if shape.visible else "eye_off",
                    theme.get("sub", "#8b93a1"), 17))
                self.btn_lock.setIcon(icons.icon(
                    "lock" if not shape.locked else "unlock",
                    theme.get("sub", "#8b93a1"), 17))

    def selected_indices(self):
        return sorted(item.data(Qt.ItemDataRole.UserRole)
                      for item in self.list.selectedItems())

    def _emit_selection(self) -> None:
        if self._updating:
            return
        indices = self.selected_indices()
        self._sync_buttons(set(indices))
        if indices:
            self.selectionRequested.emit(indices[0], False)
            for index in indices[1:]:
                self.selectionRequested.emit(index, True)
        else:
            self.selectionRequested.emit(-1, False)

    def _maybe_toggle(self, _item) -> None:
        self._sync_buttons(set(self.selected_indices()))

    def _toggle_visible(self) -> None:
        for index in self.selected_indices():
            if 0 <= index < len(self._shapes):
                self.visibilityToggled.emit(index, not self._shapes[index].visible)

    def _toggle_lock(self) -> None:
        for index in self.selected_indices():
            if 0 <= index < len(self._shapes):
                self.lockToggled.emit(index, not self._shapes[index].locked)


# ══════════════════════════════════════════════════════════════
class VertexInspector(QWidget):
    """Numeric read-out and entry for the selected ROI's points."""

    vertexEdited = Signal(int, int, int, int)   # shape, vertex, x, y

    def __init__(self, parent=None):
        super().__init__(parent)
        self._index = -1
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(design.SPACE["s"])
        header = QHBoxLayout()
        header.addWidget(section_label("Vertices"))
        header.addStretch(1)
        self.hint = QLabel("-")
        self.hint.setObjectName("Subtitle")
        header.addWidget(self.hint)
        layout.addLayout(header)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["#", "x", "y"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setMaximumHeight(190)
        head = self.table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft
                                 | Qt.AlignmentFlag.AlignVCenter)
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._commit)
        layout.addWidget(self.table)

    def show_shape(self, index: int, shape) -> None:
        self._updating = True
        try:
            self._index = index
            self.table.setRowCount(0)
            if shape is None:
                self.hint.setText("no selection")
                return
            self.hint.setText("ROI %d  ·  %s" % (index + 1, shape.describe()))
            editable = not shape.is_editable_as_box() and not shape.locked
            self.table.setRowCount(len(shape.points))
            for row, (x, y) in enumerate(shape.points):
                number = QTableWidgetItem(str(row + 1))
                number.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(row, 0, number)
                for column, value in ((1, x), (2, y)):
                    cell = QTableWidgetItem(str(int(value)))
                    if not editable:
                        cell.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    self.table.setItem(row, column, cell)
        finally:
            self._updating = False

    def _commit(self, item) -> None:
        if self._updating or self._index < 0 or item.column() == 0:
            return
        row = item.row()
        try:
            x = int(float(self.table.item(row, 1).text()))
            y = int(float(self.table.item(row, 2).text()))
        except (TypeError, ValueError, AttributeError):
            return
        self.vertexEdited.emit(self._index, row, x, y)
