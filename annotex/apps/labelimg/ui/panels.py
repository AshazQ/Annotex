"""LabelImg Master's side panels: the class palette, the active class and
the box list.  The minimap, counters and section furniture are the suite's."""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFontMetrics, QIcon,
                           QPainter, QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QStyle, QStyledItemDelegate, QToolButton,
                               QVBoxLayout, QWidget)

from annotex.ui import icons
from annotex.ui.palette import qcolor, readable_on
from annotex.ui.widgets import section_label

from ....ui import style
from ....ui import design


ROLE_NAME = Qt.ItemDataRole.UserRole + 1
ROLE_COLOUR = Qt.ItemDataRole.UserRole + 2
ROLE_HOTKEY = Qt.ItemDataRole.UserRole + 3
ROLE_ID = Qt.ItemDataRole.UserRole + 4
ROW_HEIGHT = 28


def swatch_icon(colour, size=14) -> QIcon:
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(qcolor(colour)))
    painter.drawRoundedRect(QRectF(1.5, 1.5, size - 3, size - 3), 3, 3)
    painter.end()
    return QIcon(pixmap)


# ══════════════════════════════════════════════════════════════
class _ClassDelegate(QStyledItemDelegate):
    """Draws: [colour chip] name ..................... [key]"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = {}

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), ROW_HEIGHT)

    def paint(self, painter, option, index):
        theme = self.theme or {}
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(option.rect).adjusted(2, 1, -2, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(qcolor(theme.get("accent", "#df5e3b"))))
            painter.drawRoundedRect(rect, 6, 6)
            text_colour = qcolor(theme.get("onAccent", "#ffffff"))
            badge_bg = QColor(255, 255, 255, 60)
            badge_fg = text_colour
        else:
            if hovered:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(qcolor(theme.get("surfaceHover", "#2c323c"))))
                painter.drawRoundedRect(rect, 6, 6)
            text_colour = qcolor(theme.get("text", "#c8cdd6"))
            badge_bg = qcolor(theme.get("surfaceAlt", "#252a33"))
            badge_fg = qcolor(theme.get("sub", "#8b93a1"))

        chip = QRectF(rect.left() + 8, rect.center().y() - 5.5, 11, 11)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(qcolor(index.data(ROLE_COLOUR) or "#888888")))
        painter.drawRoundedRect(chip, 3, 3)

        hotkey = index.data(ROLE_HOTKEY) or ""
        badge_width = 0
        if hotkey:
            badge_font = design.font("badge", option.font)
            badge_metrics = QFontMetrics(badge_font)
            badge_width = max(18, badge_metrics.horizontalAdvance(hotkey) + 12)
            badge = QRectF(rect.right() - badge_width - 6,
                           rect.center().y() - 8, badge_width, 16)
            painter.setBrush(QBrush(badge_bg))
            painter.drawRoundedRect(badge, 4, 4)
            painter.setFont(badge_font)
            painter.setPen(badge_fg)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, hotkey)
            badge_width += 10

        painter.setFont(option.font)
        painter.setPen(text_colour)
        text_rect = QRect(int(chip.right() + 8), int(rect.top()),
                          int(rect.width() - chip.width() - badge_width - 24),
                          int(rect.height()))
        metrics = QFontMetrics(option.font)
        painter.drawText(text_rect,
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         metrics.elidedText(index.data(ROLE_NAME) or "",
                                            Qt.TextElideMode.ElideRight,
                                            text_rect.width()))
        painter.restore()


class ClassPalette(QWidget):
    """Search box + class list, with every class's hotkey on show."""

    classChosen = Signal(str)
    manageRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries = []
        self._hotkeys = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(section_label("Classes"))
        header.addStretch(1)
        self.project_label = QLabel("")
        self.project_label.setObjectName("Subtitle")
        header.addWidget(self.project_label)
        self.manage_button = QToolButton()
        self.manage_button.setObjectName("Tool")
        self.manage_button.setToolTip("Class Manager  [Ctrl+M]")
        self.manage_button.setIconSize(QSize(16, 16))
        self.manage_button.clicked.connect(self.manageRequested.emit)
        header.addWidget(self.manage_button)
        layout.addLayout(header)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search classes…   /")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refresh)
        self.search.returnPressed.connect(self._choose_first)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(True)
        self.list.setMinimumHeight(160)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.delegate = _ClassDelegate(self.list)
        self.list.setItemDelegate(self.delegate)
        self.list.itemClicked.connect(self._on_clicked)
        layout.addWidget(self.list, 1)

        self.empty_hint = QLabel("No classes yet - open the Class Manager "
                                 "or draw a box and type a name.")
        self.empty_hint.setObjectName("Hint")
        self.empty_hint.setWordWrap(True)
        layout.addWidget(self.empty_hint)

    def set_theme(self, theme: dict) -> None:
        self.delegate.theme = dict(theme)
        self.manage_button.setIcon(icons.icon("settings", theme.get("sub", "#8b93a1"), 16))
        self.list.viewport().update()

    def set_entries(self, entries, hotkeys=None, project_name="") -> None:
        self._entries = list(entries)
        self._hotkeys = dict(hotkeys or {})
        self.project_label.setText(project_name)
        self._refresh()

    def current_name(self):
        item = self.list.currentItem()
        return item.data(ROLE_NAME) if item else None

    def select_name(self, name) -> bool:
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(ROLE_NAME) == name:
                self.list.setCurrentItem(item)
                self.list.scrollToItem(item)
                return True
        self.list.clearSelection()
        return False

    def focus_search(self) -> None:
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def _refresh(self) -> None:
        needle = self.search.text().strip().lower()
        previous = self.current_name()
        self.list.clear()
        for entry in self._entries:
            if needle and needle not in entry.name.lower():
                continue
            item = QListWidgetItem()
            item.setData(ROLE_NAME, entry.name)
            item.setData(ROLE_COLOUR, entry.color)
            item.setData(ROLE_ID, entry.id)
            key = self._hotkeys.get(entry.name, "")
            item.setData(ROLE_HOTKEY, key)
            tip = "ID %d" % entry.id
            if entry.description:
                tip += " - %s" % entry.description
            if key:
                tip += "\nPress %s to assign" % key
            item.setToolTip(tip)
            item.setSizeHint(QSize(0, ROW_HEIGHT))
            self.list.addItem(item)
        has_rows = self.list.count() > 0
        self.list.setVisible(has_rows)
        self.empty_hint.setVisible(not has_rows)
        if not has_rows and needle:
            self.empty_hint.setText("No class matches “%s”. Press Enter in the "
                                    "label dialog to add it." % self.search.text().strip())
        elif not has_rows:
            self.empty_hint.setText("No classes yet - open the Class Manager "
                                    "or draw a box and type a name.")
        if previous:
            self.select_name(previous)

    def _choose_first(self) -> None:
        if self.list.count():
            name = self.list.item(0).data(ROLE_NAME)
            self.select_name(name)
            self.classChosen.emit(name)

    def _on_clicked(self, item) -> None:
        name = item.data(ROLE_NAME)
        if name:
            self.classChosen.emit(name)


