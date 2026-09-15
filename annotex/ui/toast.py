"""Toasts: a short confirmation that something happened, without a dialog.

    from annotex.ui import toast
    toast.show(self, "12 boxes cleared", tone="good", action="Undo", on_action=self.undo)

A toast floats at the bottom centre of its window, fades in, waits, and
fades out.  A new toast replaces the one already showing.  Hovering keeps it
up.  With reduced motion (ANNOTEX_REDUCED_MOTION=1, or no real screen) it
appears and disappears without fading.

A toast only ever confirms or offers an undo - anything the user must read
or decide is a message (annotex.ui.dialogs.messages).
"""

from __future__ import annotations

import os

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QPushButton, QWidget)

from . import design

DURATION = 2600            # how long a toast stays, in milliseconds
LONG_DURATION = 5000       # ... when it offers an action, so there is time to press it
TONES = ("good", "info", "warn", "danger")


def reduced_motion() -> bool:
    if os.environ.get("ANNOTEX_REDUCED_MOTION", "").strip() not in ("", "0"):
        return True
    return QApplication.platformName() in ("offscreen", "minimal")


class Toast(QFrame):
    def __init__(self, host, text, tone="good", action="", on_action=None, duration=None):
        super().__init__(host)
        self.setObjectName("Toast")
        self.setProperty("tone", tone if tone in TONES else "info")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._host = host
        self._closing = False
        self._animation = None

        layout = QHBoxLayout(self)
        design.margins(layout, "s", "l")
        layout.setSpacing(design.SPACE["m"])
        self.mark = QFrame()
        self.mark.setObjectName("ToastMark")
        self.mark.setProperty("tone", self.property("tone"))
        self.mark.setFixedSize(design.SPACE["s"], design.SPACE["s"])
        layout.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignVCenter)
        self.label = QLabel(text)
        self.label.setObjectName("ToastText")
        layout.addWidget(self.label, 1)
        self.button = None
        if action:
            self.button = QPushButton(action)
            self.button.setObjectName("ToastAction")
            self.button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.button.clicked.connect(lambda: self._act(on_action))
            layout.addWidget(self.button)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._wait = duration or (LONG_DURATION if action else DURATION)
        host.installEventFilter(self)

    # ── showing and hiding ────────────────────────────────
    def popup(self) -> None:
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        if reduced_motion():
            self._effect.setOpacity(1.0)
        else:
            self._fade(0.0, 1.0, design.MOTION["normal"])
        self._timer.start(self._wait)

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        if reduced_motion():
            self._finish()
        else:
            self._fade(self._effect.opacity(), 0.0, design.MOTION["fast"], self._finish)

    def _finish(self) -> None:
        try:
            self._host.removeEventFilter(self)
        except RuntimeError:
            pass
        self.hide()
        self.deleteLater()

    def _fade(self, start, end, duration, then=None) -> None:
        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setDuration(duration)
        self._animation.setStartValue(start)
        self._animation.setEndValue(end)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        if then is not None:
            self._animation.finished.connect(then)
        self._animation.start()

    def _act(self, callback) -> None:
        self.dismiss()
        if callback is not None:
            callback()

    # ── staying put ───────────────────────────────────────
    def _place(self) -> None:
        host = self._host.rect()
        width = min(self.sizeHint().width(), max(0, host.width() - 2 * design.SPACE["xl"]))
        self.resize(width, self.sizeHint().height())
        self.move((host.width() - width) // 2, host.height() - self.height() - design.SPACE["xl"])

    def eventFilter(self, watched, event) -> bool:
        if watched is self._host and event.type() == QEvent.Type.Resize:
            self._place()
        return False

    def enterEvent(self, event):
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._closing:
            self._timer.start(DURATION)
        super().leaveEvent(event)


def _host_for(widget) -> QWidget:
    return widget.window() if isinstance(widget, QWidget) else None


def show(widget, text, tone="good", action="", on_action=None, duration=None):
    """Show a toast over the window `widget` belongs to; returns it (or None
    when there is no window to show it in)."""
    host = _host_for(widget)
    if host is None:
        return None
    current = getattr(host, "_annotex_toast", None)
    if current is not None:
        try:
            current.dismiss()
        except RuntimeError:
            pass
    toast = Toast(host, text, tone, action, on_action, duration)
    host._annotex_toast = toast
    toast.destroyed.connect(lambda *_a, h=host, t=toast: _forget(h, t))
    toast.popup()
    return toast


def _forget(host, toast) -> None:
    try:
        if getattr(host, "_annotex_toast", None) is toast:
            host._annotex_toast = None
    except RuntimeError:
        pass
