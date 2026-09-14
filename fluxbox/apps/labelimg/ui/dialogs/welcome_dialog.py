"""First-run tour and the About box."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QLabel, QStackedWidget, QVBoxLayout, QWidget

from fluxbox.ui import icons
from fluxbox.ui.dialogs.common import Dialog, card, hint, row

from ...config import APP_NAME, APP_TAGLINE, APP_VERSION, BACKUP_DIR

PAGES = [
    ("folder", "Open a folder of images",
     "<b>Ctrl+U</b> opens a folder; every image in it, sub-folders included, "
     "becomes a frame to work through. Annotations are saved beside the images, "
     "or wherever <b>Ctrl+R</b> points them."),
    ("tag", "Classes live in projects",
     "<b>Ctrl+M</b> opens the Class Manager. IDs are permanent, so YOLO files "
     "never get renumbered. Keys <b>1 … 0</b> pick the first ten classes - with a "
     "box selected they relabel it, otherwise they arm the next box."),
    ("rect", "Draw, fix, accept",
     "<b>W</b> draws a box, <b>V</b> selects. Drag handles to resize, arrows to "
     "nudge, <b>Enter</b> accepts the frame and moves on, <b>N</b> marks it as "
     "background, <b>Space</b> toggles verified."),
    ("save", "Nothing is lost on the way",
     "Leaving an image saves it. Every write is verified before it replaces the "
     "old file, the previous version is kept in <b>%s</b>, and unsaved work is "
     "drafted every few seconds." % BACKUP_DIR),
    ("command", "Everything has a key",
     "<b>?</b> shows every shortcut, <b>Ctrl+K</b> runs any command by name, "
     "<b>F6</b> reviews the batch and <b>F7</b> shows the dashboard."),
]


class WelcomeDialog(Dialog):
    def __init__(self, parent, theme=None):
        super().__init__(parent, "Welcome to %s" % APP_NAME, "", width=620, height=430)
        self._theme = dict(theme or {})
        self._index = 0
        self.stack = QStackedWidget()
        for icon_name, title, text in PAGES:
            self.stack.addWidget(self._page(icon_name, title, text))
        self.body.addWidget(self.stack, 1)
        self.dots = QLabel()
        self.dots.setObjectName("Subtitle")
        self.dots.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.dots)
        self.again = QCheckBox("Show this the next time")
        self.buttons.insertWidget(0, self.again)
        self.buttons.insertStretch(1, 1)
        self.back_button = self.add_button("Back", slot=lambda: self._step(-1))
        self.next_button = self.add_button("Next", primary=True, slot=lambda: self._step(1))
        self._sync()

    def _page(self, icon_name, title, text) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(14)
        badge = QLabel()
        badge.setPixmap(icons.pixmap(icon_name, self._theme.get("accent", "#df5e3b"),
                                     44, 1.6, 2.0))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(badge)
        heading = QLabel(title)
        heading.setObjectName("Title")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setObjectName("Hint")
        layout.addWidget(body)
        layout.addStretch(1)
        return page

    def _step(self, delta) -> None:
        target = self._index + int(delta)
        if target < 0:
            return
        if target >= self.stack.count():
            self.accept()
            return
        self._index = target
        self.stack.setCurrentIndex(target)
        self._sync()

    def _sync(self) -> None:
        self.back_button.setEnabled(self._index > 0)
        self.next_button.setText("Get started" if self._index == self.stack.count() - 1
                                 else "Next")
        self.dots.setText("  ".join("●" if i == self._index else "○"
                                    for i in range(self.stack.count())))

    def show_again(self) -> bool:
        return self.again.isChecked()


class AboutDialog(Dialog):
    def __init__(self, parent, extras, theme=None):
        super().__init__(parent, "About %s" % APP_NAME, "", width=480)
        theme = dict(theme or {})
        badge = QLabel()
        badge.setPixmap(icons.mark_pixmap("box", theme.get("accent", "#df5e3b"),
                                          theme.get("surfaceAlt", "#252a33"), 44))
        title = QLabel("<b>%s</b> %s<br><span style='color:%s'>%s</span>"
                       % (APP_NAME, APP_VERSION, theme.get("sub", "#8b93a1"), APP_TAGLINE))
        title.setTextFormat(Qt.TextFormat.RichText)
        self.body.addWidget(row(badge, title, None))
        frame, inner = card("Environment")
        for label, value in extras:
            value_label = QLabel(str(value))
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            inner.addWidget(row(QLabel(label), None, value_label))
        self.body.addWidget(frame)
        self.body.addWidget(hint("Pascal VOC, YOLO and CreateML files are written by "
                                 "LabelImg's own writers, byte for byte as before."))
        self.add_close_button()
