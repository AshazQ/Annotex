"""The annotation canvas.

One widget owns the shapes and every interaction with them.  The picture,
zoom, pan and the screen/image maths come from the suite's ImageViewport, so
navigating an image feels the same in every tool.  All shape data lives in
original image pixel coordinates; screen coordinates are derived on every
paint, so zooming can never move an ROI off its pixels.

The widget never writes to disk and never touches the store.  It reports what
changed through `shapesChanged`, and the window decides what to persist.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QFontMetrics,
                           QPainter, QPen, QPixmap, QPolygonF)

from annotex.ui.viewport import ImageViewport

from ....ui import design
from ..config import (EDGE_TOLERANCE, MAX_POINTS_PER_POLY, MAX_POLYS_PER_IMAGE,
                      MIN_POINTS, SHAPE_CIRCLE, SHAPE_POLYGON, SHAPE_RECT,
                      VERTEX_RADIUS, ZOOM_MAX, ZOOM_MIN, ZOOM_STEP)
from ..core import geometry as geo
from ..core.model import Shape
from .palette import CANVAS, qcolor

# tools
T_SELECT = "select"
T_POLYGON = "polygon"
T_RECT = "rect"
T_CIRCLE = "circle"
T_LASSO = "lasso"
T_PAN = "pan"

TOOL_CURSORS = {
    T_SELECT: Qt.CursorShape.ArrowCursor,
    T_POLYGON: Qt.CursorShape.CrossCursor,
    T_RECT: Qt.CursorShape.CrossCursor,
    T_CIRCLE: Qt.CursorShape.CrossCursor,
    T_LASSO: Qt.CursorShape.CrossCursor,
    T_PAN: Qt.CursorShape.OpenHandCursor,
}

# drag kinds
D_NONE = ""
D_PAN = "pan"
D_MOVE = "move"
D_VERTEX = "vertex"
D_BOX = "box"
D_ROTATE = "rotate"
D_MARQUEE = "marquee"
D_NEW_BOX = "new_box"
D_LASSO = "lasso"

HANDLE_ORDER = ("nw", "n", "ne", "e", "se", "s", "sw", "w")


class Canvas(ImageViewport):
    """Image + shapes + every direct-manipulation gesture."""

    shapesChanged = Signal(str)          # history label
    selectionChanged = Signal()
    statusMessage = Signal(str, str)     # text, level
    toolFinished = Signal(str)           # tool auto-returning to select

    zoom_min = ZOOM_MIN
    zoom_max = ZOOM_MAX
    zoom_step = ZOOM_STEP

    def __init__(self, parent=None):
        super().__init__(parent)

        # content
        self.shapes = []
        self.selection = set()

        # interaction
        self.tool = T_SELECT
        self._drag = D_NONE
        self._drag_index = -1
        self._drag_vertex = -1
        self._drag_handle = ""
        self._drag_origin = QPointF()
        self._drag_start_img = QPointF()
        self._drag_shapes = []
        self._drag_bounds = None
        self._drag_moved = False
        self._marquee = QRectF()
        self._draft = []                 # in-progress polygon / lasso points
        self._draft_kind = SHAPE_POLYGON
        self._new_box = None             # (start, current) while dragging a box
        self._hover_vertex = None
        self._hover_shape = -1
        self._hover_handle = ""
        self._cursor_img = QPointF()
        self._snapped = False
        self._space_pan = False

        # options
        self.show_crosshair = True
        self.show_coordinates = True
        self.snap_to_edges = True
        self.snap_to_shapes = True
        self.fill_opacity = 28
        self.line_width = 2
        self.read_only = False

        self._colours = dict(CANVAS)
        self._label_font = design.font("label")

    # ══════════════════════════════════════════════════════
    # CONTENT
    # ══════════════════════════════════════════════════════
    def set_options(self, **kw) -> None:
        for key, value in kw.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.update()

    def load_image(self, pixmap: QPixmap | None, shapes=None) -> None:
        """Show a new image.  Passing None clears the canvas."""
        self.shapes = list(shapes or [])
        self.selection.clear()
        self._cancel_interaction()
        self.set_pixmap(pixmap)
        self.selectionChanged.emit()

    def set_shapes(self, shapes, keep_selection: bool = False) -> None:
        """Replace the shape list (used by undo / redo and bulk actions)."""
        self.shapes = list(shapes or [])
        if not keep_selection:
            self.selection.clear()
        else:
            self.selection = {i for i in self.selection if i < len(self.shapes)}
        self._cancel_interaction()
        self.update()
        self.selectionChanged.emit()

    def snapshot(self):
        return [s.copy() for s in self.shapes]

    def is_drawing(self) -> bool:
        return bool(self._draft) or self._new_box is not None

    # ══════════════════════════════════════════════════════
    # VIEW
    # ══════════════════════════════════════════════════════
    def zoom_to_selection(self) -> None:
        rect = self._selection_rect()
        if rect is None:
            self.statusMessage.emit("Select an ROI first", "warning")
            return
        self.zoom_to_rect(rect)

    def zoom_to_all_shapes(self) -> None:
        if not self.shapes:
            self.fit_to_view()
            return
        bounds = [s.bounds for s in self.shapes]
        rect = QRectF(QPointF(min(b[0] for b in bounds), min(b[1] for b in bounds)),
                      QPointF(max(b[2] for b in bounds), max(b[3] for b in bounds)))
        self.zoom_to_rect(rect.adjusted(-8, -8, 8, 8))

    # ══════════════════════════════════════════════════════
    # TOOLS
    # ══════════════════════════════════════════════════════
    def set_tool(self, tool: str) -> None:
        if tool not in TOOL_CURSORS:
            return
        if self.tool != tool:
            self.finish_draft(quiet=True)
        self.tool = tool
        if tool != T_SELECT:
            self.clear_selection()
        self.setCursor(QCursor(TOOL_CURSORS[tool]))
        self.update()

    def _effective_tool(self) -> str:
        return T_PAN if self._space_pan else self.tool

    # ══════════════════════════════════════════════════════
    # SELECTION
    # ══════════════════════════════════════════════════════
    def clear_selection(self) -> None:
        if self.selection:
            self.selection.clear()
            self.update()
            self.selectionChanged.emit()

    def select_index(self, index: int, additive: bool = False) -> None:
        if not (0 <= index < len(self.shapes)):
            return
        if additive:
            self.selection.symmetric_difference_update({index})
        else:
            self.selection = {index}
        self.update()
        self.selectionChanged.emit()

    def select_all(self) -> None:
        pickable = {i for i, s in enumerate(self.shapes)
                    if s.visible and not s.locked}
        if pickable != self.selection:
            self.selection = pickable
            self.update()
            self.selectionChanged.emit()

    def selected_shapes(self):
        return [self.shapes[i] for i in sorted(self.selection)
                if 0 <= i < len(self.shapes)]

    def _selection_rect(self):
        shapes = self.selected_shapes() or self.shapes
        if not shapes:
            return None
        bounds = [s.bounds for s in shapes]
        return QRectF(QPointF(min(b[0] for b in bounds), min(b[1] for b in bounds)),
                      QPointF(max(b[2] for b in bounds), max(b[3] for b in bounds)))

    # ══════════════════════════════════════════════════════
    # HIT TESTING
    # ══════════════════════════════════════════════════════
    def _pickable(self, index: int) -> bool:
        shape = self.shapes[index]
        return shape.visible and not shape.locked

    def _vertex_at(self, pos: QPointF):
        order = sorted(range(len(self.shapes)),
                       key=lambda i: (i not in self.selection, -i))
        for i in order:
            if not self._pickable(i):
                continue
            shape = self.shapes[i]
            if shape.is_editable_as_box():
                continue
            for j, (x, y) in enumerate(shape.points):
                if (self.to_widget(x, y) - pos).manhattanLength() <= VERTEX_RADIUS * 2:
                    if QLineF(self.to_widget(x, y), pos).length() <= VERTEX_RADIUS:
                        return (i, j)
        return None

    def _handle_rects(self, index: int):
        """Screen rectangles for the eight box handles of a rect/circle."""
        if not (0 <= index < len(self.shapes)):
            return {}
        x0, y0, x1, y1 = self.shapes[index].bounds
        tl = self.to_widget(x0, y0)
        br = self.to_widget(x1, y1)
        rect = QRectF(tl, br).normalized()
        size = 9.0
        cx, cy = rect.center().x(), rect.center().y()
        spots = {
            "nw": (rect.left(), rect.top()), "n": (cx, rect.top()),
            "ne": (rect.right(), rect.top()), "e": (rect.right(), cy),
            "se": (rect.right(), rect.bottom()), "s": (cx, rect.bottom()),
            "sw": (rect.left(), rect.bottom()), "w": (rect.left(), cy),
        }
        return {name: QRectF(x - size / 2, y - size / 2, size, size)
                for name, (x, y) in spots.items()}

    def _rotate_handle(self, index: int):
        if not (0 <= index < len(self.shapes)):
            return None
        x0, y0, x1, y1 = self.shapes[index].bounds
        top = self.to_widget((x0 + x1) / 2.0, y0)
        spot = QPointF(top.x(), top.y() - 26)
        return QRectF(spot.x() - 6, spot.y() - 6, 12, 12)

    def _handle_at(self, pos: QPointF):
        for i in sorted(self.selection):
            if not (0 <= i < len(self.shapes)) or not self._pickable(i):
                continue
            spot = self._rotate_handle(i)
            if spot is not None and spot.contains(pos):
                return (i, "rotate")
            if self.shapes[i].is_editable_as_box():
                for name, rect in self._handle_rects(i).items():
                    if rect.contains(pos):
                        return (i, name)
        return None

    def _edge_at(self, pos: QPointF):
        best, best_d = None, EDGE_TOLERANCE + 1.0
        for i, shape in enumerate(self.shapes):
            if not self._pickable(i) or shape.is_editable_as_box():
                continue
            pts = shape.points
            n = len(pts)
            if n < 2:
                continue
            for vi in range(n):
                a = self.to_widget(*pts[vi])
                b = self.to_widget(*pts[(vi + 1) % n])
                d = geo.point_segment_distance(pos.x(), pos.y(),
                                               a.x(), a.y(), b.x(), b.y())
                if d < best_d:
                    best_d, best = d, (i, vi + 1)
        return best

    def _shape_at(self, pos: QPointF):
        point = self.to_image(pos, clamp=False)
        for i in sorted(range(len(self.shapes)), reverse=True):
            if not self._pickable(i):
                continue
            if self.shapes[i].contains(point.x(), point.y()):
                return i
        return -1

    # ══════════════════════════════════════════════════════
    # SNAPPING
    # ══════════════════════════════════════════════════════
    def _snap(self, point: QPointF, exclude=-1):
        w, h = self.image_size
        tolerance = max(3.0, 7.0 / max(self._scale, 0.05))
        others = [s.points for i, s in enumerate(self.shapes)
                  if i != exclude and s.visible]
        x, y, hit = geo.snap_point(point.x(), point.y(), w, h, others,
                                   tolerance, self.snap_to_edges,
                                   self.snap_to_shapes)
        self._snapped = hit
        return QPointF(x, y)

    # ══════════════════════════════════════════════════════
    # MOUSE
    # ══════════════════════════════════════════════════════
    def mousePressEvent(self, event):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if not self.has_image():
            return
        pos = QPointF(event.position())
        button = event.button()
        mods = event.modifiers()
        self._drag_moved = False

        if button == Qt.MouseButton.MiddleButton or self._effective_tool() == T_PAN:
            self._begin_pan(pos)
            return

        if button == Qt.MouseButton.RightButton:
            if self._draft:
                self.finish_draft()
            return

        if button != Qt.MouseButton.LeftButton:
            return

        if self.read_only:
            self.statusMessage.emit("Read-only mode - editing is disabled",
                                    "warning")
            return

        tool = self.tool
        if tool == T_POLYGON:
            self._add_draft_point(pos)
            return
        if tool in (T_RECT, T_CIRCLE):
            start = self._snap(self.to_image(pos))
            self._new_box = (start, QPointF(start))
            self._draft_kind = SHAPE_RECT if tool == T_RECT else SHAPE_CIRCLE
            self._drag = D_NEW_BOX
            return
        if tool == T_LASSO:
            self._draft = [self.to_image(pos)]
            self._draft_kind = SHAPE_POLYGON
            self._drag = D_LASSO
            return

        # ── select tool ───────────────────────────────────
        handle = self._handle_at(pos)
        if handle is not None:
            index, name = handle
            self._begin_handle_drag(index, name, pos)
            return

        vertex = self._vertex_at(pos)
        if vertex is not None:
            index, vi = vertex
            if mods & Qt.KeyboardModifier.ControlModifier:
                self.delete_vertex(index, vi)
                return
            self._drag = D_VERTEX
            self._drag_index, self._drag_vertex = index, vi
            self._drag_shapes = self.snapshot()
            if index not in self.selection:
                self.selection = {index}
                self.selectionChanged.emit()
            self.update()
            return

        index = self._shape_at(pos)
        if index >= 0:
            additive = bool(mods & (Qt.KeyboardModifier.ShiftModifier
                                    | Qt.KeyboardModifier.ControlModifier))
            if additive:
                self.selection.symmetric_difference_update({index})
            elif index not in self.selection:
                self.selection = {index}
            self.selectionChanged.emit()
            self._drag = D_MOVE
            self._drag_index = index
            self._drag_start_img = self.to_image(pos, clamp=False)
            self._drag_shapes = self.snapshot()
            self.update()
            return

        # empty space: rubber-band select
        self._drag = D_MARQUEE
        self._drag_origin = pos
        self._marquee = QRectF(pos, pos)
        if not (mods & (Qt.KeyboardModifier.ShiftModifier
                        | Qt.KeyboardModifier.ControlModifier)):
            self.clear_selection()
        self.update()

    def mouseMoveEvent(self, event):
        pos = QPointF(event.position())
        if self.has_image():
            self._cursor_img = self.to_image(pos, clamp=False)
            if self.show_coordinates:
                self.cursorMoved.emit(int(self._cursor_img.x()),
                                      int(self._cursor_img.y()))

        if self._drag == D_PAN:
            delta = pos - self._drag_origin
            self._offset += delta
            self._drag_origin = pos
            self._drag_moved = True
            self.viewChanged.emit()
            self.update()
            return

        if self._drag == D_NEW_BOX and self._new_box is not None:
            self._new_box = (self._new_box[0], self._snap(self.to_image(pos)))
            self._drag_moved = True
            self.update()
            return

        if self._drag == D_LASSO:
            point = self.to_image(pos)
            if not self._draft or QLineF(self._draft[-1], point).length() > 1.5:
                self._draft.append(point)
            self._drag_moved = True
            self.update()
            return

        if self._drag == D_MARQUEE:
            self._marquee = QRectF(self._drag_origin, pos).normalized()
            self._drag_moved = True
            self.update()
            return

        if self._drag == D_VERTEX:
            self._move_vertex(pos)
            return

        if self._drag == D_MOVE:
            self._move_selection(pos)
            return

        if self._drag == D_BOX:
            self._resize_box(pos)
            return

        if self._drag == D_ROTATE:
            self._rotate_selection(pos)
            return

        # ── hover feedback ────────────────────────────────
        if self.tool == T_SELECT and self.has_image():
            self._update_hover(pos)
        elif self._draft:
            self.update()
        elif self.show_crosshair and self.tool in (T_POLYGON, T_RECT, T_CIRCLE,
                                                   T_LASSO):
            self.update()

    def mouseReleaseEvent(self, event):
        drag = self._drag

        if drag == D_PAN:
            self._drag = D_NONE
            self.setCursor(QCursor(TOOL_CURSORS[self._effective_tool()]))
            return

        if drag == D_NEW_BOX and self._new_box is not None:
            self._commit_new_box()
            return

        if drag == D_LASSO:
            self._commit_lasso()
            return

        if drag == D_MARQUEE:
            self._commit_marquee(event.modifiers())
            return

        if drag in (D_VERTEX, D_MOVE, D_BOX, D_ROTATE):
            self._drag = D_NONE
            if self._drag_moved:
                labels = {D_VERTEX: "Move vertex", D_MOVE: "Move ROI",
                          D_BOX: "Resize ROI", D_ROTATE: "Rotate ROI"}
                self.shapesChanged.emit(labels.get(drag, "Edit ROI"))
            self._drag_shapes = []
            self._drag_index = -1
            self._drag_vertex = -1
            self._drag_handle = ""
            self.update()
            return

        self._drag = D_NONE

    def mouseDoubleClickEvent(self, event):
        if not self.has_image() or self.read_only:
            return
        pos = QPointF(event.position())
        if self.tool == T_POLYGON and self._draft:
            self.finish_draft()
            return
        if self.tool != T_SELECT:
            return
        edge = self._edge_at(pos)
        if edge is None:
            return
        index, position = edge
        shape = self.shapes[index]
        if len(shape.points) >= MAX_POINTS_PER_POLY:
            self.statusMessage.emit(
                "That ROI already has the maximum number of points", "warning")
            return
        point = self.to_image(pos)
        shape.points.insert(position, (int(round(point.x())),
                                       int(round(point.y()))))
        if shape.kind == SHAPE_RECT:
            shape.kind = SHAPE_POLYGON       # no longer a four-corner box
        self.selection = {index}
        self._hover_vertex = (index, position)
        self.shapesChanged.emit("Add vertex")
        self.selectionChanged.emit()
        self.statusMessage.emit("Point added to ROI %d" % (index + 1), "good")
        self.update()

    def leaveEvent(self, event):
        self._hover_vertex = None
        self._hover_shape = -1
        self._hover_handle = ""
        self.update()
        super().leaveEvent(event)

    # ── gesture helpers ───────────────────────────────────
    def _begin_pan(self, pos: QPointF) -> None:
        self._drag = D_PAN
        self._drag_origin = pos
        self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))

    def _begin_handle_drag(self, index, name, pos) -> None:
        self._drag_shapes = self.snapshot()
        self._drag_index = index
        self._drag_handle = name
        self._drag_bounds = self.shapes[index].bounds
        self._drag_start_img = self.to_image(pos, clamp=False)
        self._drag = D_ROTATE if name == "rotate" else D_BOX

    def _update_hover(self, pos: QPointF) -> None:
        handle = self._handle_at(pos)
        vertex = None if handle else self._vertex_at(pos)
        shape = -1
        if handle is None and vertex is None:
            shape = self._shape_at(pos)

        handle_name = handle[1] if handle else ""
        if (handle_name, vertex, shape) == (self._hover_handle,
                                            self._hover_vertex,
                                            self._hover_shape):
            return
        self._hover_handle = handle_name
        self._hover_vertex = vertex
        self._hover_shape = shape

        cursors = {"nw": Qt.CursorShape.SizeFDiagCursor,
                   "se": Qt.CursorShape.SizeFDiagCursor,
                   "ne": Qt.CursorShape.SizeBDiagCursor,
                   "sw": Qt.CursorShape.SizeBDiagCursor,
                   "n": Qt.CursorShape.SizeVerCursor,
                   "s": Qt.CursorShape.SizeVerCursor,
                   "e": Qt.CursorShape.SizeHorCursor,
                   "w": Qt.CursorShape.SizeHorCursor}
        if handle_name == "rotate":
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        elif handle_name:
            self.setCursor(QCursor(cursors.get(handle_name,
                                               Qt.CursorShape.ArrowCursor)))
        elif vertex is not None:
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        elif shape >= 0:
            self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.update()

    def _move_vertex(self, pos: QPointF) -> None:
        if not (0 <= self._drag_index < len(self.shapes)):
            return
        shape = self.shapes[self._drag_index]
        if not (0 <= self._drag_vertex < len(shape.points)):
            return
        point = self._snap(self.to_image(pos), exclude=self._drag_index)
        shape.points[self._drag_vertex] = (int(round(point.x())),
                                           int(round(point.y())))
        self._drag_moved = True
        self.update()

    def _move_selection(self, pos: QPointF) -> None:
        current = self.to_image(pos, clamp=False)
        dx = current.x() - self._drag_start_img.x()
        dy = current.y() - self._drag_start_img.y()
        if not dx and not dy:
            return
        w, h = self.image_size
        targets = self.selection or {self._drag_index}
        for i in targets:
            if 0 <= i < len(self.shapes) and i < len(self._drag_shapes):
                self.shapes[i] = self._drag_shapes[i].translated(dx, dy, w, h)
        self._drag_moved = True
        self.update()

    def _resize_box(self, pos: QPointF) -> None:
        if not (0 <= self._drag_index < len(self.shapes)) or not self._drag_bounds:
            return
        x0, y0, x1, y1 = self._drag_bounds
        point = self.to_image(pos)
        name = self._drag_handle
        if "w" in name:
            x0 = point.x()
        if "e" in name:
            x1 = point.x()
        if "n" in name:
            y0 = point.y()
        if "s" in name:
            y1 = point.y()
        if abs(x1 - x0) < 2 or abs(y1 - y0) < 2:
            return
        w, h = self.image_size
        base = self._drag_shapes[self._drag_index]
        self.shapes[self._drag_index] = base.resized_box(x0, y0, x1, y1, w, h)
        self._drag_moved = True
        self.update()

    def _rotate_selection(self, pos: QPointF) -> None:
        if not (0 <= self._drag_index < len(self.shapes)):
            return
        base = self._drag_shapes[self._drag_index]
        cx, cy = base.centroid
        start = math.atan2(self._drag_start_img.y() - cy,
                           self._drag_start_img.x() - cx)
        point = self.to_image(pos, clamp=False)
        now = math.atan2(point.y() - cy, point.x() - cx)
        degrees = math.degrees(now - start)
        w, h = self.image_size
        self.shapes[self._drag_index] = base.rotated(degrees, w, h)
        self._drag_moved = True
        self.update()

    def _commit_marquee(self, mods) -> None:
        self._drag = D_NONE
        rect = self._marquee
        self._marquee = QRectF()
        if rect.width() < 3 and rect.height() < 3:
            self.update()
            return
        top_left = self.to_image(rect.topLeft(), clamp=False)
        bottom_right = self.to_image(rect.bottomRight(), clamp=False)
        area = QRectF(top_left, bottom_right).normalized()
        additive = bool(mods & (Qt.KeyboardModifier.ShiftModifier
                                | Qt.KeyboardModifier.ControlModifier))
        picked = set()
        for i, shape in enumerate(self.shapes):
            if not self._pickable(i):
                continue
            x0, y0, x1, y1 = shape.bounds
            if area.intersects(QRectF(QPointF(x0, y0), QPointF(x1, y1))):
                picked.add(i)
        self.selection = (self.selection | picked) if additive else picked
        self.selectionChanged.emit()
        if picked:
            self.statusMessage.emit("%d ROI(s) selected" % len(self.selection),
                                    "info")
        self.update()

    # ══════════════════════════════════════════════════════
    # DRAFTING
    # ══════════════════════════════════════════════════════
    def _add_draft_point(self, pos: QPointF) -> None:
        if len(self._draft) >= MIN_POINTS:
            first = self.to_widget(self._draft[0].x(), self._draft[0].y())
            if QLineF(first, pos).length() < 12.0:
                self.finish_draft()
                return
        if len(self._draft) >= MAX_POINTS_PER_POLY:
            self.statusMessage.emit(
                "Point limit reached (%d) - press Enter to close the shape"
                % MAX_POINTS_PER_POLY, "warning")
            return
        self._draft.append(self._snap(self.to_image(pos)))
        self._draft_kind = SHAPE_POLYGON
        count = len(self._draft)
        self.statusMessage.emit(
            "Point %d placed%s" % (count, "  ·  click the first point, press "
                                   "Enter or right-click to close"
                                   if count >= MIN_POINTS else ""), "info")
        self.update()

    def _commit_new_box(self) -> None:
        self._drag = D_NONE
        box = self._new_box
        self._new_box = None
        if box is None:
            return
        start, end = box
        if abs(end.x() - start.x()) < 3 or abs(end.y() - start.y()) < 3:
            self.statusMessage.emit("Drag to size the shape", "warning")
            self.update()
            return
        if self._draft_kind == SHAPE_RECT:
            shape = Shape.rect(start.x(), start.y(), end.x(), end.y())
        else:
            cx, cy = (start.x() + end.x()) / 2.0, (start.y() + end.y()) / 2.0
            shape = Shape.circle(cx, cy, abs(end.x() - start.x()) / 2.0,
                                 abs(end.y() - start.y()) / 2.0)
        self._append_shape(shape, "Draw %s" % self._draft_kind)

    def _commit_lasso(self) -> None:
        self._drag = D_NONE
        points = [(p.x(), p.y()) for p in self._draft]
        self._draft = []
        if len(points) < MIN_POINTS:
            self.update()
            return
        tolerance = max(1.5, 2.5 / max(self._scale, 0.05))
        simplified = geo.simplify_polygon(points, tolerance)
        self._append_shape(Shape.polygon(simplified), "Draw freehand")

    def finish_draft(self, quiet: bool = False) -> bool:
        """Close the polygon being drawn.  Returns True when one was added."""
        points = [(p.x(), p.y()) for p in self._draft]
        self._draft = []
        if len(points) < MIN_POINTS:
            if points and not quiet:
                self.statusMessage.emit(
                    "Need at least %d points to close a shape" % MIN_POINTS,
                    "warning")
            self.update()
            return False
        return self._append_shape(Shape.polygon(points), "Draw polygon")

    def cancel_draft(self) -> bool:
        if self._draft or self._new_box is not None:
            self._draft = []
            self._new_box = None
            self._drag = D_NONE
            self.statusMessage.emit("Shape discarded", "info")
            self.update()
            return True
        if self.selection:
            self.clear_selection()
            return True
        return False

    def undo_draft_point(self) -> bool:
        if not self._draft:
            return False
        self._draft.pop()
        self.statusMessage.emit("Last point removed", "info")
        self.update()
        return True

    def _append_shape(self, shape: Shape, label: str) -> bool:
        if len(self.shapes) >= MAX_POLYS_PER_IMAGE:
            self.statusMessage.emit(
                "This image already has %d ROIs, which is the limit"
                % MAX_POLYS_PER_IMAGE, "warning")
            self.update()
            return False
        width, height = self.image_size
        clean, messages = shape.validated(width, height)
        if clean is None:
            self.statusMessage.emit("ROI rejected: %s" % "; ".join(messages),
                                    "danger")
            self.update()
            return False
        self.shapes.append(clean)
        self.selection = {len(self.shapes) - 1}
        self.shapesChanged.emit(label)
        self.selectionChanged.emit()
        note = ("  (%s)" % "; ".join(messages)) if messages else ""
        self.statusMessage.emit(
            "ROI %d added%s" % (len(self.shapes), note),
            "warning" if messages else "good")
        self.update()
        return True

    def _cancel_interaction(self) -> None:
        self._drag = D_NONE
        self._draft = []
        self._new_box = None
        self._marquee = QRectF()
        self._drag_shapes = []
        self._hover_vertex = None
        self._hover_shape = -1
        self._hover_handle = ""

    # ══════════════════════════════════════════════════════
    # SHAPE OPERATIONS
    # ══════════════════════════════════════════════════════
    def delete_vertex(self, index: int, vertex: int) -> None:
        if not (0 <= index < len(self.shapes)):
            return
        shape = self.shapes[index]
        if shape.is_editable_as_box():
            self.statusMessage.emit(
                "A rectangle or circle is resized with its handles", "warning")
            return
        if len(shape.points) <= MIN_POINTS:
            self.statusMessage.emit(
                "An ROI needs at least %d points - delete the whole ROI instead"
                % MIN_POINTS, "warning")
            return
        shape.points.pop(vertex)
        self._hover_vertex = None
        self.selection = {index}
        self.shapesChanged.emit("Delete vertex")
        self.selectionChanged.emit()
        self.statusMessage.emit("Point removed from ROI %d" % (index + 1), "good")
        self.update()

    def delete_selected(self) -> bool:
        if not self.selection:
            self.statusMessage.emit("Select an ROI first", "warning")
            return False
        keep = [s for i, s in enumerate(self.shapes) if i not in self.selection]
        removed = len(self.shapes) - len(keep)
        self.shapes = keep
        self.selection.clear()
        self.shapesChanged.emit("Delete ROI" if removed == 1 else "Delete ROIs")
        self.selectionChanged.emit()
        self.statusMessage.emit("%d ROI(s) deleted" % removed, "good")
        self.update()
        return True

    def duplicate_selected(self) -> bool:
        if not self.selection:
            self.statusMessage.emit("Select an ROI first", "warning")
            return False
        width, height = self.image_size
        shift = max(8, int(round(min(width or 100, height or 100) * 0.02)))
        added = []
        for shape in self.selected_shapes():
            self.shapes.append(shape.translated(shift, shift, width, height))
            added.append(len(self.shapes) - 1)
        self.selection = set(added)
        self.shapesChanged.emit("Duplicate ROI")
        self.selectionChanged.emit()
        self.statusMessage.emit("%d ROI(s) duplicated" % len(added), "good")
        self.update()
        return True

    def clear_all(self) -> bool:
        if not self.shapes:
            self.statusMessage.emit("Nothing to clear", "info")
            return False
        count = len(self.shapes)
        self.shapes = []
        self.selection.clear()
        self._draft = []
        self.shapesChanged.emit("Clear all ROIs")
        self.selectionChanged.emit()
        self.statusMessage.emit("%d ROI(s) cleared - Ctrl+Z brings them back"
                                % count, "good")
        self.update()
        return True

    def nudge_selected(self, dx, dy) -> bool:
        if not self.selection:
            self.statusMessage.emit("Select an ROI first", "warning")
            return False
        width, height = self.image_size
        for i in sorted(self.selection):
            self.shapes[i] = self.shapes[i].translated(dx, dy, width, height)
        self.shapesChanged.emit("Nudge ROI")
        self.update()
        return True

    def set_selected_locked(self, locked: bool) -> None:
        for i in sorted(self.selection):
            self.shapes[i].locked = bool(locked)
        self.shapesChanged.emit("Lock ROI" if locked else "Unlock ROI")
        self.selectionChanged.emit()
        self.update()

    def set_shape_visible(self, index: int, visible: bool) -> None:
        if 0 <= index < len(self.shapes):
            self.shapes[index].visible = bool(visible)
            self.selectionChanged.emit()
            self.update()

    def set_shape_locked(self, index: int, locked: bool) -> None:
        if 0 <= index < len(self.shapes):
            self.shapes[index].locked = bool(locked)
            self.selectionChanged.emit()
            self.update()

    def add_shapes(self, shapes, label="Add ROIs") -> int:
        """Used by 'copy from previous image' and paste."""
        width, height = self.image_size
        room = MAX_POLYS_PER_IMAGE - len(self.shapes)
        added = []
        for shape in list(shapes)[:max(0, room)]:
            clean, _messages = shape.copy().validated(width, height)
            if clean is not None:
                self.shapes.append(clean)
                added.append(len(self.shapes) - 1)
        if added:
            self.selection = set(added)
            self.shapesChanged.emit(label)
            self.selectionChanged.emit()
            self.update()
        return len(added)

    def replace_vertex(self, index: int, vertex: int, x, y) -> None:
        """Numeric entry from the vertex inspector."""
        if not (0 <= index < len(self.shapes)):
            return
        shape = self.shapes[index]
        if not (0 <= vertex < len(shape.points)):
            return
        width, height = self.image_size
        shape.points[vertex] = (int(geo.clamp(x, 0, max(0, width - 1))),
                                int(geo.clamp(y, 0, max(0, height - 1))))
        self.shapesChanged.emit("Set vertex")
        self.update()

    # ── alignment ─────────────────────────────────────────
    def align_selected(self, mode: str) -> bool:
        shapes = self.selected_shapes()
        if len(shapes) < 2:
            self.statusMessage.emit("Select at least two ROIs to align",
                                    "warning")
            return False
        bounds = [s.bounds for s in shapes]
        width, height = self.image_size
        left = min(b[0] for b in bounds)
        right = max(b[2] for b in bounds)
        top = min(b[1] for b in bounds)
        bottom = max(b[3] for b in bounds)
        cx = (left + right) / 2.0
        cy = (top + bottom) / 2.0

        for i, index in enumerate(sorted(self.selection)):
            x0, y0, x1, y1 = bounds[i]
            dx = dy = 0.0
            if mode == "left":
                dx = left - x0
            elif mode == "right":
                dx = right - x1
            elif mode == "hcentre":
                dx = cx - (x0 + x1) / 2.0
            elif mode == "top":
                dy = top - y0
            elif mode == "bottom":
                dy = bottom - y1
            elif mode == "vcentre":
                dy = cy - (y0 + y1) / 2.0
            if dx or dy:
                self.shapes[index] = self.shapes[index].translated(dx, dy,
                                                                   width, height)
        self.shapesChanged.emit("Align ROIs")
        self.statusMessage.emit("Aligned %d ROIs" % len(shapes), "good")
        self.update()
        return True

    def distribute_selected(self, horizontal: bool = True) -> bool:
        indices = sorted(self.selection)
        if len(indices) < 3:
            self.statusMessage.emit(
                "Select at least three ROIs to distribute them", "warning")
            return False
        axis = 0 if horizontal else 1
        ordered = sorted(indices,
                         key=lambda i: self.shapes[i].centroid[axis])
        first = self.shapes[ordered[0]].centroid[axis]
        last = self.shapes[ordered[-1]].centroid[axis]
        step = (last - first) / float(len(ordered) - 1)
        width, height = self.image_size
        for position, index in enumerate(ordered[1:-1], start=1):
            target = first + step * position
            current = self.shapes[index].centroid[axis]
            delta = target - current
            self.shapes[index] = self.shapes[index].translated(
                delta if horizontal else 0, 0 if horizontal else delta,
                width, height)
        self.shapesChanged.emit("Distribute ROIs")
        self.statusMessage.emit("Distributed %d ROIs" % len(ordered), "good")
        self.update()
        return True

    def equalise_selected(self) -> bool:
        """Give every selected shape the size of the first one."""
        indices = sorted(self.selection)
        if len(indices) < 2:
            self.statusMessage.emit("Select at least two ROIs", "warning")
            return False
        rx0, ry0, rx1, ry1 = self.shapes[indices[0]].bounds
        ref_w, ref_h = max(rx1 - rx0, 1.0), max(ry1 - ry0, 1.0)
        width, height = self.image_size
        for index in indices[1:]:
            shape = self.shapes[index]
            x0, y0, x1, y1 = shape.bounds
            cur_w, cur_h = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
            cx, cy = shape.centroid
            self.shapes[index] = shape.scaled(cx, cy, ref_w / cur_w,
                                              ref_h / cur_h, width, height)
        self.shapesChanged.emit("Equalise ROIs")
        self.statusMessage.emit("Matched %d ROIs to the first" % len(indices),
                                "good")
        self.update()
        return True

    # ══════════════════════════════════════════════════════
    # KEYBOARD (only what belongs to the canvas itself)
    # ══════════════════════════════════════════════════════
    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pan = True
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._draft:
                self.finish_draft()
                return
        if key == Qt.Key.Key_Escape:
            if self.cancel_draft():
                return
        if key == Qt.Key.Key_Backspace and self._draft:
            self.undo_draft_point()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pan = False
            self.setCursor(QCursor(TOOL_CURSORS[self.tool]))
            return
        super().keyReleaseEvent(event)

    # ══════════════════════════════════════════════════════
    # PAINTING
    # ══════════════════════════════════════════════════════
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), self._void)

        if not self.has_image():
            self._paint_placeholder(painter)
            painter.end()
            return

        self._paint_image(painter)
        self._paint_shapes(painter)
        self._paint_draft(painter)
        self._paint_marquee(painter)
        self._paint_crosshair(painter)
        painter.end()

    def _shape_pen(self, index, shape):
        if not shape.visible:
            return None
        if shape.locked:
            colour = qcolor(self._colours["locked"])
        elif index in self.selection:
            colour = qcolor(self._colours["selected"])
        else:
            colour = qcolor(self._colours["shape"])
        width = self.line_width + (1 if index in self.selection else 0)
        pen = QPen(colour, width)
        pen.setCosmetic(True)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if shape.locked:
            pen.setStyle(Qt.PenStyle.DashLine)
        return pen

    def _paint_shapes(self, painter) -> None:
        font = self._label_font
        painter.setFont(font)
        metrics = QFontMetrics(font)

        for index, shape in enumerate(self.shapes):
            pen = self._shape_pen(index, shape)
            if pen is None:
                continue
            polygon = QPolygonF([self.to_widget(x, y) for x, y in shape.points])
            selected = index in self.selection

            fill = qcolor(self._colours["selectedFill"] if selected
                          else self._colours["shapeFill"])
            fill.setAlpha(int(255 * max(0, min(100, self.fill_opacity)) / 100.0))
            painter.setPen(pen)
            painter.setBrush(QBrush(fill) if len(polygon) >= 3
                             else Qt.BrushStyle.NoBrush)
            if len(polygon) >= 3:
                painter.drawPolygon(polygon)
            elif len(polygon) == 2:
                painter.drawPolyline(polygon)

            if shape.locked or not shape.visible:
                self._paint_label(painter, metrics, index, shape, polygon)
                continue

            if shape.is_editable_as_box():
                if selected:
                    self._paint_box_handles(painter, index)
            else:
                self._paint_vertices(painter, index, shape, polygon, selected)
            if selected:
                self._paint_rotate_handle(painter, index)
            self._paint_label(painter, metrics, index, shape, polygon)

    def _paint_vertices(self, painter, index, shape, polygon, selected) -> None:
        base = qcolor(self._colours["vertex"])
        edge = qcolor(self._colours["selected"] if selected
                      else self._colours["shape"])
        for vi, point in enumerate(polygon):
            hot = self._hover_vertex == (index, vi)
            radius = 5.5 if hot else (4.5 if selected else 3.0)
            painter.setPen(QPen(qcolor(self._colours["vertexHot"]) if hot
                                else edge, 1.6))
            painter.setBrush(QBrush(qcolor(self._colours["vertexHot"]) if hot
                                    else base))
            painter.drawEllipse(point, radius, radius)

    def _paint_box_handles(self, painter, index) -> None:
        painter.setPen(QPen(qcolor(self._colours["selected"]), 1.6))
        painter.setBrush(QBrush(qcolor(self._colours["handle"])))
        for name, rect in self._handle_rects(index).items():
            if self._hover_handle == name:
                painter.setBrush(QBrush(qcolor(self._colours["vertexHot"])))
                painter.drawRect(rect.adjusted(-1, -1, 1, 1))
                painter.setBrush(QBrush(qcolor(self._colours["handle"])))
            else:
                painter.drawRect(rect)

    def _paint_rotate_handle(self, painter, index) -> None:
        spot = self._rotate_handle(index)
        if spot is None:
            return
        x0, y0, x1, y1 = self.shapes[index].bounds
        top = self.to_widget((x0 + x1) / 2.0, y0)
        pen = QPen(qcolor(self._colours["selected"]), 1.4)
        pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.drawLine(top, spot.center())
        painter.setPen(QPen(qcolor(self._colours["selected"]), 1.6))
        painter.setBrush(QBrush(qcolor(
            self._colours["vertexHot"] if self._hover_handle == "rotate"
            else self._colours["handle"])))
        painter.drawEllipse(spot)

    def _paint_label(self, painter, metrics, index, shape, polygon) -> None:
        if polygon.isEmpty():
            return
        text = "ROI %d" % (index + 1)
        if shape.locked:
            text += "  (locked)"
        rect = polygon.boundingRect()
        anchor = QPointF(rect.center().x(), rect.top() - 7)
        width = metrics.horizontalAdvance(text)
        anchor.setX(anchor.x() - width / 2.0)
        if anchor.y() < 12:
            anchor.setY(rect.top() + 16)
        painter.setPen(QPen(qcolor(self._colours["labelShadow"], 190)))
        painter.drawText(anchor + QPointF(1, 1), text)
        painter.setPen(QPen(qcolor(self._colours["selected"]
                                   if index in self.selection
                                   else self._colours["label"])))
        painter.drawText(anchor, text)

    def _paint_draft(self, painter) -> None:
        colour = qcolor(self._colours["drawing"])
        if self._new_box is not None:
            start, end = self._new_box
            a = self.to_widget(start.x(), start.y())
            b = self.to_widget(end.x(), end.y())
            rect = QRectF(a, b).normalized()
            fill = QColor(colour)
            fill.setAlpha(50)
            painter.setPen(QPen(colour, self.line_width, Qt.PenStyle.SolidLine))
            painter.setBrush(QBrush(fill))
            if self._draft_kind == SHAPE_CIRCLE:
                painter.drawEllipse(rect)
            else:
                painter.drawRect(rect)
            self._paint_size_hint(painter, rect, start, end)
            return

        if not self._draft:
            return

        points = [self.to_widget(p.x(), p.y()) for p in self._draft]
        pen = QPen(colour, self.line_width)
        pen.setCosmetic(True)
        painter.setPen(pen)
        if self.tool == T_LASSO:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolyline(QPolygonF(points))
        else:
            painter.drawPolyline(QPolygonF(points))
            cursor = self.mapFromGlobal(QCursor.pos())
            if self.rect().contains(cursor):
                guide = QPen(colour, 1, Qt.PenStyle.DashLine)
                painter.setPen(guide)
                painter.drawLine(points[-1], QPointF(cursor))
                if len(points) >= MIN_POINTS:
                    painter.drawLine(QPointF(cursor), points[0])
                    if QLineF(points[0], QPointF(cursor)).length() < 12.0:
                        painter.setPen(QPen(qcolor(self._colours["snap"]), 2))
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawEllipse(points[0], 11, 11)
            painter.setPen(QPen(colour, 1.5))
            for i, point in enumerate(points):
                painter.setBrush(QBrush(qcolor(
                    self._colours["snap"] if i == 0 else self._colours["drawing"])))
                painter.drawEllipse(point, 5.0 if i == 0 else 3.5,
                                    5.0 if i == 0 else 3.5)

    def _paint_size_hint(self, painter, rect, start, end) -> None:
        text = "%d x %d" % (abs(int(end.x() - start.x())),
                            abs(int(end.y() - start.y())))
        painter.setPen(QPen(qcolor(self._colours["labelShadow"], 190)))
        painter.drawText(rect.bottomRight() + QPointF(9, 15), text)
        painter.setPen(QPen(qcolor(self._colours["label"])))
        painter.drawText(rect.bottomRight() + QPointF(8, 14), text)

    def _paint_marquee(self, painter) -> None:
        if self._marquee.isEmpty():
            return
        colour = qcolor(self._colours["marquee"])
        fill = QColor(colour)
        fill.setAlpha(38)
        pen = QPen(colour, 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QBrush(fill))
        painter.drawRect(self._marquee)

    def _paint_crosshair(self, painter) -> None:
        if not self.show_crosshair:
            return
        if self.tool not in (T_POLYGON, T_RECT, T_CIRCLE, T_LASSO):
            return
        cursor = self.mapFromGlobal(QCursor.pos())
        if not self.rect().contains(cursor):
            return
        pen = QPen(qcolor(self._colours["snap"] if self._snapped
                          else self._colours["guide"]), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(cursor.x(), 0, cursor.x(), self.height())
        painter.drawLine(0, cursor.y(), self.width(), cursor.y())
