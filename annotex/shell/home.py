"""The Home dashboard.

    Good evening                                   (greeting + suite mark)
    Continue where you left off   [card] [card] [card]
    Annotation                    large cards with a colour band per tool
    Video / Images                compact coloured tiles

Every tool is drawn in its own hue (see annotex.ui.palette.TOOL_HUES), taken
from the current theme, so the dashboard reads as a set of different tools
rather than one repeated card.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFontMetrics, QImage, QImageReader,
                           QLinearGradient, QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from ..config import SUITE_NAME, SUITE_TAGLINE, SUITE_VERSION
from ..ui import icons
from ..ui.palette import mix, qcolor, with_tool
from ..ui.widgets import SegmentBar, section_label
from . import activity
from .registry import SECTIONS

THUMB_W, THUMB_H = 120, 78


def greeting(hour=None) -> str:
    hour = datetime.now().hour if hour is None else hour
    if hour < 5:
        return "Working late"
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


def _px(name, colour, size):
    return icons.pixmap(name, colour, size, ratio=2.0)


def _tool_icon(spec) -> str:
    return spec.icon


# ══════════════════════════════════════════════════════════════
class _Lift:
    """A soft coloured shadow while the pointer is over a card."""

    def _init_lift(self):
        self._lift_colour = QColor(0, 0, 0, 90)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        # One effect for the card's whole life, only switched on and off.
        # Creating or deleting it from enter/leave crashed the application:
        # Qt sends Leave while it is hiding Home to show a tool, and deleting
        # the effect (a child object) in the middle of that walk over the
        # children is a use-after-free inside Qt.
        self._lift = QGraphicsDropShadowEffect()
        self._lift.setBlurRadius(34)
        self._lift.setOffset(0, 8)
        self._lift.setEnabled(False)
        self.setGraphicsEffect(self._lift)

    def enterEvent(self, event):
        self._lift.setColor(self._lift_colour)
        self._lift.setEnabled(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._lift.setEnabled(False)
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._lift.setEnabled(False)
        super().hideEvent(event)


def _card_style(object_name, t) -> str:
    """Per-card rules: the card's own hue on its hover border and buttons."""
    return ("QFrame#%(n)s:hover { border-color: %(accent)s; }"
            "QPushButton#Primary { background: %(accent)s; border-color: %(accent)s; color: %(on)s; }"
            "QPushButton#Primary:hover { background: %(hover)s; border-color: %(hover)s; }"
            "QPushButton#Link:hover { color: %(accent)s; }"
            "QLabel#ToolChip { background: %(soft)s; color: %(accent)s; border-radius: 9px;"
            " padding: 2px 9px; font-size: 11px; font-weight: 600; }"
            % {"n": object_name, "accent": t["accent"], "hover": t["accentHover"],
               "on": t["onAccent"], "soft": t["accentSoft"]})


def _tile_pixmap(icon, accent, soft, size=46) -> QPixmap:
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(qcolor(soft)))
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.28, size * 0.28)
    glyph = int(size * 0.56)
    painter.drawPixmap(int((size - glyph) / 2), int((size - glyph) / 2),
                       _px(icon, accent, glyph))
    painter.end()
    return pixmap


# ══════════════════════════════════════════════════════════════
class ToolBand(QWidget):
    """The coloured top of a feature card."""

    def __init__(self, spec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.setFixedHeight(96)
        self._t = None

    def set_theme(self, tool_theme) -> None:
        self._t = tool_theme
        self.update()

    def paintEvent(self, event):
        t = self._t
        if t is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, 0)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(rect.x(), rect.y(), rect.width(), rect.height() + 24), 15, 15)
        painter.setClipPath(clip)

        accent = t["accent"]
        dark = t["kind"] == "dark"
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, qcolor(accent))
        gradient.setColorAt(1.0, qcolor(mix(accent, t["surface"], 0.55 if dark else 0.7)))
        painter.fillRect(rect, QBrush(gradient))

        ink = QColor(t["onAccent"])
        rings = QColor(ink)
        rings.setAlpha(38)
        painter.setPen(QPen(rings, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(rect.right() - 36, rect.top() + 18), 64, 64)
        painter.drawEllipse(QPointF(rect.right() - 36, rect.top() + 18), 38, 38)
        painter.drawEllipse(QPointF(rect.right() - 150, rect.bottom() + 6), 30, 30)

        painter.setOpacity(0.2)
        big = _px(_tool_icon(self.spec), ink.name(), 76)
        painter.drawPixmap(int(rect.right() - 118), int(rect.top() + 10), big)
        painter.setOpacity(1.0)

        tile = QRectF(20, rect.bottom() - 60, 50, 50)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(qcolor(t["surface"])))
        painter.drawRoundedRect(tile, 14, 14)
        painter.drawPixmap(int(tile.x() + 11), int(tile.y() + 11),
                           _px(_tool_icon(self.spec), accent, 28))
        painter.end()


