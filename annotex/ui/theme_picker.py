"""Choosing a theme: a combo box for Settings and a submenu for View menus.

Each entry carries a small swatch - the theme's background, surface and a
few of its hues - so the looks can be told apart before picking one.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QComboBox, QMenu

from .palette import THEMES, qcolor, theme_ids

SWATCH_HUES = ("orange", "blue", "purple", "green")


def swatch(theme: dict, width: int = 40, height: int = 18) -> QPixmap:
    ratio = 2
    pixmap = QPixmap(width * ratio, height * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    outer = QRectF(0.5, 0.5, width - 1, height - 1)
    painter.setPen(QPen(qcolor(theme["borderStrong"]), 1))
    painter.setBrush(QBrush(qcolor(theme["appBg"])))
    painter.drawRoundedRect(outer, 5, 5)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(qcolor(theme["surface"])))
    painter.drawRoundedRect(QRectF(4, 4, width * 0.42, height - 8), 3, 3)
    dot = (height - 8) / 2.0
    x = width * 0.42 + 8
    for hue in SWATCH_HUES:
        painter.setBrush(QBrush(QColor(theme["hues"][hue])))
        painter.drawEllipse(QRectF(x, height / 2.0 - dot / 2.0 - 0.5, dot + 1, dot + 1))
        x += dot + 2.5
    painter.end()
    return pixmap


def _entries(include_system=True):
    """[(value, label, theme or None)] with None value marking a separator."""
    rows = []
    if include_system:
        rows.append(("system", "Follow the system", None))
    for kind in ("dark", "light"):
        rows.append((None, kind, None))
        for theme_id in theme_ids(kind):
            rows.append((theme_id, THEMES[theme_id]["label"], THEMES[theme_id]))
    return rows


class ThemeCombo(QComboBox):
    """Every theme, dark ones first, each with its swatch."""

    def __init__(self, current="dark", parent=None, include_system=True):
        super().__init__(parent)
        self.setIconSize(QSize(40, 18))
        self.setMaxVisibleItems(24)
        for value, label, theme in _entries(include_system):
            if value is None:
                self.insertSeparator(self.count())
                continue
            if theme is None:
                self.addItem(label, value)
            else:
                self.addItem(QIcon(swatch(theme)), label, value)
        index = self.findData(str(current or "dark"))
        self.setCurrentIndex(max(0, index if index >= 0 else self.findData("dark")))

    def value(self) -> str:
        return self.currentData() or "dark"


def theme_menu(parent, current, on_pick, title="Theme") -> QMenu:
    """A View-menu submenu with every theme as a checkable entry."""
    menu = QMenu(title, parent)
    group = QActionGroup(menu)
    group.setExclusive(True)
    for value, label, theme in _entries(True):
        if value is None:
            menu.addSeparator()
            continue
        action = QAction(label, menu)
        if theme is not None:
            action.setIcon(QIcon(swatch(theme)))
        action.setCheckable(True)
        action.setChecked(value == current)
        action.setData(value)
        action.triggered.connect(lambda _checked=False, v=value: on_pick(v))
        group.addAction(action)
        menu.addAction(action)
    menu.aboutToShow.connect(lambda: _sync(menu, parent))
    menu._current = lambda: current
    return menu


def _sync(menu, parent) -> None:
    """Tick the theme in use when the menu opens."""
    current = getattr(parent, "theme_setting_for_menu", None)
    value = current() if callable(current) else None
    if value is None:
        return
    for action in menu.actions():
        if action.isCheckable():
            action.setChecked(action.data() == value)