# ══════════════════════════════════════════════════════════════
class ActiveClassChip(QWidget):
    """The class the next box will get."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.caption = QLabel("Next box")
        self.caption.setObjectName("StatLabel")
        layout.addWidget(self.caption)
        self.chip = QLabel("")
        layout.addWidget(self.chip)
        layout.addStretch(1)
        self.key = QLabel("")
        self.key.setObjectName("Kbd")
        layout.addWidget(self.key)
        self.set_class(None)

    def set_theme(self, theme) -> None:
        self._theme = dict(theme)

    def set_class(self, name, colour="", hotkey="") -> None:
        if not name:
            self.chip.setText("no active class - you will be asked")
            style.clear_swatch(self.chip)
            style.set_tone(self.chip, "sub")
            self.key.setVisible(False)
            return
        fg = readable_on(colour or "#888888")
        self.chip.setText(name)
        style.swatch(self.chip, colour or "#888888", fg)
        self.key.setText(hotkey)
        self.key.setVisible(bool(hotkey))


# ══════════════════════════════════════════════════════════════
class BoxListPanel(QWidget):
    """Every box on the current image."""

    selectionRequested = Signal(object)          # list of indices
    visibilityToggled = Signal(object, bool)
    lockToggled = Signal(object, bool)
    difficultToggled = Signal(object, bool)
    editRequested = Signal()
    duplicateRequested = Signal()
    deleteRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = {}
        self._boxes = []
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(section_label("Boxes on this image"))
        header.addStretch(1)
        self.count_label = QLabel("0")
        self.count_label.setObjectName("Subtitle")
        header.addWidget(self.count_label)
        layout.addLayout(header)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setUniformItemSizes(True)
        self.list.setMinimumHeight(64)
        self.list.itemSelectionChanged.connect(self._emit_selection)
        self.list.itemDoubleClicked.connect(lambda _i: self.editRequested.emit())
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.buttons = {}
        for name, icon_name, tip in (
                ("edit", "tag", "Change the class  [Ctrl+E]"),
                ("difficult", "flag", "Mark or unmark as difficult"),
                ("visible", "eye", "Hide or show"),
                ("lock", "lock", "Lock or unlock  [Ctrl+L]"),
                ("duplicate", "copy", "Duplicate  [Ctrl+D]"),
                ("delete", "trash", "Delete  [Delete]")):
            button = QToolButton()
            button.setObjectName("Tool")
            button.setToolTip(tip)
            button.setIconSize(QSize(design.ICON["s"], design.ICON["s"]))
            button.setProperty("iconName", icon_name)
            self.buttons[name] = button
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)

        self.buttons["edit"].clicked.connect(self.editRequested.emit)
        self.buttons["duplicate"].clicked.connect(self.duplicateRequested.emit)
        self.buttons["delete"].clicked.connect(self.deleteRequested.emit)
        self.buttons["visible"].clicked.connect(
            lambda: self._toggle(self.visibilityToggled, "visible"))
        self.buttons["lock"].clicked.connect(
            lambda: self._toggle(self.lockToggled, "locked"))
        self.buttons["difficult"].clicked.connect(
            lambda: self._toggle(self.difficultToggled, "difficult"))

    def set_theme(self, theme) -> None:
        self._theme = dict(theme)
        for name, button in self.buttons.items():
            colour = theme.get("danger" if name == "delete" else "sub", "#8b93a1")
            button.setIcon(icons.icon(button.property("iconName"), colour, 17))

    def refresh(self, boxes, selection, colour_for) -> None:
        self._boxes = list(boxes or [])
        selection = set(selection or ())
        theme = self._theme or {}
        self._updating = True
        try:
            self.list.clear()
            for index, box in enumerate(self._boxes):
                marks = []
                if box.difficult:
                    marks.append("difficult")
                if not box.visible:
                    marks.append("hidden")
                if box.locked:
                    marks.append("locked")
                text = "%s   %s" % (box.label or "?", box.describe())
                if marks:
                    text += "  ·  " + ", ".join(marks)
                item = QListWidgetItem(swatch_icon(colour_for(box.label)), text)
                item.setData(Qt.ItemDataRole.UserRole, index)
                if not box.visible or box.locked:
                    item.setForeground(QBrush(qcolor(theme.get("muted", "#6f7784"))))
                self.list.addItem(item)
                item.setSelected(index in selection)
            self.count_label.setText(str(len(self._boxes)))
        finally:
            self._updating = False
        self._sync(selection)

    def selected_indices(self):
        return sorted(item.data(Qt.ItemDataRole.UserRole)
                      for item in self.list.selectedItems())

    def set_selection(self, indices) -> None:
        """Show this selection without rebuilding the list.

        Picking a box must not cost a rebuild of every row: on a crowded
        image that is the difference between instant and a visible pause."""
        wanted = set(indices or ())
        self._updating = True
        blocked = self.list.blockSignals(True)
        self.list.setUpdatesEnabled(False)
        try:
            for row in range(self.list.count()):
                item = self.list.item(row)
                if item is None:
                    continue
                index = item.data(Qt.ItemDataRole.UserRole)
                item.setSelected((row if index is None else index) in wanted)
            if wanted:
                for row in range(self.list.count()):
                    item = self.list.item(row)
                    if item is not None and item.isSelected():
                        self.list.scrollToItem(item)
                        break
        finally:
            self.list.setUpdatesEnabled(True)
            self.list.blockSignals(blocked)
            self._updating = False
        self._sync(wanted)

    def _sync(self, selection) -> None:
        for button in self.buttons.values():
            button.setEnabled(bool(selection))

    def _emit_selection(self) -> None:
        if self._updating:
            return
        indices = self.selected_indices()
        self._sync(set(indices))
        self.selectionRequested.emit(indices)

    def _toggle(self, signal, attribute) -> None:
        indices = [i for i in self.selected_indices() if 0 <= i < len(self._boxes)]
        if not indices:
            return
        current = all(getattr(self._boxes[i], attribute) for i in indices)
        signal.emit(indices, not current)
