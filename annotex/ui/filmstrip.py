"""The film strip: a scrollable row of thumbnails with per-image status.

Thumbnails are decoded on a worker pool, never on the UI thread, so opening a
folder of 4000x3000 photographs does not freeze the window.  Results arrive
by signal and are cached by path.

Statuses are plain strings; each tool picks its own vocabulary and the strip
maps it onto theme colours through STATUS_COLOURS.
"""

from __future__ import annotations

import os

from PySide6.QtCore import (QObject, QRect, QRectF, QRunnable, Qt,
                            QThreadPool, Signal, Slot)
from PySide6.QtGui import (QBrush, QColor, QImage, QPainter, QPen,
                           QPixmap)
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import design
from .palette import qcolor

THUMB_W, THUMB_H = 96, 72
GAP = 8
PADDING = 10

# status -> (theme key, fallback colour).  "todo" is the unvisited state and
# never gets a dot.
STATUS_COLOURS = {
    "todo": ("border", "#333a45"),
    "roi": ("good", "#5cbf6b"),
    "no_roi": ("sub", "#8b93a1"),
    "labelled": ("good", "#5cbf6b"),
    "background": ("sub", "#8b93a1"),
    "verified": ("info", "#5b9cea"),
}


class _LoaderSignals(QObject):
    done = Signal(str, QImage)


