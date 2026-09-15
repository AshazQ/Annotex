"""The style guide: every piece of the design system, side by side.

Text styles, spacing, corners, the theme's colours and every control, drawn
with the real stylesheet in the current theme - so a style that is off shows
up at a glance.  Open it from Display, or with Ctrl+Alt+Shift+D.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QProgressBar, QPushButton, QRadioButton, QSlider,
                               QSpinBox, QVBoxLayout, QWidget)

from ..ui import design, icons
from ..ui.dialogs.common import Dialog, card
from ..ui.palette import qcolor

TEXT_STYLES = (("Large", "large", "Good afternoon"), ("Title", "title", "Page and dialog titles"),
               ("Headline", "headline", "Card and section titles"),
               ("", "body", "Body text - everything, by default"),
               ("Subtitle", "footnote", "Subtitles and hints"),
               ("SectionHeader", "caption", "Section header"))
COLOUR_TOKENS = ("appBg", "surface", "surfaceAlt", "surfaceHover", "border", "borderStrong",
                 "title", "text", "sub", "muted", "accent", "accentSoft", "good", "warn",
                 "danger", "info")


class _Swatch(QWidget):
    """A colour, a corner radius or a spacing step, painted - never styled
    inline - so the guide obeys the rules it shows."""

    def __init__(self, kind, value, theme, parent=None):
        super().__init__(parent)
        self.kind, self.value, self.theme = kind, value, theme
        self.setFixedSize(QSize(design.SPACE["xxl"] * 2, design.SPACE["xxl"] + design.SPACE["m"]))

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            area = QRectF(self.rect()).adjusted(design.HAIRLINE, design.HAIRLINE,
                                                -design.HAIRLINE, -design.HAIRLINE)
            border = QPen(qcolor(self.theme["borderStrong"]), design.HAIRLINE)
            if self.kind == "colour":
                painter.setPen(border)
                painter.setBrush(QBrush(qcolor(self.theme[self.value])))
                painter.drawRoundedRect(area, design.RADIUS["s"], design.RADIUS["s"])
            elif self.kind == "radius":
                painter.setPen(border)
                painter.setBrush(QBrush(qcolor(self.theme["surfaceAlt"])))
                painter.drawRoundedRect(area, self.value, self.value)
            else:                                            # a spacing step
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(qcolor(self.theme["accent"])))
                painter.drawRect(QRectF(0, area.center().y() - design.SPACE["xs"] / 2.0,
                                        self.value, design.SPACE["xs"]))
        finally:
            painter.end()


def _caption(text) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Hint")
    label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    return label


class StyleGuideDialog(Dialog):
    def __init__(self, parent, theme):
        super().__init__(parent, "Style guide",
                         "Every text style, size, colour and control of the design system, in "
                         "the current theme.", width=760)
        self.theme = theme

        frame, inner = card("Text")
        for object_name, style, sample in TEXT_STYLES:
            size, weight = design.TYPE[style]
            row = QHBoxLayout()
            row.setSpacing(design.SPACE["m"])
            label = QLabel(sample)
            if object_name:
                label.setObjectName(object_name)
            row.addWidget(label, 1)
            row.addWidget(_caption("%s  ·  %d px  ·  %d" % (style, size, weight)))
            inner.addLayout(row)
        self.body.addWidget(frame)

        frame, inner = card("Spacing and corners")
        grid = QGridLayout()
        grid.setHorizontalSpacing(design.SPACE["m"])
        grid.setVerticalSpacing(design.SPACE["xs"])
        for column, (name, value) in enumerate(design.SPACE.items()):
            grid.addWidget(_Swatch("space", value, theme), 0, column)
            grid.addWidget(_caption("%s %d" % (name, value)), 1, column)
        for column, (name, value) in enumerate(design.RADIUS.items()):
            grid.addWidget(_Swatch("radius", value, theme), 2, column)
            grid.addWidget(_caption("radius %s %d" % (name, value)), 3, column)
        inner.addLayout(grid)
        self.body.addWidget(frame)

        frame, inner = card("Colours")
        grid = QGridLayout()
        grid.setHorizontalSpacing(design.SPACE["m"])
        grid.setVerticalSpacing(design.SPACE["xs"])
        per_row = 8
        for index, token in enumerate(COLOUR_TOKENS):
            grid.addWidget(_Swatch("colour", token, theme), (index // per_row) * 2, index % per_row)
            grid.addWidget(_caption(token), (index // per_row) * 2 + 1, index % per_row)
        inner.addLayout(grid)
        self.body.addWidget(frame)

        frame, inner = card("Controls")
        buttons = QHBoxLayout()
        buttons.setSpacing(design.SPACE["s"])
        for object_name, text in (("Primary", "Primary"), ("", "Secondary"), ("Quiet", "Quiet"),
                                  ("Danger", "Danger"), ("Link", "Link")):
            button = QPushButton(text)
            if object_name:
                button.setObjectName(object_name)
            buttons.addWidget(button)
        disabled = QPushButton("Disabled")
        disabled.setEnabled(False)
        buttons.addWidget(disabled)
        tool = QPushButton()
        tool.setObjectName("Tool")
        tool.setFixedSize(design.TOOL_BUTTON, design.TOOL_BUTTON)
        tool.setIcon(icons.icon("settings", theme["text"], design.ICON["m"]))
        tool.setIconSize(QSize(design.ICON["m"], design.ICON["m"]))
        buttons.addWidget(tool)
        buttons.addStretch(1)
        inner.addLayout(buttons)

        fields = QHBoxLayout()
        fields.setSpacing(design.SPACE["s"])
        edit = QLineEdit()
        edit.setPlaceholderText("A text field")
        combo = QComboBox()
        combo.addItems(["A choice", "Another choice"])
        spin = QSpinBox()
        spin.setValue(42)
        for widget in (edit, combo, spin):
            fields.addWidget(widget)
        inner.addLayout(fields)

        toggles = QHBoxLayout()
        toggles.setSpacing(design.SPACE["l"])
        check = QCheckBox("A check box")
        check.setChecked(True)
        radio = QRadioButton("A radio button")
        radio.setChecked(True)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setValue(60)
        progress = QProgressBar()
        progress.setValue(40)
        for widget in (check, radio, slider, progress):
            toggles.addWidget(widget)
        inner.addLayout(toggles)

        grouped = QListWidget()
        grouped.addItems(["A grouped list", "Its rows", "The chosen one"])
        grouped.setCurrentRow(2)
        grouped.setFixedHeight(design.CONTROL_HEIGHT * 4)
        inner.addWidget(grouped)
        self.body.addWidget(frame)

        self.add_close_button()
