"""The image viewport every annotation canvas in the suite is built on.

It owns the picture and the view - zoom, pan, fit, the maths between screen
and image pixels, and drawing only the visible part of the image - and
nothing else.  Tools subclass it and add their own shapes and gestures, so
zooming feels identical in every tool and a fix here fixes all of them.

All geometry a subclass stores should be in original image pixels; screen
coordinates are derived on every paint, so zooming can never move an
annotation off its pixels.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QWidget

from . import design
from .palette import qcolor

ZOOM_MIN = 0.05
ZOOM_MAX = 32.0
ZOOM_STEP = 1.15

# 50 is neutral.  Above brightens, below darkens (an Overlay blend, the same
# response LabelImg's brightness control has always had).
BRIGHTNESS_NEUTRAL = 50


def _clamp(value, low, high):
    if low > high:
        return low
    return low if value < low else (high if value > high else value)


_PAINT_FAULTS = set()


def report_paint_fault(where: str) -> None:
    """A fault while drawing is written to the console once and then swallowed.

    A repaint happens many times a second; letting one bad frame raise would
    either bury the screen in dialogs or, on some Qt builds, end the process.
    Neither is acceptable when somebody is halfway through a batch."""
    import traceback
    text = traceback.format_exc()
    key = "%s|%s" % (where, text.strip().splitlines()[-1] if text else "")
    if key in _PAINT_FAULTS:
        return
    _PAINT_FAULTS.add(key)
    try:
        import sys
        sys.stderr.write("%s could not be drawn completely:\n%s" % (where, text))
    except Exception:
        pass


class ImageViewport(QWidget):
    """A zoomable, pannable image.  Subclass it to add shapes."""

    zoomChanged = Signal(float)
    cursorMoved = Signal(int, int)
    viewChanged = Signal()

    zoom_min = ZOOM_MIN
    zoom_max = ZOOM_MAX
    zoom_step = ZOOM_STEP

    # to_image(clamp=True) keeps points inside [0, size-1] by default.
    # LabelImg's files have always allowed a box edge to sit exactly on the
    # image border (x == width), so its canvas widens the range by one.
    clamp_inclusive = False

    placeholder_text = "No image loaded"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMinimumSize(320, 240)

        self.pixmap = None
        self.image_size = (0, 0)

        self._scale = 1.0
        self._fit_scale = 1.0
        self._offset = QPointF(0.0, 0.0)
        self._void = QColor("#101319")
        self.brightness = BRIGHTNESS_NEUTRAL

    # ══════════════════════════════════════════════════════
    # CONTENT
    # ══════════════════════════════════════════════════════
    def set_theme(self, theme: dict) -> None:
        self._void = qcolor(theme.get("canvasVoid", "#101319"))
        self.update()

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        """Show a new picture (None clears it) and fit it to the view."""
        self.pixmap = pixmap if pixmap is not None and not pixmap.isNull() else None
        self.image_size = ((self.pixmap.width(), self.pixmap.height())
                           if self.pixmap else (0, 0))
        self.fit_to_view()

    def has_image(self) -> bool:
        return self.pixmap is not None

    def set_brightness(self, value) -> None:
        self.brightness = int(_clamp(int(value), 0, 100))
        self.update()

    # ══════════════════════════════════════════════════════
    # VIEW MATHS
    # ══════════════════════════════════════════════════════
    def _transform(self) -> QTransform:
        t = QTransform()
        t.translate(self._offset.x(), self._offset.y())
        t.scale(self._scale, self._scale)
        return t

    def to_widget(self, x, y) -> QPointF:
        return QPointF(x * self._scale + self._offset.x(),
                       y * self._scale + self._offset.y())

    def to_image(self, pos, clamp: bool = True) -> QPointF:
        x = (pos.x() - self._offset.x()) / max(self._scale, 1e-9)
        y = (pos.y() - self._offset.y()) / max(self._scale, 1e-9)
        if clamp and self.image_size[0]:
            edge = 0 if self.clamp_inclusive else 1
            x = _clamp(x, 0, self.image_size[0] - edge)
            y = _clamp(y, 0, self.image_size[1] - edge)
        return QPointF(x, y)

    def image_rect(self) -> QRectF:
        w, h = self.image_size
        return QRectF(self._offset.x(), self._offset.y(),
                      w * self._scale, h * self._scale)

    def visible_image_rect(self) -> QRectF:
        """The part of the image currently on screen, in image pixels."""
        w, h = self.image_size
        if not w:
            return QRectF()
        top_left = self.to_image(QPointF(0, 0), clamp=False)
        bottom_right = self.to_image(QPointF(self.width(), self.height()),
                                     clamp=False)
        rect = QRectF(top_left, bottom_right).normalized()
        return rect.intersected(QRectF(0, 0, w, h))

    @property
    def scale(self) -> float:
        return self._scale

    def zoom_percent(self) -> float:
        return self._scale * 100.0

    def is_fitted(self) -> bool:
        return abs(self._scale - self._fit_scale) < 1e-6

    def fit_to_view(self) -> None:
        w, h = self.image_size
        if not w or not h or self.width() < 8 or self.height() < 8:
            self._scale = self._fit_scale = 1.0
            self._offset = QPointF(0, 0)
            self.update()
            return
        margin = 16
        sx = (self.width() - margin * 2) / float(w)
        sy = (self.height() - margin * 2) / float(h)
        self._fit_scale = max(min(sx, sy), 1e-6)
        self._scale = self._fit_scale
        self._center()
        self.zoomChanged.emit(self.zoom_percent())
        self.viewChanged.emit()
        self.update()

    def fit_to_width(self) -> None:
        w, h = self.image_size
        if not w or self.width() < 8:
            return
        scale = _clamp((self.width() - 32) / float(w), self.zoom_min,
                       self.zoom_max)
        self._scale = scale
        self._offset = QPointF((self.width() - w * scale) / 2.0, 16.0)
        self.zoomChanged.emit(self.zoom_percent())
        self.viewChanged.emit()
        self.update()

    def _center(self) -> None:
        w, h = self.image_size
        self._offset = QPointF((self.width() - w * self._scale) / 2.0,
                               (self.height() - h * self._scale) / 2.0)

    def set_zoom(self, scale, anchor: QPointF | None = None) -> None:
        if not self.has_image():
            return
        scale = _clamp(float(scale), self.zoom_min, self.zoom_max)
        if abs(scale - self._scale) < 1e-9:
            return
        if anchor is None:
            anchor = QPointF(self.width() / 2.0, self.height() / 2.0)
        before = self.to_image(anchor, clamp=False)
        self._scale = scale
        self._offset = QPointF(anchor.x() - before.x() * scale,
                               anchor.y() - before.y() * scale)
        self.zoomChanged.emit(self.zoom_percent())
        self.viewChanged.emit()
        self.update()

    def zoom_in(self) -> None:
        self.set_zoom(self._scale * self.zoom_step)

    def zoom_out(self) -> None:
        self.set_zoom(self._scale / self.zoom_step)

    def zoom_to_rect(self, rect: QRectF, padding: float = 40.0) -> None:
        """Frame an image-space rectangle."""
        if not self.has_image() or rect.isEmpty():
            return
        avail_w = max(1.0, self.width() - padding * 2)
        avail_h = max(1.0, self.height() - padding * 2)
        scale = _clamp(min(avail_w / rect.width(), avail_h / rect.height()),
                       self.zoom_min, self.zoom_max)
        self._scale = scale
        centre = rect.center()
        self._offset = QPointF(self.width() / 2.0 - centre.x() * scale,
                               self.height() / 2.0 - centre.y() * scale)
        self.zoomChanged.emit(self.zoom_percent())
        self.viewChanged.emit()
        self.update()

    def pan_by(self, dx, dy) -> None:
        self._offset += QPointF(dx, dy)
        self.viewChanged.emit()
        self.update()

    def center_on(self, image_point: QPointF) -> None:
        self._offset = QPointF(
            self.width() / 2.0 - image_point.x() * self._scale,
            self.height() / 2.0 - image_point.y() * self._scale)
        self.viewChanged.emit()
        self.update()

    # ══════════════════════════════════════════════════════
    # EVENTS
    # ══════════════════════════════════════════════════════
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.has_image() and self.is_fitted():
            self.fit_to_view()
        else:
            self.viewChanged.emit()

    def wheelEvent(self, event):
        if not self.has_image():
            return
        delta = event.angleDelta().y()
        if not delta:
            return
        factor = self.zoom_step if delta > 0 else 1.0 / self.zoom_step
        self.set_zoom(self._scale * factor, QPointF(event.position()))
        event.accept()

    # ══════════════════════════════════════════════════════
    # PAINTING
    # ══════════════════════════════════════════════════════
    def _paint_placeholder(self, painter) -> None:
        painter.setPen(QPen(qcolor("#5a616d")))
        font = design.font("body", self.font())
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                         self.placeholder_text)

    def _paint_image(self, painter) -> None:
        source = self.visible_image_rect()
        if source.isEmpty():
            return
        if self.brightness == BRIGHTNESS_NEUTRAL:
            # Draw only the visible region so a 12 MP photo at 30x costs
            # nothing.
            target = QRectF(self.to_widget(source.left(), source.top()),
                            self.to_widget(source.right(), source.bottom()))
            painter.drawPixmap(target, self.pixmap, source)
            return

        region = source.toAlignedRect().intersected(self.pixmap.rect())
        if region.isEmpty():
            return
        piece = self.pixmap.copy(region)
        blend = QPainter(piece)
        blend.setCompositionMode(QPainter.CompositionMode.CompositionMode_Overlay)
        strength = int(self.brightness / 100.0 * 255 + 0.5)
        blend.fillRect(piece.rect(), QColor(strength, strength, strength))
        blend.end()
        target = QRectF(self.to_widget(region.left(), region.top()),
                        self.to_widget(region.left() + region.width(),
                                       region.top() + region.height()))
        painter.drawPixmap(target, piece, QRectF(piece.rect()))
