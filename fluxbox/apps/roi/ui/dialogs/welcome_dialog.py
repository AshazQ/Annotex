"""First-run tour, the About box, and crash-recovery prompts."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QLabel, QStackedWidget,
                               QVBoxLayout, QWidget)

from ...config import (APP_NAME, APP_TAGLINE, APP_VERSION, JSON_NAME,
                       MAP_NAME, NO_ROI_DIR, PRINTED_DIR, XLSX_NAME)
from .. import icons
from .common import Dialog, card, hint, row

PAGES = [
    ("folder", "Point it at a folder of images",
     "Open a batch folder and every supported image in it becomes a page to "
     "work through. Two subfolders are created beside your images: "
     "<b>%s</b> for images with nothing to mark, and <b>%s</b> for a copy of "
     "each image with its ROIs burnt in." % (NO_ROI_DIR, PRINTED_DIR)),
    ("polygon", "Draw with the tool that fits",
     "<b>W</b> draws a polygon point by point, <b>B</b> drags out a "
     "rectangle, <b>C</b> a circle, and <b>G</b> traces freehand. Press "
     "<b>V</b> to go back to the select tool, where you drag vertices, "
     "double-click an edge to add a point, and Ctrl+click one to remove it."),
    ("save", "Save moves you forward",
     "<b>S</b> saves the current image and steps to the next one. <b>N</b> "
     "files an image under no_roi. Nothing is ever lost on the way: leaving "
     "an image commits whatever is on screen, and a failed write stops the "
     "move instead of losing your work."),
    ("export", "The outputs are ready to use",
     "Every save writes <b>%s</b>, <b>%s</b> and <b>%s</b> - atomically, "
     "verified, with a rolling backup. COCO, YOLO, Pascal VOC and mask "
     "exports are one dialog away, and <b>F8</b> writes an HTML report for "
     "the whole batch." % (XLSX_NAME, JSON_NAME, MAP_NAME)),
    ("command", "Everything has a key",
     "Press <b>?</b> for the full shortcut sheet and <b>Ctrl+K</b> for the "
     "command palette, which runs any command by name. Every shortcut can be "
     "rebound in Settings."),
]


class WelcomeDialog(Dialog):
    """A short tour shown once, and available again from the menu."""

    def __init__(self, parent, theme=None):
        super().__init__(parent, "Welcome to %s" % APP_NAME,
                         "", width=620, height=430)
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

        self.skip_box = QCheckBox("Show this the next time I start")
        self.skip_box.setChecked(False)
        self.buttons.insertWidget(0, self.skip_box)
        self.buttons.insertStretch(1, 1)

        self.back_button = self.add_button("Back", slot=lambda: self._step(-1))
        self.next_button = self.add_button("Next", primary=True,
                                           slot=lambda: self._step(1))
        self._sync()

    def _page(self, icon_name, title, text) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(14)
        layout.setContentsMargins(6, 10, 6, 6)

        badge = QLabel()
        badge.setPixmap(icons.pixmap(icon_name,
                                     self._theme.get("accent", "#df5e3b"),
                                     44, 1.6, 2.0))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(badge)

        heading = QLabel(title)
        heading.setObjectName("Title")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setWordWrap(True)
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
        last = self._index == self.stack.count() - 1
        self.next_button.setText("Get started" if last else "Next")
        self.dots.setText("  ".join("●" if i == self._index else "○"
                                    for i in range(self.stack.count())))

    def show_again(self) -> bool:
        return self.skip_box.isChecked()


class AboutDialog(Dialog):
    def __init__(self, parent, extras, theme=None):
        super().__init__(parent, "About %s" % APP_NAME, "", width=470)
        theme = dict(theme or {})

        badge = QLabel()
        badge.setPixmap(icons.pixmap("polygon", theme.get("accent", "#df5e3b"),
                                     40, 1.6, 2.0))
        title = QLabel("<b>%s</b> %s<br><span style='color:%s'>%s</span>"
                       % (APP_NAME, APP_VERSION, theme.get("sub", "#8b93a1"),
                          APP_TAGLINE))
        title.setTextFormat(Qt.TextFormat.RichText)
        self.body.addWidget(row(badge, title, None))

        frame, inner = card("Environment")
        for label, value in extras:
            inner.addWidget(row(QLabel(label), None, QLabel(str(value))))
        self.body.addWidget(frame)
        self.body.addWidget(hint(
            "Annotations are written atomically and verified by reading them "
            "back, with a rolling backup of the previous good copy."))
        self.add_close_button()