class _ThumbTask(QRunnable):
    """Decode one thumbnail off the UI thread."""

    def __init__(self, path, signals, width=THUMB_W * 2, height=THUMB_H * 2):
        super().__init__()
        self.path = path
        self.signals = signals
        self.width = width
        self.height = height
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        image = QImage()
        try:
            reader = QImage(self.path)
            if not reader.isNull():
                image = reader.scaled(
                    self.width, self.height,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
        except Exception:
            image = QImage()
        try:
            self.signals.done.emit(self.path, image)
        except RuntimeError:
            pass                     # the strip was destroyed mid-flight


class FilmStrip(QWidget):
    """Horizontal thumbnail navigator."""

    imagePicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(THUMB_H + PADDING * 2 + 16)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)

        self.folder = ""
        self.names = []
        self.index = 0
        self.statuses = {}           # name -> status string
        self.empty_text = "No batch loaded"
        self._thumbs = {}
        self._requested = set()
        self._offset = 0.0
        self._hover = -1
        self._theme = {}

        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(max(2, min(4, QThreadPool.globalInstance()
                                                .maxThreadCount())))
        self._signals = _LoaderSignals()
        self._signals.done.connect(self._thumb_ready)

    # ── content ───────────────────────────────────────────
    def set_theme(self, theme: dict) -> None:
        self._theme = dict(theme)
        self.update()

    def set_batch(self, folder, names, statuses=None) -> None:
        """Show this batch.

        Called again for the same folder after every save, so it keeps the
        thumbnails it already decoded and the place the strip was scrolled
        to - re-reading them all and jumping back to the first image on every
        save is both slow and disorienting."""
        folder = str(folder or "")
        moved = folder != self.folder
        self.folder = folder
        self.names = list(names or [])
        self.statuses = dict(statuses or {})
        if moved:
            self._thumbs.clear()
            self._requested.clear()
            self._offset = 0.0
            self.index = 0
        else:
            self._offset = min(self._offset, self._max_offset())
            self.index = max(0, min(self.index, len(self.names) - 1))
        self.update()

    def set_statuses(self, statuses) -> None:
        self.statuses = dict(statuses or {})
        self.update()

    def set_index(self, index: int) -> None:
        index = max(0, int(index))
        if index == self.index:
            self._ensure_visible()       # the strip may have been re-laid out
            self.update()
            return
        self.index = index
        self._ensure_visible()
        self.update()

    def clear(self) -> None:
        self.set_batch("", [], {})

    # ── geometry ──────────────────────────────────────────
    def _step(self) -> int:
        return THUMB_W + GAP

    def _content_width(self) -> int:
        return max(0, len(self.names) * self._step() - GAP + PADDING * 2)

    def _max_offset(self) -> float:
        return max(0.0, self._content_width() - self.width())

    def _rect_for(self, position: int) -> QRect:
        x = int(PADDING + position * self._step() - self._offset)
        return QRect(x, PADDING, THUMB_W, THUMB_H)

    def _index_at(self, x: int) -> int:
        if not self.names:
            return -1
        position = int((x + self._offset - PADDING + GAP / 2) // self._step())
        if 0 <= position < len(self.names):
            return position
        return -1

    def _ensure_visible(self) -> None:
        if not self.names:
            return
        rect = self._rect_for(self.index)
        if rect.left() < PADDING:
            self._offset = max(0.0, self.index * self._step())
        elif rect.right() > self.width() - PADDING:
            self._offset = min(self._max_offset(),
                               (self.index + 1) * self._step()
                               - self.width() + PADDING * 2)

    # ── thumbnails ────────────────────────────────────────
    def _request(self, name) -> None:
        path = os.path.join(self.folder, name)
        if path in self._requested or path in self._thumbs:
            return
        self._requested.add(path)
        self._pool.start(_ThumbTask(path, self._signals))

    @Slot(str, QImage)
    def _thumb_ready(self, path, image) -> None:
        self._requested.discard(path)
        if image.isNull():
            self._thumbs[path] = None
        else:
            self._thumbs[path] = QPixmap.fromImage(image)
        if len(self._thumbs) > 600:
            for key in list(self._thumbs)[:200]:
                self._thumbs.pop(key, None)
        self.update()

    # ── events ────────────────────────────────────────────
    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        if not delta:
            return
        self._offset = max(0.0, min(self._max_offset(),
                                    self._offset - delta * 0.6))
        self.update()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        position = self._index_at(int(event.position().x()))
        if position >= 0 and position != self.index:
            self.imagePicked.emit(position)

    def mouseMoveEvent(self, event):
        hover = self._index_at(int(event.position().x()))
        if hover != self._hover:
            self._hover = hover
            if 0 <= hover < len(self.names):
                self.setToolTip(self.names[hover])
            else:
                self.setToolTip("")
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._offset = min(self._offset, self._max_offset())
        self._ensure_visible()

    # ── painting ──────────────────────────────────────────
    def _status_colour(self, status) -> QColor:
        key, fallback = STATUS_COLOURS.get(status, STATUS_COLOURS["todo"])
        return qcolor(self._theme.get(key, fallback))

    def paintEvent(self, event):
        theme = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), qcolor(theme.get("appBg", "#14171d")))

        if not self.names:
            painter.setPen(QPen(qcolor(theme.get("muted", "#6f7784"))))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             self.empty_text)
            painter.end()
            return

        accent = qcolor(theme.get("accent", "#df5e3b"))
        placeholder = qcolor(theme.get("surfaceAlt", "#252a33"))
        label_colour = qcolor(theme.get("muted", "#6f7784"))
        font = design.font("caption", self.font())
        painter.setFont(font)

        first = max(0, int((self._offset - PADDING) // self._step()) - 1)
        last = min(len(self.names),
                   first + int(self.width() // self._step()) + 3)

        for position in range(first, last):
            name = self.names[position]
            rect = self._rect_for(position)
            if rect.right() < 0 or rect.left() > self.width():
                continue

            self._request(name)
            pixmap = self._thumbs.get(os.path.join(self.folder, name))
            target = QRectF(rect)
            painter.save()
            painter.setClipRect(rect)
            if pixmap:
                source = QRectF(
                    max(0, (pixmap.width() - rect.width() * 2) / 2.0),
                    max(0, (pixmap.height() - rect.height() * 2) / 2.0),
                    min(pixmap.width(), rect.width() * 2),
                    min(pixmap.height(), rect.height() * 2))
                painter.drawPixmap(target, pixmap, source)
            else:
                painter.fillRect(rect, placeholder)
                painter.setPen(QPen(label_colour))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                                 str(position + 1))
            painter.restore()

            current = (position == self.index)
            status = self.statuses.get(name, "todo")
            pen_colour = accent if current else self._status_colour(status)
            painter.setPen(QPen(pen_colour, 2.4 if current else 1.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(rect).adjusted(0.75, 0.75,
                                                          -0.75, -0.75), 7, 7)

            if position == self._hover and not current:
                painter.fillRect(rect, QColor(255, 255, 255, 26))

            if status != "todo":
                dot = QRectF(rect.right() - 12, rect.top() + 5, 7, 7)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(self._status_colour(status)))
                painter.drawEllipse(dot)

            painter.setPen(QPen(accent if current else label_colour))
            painter.drawText(QRect(rect.left(), rect.bottom() + 2,
                                   rect.width(), 14),
                             Qt.AlignmentFlag.AlignCenter,
                             str(position + 1))

        if self._max_offset() > 0:
            track = QRectF(PADDING, self.height() - 4,
                           self.width() - PADDING * 2, 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(qcolor(theme.get("border", "#333a45"))))
            painter.drawRoundedRect(track, 1, 1)
            fraction = self.width() / float(self._content_width())
            start = self._offset / float(self._content_width())
            thumb = QRectF(track.left() + track.width() * start, track.top(),
                           max(24.0, track.width() * fraction), track.height())
            painter.setBrush(QBrush(qcolor(theme.get("borderStrong", "#454d5a"))))
            painter.drawRoundedRect(thumb, 1, 1)

        painter.end()

    def shutdown(self) -> None:
        if getattr(self, "_shut_down", False):
            return
        self._shut_down = True
        try:
            self._signals.done.disconnect()
        except Exception:
            pass
        self._pool.clear()
