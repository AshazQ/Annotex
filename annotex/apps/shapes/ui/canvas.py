"""The LabelImg Shapes canvas.

One widget owns the shapes of the current image and every gesture on them.
Zoom, pan and the screen/image maths come from the suite's ImageViewport.
Shapes live in image pixels; screen positions are derived on every paint.

Drawing a shape does not add it: the canvas emits `shapeDrawn` with a shape
that has no class yet, and the window gives it one and calls `add_shape`.
The canvas never touches the disk.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QFontMetrics, QPainter,
                           QPen, QPixmap, QPolygonF)

from annotex.ui.palette import CANVAS, qcolor, readable_on
from annotex.ui.viewport import ImageViewport

from ..config import (KIND_CIRCLE, KIND_FREEHAND, KIND_OBB, MAX_POINTS,
                      MAX_SHAPES_PER_IMAGE, MIN_POINTS, MIN_SIZE, POINT_KINDS)
from ..core import geometry as geo
from ..core.model import Shape

# tools
T_SELECT = "select"
T_POLYGON = "polygon"
T_OBB = "obb"
T_CIRCLE = "circle"
T_ELLIPSE = "ellipse"
T_FREEHAND = "freehand"
T_PAN = "pan"
DRAW_TOOLS = (T_POLYGON, T_OBB, T_CIRCLE, T_ELLIPSE, T_FREEHAND)

TOOL_CURSORS = {
    T_SELECT: Qt.CursorShape.ArrowCursor,
    T_POLYGON: Qt.CursorShape.CrossCursor,
    T_OBB: Qt.CursorShape.CrossCursor,
    T_CIRCLE: Qt.CursorShape.CrossCursor,
    T_ELLIPSE: Qt.CursorShape.CrossCursor,
    T_FREEHAND: Qt.CursorShape.CrossCursor,
    T_PAN: Qt.CursorShape.OpenHandCursor,
}

# drags
D_NONE = ""
D_PAN = "pan"
D_MOVE = "move"
D_VERTEX = "vertex"
D_HANDLE = "handle"
D_ROTATE = "rotate"
D_MARQUEE = "marquee"
D_NEW = "new"
D_FREEHAND = "freehand"

HANDLE_NAMES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")
HANDLE_PICK = 7.0
VERTEX_PICK = 7.0
EDGE_PICK = 6.0
CLOSE_PICK = 12.0
ROTATE_OFFSET = 26.0


class ShapeCanvas(ImageViewport):
    shapesChanged = Signal(str)          # history label
    selectionChanged = Signal()
    statusMessage = Signal(str, str)     # text, level
    shapeDrawn = Signal(object)          # a Shape still without a class
    editLabelRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.shapes = []
        self.selection = set()
        self.tool = T_SELECT

        self._drag = D_NONE
        self._drag_index = -1
        self._drag_vertex = -1
        self._drag_handle = ""
        self._drag_origin = QPointF()
        self._drag_start = QPointF()
        self._drag_shapes = []
        self._drag_moved = False
        self._marquee = QRectF()
        self._draft = []                 # polygon / freehand points (QPointF, image)
        self._new = None                 # (start, current) image points
        self._hover_vertex = None
        self._hover_handle = ""
        self._hover_shape = -1
        self._space_pan = False

        self.show_crosshair = True
        self.show_labels = True
        self.fill_opacity = 22
        self.line_width = 2
        self.curve_segments = 64
        self.read_only = False

        self._colour_provider = None
        self._colours = dict(CANVAS)
        self._label_font = QFont()
        self._label_font.setPointSizeF(max(8.0, self._label_font.pointSizeF() - 0.5))
        self._label_font.setBold(True)

    # ══════════════════════════════════════════════════════
    # CONTENT
    # ══════════════════════════════════════════════════════
    def set_options(self, **kw) -> None:
        for key, value in kw.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.update()

    def set_theme(self, theme: dict) -> None:
        super().set_theme(theme)
        self._colours["selected"] = theme.get("accent", CANVAS["selected"])
        self.update()

    def set_colour_provider(self, provider) -> None:
        self._colour_provider = provider
        self.update()

    def colour_for(self, shape) -> QColor:
        if self._colour_provider is not None and shape.label:
            try:
                return qcolor(self._colour_provider(shape.label))
            except Exception:
                pass
        return qcolor(self._colours["shape"])

    def load_image(self, pixmap: QPixmap | None, shapes=None) -> None:
        self.shapes = [s.copy() for s in (shapes or [])]
        self.selection.clear()
        self._cancel_interaction()
        self.set_pixmap(pixmap)
        self.selectionChanged.emit()

    def set_shapes(self, shapes, keep_selection: bool = False) -> None:
        self.shapes = [s.copy() for s in (shapes or [])]
        if keep_selection:
            self.selection = {i for i in self.selection if i < len(self.shapes)}
        else:
            self.selection.clear()
        self._cancel_interaction()
        self.update()
        self.selectionChanged.emit()

    def snapshot(self):
        return [s.copy() for s in self.shapes]

    def is_drawing(self) -> bool:
        return bool(self._draft) or self._new is not None

    # ══════════════════════════════════════════════════════
    # TOOLS & SELECTION
    # ══════════════════════════════════════════════════════
    def set_tool(self, tool: str) -> None:
        if tool not in TOOL_CURSORS:
            return
        if tool != self.tool:
            self.cancel_draft(quiet=True)
        self.tool = tool
        if tool != T_SELECT:
            self.clear_selection()
        self.setCursor(QCursor(TOOL_CURSORS[tool]))
        self.update()

    def _effective_tool(self) -> str:
        return T_PAN if self._space_pan else self.tool

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

    def select_indices(self, indices) -> None:
        self.selection = {i for i in indices if 0 <= i < len(self.shapes)}
        self.update()
        self.selectionChanged.emit()

    def select_all(self) -> None:
        self.select_indices(i for i, s in enumerate(self.shapes) if s.visible and not s.locked)

    def selected_indices(self):
        return sorted(i for i in self.selection if 0 <= i < len(self.shapes))

    def selected_shapes(self):
        return [self.shapes[i] for i in self.selected_indices()]

    def zoom_to_selection(self) -> None:
        shapes = self.selected_shapes() or self.shapes
        if not shapes:
            self.fit_to_view()
            return
        bounds = [s.bounds for s in shapes]
        rect = QRectF(QPointF(min(b[0] for b in bounds), min(b[1] for b in bounds)),
                      QPointF(max(b[2] for b in bounds), max(b[3] for b in bounds)))
        self.zoom_to_rect(rect.adjusted(-10, -10, 10, 10))

    # ══════════════════════════════════════════════════════
    # HIT TESTING
    # ══════════════════════════════════════════════════════
    def _pickable(self, index: int) -> bool:
        shape = self.shapes[index]
        return shape.visible and not shape.locked

    def _widget_point(self, point):
        return self.to_widget(point[0], point[1])

    def _screen_outline(self, shape) -> QPolygonF:
        return QPolygonF([self._widget_point(p) for p in shape.outline(self.curve_segments)])

    def _handle_points(self, index):
        """{name: widget point} for the resize handles of a parametric shape."""
        shape = self.shapes[index]
        if not shape.parametric:
            return {}
        hw, hh = shape.w / 2.0, shape.h / 2.0
        local = {"nw": (-hw, -hh), "n": (0.0, -hh), "ne": (hw, -hh), "e": (hw, 0.0),
                 "se": (hw, hh), "s": (0.0, hh), "sw": (-hw, hh), "w": (-hw, 0.0)}
        names = ("n", "e", "s", "w") if shape.kind == KIND_CIRCLE else HANDLE_NAMES
        return {name: self._widget_point(shape.from_local(*local[name])) for name in names}

    def _rotate_point(self, index):
        """(anchor, handle) in widget coordinates, or None for a circle."""
        shape = self.shapes[index]
        if shape.kind == KIND_CIRCLE:
            return None
        if shape.parametric:
            centre = self._widget_point((shape.cx, shape.cy))
            top = self._widget_point(shape.from_local(0.0, -shape.h / 2.0))
            dx, dy = top.x() - centre.x(), top.y() - centre.y()
            length = math.hypot(dx, dy)
            if length < 1e-6:
                dx, dy, length = 0.0, -1.0, 1.0
            return top, QPointF(top.x() + dx / length * ROTATE_OFFSET,
                                top.y() + dy / length * ROTATE_OFFSET)
        x0, y0, x1, y1 = shape.bounds
        top = self.to_widget((x0 + x1) / 2.0, y0)
        return top, QPointF(top.x(), top.y() - ROTATE_OFFSET)

    def _handle_at(self, pos: QPointF):
        for i in sorted(self.selection, reverse=True):
            if not (0 <= i < len(self.shapes)) or not self._pickable(i):
                continue
            spot = self._rotate_point(i)
            if spot is not None and QLineF(spot[1], pos).length() <= HANDLE_PICK:
                return (i, "rotate")
            for name, point in self._handle_points(i).items():
                if QLineF(point, pos).length() <= HANDLE_PICK:
                    return (i, name)
        return None

    def _vertex_at(self, pos: QPointF):
        order = sorted(range(len(self.shapes)), key=lambda i: (i not in self.selection, -i))
        for i in order:
            shape = self.shapes[i]
            if not self._pickable(i) or shape.kind not in POINT_KINDS:
                continue
            if i not in self.selection and i != self._hover_shape:
                continue
            for j, point in enumerate(shape.points):
                if QLineF(self._widget_point(point), pos).length() <= VERTEX_PICK:
                    return (i, j)
        return None

    def _edge_at(self, pos: QPointF):
        best, best_distance = None, EDGE_PICK
        for i, shape in enumerate(self.shapes):
            if not self._pickable(i) or shape.kind not in POINT_KINDS:
                continue
            points = [self._widget_point(p) for p in shape.points]
            for j in range(len(points)):
                a, b = points[j], points[(j + 1) % len(points)]
                distance = geo.point_segment_distance(pos.x(), pos.y(), a.x(), a.y(), b.x(), b.y())
                if distance < best_distance:
                    best, best_distance = (i, j + 1), distance
        return best

    def _shape_at(self, pos: QPointF) -> int:
        point = self.to_image(pos, clamp=False)
        for i in reversed(range(len(self.shapes))):
            if self._pickable(i) and self.shapes[i].contains(point.x(), point.y()):
                return i
        return -1

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
            self._drag = D_PAN
            self._drag_origin = pos
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            return
        if button == Qt.MouseButton.RightButton:
            if self._draft and self.tool == T_POLYGON:
                self.finish_draft()
            return
        if button != Qt.MouseButton.LeftButton:
            return
        if self.read_only:
            self.statusMessage.emit("This folder is open read-only", "warning")
            return

        tool = self.tool
        image = self.to_image(pos)
        if tool == T_POLYGON:
            self._add_draft_point(pos)
            return
        if tool in (T_OBB, T_CIRCLE, T_ELLIPSE):
            self._new = (image, QPointF(image))
            self._drag = D_NEW
            return
        if tool == T_FREEHAND:
            self._draft = [image]
            self._drag = D_FREEHAND
            return

        # ── select tool ───────────────────────────────────
        handle = self._handle_at(pos)
        if handle is not None:
            index, name = handle
            self._drag_shapes = self.snapshot()
            self._drag_index = index
            self._drag_handle = name
            self._drag_start = self.to_image(pos, clamp=False)
            self._drag = D_ROTATE if name == "rotate" else D_HANDLE
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
            self._drag_start = self.to_image(pos, clamp=False)
            self._drag_shapes = self.snapshot()
            self.update()
            return

        self._drag = D_MARQUEE
        self._drag_origin = pos
        self._marquee = QRectF(pos, pos)
        if not (mods & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)):
            self.clear_selection()
        self.update()

    def mouseMoveEvent(self, event):
        pos = QPointF(event.position())
        if self.has_image():
            image = self.to_image(pos, clamp=False)
            self.cursorMoved.emit(int(image.x()), int(image.y()))

        drag = self._drag
        if drag == D_PAN:
            self._offset += pos - self._drag_origin
            self._drag_origin = pos
            self.viewChanged.emit()
            self.update()
            return
        if drag == D_NEW and self._new is not None:
            self._new = (self._new[0], self.to_image(pos))
            self.update()
            return
        if drag == D_FREEHAND:
            point = self.to_image(pos)
            if not self._draft or QLineF(self._draft[-1], point).length() * self._scale > 2.0:
                self._draft.append(point)
            self.update()
            return
        if drag == D_MARQUEE:
            self._marquee = QRectF(self._drag_origin, pos).normalized()
            self.update()
            return
        if drag == D_VERTEX:
            self._move_vertex(pos)
            return
        if drag == D_MOVE:
            self._move_selection(pos)
            return
        if drag == D_HANDLE:
            self._resize(pos, event.modifiers())
            return
        if drag == D_ROTATE:
            self._rotate(pos, event.modifiers())
            return

        if self.tool == T_SELECT and self.has_image():
            self._update_hover(pos)
        elif self.tool in DRAW_TOOLS:
            self.update()

    def mouseReleaseEvent(self, event):
        drag = self._drag
        if drag == D_PAN:
            self._drag = D_NONE
            self.setCursor(QCursor(TOOL_CURSORS[self._effective_tool()]))
            return
        if drag == D_NEW:
            self._commit_new(event.modifiers())
            return
        if drag == D_FREEHAND:
            self._commit_freehand()
            return
        if drag == D_MARQUEE:
            self._commit_marquee(event.modifiers())
            return
        if drag in (D_VERTEX, D_MOVE, D_HANDLE, D_ROTATE):
            self._drag = D_NONE
            if self._drag_moved:
                labels = {D_VERTEX: "Move point", D_MOVE: "Move shape",
                          D_HANDLE: "Resize shape", D_ROTATE: "Rotate shape"}
                self.shapesChanged.emit(labels[drag])
            self._drag_shapes = []
            self._drag_index = self._drag_vertex = -1
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
        if edge is not None:
            index, position = edge
            shape = self.shapes[index]
            if len(shape.points) >= MAX_POINTS:
                self.statusMessage.emit("That shape already has the most points allowed", "warning")
                return
            point = self.to_image(pos)
            shape.points.insert(position, (point.x(), point.y()))
            self.selection = {index}
            self.shapesChanged.emit("Add point")
            self.selectionChanged.emit()
            self.update()
            return
        index = self._shape_at(pos)
        if index >= 0:
            self.select_index(index)
            self.editLabelRequested.emit()

    def leaveEvent(self, event):
        self._hover_vertex = None
        self._hover_handle = ""
        self._hover_shape = -1
        self.update()
        super().leaveEvent(event)

    # ── gestures ──────────────────────────────────────────
    def _update_hover(self, pos: QPointF) -> None:
        handle = self._handle_at(pos)
        shape = self._shape_at(pos)
        self._hover_shape = shape
        vertex = None if handle else self._vertex_at(pos)
        name = handle[1] if handle else ""
        self._hover_handle, self._hover_vertex = name, vertex
        if name == "rotate":
            cursor = Qt.CursorShape.CrossCursor
        elif name:
            cursor = Qt.CursorShape.SizeAllCursor
        elif vertex is not None:
            cursor = Qt.CursorShape.PointingHandCursor
        elif shape >= 0:
            cursor = Qt.CursorShape.SizeAllCursor
        else:
            cursor = Qt.CursorShape.ArrowCursor
        self.setCursor(QCursor(cursor))
        self.update()

    def _move_vertex(self, pos: QPointF) -> None:
        if not (0 <= self._drag_index < len(self.shapes)):
            return
        shape = self.shapes[self._drag_index]
        if not (0 <= self._drag_vertex < len(shape.points)):
            return
        point = self.to_image(pos)
        shape.points[self._drag_vertex] = (point.x(), point.y())
        self._drag_moved = True
        self.update()

    def _move_selection(self, pos: QPointF) -> None:
        current = self.to_image(pos, clamp=False)
        dx = current.x() - self._drag_start.x()
        dy = current.y() - self._drag_start.y()
        if not dx and not dy:
            return
        width, height = self.image_size
        for i in (self.selection or {self._drag_index}):
            if 0 <= i < len(self.shapes) and i < len(self._drag_shapes):
                self.shapes[i] = self._drag_shapes[i].translated(dx, dy, width, height)
        self._drag_moved = True
        self.update()

    def _resize(self, pos: QPointF, mods) -> None:
        index = self._drag_index
        if not (0 <= index < len(self.shapes)) or index >= len(self._drag_shapes):
            return
        base = self._drag_shapes[index]
        point = self.to_image(pos, clamp=False)
        if base.kind == KIND_CIRCLE:
            radius = math.hypot(point.x() - base.cx, point.y() - base.cy)
            self.shapes[index] = base.with_radius(radius)
        else:
            lx, ly = base.to_local(point.x(), point.y())
            x0, x1 = -base.w / 2.0, base.w / 2.0
            y0, y1 = -base.h / 2.0, base.h / 2.0
            name = self._drag_handle
            if "w" in name:
                x0 = min(lx, x1 - MIN_SIZE)
            if "e" in name:
                x1 = max(lx, x0 + MIN_SIZE)
            if "n" in name:
                y0 = min(ly, y1 - MIN_SIZE)
            if "s" in name:
                y1 = max(ly, y0 + MIN_SIZE)
            if mods & Qt.KeyboardModifier.ShiftModifier and len(name) == 2 and base.h > 0:
                ratio = base.w / base.h
                height = abs(x1 - x0) / ratio
                if "n" in name:
                    y0 = y1 - height
                else:
                    y1 = y0 + height
            self.shapes[index] = base.with_local_box(x0, y0, x1, y1)
        self._drag_moved = True
        self.update()

    def _rotate(self, pos: QPointF, mods) -> None:
        index = self._drag_index
        if not (0 <= index < len(self.shapes)) or index >= len(self._drag_shapes):
            return
        base = self._drag_shapes[index]
        cx, cy = base.centroid
        start = math.atan2(self._drag_start.y() - cy, self._drag_start.x() - cx)
        point = self.to_image(pos, clamp=False)
        degrees = math.degrees(math.atan2(point.y() - cy, point.x() - cx) - start)
        if mods & Qt.KeyboardModifier.ShiftModifier:
            if base.parametric:
                degrees = round((base.angle + degrees) / 15.0) * 15.0 - base.angle
            else:
                degrees = round(degrees / 15.0) * 15.0
        self.shapes[index] = base.rotated(degrees)
        self._drag_moved = True
        self.update()

    def _commit_marquee(self, mods) -> None:
        self._drag = D_NONE
        rect, self._marquee = self._marquee, QRectF()
        if rect.width() < 3 and rect.height() < 3:
            self.update()
            return
        area = QRectF(self.to_image(rect.topLeft(), clamp=False),
                      self.to_image(rect.bottomRight(), clamp=False)).normalized()
        picked = set()
        for i, shape in enumerate(self.shapes):
            if self._pickable(i):
                x0, y0, x1, y1 = shape.bounds
                if area.intersects(QRectF(QPointF(x0, y0), QPointF(x1, y1))):
                    picked.add(i)
        additive = bool(mods & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier))
        self.selection = (self.selection | picked) if additive else picked
        self.selectionChanged.emit()
        self.update()

    # ══════════════════════════════════════════════════════
    # DRAWING
    # ══════════════════════════════════════════════════════
    def _add_draft_point(self, pos: QPointF) -> None:
        if len(self._draft) >= MIN_POINTS:
            first = self._widget_point((self._draft[0].x(), self._draft[0].y()))
            if QLineF(first, pos).length() < CLOSE_PICK:
                self.finish_draft()
                return
        if len(self._draft) >= MAX_POINTS:
            self.statusMessage.emit("Point limit reached - press Enter to close the shape", "warning")
            return
        self._draft.append(self.to_image(pos))
        count = len(self._draft)
        self.statusMessage.emit("Point %d%s" % (count, "  ·  click the first point, press Enter "
                                                "or right-click to close" if count >= MIN_POINTS
                                                else ""), "info")
        self.update()

    def draft_shape(self, mods=Qt.KeyboardModifier.NoModifier):
        """The shape the current box / circle / ellipse drag would make."""
        if self._new is None:
            return None
        start, end = self._new
        if self.tool == T_CIRCLE:
            radius = math.hypot(end.x() - start.x(), end.y() - start.y())
            return Shape.circle("", start.x(), start.y(), radius)
        cx, cy = (start.x() + end.x()) / 2.0, (start.y() + end.y()) / 2.0
        w, h = abs(end.x() - start.x()), abs(end.y() - start.y())
        if mods & Qt.KeyboardModifier.ShiftModifier:
            w = h = max(w, h)
        if self.tool == T_OBB:
            return Shape.obb("", cx, cy, w, h, 0.0)
        return Shape.ellipse("", cx, cy, w, h, 0.0)

    def _commit_new(self, mods) -> None:
        self._drag = D_NONE
        shape = self.draft_shape(mods)
        self._new = None
        self.update()
        if shape is None:
            return
        if shape.w < MIN_SIZE * 2 or shape.h < MIN_SIZE * 2:
            self.statusMessage.emit("Drag to size the shape", "warning")
            return
        self.shapeDrawn.emit(shape)

    def _commit_freehand(self) -> None:
        self._drag = D_NONE
        points = [(p.x(), p.y()) for p in self._draft]
        self._draft = []
        self.update()
        if len(points) < MIN_POINTS:
            return
        tolerance = max(0.75, 1.5 / max(self._scale, 0.05))
        simplified = geo.simplify(points, tolerance)
        if len(simplified) < MIN_POINTS:
            self.statusMessage.emit("Draw a larger outline", "warning")
            return
        self.shapeDrawn.emit(Shape.polygon("", simplified, KIND_FREEHAND))

    def finish_draft(self) -> bool:
        points = [(p.x(), p.y()) for p in self._draft]
        self._draft = []
        self.update()
        if len(points) < MIN_POINTS:
            if points:
                self.statusMessage.emit("A polygon needs at least %d points" % MIN_POINTS, "warning")
            return False
        self.shapeDrawn.emit(Shape.polygon("", points))
        return True

    def cancel_draft(self, quiet=False) -> bool:
        if self._draft or self._new is not None:
            self._draft = []
            self._new = None
            self._drag = D_NONE
            if not quiet:
                self.statusMessage.emit("Shape discarded", "info")
            self.update()
            return True
        return False

    def undo_draft_point(self) -> bool:
        if not self._draft or self.tool != T_POLYGON:
            return False
        self._draft.pop()
        self.update()
        return True

    def _cancel_interaction(self) -> None:
        self._drag = D_NONE
        self._draft = []
        self._new = None
        self._marquee = QRectF()
        self._drag_shapes = []
        self._hover_vertex = None
        self._hover_handle = ""
        self._hover_shape = -1

    # ══════════════════════════════════════════════════════
    # OPERATIONS
    # ══════════════════════════════════════════════════════
    def add_shape(self, shape: Shape, label: str = "Draw shape") -> bool:
        if len(self.shapes) >= MAX_SHAPES_PER_IMAGE:
            self.statusMessage.emit("This image already has the most shapes allowed", "warning")
            return False
        width, height = self.image_size
        clean, messages = shape.validated(width, height)
        if clean is None:
            self.statusMessage.emit("Shape not added: %s" % "; ".join(messages), "danger")
            return False
        self.shapes.append(clean)
        self.selection = {len(self.shapes) - 1}
        self.shapesChanged.emit(label)
        self.selectionChanged.emit()
        self.update()
        return True

    def add_shapes(self, shapes, label="Add shapes") -> int:
        width, height = self.image_size
        added = []
        for shape in shapes:
            if len(self.shapes) >= MAX_SHAPES_PER_IMAGE:
                break
            clean, _messages = shape.validated(width, height)
            if clean is not None:
                self.shapes.append(clean)
                added.append(len(self.shapes) - 1)
        if added:
            self.selection = set(added)
            self.shapesChanged.emit(label)
            self.selectionChanged.emit()
            self.update()
        return len(added)

    def delete_vertex(self, index: int, vertex: int) -> None:
        shape = self.shapes[index]
        if len(shape.points) <= MIN_POINTS:
            self.statusMessage.emit("A shape needs at least %d points - delete the shape instead"
                                    % MIN_POINTS, "warning")
            return
        shape.points.pop(vertex)
        self._hover_vertex = None
        self.selection = {index}
        self.shapesChanged.emit("Delete point")
        self.selectionChanged.emit()
        self.update()

    def delete_selected(self) -> int:
        indices = set(self.selected_indices())
        if not indices:
            return 0
        self.shapes = [s for i, s in enumerate(self.shapes) if i not in indices]
        self.selection.clear()
        self.shapesChanged.emit("Delete shape" if len(indices) == 1 else "Delete shapes")
        self.selectionChanged.emit()
        self.update()
        return len(indices)

    def duplicate_selected(self) -> int:
        chosen = self.selected_shapes()
        if not chosen:
            return 0
        width, height = self.image_size
        shift = max(8.0, min(width or 100, height or 100) * 0.02)
        start = len(self.shapes)
        for shape in chosen:
            self.shapes.append(shape.translated(shift, shift, width, height))
        self.selection = set(range(start, len(self.shapes)))
        self.shapesChanged.emit("Duplicate shape")
        self.selectionChanged.emit()
        self.update()
        return len(chosen)

    def clear_all(self) -> int:
        count = len(self.shapes)
        if not count:
            return 0
        self.shapes = []
        self.selection.clear()
        self.shapesChanged.emit("Clear all shapes")
        self.selectionChanged.emit()
        self.update()
        return count

    def nudge_selected(self, dx, dy) -> bool:
        if not self.selection:
            return False
        width, height = self.image_size
        for i in self.selected_indices():
            self.shapes[i] = self.shapes[i].translated(dx, dy, width, height)
        self.shapesChanged.emit("Nudge shape")
        self.update()
        return True

    def rotate_selected(self, degrees) -> bool:
        indices = [i for i in self.selected_indices() if self.shapes[i].kind != KIND_CIRCLE]
        if not indices:
            return False
        for i in indices:
            self.shapes[i] = self.shapes[i].rotated(degrees)
        self.shapesChanged.emit("Rotate shape")
        self.update()
        return True

    def relabel(self, indices, label) -> int:
        changed = 0
        for i in indices:
            if 0 <= i < len(self.shapes) and self.shapes[i].label != label:
                self.shapes[i].label = label
                changed += 1
        if changed:
            self.shapesChanged.emit("Change class")
            self.update()
        return changed

    def set_locked(self, indices, value) -> None:
        for i in indices:
            if 0 <= i < len(self.shapes):
                self.shapes[i].locked = bool(value)
        if value:
            self.selection -= set(indices)
        self.selectionChanged.emit()
        self.update()

    def set_visible(self, indices, value) -> None:
        for i in indices:
            if 0 <= i < len(self.shapes):
                self.shapes[i].visible = bool(value)
        if not value:
            self.selection -= set(indices)
        self.selectionChanged.emit()
        self.update()

    # ══════════════════════════════════════════════════════
    # KEYBOARD
    # ══════════════════════════════════════════════════════
    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Space and not event.isAutoRepeat() and not self._draft:
            self._space_pan = True
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._draft:
            self.finish_draft()
            return
        if key == Qt.Key.Key_Escape:
            if self.cancel_draft():
                return
            if self.selection:
                self.clear_selection()
                return
        if key == Qt.Key.Key_Backspace and self.undo_draft_point():
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat() and self._space_pan:
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

    def _paint_shapes(self, painter) -> None:
        painter.setFont(self._label_font)
        metrics = QFontMetrics(self._label_font)
        selected_colour = qcolor(self._colours["selected"])
        for index, shape in enumerate(self.shapes):
            if not shape.visible:
                continue
            selected = index in self.selection
            colour = self.colour_for(shape)
            polygon = self._screen_outline(shape)
            pen = QPen(selected_colour if selected else colour,
                       self.line_width + (1 if selected else 0))
            pen.setCosmetic(True)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            if shape.locked:
                pen.setStyle(Qt.PenStyle.DashLine)
            fill = QColor(colour)
            fill.setAlpha(int(255 * max(0, min(100, self.fill_opacity)) / 100.0))
            painter.setPen(pen)
            painter.setBrush(QBrush(fill))
            painter.drawPolygon(polygon)

            if not shape.locked and shape.kind in POINT_KINDS and (selected or index == self._hover_shape):
                self._paint_vertices(painter, index, shape, selected, colour)
            if selected and not shape.locked:
                self._paint_handles(painter, index)
            if self.show_labels:
                self._paint_chip(painter, metrics, shape, polygon, colour, selected)

    def _paint_vertices(self, painter, index, shape, selected, colour) -> None:
        dense = len(shape.points) > 80 and not selected
        if dense:
            return
        for j, point in enumerate(shape.points):
            hot = self._hover_vertex == (index, j)
            radius = 5.0 if hot else (3.8 if selected else 2.6)
            painter.setPen(QPen(qcolor(self._colours["vertexHot"]) if hot else colour, 1.4))
            painter.setBrush(QBrush(qcolor(self._colours["vertexHot"] if hot else self._colours["vertex"])))
            painter.drawEllipse(self._widget_point(point), radius, radius)

    def _paint_handles(self, painter, index) -> None:
        accent = qcolor(self._colours["selected"])
        spot = self._rotate_point(index)
        if spot is not None:
            anchor, handle = spot
            guide = QPen(accent, 1.3)
            guide.setStyle(Qt.PenStyle.DotLine)
            painter.setPen(guide)
            painter.drawLine(anchor, handle)
            painter.setPen(QPen(accent, 1.6))
            painter.setBrush(QBrush(qcolor(self._colours["vertexHot"] if self._hover_handle == "rotate"
                                           else self._colours["handle"])))
            painter.drawEllipse(handle, 5.5, 5.5)
        shape = self.shapes[index]
        if shape.parametric:
            painter.setPen(QPen(accent, 1.6))
            for name, point in self._handle_points(index).items():
                hot = self._hover_handle == name
                painter.setBrush(QBrush(qcolor(self._colours["vertexHot"] if hot else self._colours["handle"])))
                size = 5.5 if hot else 4.5
                painter.drawRect(QRectF(point.x() - size, point.y() - size, size * 2, size * 2))
            centre = self._widget_point((shape.cx, shape.cy))
            painter.drawLine(QPointF(centre.x() - 4, centre.y()), QPointF(centre.x() + 4, centre.y()))
            painter.drawLine(QPointF(centre.x(), centre.y() - 4), QPointF(centre.x(), centre.y() + 4))

    def _paint_chip(self, painter, metrics, shape, polygon, colour, selected) -> None:
        text = shape.label or "?"
        if shape.locked:
            text += "  (locked)"
        rect = polygon.boundingRect()
        width = metrics.horizontalAdvance(text) + 10
        height = metrics.height() + 4
        x = rect.center().x() - width / 2.0
        y = rect.top() - height - 4
        if y < 2:
            y = rect.top() + 4
        chip = QRectF(x, y, width, height)
        background = qcolor(self._colours["selected"]) if selected else QColor(colour)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(background))
        painter.drawRoundedRect(chip, 4, 4)
        painter.setPen(QPen(QColor(readable_on(background.name()))))
        painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_draft(self, painter) -> None:
        colour = qcolor(self._colours["drawing"])
        pen = QPen(colour, self.line_width)
        pen.setCosmetic(True)
        if self._new is not None:
            shape = self.draft_shape()
            if shape is not None:
                fill = QColor(colour)
                fill.setAlpha(45)
                painter.setPen(pen)
                painter.setBrush(QBrush(fill))
                painter.drawPolygon(self._screen_outline(shape))
                if shape.kind == KIND_CIRCLE:
                    start = self._widget_point((shape.cx, shape.cy))
                    painter.drawLine(start, self._widget_point((self._new[1].x(), self._new[1].y())))
                text = shape.describe()
                anchor = self._widget_point((self._new[1].x(), self._new[1].y())) + QPointF(10, 16)
                painter.setPen(QPen(qcolor(self._colours["labelShadow"], 190)))
                painter.drawText(anchor + QPointF(1, 1), text)
                painter.setPen(QPen(qcolor(self._colours["label"])))
                painter.drawText(anchor, text)
            return
        if not self._draft:
            return
        points = [self._widget_point((p.x(), p.y())) for p in self._draft]
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF(points))
        if self.tool != T_POLYGON:
            return
        cursor = QPointF(self.mapFromGlobal(QCursor.pos()))
        if self.rect().contains(cursor.toPoint()):
            painter.setPen(QPen(colour, 1, Qt.PenStyle.DashLine))
            painter.drawLine(points[-1], cursor)
            if len(points) >= MIN_POINTS:
                painter.drawLine(cursor, points[0])
                if QLineF(points[0], cursor).length() < CLOSE_PICK:
                    painter.setPen(QPen(qcolor(self._colours["snap"]), 2))
                    painter.drawEllipse(points[0], 11, 11)
        painter.setPen(QPen(colour, 1.5))
        for i, point in enumerate(points):
            painter.setBrush(QBrush(qcolor(self._colours["snap"] if i == 0 else self._colours["drawing"])))
            painter.drawEllipse(point, 5.0 if i == 0 else 3.5, 5.0 if i == 0 else 3.5)

    def _paint_marquee(self, painter) -> None:
        if self._marquee.isEmpty():
            return
        colour = qcolor(self._colours["marquee"])
        fill = QColor(colour)
        fill.setAlpha(38)
        painter.setPen(QPen(colour, 1, Qt.PenStyle.DashLine))
        painter.setBrush(QBrush(fill))
        painter.drawRect(self._marquee)

    def _paint_crosshair(self, painter) -> None:
        if not self.show_crosshair or self.tool not in DRAW_TOOLS:
            return
        cursor = self.mapFromGlobal(QCursor.pos())
        if not self.rect().contains(cursor):
            return
        painter.setPen(QPen(qcolor(self._colours["guide"]), 1, Qt.PenStyle.DashLine))
        painter.drawLine(cursor.x(), 0, cursor.x(), self.height())
        painter.drawLine(0, cursor.y(), self.width(), cursor.y())
