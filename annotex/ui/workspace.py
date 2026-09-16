"""The annotation workspace the three labelling tools share.

    ╭──╮┌──────────────────────────────────┐╭──╮┌──────────┐
    │▸ ││                                  ││«  ││          │
    │▭ ││              image               ││💾 ││  panel   │
    │✋ ││                                  ││⏎  ││          │
    │──││                                  │╰──╯│          │
    │↶ │├──────────────────────────────────┤    │          │
    │↷ ││ ▾  folder  ·  image  ·  format   │    │          │
    ╰──╯│ filmstrip (folds away)           │    │          │
        └──────────────────────────────────┘    └──────────┘

* The tools sit in a pill-shaped rail on the left instead of a header row,
  so the image starts at the top of the window.
* The side panel folds into a slim strip that keeps its most-used buttons;
  the strip's first button (or the tool's shortcut) opens it again.
* The filmstrip folds under a one-line bar that also carries the folder and
  image details the header used to show.

Nothing is taken away - every button is still one click away - and each tool
remembers what was folded.  Long paths are elided instead of widening the
window, so the layout fits a small laptop screen at any display scaling.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QPainter
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QScrollArea,
                               QSizePolicy, QSplitter, QVBoxLayout, QWidget)

from . import design
from . import icons

from .design import NAV_BUTTON, RAIL_BUTTON, RAIL_WIDTH


class ElidedLabel(QLabel):
    """A one-line label that shortens its text with "…" to the room it has,
    instead of demanding the full width of a long path."""

    def __init__(self, text="", mode=Qt.TextElideMode.ElideMiddle, parent=None):
        super().__init__(parent)
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text) -> None:
        text = "" if text is None else str(text)
        super().setText(text)
        self.setToolTip(text)
        self.update()

    def minimumSizeHint(self) -> QSize:
        return QSize(24, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(min(hint.width(), 520), hint.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            rect = self.contentsRect()
            text = self.fontMetrics().elidedText(self.text(), self._mode, rect.width())
            self.style().drawItemText(painter, rect,
                                      int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                                      self.palette(), self.isEnabled(), text, self.foregroundRole())
        finally:
            painter.end()


class ToolRail(QFrame):
    """A vertical, pill-shaped bar of tool buttons.  On a screen too short
    for all of them it scrolls with the mouse wheel rather than clipping."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Rail")
        self.setFixedWidth(RAIL_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 8)
        outer.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("RailScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName("RailBody")
        self._layout = QVBoxLayout(holder)
        self._layout.setContentsMargins(0, 0, 0, 0)
        # The circles sit directly under one another: at this size the gap
        # would cost a button or two of height on a short laptop screen.
        self._layout.setSpacing(0)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        # The scroll area resizes its body to the viewport, which would
        # squash the buttons flat on a short screen.  Holding the body to the
        # column's own minimum keeps every button square - so its hover and
        # chosen states stay circles - and scrolls instead.
        self._layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.scroll.setWidget(holder)
        outer.addWidget(self.scroll)
        self.buttons = []

    def add(self, widget):
        if isinstance(widget, QPushButton):
            widget.setFixedSize(*RAIL_BUTTON)
            self.buttons.append(widget)
        self._layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)
        self.updateGeometry()
        return widget

    def add_separator(self) -> None:
        line = QFrame()
        line.setObjectName("RailSep")
        line.setFixedSize(24, 1)
        self._layout.addSpacing(2)
        self._layout.addWidget(line, 0, Qt.AlignmentFlag.AlignHCenter)
        self._layout.addSpacing(2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._whole_buttons()

    def _whole_buttons(self) -> None:
        """Show whole buttons only.  A rail too short for every tool scrolls,
        and a half-cut circle at the bottom edge would look like a fault."""
        step = RAIL_BUTTON[1]
        room = self.contentsRect().height() - self._padding()
        body = self.scroll.widget()
        wanted = body.sizeHint().height() if body is not None else 0
        if room >= wanted:
            self.scroll.setMaximumHeight(16777215)
            return
        self.scroll.setMaximumHeight(max(step, (room // step) * step))

    def _padding(self) -> int:
        """The room the buttons do not get: the layout's own top and bottom."""
        margins = self.layout().contentsMargins()
        return margins.top() + margins.bottom()

    def _border(self) -> int:
        """The pill's hairline, top and bottom, which the stylesheet draws."""
        frame = self.contentsMargins()
        return frame.top() + frame.bottom()

    def sizeHint(self) -> QSize:
        # The pill is drawn with a hairline border.  Asking only for the
        # buttons plus the layout's padding left the rail two pixels short of
        # its own column on every screen, so it scrolled even on a large
        # monitor - and the rounding below turned those two pixels into a
        # whole hidden button.  Ask for what it actually takes to draw.
        body = self.scroll.widget()
        inner = body.sizeHint().height() if body is not None else 0
        return QSize(RAIL_WIDTH, inner + self._padding() + self._border())

    def minimumSizeHint(self) -> QSize:
        return QSize(RAIL_WIDTH, 60)


class SidePanel(QWidget):
    """The side panel, which folds into a slim strip.

    Open, it is just the panel with a small fold button above it - no strip
    eating into the image.  Folded, only the strip is left: its first button
    opens the panel again, and the buttons below it (save, next, …) stay
    usable, so folding never takes a feature away."""

    collapsedChanged = Signal(bool)

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel
        self._collapsed = False
        self._restore_width = 0
        self._theme = None
        self.shortcut_text = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # folded: the strip
        self.strip = ToolRail()
        self.toggle_button = QPushButton()
        self.toggle_button.setObjectName("Tool")
        self.toggle_button.clicked.connect(self.toggle)
        self.strip.add(self.toggle_button)
        self.strip.add_separator()
        self.strip_view = QWidget()
        strip_column = QVBoxLayout(self.strip_view)
        strip_column.setContentsMargins(0, 0, 0, 0)
        strip_column.addWidget(self.strip)
        strip_column.addStretch(1)
        layout.addWidget(self.strip_view)

        # open: the panel, with its fold button above it
        self.open_view = QWidget()
        open_column = QVBoxLayout(self.open_view)
        open_column.setContentsMargins(0, 0, 0, 0)
        open_column.setSpacing(2)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 4, 0)
        header.addStretch(1)
        self.fold_button = QPushButton()
        self.fold_button.setObjectName("Tool")
        self.fold_button.setFixedSize(30, 24)
        self.fold_button.clicked.connect(self.toggle)
        header.addWidget(self.fold_button)
        open_column.addLayout(header)
        open_column.addWidget(panel, 1)
        layout.addWidget(self.open_view, 1)
        self._apply_state()

    def add_strip_button(self, button):
        return self.strip.add(button)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def _splitter(self):
        parent = self.parentWidget()
        return parent if isinstance(parent, QSplitter) else None

    def _apply_state(self) -> None:
        collapsed = self._collapsed
        self.strip_view.setVisible(collapsed)
        self.open_view.setVisible(not collapsed)
        if collapsed:
            self.setMinimumWidth(RAIL_WIDTH)
            self.setMaximumWidth(RAIL_WIDTH)
        else:
            self.setMinimumWidth(self.panel.minimumWidth())
            self.setMaximumWidth(max(self.panel.maximumWidth(), self.panel.minimumWidth()))
        self._sync()

    def set_collapsed(self, collapsed) -> None:
        collapsed = bool(collapsed)
        changed = collapsed != self._collapsed
        splitter = self._splitter()
        if collapsed and not self._collapsed and splitter is not None:
            sizes = splitter.sizes()
            if sizes and sizes[-1] > RAIL_WIDTH:
                self._restore_width = sizes[-1]
        self._collapsed = collapsed
        self._apply_state()
        # A splitter keeps a child's old share when its limits change, so hand
        # the width over explicitly - otherwise folding frees nothing.
        if splitter is not None:
            sizes = splitter.sizes()
            total = sum(sizes)
            if total > 0 and len(sizes) >= 2:
                if collapsed:
                    width = RAIL_WIDTH
                else:
                    wanted = self._restore_width or (self.minimumWidth() + 40)
                    width = max(self.minimumWidth(), min(self.maximumWidth(), wanted))
                width = min(width, total)
                splitter.setSizes(sizes[:-2] + [max(0, sizes[-2] + sizes[-1] - width), width])
        if changed:
            self.collapsedChanged.emit(collapsed)

    def toggle(self) -> None:
        self.set_collapsed(not self._collapsed)

    def apply_theme(self, theme) -> None:
        self._theme = theme
        self._sync()

    def _sync(self) -> None:
        key = "   [%s]" % self.shortcut_text if self.shortcut_text else ""
        self.toggle_button.setToolTip("Show the side panel" + key)
        self.fold_button.setToolTip("Fold the side panel away for a bigger image" + key)
        if self._theme is not None:
            self.toggle_button.setIcon(icons.icon("panel_open", self._theme["text"], 19))
            self.toggle_button.setIconSize(QSize(design.ICON["m"], design.ICON["m"]))
            self.fold_button.setIcon(icons.icon("panel_close", self._theme["sub"], 16))
            self.fold_button.setIconSize(QSize(16, 16))


class FoldBar(QWidget):
    """One line under the image: a button that folds the filmstrip away, and
    the folder and image details beside it."""

    foldedChanged = Signal(bool)

    def __init__(self, target, parent=None):
        super().__init__(parent)
        self.target = target
        self._folded = False
        self._theme = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(8)
        self.button = QPushButton()
        self.button.setObjectName("Tool")
        self.button.setFixedSize(28, 24)
        self.button.clicked.connect(self.toggle)
        layout.addWidget(self.button)
        self.info = QHBoxLayout()
        self.info.setSpacing(design.SPACE["s"])
        layout.addLayout(self.info, 1)
        self._sync()

    def add_info(self, widget, stretch=0):
        self.info.addWidget(widget, stretch)
        return widget

    def is_folded(self) -> bool:
        return self._folded

    def set_folded(self, folded) -> None:
        folded = bool(folded)
        changed = folded != self._folded
        self._folded = folded
        self.target.setVisible(not folded)
        self._sync()
        if changed:
            self.foldedChanged.emit(folded)

    def toggle(self) -> None:
        self.set_folded(not self._folded)

    def apply_theme(self, theme) -> None:
        self._theme = theme
        self._sync()

    def _sync(self) -> None:
        self.button.setToolTip("Show the filmstrip" if self._folded else "Fold the filmstrip away")
        if self._theme is not None:
            self.button.setIcon(icons.icon("chevron_up" if self._folded else "chevron_down",
                                           self._theme["sub"], 16))
            self.button.setIconSize(QSize(16, 16))


class NavArrows(QObject):
    """Two round buttons floating at the right edge of the image - previous
    above, next below - for stepping through a folder with the mouse."""

    SIZE = NAV_BUTTON

    def __init__(self, frame, on_prev, on_next):
        super().__init__(frame)
        self.frame = frame
        self.prev_button = self._button("Previous image", on_prev)
        self.next_button = self._button("Next image", on_next)
        frame.installEventFilter(self)
        self._place()

    def _button(self, tip, slot) -> QPushButton:
        button = QPushButton(self.frame)
        button.setObjectName("NavRound")
        button.setFixedSize(self.SIZE, self.SIZE)
        button.setIconSize(QSize(20, 20))
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)     # keys stay with the canvas
        button.clicked.connect(lambda _checked=False: slot())
        button.show()
        return button

    def eventFilter(self, obj, event):
        if obj is self.frame and event.type() in (QEvent.Type.Resize, QEvent.Type.Show,
                                                   QEvent.Type.LayoutRequest):
            self._place()
        return False

    def _place(self) -> None:
        rect = self.frame.rect()
        x = rect.width() - self.SIZE - 12
        middle = rect.height() // 2
        self.prev_button.move(x, middle - self.SIZE - 5)
        self.next_button.move(x, middle + 5)
        self.prev_button.raise_()
        self.next_button.raise_()

    def apply_theme(self, theme) -> None:
        self.prev_button.setIcon(icons.icon("prev", theme["title"], 20))
        self.next_button.setIcon(icons.icon("next", theme["title"], 20))


def _remember(settings, key, value) -> None:
    try:
        settings.set(key, bool(value))
    except Exception:
        pass


class Workspace:
    """Everything `assemble` built, for the tool to keep hold of."""

    def __init__(self, central, rail, splitter, side, fold, nav=None):
        self.central = central
        self.rail = rail
        self.splitter = splitter
        self.side = side
        self.fold = fold
        self.nav = nav

    def apply_theme(self, theme) -> None:
        self.side.apply_theme(theme)
        self.fold.apply_theme(theme)
        if self.nav is not None:
            self.nav.apply_theme(theme)


def assemble(window, rail, canvas_frame, filmstrip, side_widget, settings=None,
             info=(), side_width=340, shortcut=None, on_prev=None, on_next=None) -> Workspace:
    """Lay a labelling tool out as a workspace and make it its central widget.

    `info` is [(widget, stretch)] for the line under the image.  The folded
    state is read from and written to `settings` (side_collapsed,
    filmstrip_folded) when given.  `shortcut` adds a key that folds the side
    panel, for a tool that has no such action of its own."""
    central = QWidget()
    window.setCentralWidget(central)
    root = QHBoxLayout(central)
    design.margins(root, "s", "s", "xs", "s")
    root.setSpacing(8)

    rail_column = QVBoxLayout()
    rail_column.setContentsMargins(0, 0, 0, 0)
    rail_column.addWidget(rail)
    rail_column.addStretch(1)
    root.addLayout(rail_column)

    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(8)
    column = QWidget()
    column_layout = QVBoxLayout(column)
    column_layout.setContentsMargins(0, 0, 0, 0)
    column_layout.setSpacing(4)
    column_layout.addWidget(canvas_frame, 1)
    fold = FoldBar(filmstrip)
    for widget, stretch in info:
        fold.add_info(widget, stretch)
    column_layout.addWidget(fold)
    column_layout.addWidget(filmstrip)
    splitter.addWidget(column)

    side = SidePanel(side_widget)
    splitter.addWidget(side)
    splitter.setStretchFactor(0, 1)
    splitter.setStretchFactor(1, 0)
    splitter.setSizes([1000, side_width])
    root.addWidget(splitter, 1)

    if shortcut:
        action = QAction("Fold or show the side panel", window)
        action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(side.toggle)
        window.addAction(action)
        side.shortcut_text = shortcut
        side._sync()

    if settings is not None:
        side.set_collapsed(bool(settings.get("side_collapsed", False)))
        fold.set_folded(bool(settings.get("filmstrip_folded", False)))
        side.collapsedChanged.connect(lambda value: _remember(settings, "side_collapsed", value))
        fold.foldedChanged.connect(lambda value: _remember(settings, "filmstrip_folded", value))
    nav = NavArrows(canvas_frame, on_prev, on_next) if on_prev and on_next else None
    return Workspace(central, rail, splitter, side, fold, nav)
