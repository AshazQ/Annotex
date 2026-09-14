"""Small building blocks shared by the dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QDialog, QFrame, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout, QWidget)


class Dialog(QDialog):
    """A dialog that already carries the application palette and a title row."""

    def __init__(self, parent, title, subtitle="", width=560, height=0):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        if width:
            self.setMinimumWidth(width)
        if height:
            self.setMinimumHeight(height)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(20, 18, 20, 18)
        self._root.setSpacing(14)

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

        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        self._root.addLayout(self.body, 1)

        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(8)
        self.buttons.addStretch(1)
        self._root.addLayout(self.buttons)

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
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    if title:
        label = QLabel(title)
        label.setObjectName("SectionHeader")
        layout.addWidget(label)
    return frame, layout


def row(*widgets, stretch_last=False, spacing=8) -> QWidget:
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
        text_colour = "#ffffff" if self._colour.lightness() < 140 else "#111111"
        self.setText(self._colour.name().upper())
        self.setStyleSheet(
            "QPushButton { background: %s; color: %s; border: 1px solid "
            "rgba(128,128,128,0.5); border-radius: 8px; font-size: 11px; "
            "font-weight: 600; }" % (self._colour.name(), text_colour))

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(self._colour, self,
                                       "Choose a colour")
        if chosen.isValid():
            self._colour = chosen
            self._refresh()
