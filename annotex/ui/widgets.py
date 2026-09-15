"""Small panels every tool's side column is assembled from.

The minimap, the progress counters, the per-image comment and the section
furniture.  Tool-specific panels (ROI's vertex inspector, LabelImg's class
palette) live with their tools.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QLabel, QPlainTextEdit,
                               QVBoxLayout, QWidget)

from . import style
from . import design
from .palette import qcolor


def section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionHeader")
    return label


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFixedHeight(1)
    return line


# ══════════════════════════════════════════════════════════════
class StatsPanel(QWidget):
    """Batch counters plus a segmented progress bar.

    `fields` is [(key, caption, value_colour_key, bar_colour_key)].  A field
    whose bar colour is None is a total: it gets a counter but no segment.
    The default is ROI Studio's layout."""

    ROI_FIELDS = (("total", "Images", "title", None),
                  ("roi", "ROI drawn", "good", "good"),
                  ("no_roi", "No ROI", "sub", "sub"),
                  ("todo", "Remaining", "accent", "border"))

    def __init__(self, parent=None, fields=None, title="Batch progress"):
        super().__init__(parent)
        self._theme = {}
        self.fields = list(fields or self.ROI_FIELDS)
        self._values = {key: 0 for key, *_rest in self.fields}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.title_label = section_label(title)
        layout.addWidget(self.title_label)

        self.bar = SegmentBar()
        layout.addWidget(self.bar)

        grid = QGridLayout()
        grid.setHorizontalSpacing(design.SPACE["s"])
        grid.setVerticalSpacing(4)
        self._labels = {}
        for column, (key, text, _value_key, _bar_key) in enumerate(self.fields):
            value = QLabel("0")
            value.setObjectName("StatValue")
            caption = QLabel(text)
            caption.setObjectName("StatLabel")
            grid.addWidget(value, 0, column)
            grid.addWidget(caption, 1, column)
            self._labels[key] = value
        layout.addLayout(grid)

    def set_theme(self, theme: dict) -> None:
        self._theme = dict(theme)
        self._recolour()

    def set_values(self, *args, **kwargs) -> None:
        """Positional values follow the field order; keywords by key."""
        for (key, *_rest), value in zip(self.fields, args):
            self._values[key] = value
        for key, value in kwargs.items():
            if key in self._values:
                self._values[key] = value
        for key, value in self._values.items():
            self._labels[key].setText(str(value))
        self._recolour()

    def set_tooltip(self, key, text) -> None:
        if key in self._labels:
            self._labels[key].setToolTip(text)

    def _recolour(self) -> None:
        theme = self._theme or {}
        segments = []
        for key, _text, value_key, bar_key in self.fields:
            style.set_tone(self._labels[key], value_key if value_key in style.TONES else "text")
            if bar_key:
                segments.append((int(self._values.get(key) or 0),
                                 theme.get(bar_key, "#333a45")))
        self.bar.set_theme(theme)
        self.bar.set_segments(segments)


