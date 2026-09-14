"""The Home dashboard: every tool as a card, grouped into sections."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from ..config import SUITE_NAME, SUITE_TAGLINE, SUITE_VERSION
from ..ui import icons
from ..ui.widgets import section_label
from .registry import SECTIONS


class ToolCard(QFrame):
    openRequested = Signal(str)
    folderRequested = Signal(str, str)           # tool id, folder ("" = ask)

    def __init__(self, spec, shortcut, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.setObjectName("ToolCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(14)
        self.mark = QLabel()
        self.mark.setFixedSize(46, 46)
        top.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        name = QLabel(spec.name)
        name.setObjectName("CardTitle")
        tagline = QLabel(spec.tagline)
        tagline.setObjectName("Subtitle")
        titles.addWidget(name)
        titles.addWidget(tagline)
        top.addLayout(titles, 1)
        key = QLabel(shortcut)
        key.setObjectName("Kbd")
        key.setToolTip("Open %s from anywhere in %s" % (spec.name, SUITE_NAME))
        top.addWidget(key, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        description = QLabel(spec.description)
        description.setObjectName("Hint")
        description.setWordWrap(True)
        layout.addWidget(description)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        for text in spec.highlights:
            chip = QLabel(text)
            chip.setObjectName("Chip")
            chips.addWidget(chip)
        chips.addStretch(1)
        layout.addLayout(chips)

        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(0)
        if spec.recent is not None:
            layout.addWidget(section_label("Recent folders"))
            layout.addLayout(self.recent_box)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.open_button = QPushButton("Open")
        self.open_button.setObjectName("Primary")
        self.open_button.clicked.connect(lambda: self.openRequested.emit(spec.id))
        buttons.addWidget(self.open_button)
        folder_button = QPushButton("Open a folder…")
        folder_button.clicked.connect(lambda: self.folderRequested.emit(spec.id, ""))
        buttons.addWidget(folder_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def set_theme(self, theme) -> None:
        self.mark.setPixmap(icons.mark_pixmap(self.spec.icon if self.spec.icon not in ("polygon", "rect")
                                              else ("polygon" if self.spec.icon == "polygon" else "box"),
                                              theme["accent"], theme["surfaceAlt"], 46))

    def set_recent(self, folders) -> None:
        if self.spec.recent is None:
            return
        while self.recent_box.count():
            item = self.recent_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not folders:
            empty = QLabel("Nothing yet - open a folder to start.")
            empty.setObjectName("Hint")
            self.recent_box.addWidget(empty)
            return
        metrics = QFontMetrics(self.font())
        for folder in folders[:3]:
            link = QPushButton(metrics.elidedText(folder, Qt.TextElideMode.ElideMiddle, 380))
            link.setObjectName("Link")
            link.setToolTip(folder)
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.clicked.connect(lambda _c=False, f=folder: self.folderRequested.emit(self.spec.id, f))
            self.recent_box.addWidget(link)


class HomePage(QWidget):
    openRequested = Signal(str)
    folderRequested = Signal(str, str)
    themeToggleRequested = Signal()

    def __init__(self, tools, parent=None):
        super().__init__(parent)
        self.tools = list(tools)
        self.cards = []
        self.sections = []                        # (label, grid, [cards])
        self._columns = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        holder = QWidget()
        scroll.setWidget(holder)
        centre = QHBoxLayout(holder)
        centre.setContentsMargins(24, 26, 24, 26)
        centre.addStretch(1)
        column = QWidget()
        column.setMaximumWidth(1320)
        column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        centre.addWidget(column, 100)
        centre.addStretch(1)
        body = QVBoxLayout(column)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)

        hero = QHBoxLayout()
        hero.setSpacing(16)
        self.hero_mark = QLabel()
        self.hero_mark.setFixedSize(60, 60)
        hero.addWidget(self.hero_mark)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel(SUITE_NAME)
        title.setObjectName("Hero")
        subtitle = QLabel("%s  ·  pick a tool to begin" % SUITE_TAGLINE)
        subtitle.setObjectName("Subtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        hero.addLayout(titles, 1)
        self.theme_button = QPushButton("Theme")
        self.theme_button.setObjectName("Quiet")
        self.theme_button.setIconSize(QSize(17, 17))
        self.theme_button.setToolTip("Switch light / dark for every tool  [Ctrl+T]")
        self.theme_button.clicked.connect(self.themeToggleRequested.emit)
        hero.addWidget(self.theme_button, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(hero)

        numbers = {spec.id: index for index, spec in enumerate(self.tools, start=1)}
        for key, label in SECTIONS:
            specs = [s for s in self.tools if s.section == key]
            if not specs:
                continue
            body.addSpacing(6)
            body.addWidget(section_label(label))
            grid = QGridLayout()
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(14)
            body.addLayout(grid)
            cards = []
            for spec in specs:
                number = numbers[spec.id]
                card = ToolCard(spec, "Ctrl+%d" % number if number <= 9 else "")
                card.openRequested.connect(self.openRequested.emit)
                card.folderRequested.connect(self.folderRequested.emit)
                cards.append(card)
                self.cards.append(card)
            self.sections.append((label, grid, cards))

        self.ghost = QFrame()
        self.ghost.setObjectName("GhostCard")
        ghost_layout = QVBoxLayout(self.ghost)
        ghost_layout.setContentsMargins(20, 18, 20, 18)
        ghost_title = QLabel("More tools")
        ghost_title.setObjectName("CardTitle")
        ghost_text = QLabel("New tools appear here as they join %s, and share its theme, "
                            "job queue and safe-saving." % SUITE_NAME)
        ghost_text.setObjectName("Hint")
        ghost_text.setWordWrap(True)
        ghost_layout.addWidget(ghost_title)
        ghost_layout.addWidget(ghost_text)
        ghost_layout.addStretch(1)
        if self.sections:
            self.sections[-1][2].append(self.ghost)

        footer = QLabel("Ctrl+Shift+H comes back here from any tool  ·  Ctrl+Q quits  ·  "
                        "%s %s" % (SUITE_NAME, SUITE_VERSION))
        footer.setObjectName("Subtitle")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addStretch(1)
        body.addWidget(footer)
        self._reflow(force=True)

    def set_theme(self, theme) -> None:
        self.hero_mark.setPixmap(icons.mark_pixmap("suite", theme["accent"], theme["surfaceAlt"], 60))
        self.theme_button.setIcon(icons.icon("sun" if theme["name"] == "dark" else "moon",
                                             theme["text"], 17))
        self.theme_button.setText("Light theme" if theme["name"] == "dark" else "Dark theme")
        for card in self.cards:
            card.set_theme(theme)

    def refresh(self) -> None:
        for card in self.cards:
            try:
                folders = card.spec.recent() if card.spec.recent else []
            except Exception:
                folders = []
            card.set_recent([f for f in folders if os.path.isdir(f)])

    def _reflow(self, force=False) -> None:
        width = self.width()
        columns = 1 if width < 900 else (2 if width < 1380 else 3)
        if columns == self._columns and not force:
            return
        self._columns = columns
        for _label, grid, widgets in self.sections:
            for widget in widgets:
                grid.removeWidget(widget)
            for position, widget in enumerate(widgets):
                grid.addWidget(widget, position // columns, position % columns, Qt.AlignmentFlag.AlignTop)
            for column in range(3):
                grid.setColumnStretch(column, 1 if column < columns else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()
