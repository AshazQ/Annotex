"""Messages: every question, notice and warning in one look and one voice.

    from annotex.ui.dialogs import messages
    if messages.ask(self, "Clear every box", "Remove all 4 boxes?", confirm="Clear",
                    destructive=True):
        ...
    messages.warn(self, "Could not save", str(exc))

A message is a small sheet drawn with the application's own stylesheet and
theme - never the platform's grey box - with a glyph for its kind, a title,
the text, optional details behind "Show details", and buttons named for what
they do.  Escape always means the safe answer.

Always call these through the module (messages.ask, not a copied name), so
the tests can answer for the user by replacing them.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from .. import design, icons

SHEET_WIDTH = 440
DETAIL_LINES = 10
GLYPHS = {"ask": ("help", "accent"), "inform": ("info", "info"),
          "warn": ("warning", "warn"), "error": ("warning", "danger")}


def _theme_of(widget) -> dict:
    """The theme of the window a message belongs to, or the running app's."""
    probe = widget
    while probe is not None:
        theme = getattr(probe, "theme", None)
        if isinstance(theme, dict) and "accent" in theme:
            return theme
        probe = probe.parentWidget() if isinstance(probe, QWidget) else None
    from ..palette import resolve_theme
    try:
        return resolve_theme("system", QApplication.instance())
    except Exception:
        return resolve_theme("dark")


class MessageSheet(QDialog):
    """One message.  `buttons` are (label, role) with role "primary", "danger"
    or "" - listed left to right; `default` is the index Enter presses and
    `escape` the index Escape (and closing the window) means."""

    def __init__(self, parent, kind, title, text, detail="", buttons=(("OK", "primary"),),
                 default=None, escape=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(SHEET_WIDTH)
        self.choice = escape if escape is not None else -1
        self._escape = self.choice
        theme = _theme_of(parent)

        root = QVBoxLayout(self)
        design.margins(root, "xl")
        root.setSpacing(design.SPACE["l"])

        top = QHBoxLayout()
        top.setSpacing(design.SPACE["l"])
        glyph_name, colour_key = GLYPHS.get(kind, GLYPHS["inform"])
        glyph = QLabel()
        glyph.setObjectName("MessageGlyph")
        size = design.ICON["m"] * 2
        glyph.setPixmap(icons.icon(glyph_name, theme.get(colour_key, theme.get("accent")),
                                   size).pixmap(QSize(size, size)))
        glyph.setFixedSize(size, size)
        top.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)

        words = QVBoxLayout()
        words.setSpacing(design.SPACE["s"])
        heading = QLabel(title)
        heading.setObjectName("Headline")
        heading.setWordWrap(True)
        words.addWidget(heading)
        self.text_label = QLabel(text)
        self.text_label.setObjectName("MessageText")
        self.text_label.setTextFormat(Qt.TextFormat.PlainText)
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        words.addWidget(self.text_label)
        top.addLayout(words, 1)
        root.addLayout(top)

        self.detail_box = None
        row = QHBoxLayout()
        row.setSpacing(design.SPACE["s"])
        if detail:
            self.detail_box = QPlainTextEdit(detail)
            self.detail_box.setObjectName("MessageDetail")
            self.detail_box.setReadOnly(True)
            self.detail_box.setFont(design.mono_font())
            self.detail_box.setFixedHeight(self.detail_box.fontMetrics().lineSpacing() * DETAIL_LINES)
            self.detail_box.hide()
            root.addWidget(self.detail_box)
            toggle = QPushButton("Show details")
            toggle.setObjectName("Link")
            toggle.clicked.connect(lambda: self._toggle_detail(toggle))
            row.addWidget(toggle)
        row.addStretch(1)
        self.buttons = []
        chosen_default = default if default is not None else len(buttons) - 1
        for index, (label, role) in enumerate(buttons):
            button = QPushButton(label)
            if role == "primary":
                button.setObjectName("Primary")
            elif role == "danger":
                button.setObjectName("DangerFilled")
            button.setAutoDefault(False)
            if index == chosen_default:
                button.setDefault(True)
                button.setFocus()
            button.clicked.connect(lambda _checked=False, i=index: self._pick(i))
            row.addWidget(button)
            self.buttons.append(button)
        root.addLayout(row)

    def _toggle_detail(self, toggle) -> None:
        showing = not self.detail_box.isVisible()
        self.detail_box.setVisible(showing)
        toggle.setText("Hide details" if showing else "Show details")
        self.adjustSize()

    def _pick(self, index) -> None:
        self.choice = index
        self.accept()

    def reject(self) -> None:
        self.choice = self._escape
        super().reject()

    def run(self) -> int:
        self.exec()
        return self.choice


# ── the voice ─────────────────────────────────────────────────
def ask(parent, title, text, confirm="Yes", cancel="No", default=True, destructive=False,
        detail="") -> bool:
    """A yes-or-no question.  True only when the user picks `confirm`; Escape
    and closing the sheet are always `cancel`.  default=False puts Enter on
    `cancel`, for questions where the safe answer should be the easy one."""
    role = "danger" if destructive else "primary"
    sheet = MessageSheet(parent, "ask", title, text, detail,
                         buttons=((cancel, ""), (confirm, role)),
                         default=1 if default else 0, escape=0)
    return sheet.run() == 1


def choose(parent, title, text, actions, detail="", kind="inform", cancel="Close"):
    """A notice with extra actions, e.g. "Open folder".  Returns the chosen
    action's label, or None for `cancel`."""
    buttons = [(label, "") for label in actions] + [(cancel, "primary")]
    sheet = MessageSheet(parent, kind, title, text, detail, buttons=buttons,
                         default=len(buttons) - 1, escape=len(buttons) - 1)
    picked = sheet.run()
    return actions[picked] if 0 <= picked < len(actions) else None


def inform(parent, title, text, detail="") -> None:
    MessageSheet(parent, "inform", title, text, detail).run()


def warn(parent, title, text, detail="") -> None:
    MessageSheet(parent, "warn", title, text, detail).run()


def error(parent, title, text, detail="") -> None:
    MessageSheet(parent, "error", title, text, detail).run()