class SegmentBar(QWidget):
    """A rounded progress bar made of coloured segments."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(8)
        self._segments = []
        self._theme = {}

    def set_theme(self, theme):
        self._theme = dict(theme)
        self.update()

    def set_segments(self, segments):
        self._segments = [(max(0, int(count)), colour)
                          for count, colour in segments]
        self.update()

    # ROI Studio's original three-part call, kept so nothing else changes.
    def set_values(self, roi, no_roi, todo):
        theme = self._theme or {}
        self.set_segments([(roi, theme.get("good", "#5cbf6b")),
                           (no_roi, theme.get("sub", "#8b93a1")),
                           (todo, theme.get("border", "#333a45"))])

    def paintEvent(self, event):
        theme = self._theme or {}
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        radius = self.height() / 2.0
        track = QRectF(0, 0, self.width(), self.height())
        painter.setBrush(QBrush(qcolor(theme.get("surfaceAlt", "#252a33"))))
        painter.drawRoundedRect(track, radius, radius)

        total = sum(count for count, _colour in self._segments)
        if total <= 0:
            painter.end()
            return
        x = 0.0
        for count, colour in self._segments:
            if count <= 0:
                continue
            width = self.width() * count / float(total)
            painter.setBrush(QBrush(qcolor(colour)))
            painter.drawRoundedRect(QRectF(x, 0, max(width - 1.5, 1.5),
                                           self.height()), radius, radius)
            x += width
        painter.end()


# ══════════════════════════════════════════════════════════════
class CommentBox(QWidget):
    """The per-image note."""

    def __init__(self, parent=None, title="Image comment"):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(design.SPACE["s"])
        layout.addWidget(section_label(title))
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Saved with this image")
        self.editor.setFixedHeight(70)
        self.editor.setTabChangesFocus(True)
        layout.addWidget(self.editor)

    def text(self) -> str:
        return self.editor.toPlainText().strip()

    def set_text(self, value) -> None:
        blocked = self.editor.blockSignals(True)
        self.editor.setPlainText(str(value or ""))
        self.editor.blockSignals(blocked)

    def clear(self) -> None:
        self.set_text("")


# ══════════════════════════════════════════════════════════════
class MiniMap(QWidget):
    """A thumbnail of the whole image with the viewport drawn on it.

    Shapes only need a `bounds` attribute of (x0, y0, x1, y1); an optional
    `colour` attribute tints each outline."""

    navigateTo = Signal(QPointF)                 # image coordinates

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(80)          # the class list gets the room instead
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pixmap = None
        self._image_size = (0, 0)
        self._view = QRectF()
        self._theme = {}
        self._shapes = []

    def set_theme(self, theme):
        self._theme = dict(theme)
        self.update()

    def set_image(self, pixmap, image_size) -> None:
        if pixmap is None or pixmap.isNull():
            self._pixmap = None
        else:
            self._pixmap = pixmap.scaled(
                self.width() * 2 or 320, self.height() * 2,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
        self._image_size = tuple(image_size or (0, 0))
        self.update()

    def set_view(self, rect: QRectF, shapes=None) -> None:
        self._view = QRectF(rect)
        self._shapes = list(shapes or [])
        self.update()

    def _draw_rect(self) -> QRectF:
        w, h = self._image_size
        if not w or not h:
            return QRectF()
        available = QRectF(4, 4, self.width() - 8, self.height() - 8)
        scale = min(available.width() / w, available.height() / h)
        width, height = w * scale, h * scale
        return QRectF(available.center().x() - width / 2.0,
                      available.center().y() - height / 2.0, width, height)

    def mousePressEvent(self, event):
        self._navigate(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._navigate(event)

    def _navigate(self, event) -> None:
        area = self._draw_rect()
        if area.isEmpty():
            return
        w, h = self._image_size
        x = (event.position().x() - area.left()) / area.width() * w
        y = (event.position().y() - area.top()) / area.height() * h
        self.navigateTo.emit(QPointF(max(0.0, min(float(w), x)),
                                     max(0.0, min(float(h), y))))

    def paintEvent(self, event):
        theme = self._theme or {}
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        area = self._draw_rect()
        if self._pixmap is None or area.isEmpty():
            painter.setPen(QPen(qcolor(theme.get("muted", "#6f7784"))))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "-")
            painter.end()
            return

        painter.drawPixmap(area, self._pixmap, QRectF(self._pixmap.rect()))
        w, h = self._image_size
        scale_x = area.width() / float(w)
        scale_y = area.height() / float(h)

        accent = theme.get("accent", "#df5e3b")
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for shape in self._shapes:
            if not getattr(shape, "visible", True):
                continue
            painter.setPen(QPen(qcolor(getattr(shape, "colour", None) or accent), 1))
            x0, y0, x1, y1 = shape.bounds
            painter.drawRect(QRectF(area.left() + x0 * scale_x,
                                    area.top() + y0 * scale_y,
                                    max(1.0, (x1 - x0) * scale_x),
                                    max(1.0, (y1 - y0) * scale_y)))

        if not self._view.isEmpty():
            view = QRectF(area.left() + self._view.left() * scale_x,
                          area.top() + self._view.top() * scale_y,
                          self._view.width() * scale_x,
                          self._view.height() * scale_y)
            shade = QColor(0, 0, 0, 90)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(shade))
            for piece in (QRectF(area.left(), area.top(), area.width(),
                                 max(0.0, view.top() - area.top())),
                          QRectF(area.left(), view.bottom(), area.width(),
                                 max(0.0, area.bottom() - view.bottom())),
                          QRectF(area.left(), view.top(),
                                 max(0.0, view.left() - area.left()),
                                 view.height()),
                          QRectF(view.right(), view.top(),
                                 max(0.0, area.right() - view.right()),
                                 view.height())):
                if piece.width() > 0 and piece.height() > 0:
                    painter.drawRect(piece)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(qcolor(theme.get("onAccent", "#ffffff")), 1.4))
            painter.drawRect(view)

        painter.setPen(QPen(qcolor(theme.get("border", "#333a45")), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(area)
        painter.end()