class FeatureCard(_Lift, QFrame):
    """A large card for an annotation tool."""

    openRequested = Signal(str)
    folderRequested = Signal(str, str)           # tool id, folder ("" = ask)
    forgetRequested = Signal(str, str)           # tool id, folder to drop from recent

    def __init__(self, spec, shortcut, parent=None):
        super().__init__(parent)
        self._init_lift()
        self.spec = spec
        self.setObjectName("FeatureCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.band = ToolBand(spec)
        layout.addWidget(self.band)

        body = QVBoxLayout()
        body.setContentsMargins(20, 14, 20, 18)
        body.setSpacing(9)
        top = QHBoxLayout()
        name = QLabel(spec.name)
        name.setObjectName("CardTitle")
        top.addWidget(name, 1)
        key = QLabel(shortcut)
        key.setObjectName("Kbd")
        key.setToolTip("Open %s from anywhere in %s" % (spec.name, SUITE_NAME))
        key.setVisible(bool(shortcut))           # only the first nine tools have one
        top.addWidget(key, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(top)
        tagline = QLabel(spec.tagline)
        tagline.setObjectName("Subtitle")
        body.addWidget(tagline)
        description = QLabel(spec.description)
        description.setObjectName("Hint")
        description.setWordWrap(True)
        body.addWidget(description)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for text in spec.highlights:
            chip = QLabel(text)
            chip.setObjectName("ToolChip")
            chips.addWidget(chip)
        chips.addStretch(1)
        body.addLayout(chips)

        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(0)
        if spec.recent is not None:
            body.addWidget(section_label("Recent folders"))
            body.addLayout(self.recent_box)

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
        body.addLayout(buttons)
        layout.addLayout(body)

    def set_theme(self, theme) -> None:
        t = with_tool(theme, self.spec.id)
        self.band.set_theme(t)
        self._lift_colour = qcolor(t["accent"], 80 if t["kind"] == "dark" else 60)
        self.setStyleSheet(_card_style("FeatureCard", t))

    def set_recent(self, folders) -> None:
        if self.spec.recent is None:
            return
        while self.recent_box.count():
            item = self.recent_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Hide now - deleteLater alone leaves the old link painted over
                # the card until the event loop gets to it.  Qt deletes it later;
                # never drop it from Python mid-event.
                widget.hide()
                widget.deleteLater()
        if not folders:
            empty = QLabel("Nothing yet - open a folder to start.")
            empty.setObjectName("Hint")
            self.recent_box.addWidget(empty)
            return
        metrics = QFontMetrics(self.font())
        for folder in folders[:3]:
            line = QWidget()
            line_layout = QHBoxLayout(line)
            line_layout.setContentsMargins(0, 0, 0, 0)
            line_layout.setSpacing(4)
            link = QPushButton(metrics.elidedText(folder, Qt.TextElideMode.ElideMiddle, 350))
            link.setObjectName("Link")
            link.setToolTip(folder)
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.clicked.connect(lambda _c=False, f=folder: self.folderRequested.emit(self.spec.id, f))
            line_layout.addWidget(link, 1, Qt.AlignmentFlag.AlignLeft)
            remove = QPushButton("✕")
            remove.setObjectName("Link")
            remove.setFixedWidth(26)
            remove.setCursor(Qt.CursorShape.PointingHandCursor)
            remove.setToolTip("Remove from recent folders - the folder itself is not touched")
            remove.clicked.connect(lambda _c=False, f=folder: self.forgetRequested.emit(self.spec.id, f))
            line_layout.addWidget(remove)
            self.recent_box.addWidget(line)


# Old name kept for anything that imported it.
ToolCard = FeatureCard


class TileCard(_Lift, QFrame):
    """A compact, clickable tile for a video or image tool."""

    openRequested = Signal(str)
    folderRequested = Signal(str, str)

    def __init__(self, spec, shortcut, parent=None):
        super().__init__(parent)
        self._init_lift()
        self.spec = spec
        self.recent_box = QVBoxLayout()
        self.setObjectName("TileCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("%s - %s" % (spec.name, spec.description))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 14, 14)
        layout.setSpacing(14)
        self.mark = QLabel()
        self.mark.setFixedSize(46, 46)
        layout.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        top = QHBoxLayout()
        name = QLabel(spec.name)
        name.setObjectName("TileTitle")
        top.addWidget(name, 1)
        key = QLabel(shortcut)
        key.setObjectName("Kbd")
        key.setVisible(bool(shortcut))           # only the first nine tools have one
        top.addWidget(key)
        texts.addLayout(top)
        tagline = QLabel(spec.tagline)
        tagline.setObjectName("Subtitle")
        tagline.setWordWrap(True)
        texts.addWidget(tagline)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for text in spec.highlights[:2]:
            chip = QLabel(text)
            chip.setObjectName("ToolChip")
            chips.addWidget(chip)
        chips.addStretch(1)
        self.folder_button = QPushButton("Folder…")
        self.folder_button.setObjectName("Link")
        self.folder_button.setToolTip("Open %s with a folder" % spec.name)
        self.folder_button.clicked.connect(lambda: self.folderRequested.emit(spec.id, ""))
        chips.addWidget(self.folder_button)
        texts.addLayout(chips)
        layout.addLayout(texts, 1)

    def set_theme(self, theme) -> None:
        t = with_tool(theme, self.spec.id)
        self.mark.setPixmap(_tile_pixmap(_tool_icon(self.spec), t["accent"], t["accentSoft"]))
        self._lift_colour = qcolor(t["accent"], 70 if t["kind"] == "dark" else 55)
        self.setStyleSheet(_card_style("TileCard", t))

    def set_recent(self, folders) -> None:
        pass

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.openRequested.emit(self.spec.id)
        super().mouseReleaseEvent(event)


class ContinueCard(_Lift, QFrame):
    """One recent folder: thumbnail, tool, progress and a Resume button."""

    resumeRequested = Signal(str, str)
    forgetRequested = Signal(str, str)

    def __init__(self, session, spec, parent=None):
        super().__init__(parent)
        self._init_lift()
        self.session = session
        self.spec = spec
        self.setObjectName("ContinueCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._t = None
        self._image = QImage()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 14, 12)
        layout.setSpacing(14)
        self.thumb = QLabel()
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        layout.addWidget(self.thumb)

        texts = QVBoxLayout()
        texts.setSpacing(4)
        self.chip = QLabel(spec.name)
        self.chip.setObjectName("ToolChip")
        chip_row = QHBoxLayout()
        chip_row.addWidget(self.chip)
        chip_row.addStretch(1)
        # Up here, beside the tool chip, so it never squeezes the progress line.
        self.remove = QPushButton("✕")
        self.remove.setObjectName("Link")
        self.remove.setFixedWidth(26)
        self.remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove.setToolTip("Remove from recent folders - the folder itself is not touched")
        self.remove.clicked.connect(lambda: self.forgetRequested.emit(session.tool_id, session.folder))
        chip_row.addWidget(self.remove)
        texts.addLayout(chip_row)
        title = QLabel(session.name)
        title.setObjectName("TileTitle")
        texts.addWidget(title)
        path = QLabel(QFontMetrics(self.font()).elidedText(session.folder, Qt.TextElideMode.ElideMiddle, 260))
        path.setObjectName("Subtitle")
        path.setToolTip(session.folder)
        texts.addWidget(path)
        self.bar = SegmentBar()
        texts.addWidget(self.bar)
        bottom = QHBoxLayout()
        self.progress = QLabel("Counting images…")
        self.progress.setObjectName("Hint")
        bottom.addWidget(self.progress, 1)
        self.resume = QPushButton("Resume")
        self.resume.setObjectName("Primary")
        self.resume.clicked.connect(lambda: self.resumeRequested.emit(session.tool_id, session.folder))
        bottom.addWidget(self.resume)
        texts.addLayout(bottom)
        layout.addLayout(texts, 1)

    def set_theme(self, theme) -> None:
        self._t = with_tool(theme, self.spec.id)
        t = self._t
        self._lift_colour = qcolor(t["accent"], 70 if t["kind"] == "dark" else 55)
        self.setStyleSheet(_card_style("ContinueCard", t)
                           + "QFrame#ContinueCard { border-left: 4px solid %s; }" % t["accent"])
        self.bar.set_theme(t)
        self._paint()

    def set_measured(self, session, image) -> None:
        self.session = session
        self._image = image if image is not None else QImage()
        self._paint()

    def _paint(self) -> None:
        t = self._t
        if t is None:
            return
        session = self.session
        if session.measured:
            if session.done is None:
                self.progress.setText("%d image(s)" % session.total)
                self.bar.set_segments([(1, t["accent"])] if session.total else [])
            else:
                self.progress.setText("%d of %d annotated" % (session.done, session.total))
                self.bar.set_segments([(session.done, t["accent"]),
                                       (max(0, session.total - session.done), t["border"])])
        ratio = 2
        pixmap = QPixmap(THUMB_W * ratio, THUMB_H * ratio)
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, THUMB_W, THUMB_H), 10, 10)
        painter.setClipPath(clip)
        painter.fillRect(QRectF(0, 0, THUMB_W, THUMB_H), qcolor(t["accentSoft"]))
        if not self._image.isNull():
            scaled = self._image.scaled(QSize(THUMB_W * ratio, THUMB_H * ratio),
                                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                        Qt.TransformationMode.SmoothTransformation)
            x = (scaled.width() / ratio - THUMB_W) / 2.0
            y = (scaled.height() / ratio - THUMB_H) / 2.0
            painter.drawImage(QRectF(-x, -y, scaled.width() / ratio, scaled.height() / ratio), scaled)
        else:
            glyph = 34
            painter.drawPixmap(int((THUMB_W - glyph) / 2), int((THUMB_H - glyph) / 2),
                               _px("image", t["accent"], glyph))
        painter.end()
        self.thumb.setPixmap(pixmap)


# ══════════════════════════════════════════════════════════════
class HomePage(QWidget):
    openRequested = Signal(str)
    folderRequested = Signal(str, str)
    forgetRequested = Signal(str, str)
    themeToggleRequested = Signal()
    _measured = Signal(object)

    def __init__(self, tools, parent=None):
        super().__init__(parent)
        self.tools = list(tools)
        self.cards = []
        self.sections = []                        # (label, grid, [cards])
        self.continue_cards = []
        self._columns = None
        self._theme = None
        self._generation = 0
        self._measured.connect(self._on_measured)

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
        self.greeting = QLabel(greeting())
        self.greeting.setObjectName("Greeting")
        subtitle = QLabel("%s  ·  %s  ·  %d tools" % (SUITE_NAME, SUITE_TAGLINE.lower(), len(self.tools)))
        subtitle.setObjectName("Subtitle")
        titles.addWidget(self.greeting)
        titles.addWidget(subtitle)
        hero.addLayout(titles, 1)
        self.date_label = QLabel(datetime.now().strftime("%A, %d %B"))
        self.date_label.setObjectName("Subtitle")
        hero.addWidget(self.date_label, 0, Qt.AlignmentFlag.AlignBottom)
        body.addLayout(hero)

        self.continue_section = QWidget()
        continue_layout = QVBoxLayout(self.continue_section)
        continue_layout.setContentsMargins(0, 6, 0, 0)
        continue_layout.setSpacing(10)
        continue_layout.addWidget(section_label("Continue where you left off"))
        self.continue_row = QHBoxLayout()
        self.continue_row.setSpacing(14)
        continue_layout.addLayout(self.continue_row)
        self.continue_section.setVisible(False)
        body.addWidget(self.continue_section)

        numbers = {spec.id: index for index, spec in enumerate(self.tools, start=1)}
        for key, label in SECTIONS:
            specs = [s for s in self.tools if s.section == key]
            if not specs:
                continue
            body.addSpacing(8)
            body.addWidget(section_label(label))
            grid = QGridLayout()
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(14)
            body.addLayout(grid)
            cards = []
            card_class = FeatureCard if key == "annotation" else TileCard
            for spec in specs:
                number = numbers[spec.id]
                card = card_class(spec, "Ctrl+%d" % number if number <= 9 else "")
                card.openRequested.connect(self.openRequested.emit)
                card.folderRequested.connect(self.folderRequested.emit)
                if hasattr(card, "forgetRequested"):
                    card.forgetRequested.connect(self.forgetRequested.emit)
                cards.append(card)
                self.cards.append(card)
            self.sections.append((label, grid, cards))

        footer = QLabel("Ctrl+Shift+H comes back here from any tool  ·  Ctrl+T switches light and "
                        "dark  ·  Ctrl+Q quits  ·  %s %s" % (SUITE_NAME, SUITE_VERSION))
        footer.setObjectName("Subtitle")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addStretch(1)
        body.addWidget(footer)
        self._reflow(force=True)

    # ── theme ─────────────────────────────────────────────
    def set_theme(self, theme) -> None:
        self._theme = theme
        self.hero_mark.setPixmap(icons.mark_pixmap("suite", theme["accent"], theme["surfaceAlt"], 60))
        for card in self.cards + self.continue_cards:
            card.set_theme(theme)

    # ── content ───────────────────────────────────────────
    def refresh(self, wait=False) -> None:
        self.greeting.setText(greeting())
        self.date_label.setText(datetime.now().strftime("%A, %d %B"))
        for card in self.cards:
            try:
                folders = card.spec.recent() if card.spec.recent else []
            except Exception:
                folders = []
            card.set_recent([f for f in folders if os.path.isdir(f)])
        self._build_continue(wait)

    def _build_continue(self, wait) -> None:
        for card in self.continue_cards:
            self.continue_row.removeWidget(card)
            card.deleteLater()
        self.continue_cards = []
        while self.continue_row.count():
            self.continue_row.takeAt(0)
        try:
            sessions = activity.recent_sessions(self.tools, limit=3)
        except Exception:
            sessions = []
        specs = {spec.id: spec for spec in self.tools}
        for session in sessions:
            card = ContinueCard(session, specs[session.tool_id])
            card.resumeRequested.connect(self.folderRequested.emit)
            card.forgetRequested.connect(self.forgetRequested.emit)
            if self._theme is not None:
                card.set_theme(self._theme)
            self.continue_cards.append(card)
            self.continue_row.addWidget(card, 1)
        for _spare in range(3 - len(sessions)):
            self.continue_row.addStretch(1)
        self.continue_section.setVisible(bool(sessions))
        if not sessions:
            return
        self._generation += 1
        generation = self._generation
        if wait:
            self._on_measured((generation, self._measure(sessions)))
        else:
            threading.Thread(target=lambda: self._measured.emit((generation, self._measure(sessions))),
                             daemon=True).start()

    @staticmethod
    def _measure(sessions):
        results = []
        for session in sessions:
            try:
                activity.measure(session)
            except Exception:
                session.measured = True
            image = QImage()
            if session.thumb:
                try:
                    reader = QImageReader(session.thumb)
                    reader.setAutoTransform(True)
                    size = reader.size()
                    if size.isValid() and size.width() > 0 and size.height() > 0:
                        scale = max(THUMB_W * 2.0 / size.width(), THUMB_H * 2.0 / size.height())
                        reader.setScaledSize(QSize(max(1, int(size.width() * scale)),
                                                   max(1, int(size.height() * scale))))
                    image = reader.read()
                except Exception:
                    image = QImage()
            results.append((session, image))
        return results

    def _on_measured(self, payload) -> None:
        generation, results = payload
        if generation != self._generation:
            return
        for card, (session, image) in zip(self.continue_cards, results):
            card.set_measured(session, image)

    # ── layout ────────────────────────────────────────────
    def _reflow(self, force=False) -> None:
        width = self.width()
        feature = 1 if width < 900 else (2 if width < 1280 else 3)
        tiles = 1 if width < 720 else (2 if width < 1120 else 3)
        if (feature, tiles) == self._columns and not force:
            return
        self._columns = (feature, tiles)
        for label, grid, widgets in self.sections:
            columns = feature if widgets and isinstance(widgets[0], FeatureCard) else tiles
            for widget in widgets:
                grid.removeWidget(widget)
            for position, widget in enumerate(widgets):
                grid.addWidget(widget, position // columns, position % columns)
            for column in range(3):
                grid.setColumnStretch(column, 1 if column < columns else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()
