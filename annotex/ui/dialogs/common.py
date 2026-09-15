"""Small building blocks shared by the dialogs."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QColorDialog, QDialog, QFrame, QHBoxLayout,
                               QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import style
from ..palette import readable_on
from .. import design

# How much of the screen a dialog may take before its contents scroll.
SCREEN_SHARE_W, SCREEN_SHARE_H = 0.95, 0.90


class _FitScroll(QScrollArea):
    """A scroll area that asks for its content's full size, so a dialog is
    only as small as the screen forces it to be - and scrolls then, instead
    of pushing its buttons off the bottom of a laptop screen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def sizeHint(self) -> QSize:
        inner = self.widget()
        if inner is None:
            return super().sizeHint()
        hint = inner.sizeHint()
        return QSize(hint.width() + self.verticalScrollBar().sizeHint().width(), hint.height())

    def minimumSizeHint(self) -> QSize:
        inner = self.widget()
        if inner is None:
            return super().minimumSizeHint()
        return QSize(inner.minimumSizeHint().width(), min(160, inner.minimumSizeHint().height()))


class Dialog(QDialog):
    """A dialog that already carries the application palette and a title row.

    The body scrolls when the screen is too short for it, and the dialog is
    kept inside the screen, so the buttons along the bottom are always
    reachable - whatever the display scaling."""

    def __init__(self, parent, title, subtitle="", width=560, height=0):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._wanted_width = int(width or 0)
        self._wanted_height = int(height or 0)
        if width:
            self.setMinimumWidth(min(width, self._screen_limit()[0]))
        if height:
            self.setMinimumHeight(min(height, self._screen_limit()[1]))

        self._root = QVBoxLayout(self)
        design.margins(self._root, "l", "xl")
        self._root.setSpacing(design.SPACE["m"])

        heading = QLabel(title)
        heading.setObjectName("Title")
        self._root.addWidget(heading)
        self.subtitle_label = None
        if subtitle:
            note = QLabel(subtitle)
            note.setObjectName("Subtitle")
            note.setWordWrap(True)
            self._root.addWidget(note)
            self.subtitle_label = note

        self.body_scroll = _FitScroll()
        holder = QWidget()
        holder.setObjectName("DialogBody")
        self.body = QVBoxLayout(holder)
        design.margins(self.body, "0")
        self.body.setSpacing(design.SPACE["m"])
        self.body_scroll.setWidget(holder)
        self._root.addWidget(self.body_scroll, 1)

        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(design.SPACE["s"])
        self.buttons.addStretch(1)
        self._root.addLayout(self.buttons)

    def _screen_limit(self):
        """(width, height) this dialog may use on the screen it is on."""
        screen = None
        try:
            screen = self.screen() if self.isVisible() else None
            if screen is None and self.parentWidget() is not None:
                screen = self.parentWidget().screen()
            if screen is None:
                screen = QApplication.primaryScreen()
        except Exception:
            screen = None
        if screen is None:
            return 10 ** 5, 10 ** 5
        area = screen.availableGeometry()
        return int(area.width() * SCREEN_SHARE_W), int(area.height() * SCREEN_SHARE_H)

    def fit_to_screen(self) -> None:
        """Shrink to the screen if needed (the body scrolls) and keep the whole
        dialog, title bar included, on the screen."""
        limit_w, limit_h = self._screen_limit()
        self.setMinimumWidth(min(self.minimumWidth(), limit_w))
        self.setMinimumHeight(min(self.minimumHeight(), limit_h))
        hint = self.sizeHint()
        width = min(max(self.width(), hint.width(), self._wanted_width), limit_w)
        height = min(max(self.height(), hint.height(), self._wanted_height), limit_h)
        if (width, height) != (self.width(), self.height()):
            self.resize(width, height)
        try:
            screen = self.screen() or QApplication.primaryScreen()
            area = screen.availableGeometry()
            frame = self.frameGeometry()
            x = min(max(frame.x(), area.x()), area.right() - frame.width() + 1)
            y = min(max(frame.y(), area.y()), area.bottom() - frame.height() + 1)
            if (x, y) != (frame.x(), frame.y()):
                self.move(max(area.x(), x), max(area.y(), y))
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_to_screen()

    def add_button(self, text, primary=False, slot=None, tooltip=""):
        button = QPushButton(text)
        if primary:
            button.setObjectName("Primary")
            button.setDefault(True)
        if tooltip:
            button.setToolTip(tooltip)
        if slot is not None:
            button.clicked.connect(slot)
        self.buttons.addWidget(button)
        return button

    def add_close_button(self, text="Close"):
        return self.add_button(text, slot=self.reject)


def card(title="") -> tuple:
    """A titled panel; returns (frame, inner layout)."""
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    design.margins(layout, "m", "l")
    layout.setSpacing(design.SPACE["s"])
    if title:
        label = QLabel(title)
        label.setObjectName("SectionHeader")
        layout.addWidget(label)
    return frame, layout


def row(*widgets, stretch_last=False, spacing=design.SPACE["s"]) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for index, widget in enumerate(widgets):
        if widget is None:
            layout.addStretch(1)
        elif isinstance(widget, str):
            layout.addWidget(QLabel(widget))
        else:
            layout.addWidget(widget, 1 if (stretch_last and
                                           index == len(widgets) - 1) else 0)
    return holder


def hint(text) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Hint")
    label.setWordWrap(True)
    return label


class ColourButton(QPushButton):
    """A swatch that opens the colour picker."""

    def __init__(self, colour="#00dc64", parent=None):
        super().__init__(parent)
        self.setFixedSize(76, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._colour = QColor(colour)
        self.clicked.connect(self._pick)
        self._refresh()

    def colour(self) -> str:
        return self._colour.name()

    def set_colour(self, value) -> None:
        colour = QColor(value)
        if colour.isValid():
            self._colour = colour
            self._refresh()

    def _refresh(self) -> None:
        self.setText(self._colour.name().upper())
        style.swatch(self, self._colour.name(), readable_on(self._colour.name()), "QPushButton")

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(self._colour, self,
                                       "Choose a colour")
        if chosen.isValid():
            self._colour = chosen
            self._refresh()
