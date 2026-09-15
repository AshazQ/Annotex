"""Display settings for the whole suite: how big everything is drawn.

The size is Qt's own scale factor, so text, buttons, icons and panels grow and
shrink together and nothing ends up cut off.  Qt only accepts it as the
application starts, which is why a change asks to restart.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QComboBox, QLabel

from ..config import INTERFACE_SIZES, interface_factor
from ..ui.dialogs.common import Dialog, card, hint


def restart_command():
    """(program, arguments, working folder) that starts Annotex again the way
    it was started this time - a frozen build, `python run.py` or
    `python -m annotex`."""
    if getattr(sys, "frozen", False):
        return sys.executable, list(sys.argv[1:]), os.getcwd()
    main = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if not main or os.path.basename(main) == "__main__.py" or not os.path.isfile(main):
        package_parent = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return sys.executable, ["-m", "annotex"] + list(sys.argv[1:]), package_parent
    return sys.executable, [main] + list(sys.argv[1:]), os.getcwd()


class DisplayDialog(Dialog):
    def __init__(self, parent, settings):
        super().__init__(parent, "Display",
                         "How big Annotex draws text, buttons and panels on this screen.",
                         width=500)
        self.settings = settings
        self.restart_requested = False
        applied = os.environ.get("QT_SCALE_FACTOR", "")

        frame, inner = card("Interface size")
        self.size_box = QComboBox()
        auto = interface_factor(_AutoOnly(settings))
        self.size_box.addItem("Automatic  -  fits this screen (%d %%)" % round(auto * 100), "auto")
        for factor in INTERFACE_SIZES:
            self.size_box.addItem("%d %%%s" % (round(factor * 100),
                                               "   (normal)" if factor == 1.0 else ""), factor)
        current = settings.get("ui_scale", "auto")
        index = 0
        for position in range(self.size_box.count()):
            data = self.size_box.itemData(position)
            if data == current or (data != "auto" and current != "auto" and _same(data, current)):
                index = position
        self.size_box.setCurrentIndex(index)
        inner.addWidget(self.size_box)
        inner.addWidget(hint("Smaller fits more on a small screen, or a laptop running Windows "
                             "at 125 % or 150 % scaling.  Larger is easier to read on a big "
                             "monitor.  Automatic picks the largest size that fits without "
                             "scrolling."))
        self.note = QLabel("")
        self.note.setObjectName("Hint")
        self.note.setWordWrap(True)
        inner.addWidget(self.note)
        if applied:
            self.note.setText("Now drawn at %d %%." % round(float(applied) * 100)
                              if _is_number(applied) else "")
        self.body.addWidget(frame)
        self.body.addWidget(hint("A new size is used when Annotex starts again.  Open work is "
                                 "saved first, as it is when you quit."))

        self.add_button("Cancel", slot=self.reject)
        self.add_button("Save for next start", slot=self._save_only)
        self.add_button("Save and restart now", primary=True, slot=self._save_restart)

    def chosen(self):
        return self.size_box.currentData()

    def _save_only(self) -> None:
        self.restart_requested = False
        self.accept()

    def _save_restart(self) -> None:
        self.restart_requested = True
        self.accept()


class _AutoOnly:
    """Reads a settings store as if Interface size were set to Automatic."""

    def __init__(self, settings):
        self._settings = settings

    def get(self, key, default=None):
        if key == "ui_scale":
            return "auto"
        return self._settings.get(key, default)


def _same(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 0.001
    except (TypeError, ValueError):
        return False


def _is_number(value) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
