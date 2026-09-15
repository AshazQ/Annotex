"""The box canvas.

Built on the suite's ImageViewport, so zooming and panning behave exactly as
they do in ROI Studio.  It owns the boxes on the current image and every
gesture on them - drawing, selecting, marquee, moving, resizing with eight
handles, snapping to the image border and to other boxes - and nothing else.

It never writes to disk and never decides a class on its own: a freshly drawn
box is handed to the window through `boxDrawn`, and the window labels it and
passes it back with add_box().
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QFontMetrics,
                           QPainter, QPen, QPolygonF)
from PySide6.QtWidgets import QApplication

from annotex.ui.palette import CANVAS, qcolor, readable_on
from annotex.ui.viewport import ImageViewport, report_paint_fault

from ..config import HANDLE_SIZE, MAX_BOXES_PER_IMAGE, MIN_BOX_SIDE, SNAP_PIXELS
from ..core.model import Box

T_SELECT = "select"
T_BOX = "box"
T_PAN = "pan"
T_AI = "ai"

TOOL_CURSORS = {
    T_SELECT: Qt.CursorShape.ArrowCursor,
    T_BOX: Qt.CursorShape.CrossCursor,
    T_PAN: Qt.CursorShape.OpenHandCursor,
    T_AI: Qt.CursorShape.PointingHandCursor,
}

# A click prompt and a drag prompt are told apart by this, in screen pixels.
AI_DRAG_PIXELS = 6.0

D_NONE = ""
D_PAN = "pan"
D_MOVE = "move"
D_RESIZE = "resize"
D_MARQUEE = "marquee"
D_NEW = "new"
D_AI = "ai"

HANDLE_CURSORS = {"nw": Qt.CursorShape.SizeFDiagCursor,
                  "se": Qt.CursorShape.SizeFDiagCursor,
                  "ne": Qt.CursorShape.SizeBDiagCursor,
                  "sw": Qt.CursorShape.SizeBDiagCursor,
                  "n": Qt.CursorShape.SizeVerCursor,
                  "s": Qt.CursorShape.SizeVerCursor,
                  "e": Qt.CursorShape.SizeHorCursor,
                  "w": Qt.CursorShape.SizeHorCursor}
OPPOSITE = {"nw": "se", "se": "nw", "ne": "sw", "sw": "ne"}


class BoxCanvas(ImageViewport):
    """Image + labelled boxes + every direct-manipulation gesture."""

    boxesChanged = Signal(str)               # history label
    selectionChanged = Signal()
    statusMessage = Signal(str, str)         # text, level
    boxDrawn = Signal(object)                # an unlabelled Box
    editLabelRequested = Signal(int)
    contextMenuRequested = Signal(object)    # global QPoint
    toolFinished = Signal(str)
    aiPromptChanged = Signal()               # the AI prompt was added to
    aiAccepted = Signal()                    # Enter / double-click on a proposal

    clamp_inclusive = True
    placeholder_text = "Open a folder of images to begin  ·  Ctrl+U"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.boxes = []
        self.selection = set()
        self.tool = T_SELECT

        self._drag = D_NONE
        self._drag_origin = QPointF()
        self._drag_start_img = QPointF()
        self._drag_boxes = []
        self._drag_index = -1
        self._drag_handle = ""
        self._drag_moved = False
        self._marquee = QRectF()
        self._new = None                     # (start, end) image points
        self._hover_index = -1
        self._hover_handle = ""
        self._snapped = False

        # AI (SAM) prompting
        self.ai_points = []                  # [(x, y, positive)] in image px
        self.ai_box = None                   # (x0, y0, x1, y1) in image px
        self.ai_preview = None               # proposed Box, not yet accepted
        self.ai_busy = False
        self._ai_anchor = None
        self._ai_negative = False

        # options
        self.show_crosshair = True
        self.show_coordinates = True
        self.snap_to_edges = True
        self.snap_to_boxes = True
        self.fill_opacity = 18
        self.line_width = 2
        self.show_labels = True
        self.draw_square = False
        self.read_only = False
        self.verified = False
        self.return_to_select = True

        self._colours = dict(CANVAS)
        self._good = QColor("#5cbf6b")
        self._colour_for = lambda _label: CANVAS["shape"]
        self._label_font = QFont()
        self._label_font.setPointSizeF(max(8.0, self._label_font.pointSizeF() - 0.5))
        self._label_font.setBold(True)

    # ══════════════════════════════════════════════════════
    # CONTENT
    # ══════════════════════════════════════════════════════
    def set_theme(self, theme: dict) -> None:
        self._good = qcolor(theme.get("good", "#5cbf6b"))
        super().set_theme(theme)

    def set_options(self, **kw) -> None:
        for key, value in kw.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.update()

    def set_colour_provider(self, provider) -> None:
        """`provider(label) -> '#rrggbb'`, normally the Class Manager colour."""
        self._colour_for = provider
        self.update()

    def load_image(self, pixmap, boxes=None) -> None:
        self.boxes = [box.copy() for box in (boxes or [])]
        self.selection.clear()
        self.clear_ai(quiet=True)
        self._cancel_interaction()
        self.set_pixmap(pixmap)
        self.selectionChanged.emit()

    def set_boxes(self, boxes, keep_selection: bool = False) -> None:
        self.boxes = [box.copy() for box in (boxes or [])]
        if keep_selection:
            self.selection = {i for i in self.selection if i < len(self.boxes)}
        else:
            self.selection.clear()
        self._cancel_interaction()
        self.update()
        self.selectionChanged.emit()

    def snapshot(self):
        return [box.copy() for box in self.boxes]

    def is_drawing(self) -> bool:
        return self._new is not None

    # ══════════════════════════════════════════════════════
    # TOOLS & SELECTION
    # ══════════════════════════════════════════════════════
    def set_tool(self, tool: str) -> None:
        if tool not in TOOL_CURSORS:
            return
        if tool != self.tool:
            self._new = None
            if self._drag == D_NEW:
                self._drag = D_NONE
            if T_AI in (tool, self.tool):
                self.clear_ai(quiet=True)
        self.tool = tool
        if tool in (T_BOX, T_AI):
            self.clear_selection()
        self.setCursor(QCursor(TOOL_CURSORS[tool]))
        self.update()

    def clear_selection(self) -> None:
        if self.selection:
            self.selection.clear()
            self.update()
            self.selectionChanged.emit()

    def select_index(self, index: int, additive: bool = False) -> None:
        if not (0 <= index < len(self.boxes)):
            return
        if additive:
            self.selection.symmetric_difference_update({index})
        else:
            self.selection = {index}
        self.update()
        self.selectionChanged.emit()

    def select_all(self) -> None:
        pickable = {i for i, box in enumerate(self.boxes)
                    if box.visible and not box.locked}
        if pickable != self.selection:
            self.selection = pickable
            self.update()
            self.selectionChanged.emit()

    def selected_indices(self):
        return sorted(i for i in self.selection if 0 <= i < len(self.boxes))

    def selected_boxes(self):
        return [self.boxes[i] for i in self.selected_indices()]

    # ══════════════════════════════════════════════════════
    # VIEW
    # ══════════════════════════════════════════════════════
    def _bounds_rect(self, boxes):
        if not boxes:
            return None
        return QRectF(QPointF(min(b.x0 for b in boxes), min(b.y0 for b in boxes)),
                      QPointF(max(b.x1 for b in boxes), max(b.y1 for b in boxes)))

    def zoom_to_selection(self) -> None:
        rect = self._bounds_rect(self.selected_boxes())
        if rect is None:
            self.statusMessage.emit("Select a box first", "warning")
            return
        self.zoom_to_rect(rect.adjusted(-8, -8, 8, 8))

    def zoom_to_all(self) -> None:
        rect = self._bounds_rect([b for b in self.boxes if b.visible])
        if rect is None:
            self.fit_to_view()
            return
        self.zoom_to_rect(rect.adjusted(-8, -8, 8, 8))

    # ══════════════════════════════════════════════════════
    # HIT TESTING & SNAPPING
    # ══════════════════════════════════════════════════════
    def _box_rect(self, box) -> QRectF:
        return QRectF(self.to_widget(box.x0, box.y0),
                      self.to_widget(box.x1, box.y1)).normalized()

    def _pickable(self, index: int) -> bool:
        box = self.boxes[index]
        return box.visible and not box.locked

    def _handle_rects(self, index: int):
        if not (0 <= index < len(self.boxes)):
            return {}
        rect = self._box_rect(self.boxes[index])
        size = HANDLE_SIZE
        cx, cy = rect.center().x(), rect.center().y()
        spots = {"nw": (rect.left(), rect.top()), "n": (cx, rect.top()),
                 "ne": (rect.right(), rect.top()), "e": (rect.right(), cy),
                 "se": (rect.right(), rect.bottom()), "s": (cx, rect.bottom()),
                 "sw": (rect.left(), rect.bottom()), "w": (rect.left(), cy)}
        return {name: QRectF(x - size / 2, y - size / 2, size, size)
                for name, (x, y) in spots.items()}

    def _handle_at(self, pos: QPointF):
        for index in sorted(self.selection, reverse=True):
            if not (0 <= index < len(self.boxes)) or not self._pickable(index):
                continue
            for name, rect in self._handle_rects(index).items():
                if rect.adjusted(-2, -2, 2, 2).contains(pos):
                    return index, name
        return None

    def _box_at(self, pos: QPointF) -> int:
        """The box under the cursor.  When boxes overlap the smallest one
        wins, so a helmet inside a person box can still be picked."""
        point = self.to_image(pos, clamp=False)
        margin = 3.0 / max(self._scale, 0.05)
        hits = []
        for index, box in enumerate(self.boxes):
            if not self._pickable(index):
                continue
            if (box.x0 - margin <= point.x() <= box.x1 + margin
                    and box.y0 - margin <= point.y() <= box.y1 + margin):
                hits.append((box.area, -index, index))
        return min(hits)[2] if hits else -1

    def _snap_targets(self, exclude=()):
        w, h = self.image_size
        xs, ys = [], []
        if self.snap_to_edges and w and h:
            xs += [0.0, float(w)]
            ys += [0.0, float(h)]
        if self.snap_to_boxes:
            for index, box in enumerate(self.boxes):
                if index in exclude or not box.visible:
                    continue
                xs += [box.x0, box.x1]
                ys += [box.y0, box.y1]
        return xs, ys

    def _tolerance(self) -> float:
        return SNAP_PIXELS / max(self._scale, 0.05)

    @staticmethod
    def _nearest(value, targets, tolerance):
        best, best_d = None, tolerance
        for target in targets:
            d = abs(value - target)
            if d <= best_d:
                best, best_d = target, d
        return best

    def _snap(self, point: QPointF, exclude=()) -> QPointF:
        xs, ys = self._snap_targets(exclude)
        tolerance = self._tolerance()
        sx = self._nearest(point.x(), xs, tolerance)
        sy = self._nearest(point.y(), ys, tolerance)
        self._snapped = sx is not None or sy is not None
        return QPointF(point.x() if sx is None else sx,
                       point.y() if sy is None else sy)

    def _square_active(self) -> bool:
        return self.draw_square or bool(
            QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)

    @staticmethod
    def _square(anchor: QPointF, point: QPointF) -> QPointF:
        """LabelImg's square rule: the shorter side wins."""
        size = min(abs(point.x() - anchor.x()), abs(point.y() - anchor.y()))
        dx = -1 if point.x() - anchor.x() < 0 else 1
        dy = -1 if point.y() - anchor.y() < 0 else 1
        return QPointF(anchor.x() + dx * size, anchor.y() + dy * size)

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

        if button == Qt.MouseButton.MiddleButton or self.tool == T_PAN:
            self._drag = D_PAN
            self._drag_origin = pos
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            return

        if self.tool == T_AI:
            self._ai_press(pos, button, mods)
            return

        if button == Qt.MouseButton.RightButton:
            if self._new is not None:
                self._cancel_interaction()
                self.update()
                return
            index = self._box_at(pos)
            if index >= 0 and index not in self.selection:
                self.select_index(index)
            if self.selection:
                self.contextMenuRequested.emit(event.globalPosition().toPoint())
            return

        if button != Qt.MouseButton.LeftButton:
            return

        if self.tool == T_BOX:
            if self.read_only:
                self.statusMessage.emit("Read-only batch - drawing is off",
                                        "warning")
                return
            start = self._snap(self.to_image(pos))
            self._new = (start, QPointF(start))
            self._drag = D_NEW
            return

        handle = None if self.read_only else self._handle_at(pos)
        if handle is not None:
            self._drag = D_RESIZE
            self._drag_index, self._drag_handle = handle
            self._drag_boxes = self.snapshot()
            return

        index = self._box_at(pos)
        if index >= 0:
            additive = bool(mods & (Qt.KeyboardModifier.ShiftModifier
                                    | Qt.KeyboardModifier.ControlModifier))
            if additive:
                self.selection.symmetric_difference_update({index})
            elif index not in self.selection:
                self.selection = {index}
            self.selectionChanged.emit()
            if not self.read_only and index in self.selection:
                self._drag = D_MOVE
                self._drag_index = index
                self._drag_start_img = self.to_image(pos, clamp=False)
                self._drag_boxes = self.snapshot()
            self.update()
            return

        self._drag = D_MARQUEE
        self._drag_origin = pos
        self._marquee = QRectF(pos, pos)
        if not (mods & (Qt.KeyboardModifier.ShiftModifier
                        | Qt.KeyboardModifier.ControlModifier)):
            self.clear_selection()
        self.update()

    def mouseMoveEvent(self, event):
        pos = QPointF(event.position())
        if self.has_image() and self.show_coordinates:
            point = self.to_image(pos, clamp=False)
            self.cursorMoved.emit(int(point.x()), int(point.y()))

        if self._drag == D_PAN:
            self._offset += pos - self._drag_origin
            self._drag_origin = pos
            self._drag_moved = True
            self.viewChanged.emit()
            self.update()
            return

        if self._drag == D_NEW and self._new is not None:
            start = self._new[0]
            end = self._snap(self.to_image(pos))
            if self._square_active():
                end = self._square(start, self.to_image(pos))
                w, h = self.image_size
                end = QPointF(min(max(end.x(), 0.0), float(w)),
                              min(max(end.y(), 0.0), float(h)))
            self._new = (start, end)
            self._drag_moved = True
            self.update()
            return

        if self._drag == D_AI:
            if self._ai_anchor is not None:
                moved = (pos - self._drag_origin)
                if abs(moved.x()) > AI_DRAG_PIXELS or abs(moved.y()) > AI_DRAG_PIXELS:
                    self._drag_moved = True
                current = self.to_image(pos)
                self._marquee = QRectF(self.to_widget(self._ai_anchor.x(),
                                                      self._ai_anchor.y()),
                                       self.to_widget(current.x(), current.y())).normalized()
                self.update()
            return

        if self._drag == D_MARQUEE:
            self._marquee = QRectF(self._drag_origin, pos).normalized()
            self._drag_moved = True
            self.update()
            return

        if self._drag == D_MOVE:
            self._move_selection(pos)
            return

        if self._drag == D_RESIZE:
            self._resize(pos)
            return

        if self.tool == T_SELECT and self.has_image():
            self._update_hover(pos)
        elif self.tool == T_BOX and self.show_crosshair:
            self.update()

    def mouseReleaseEvent(self, event):
        drag = self._drag
        if drag == D_PAN:
            self._drag = D_NONE
            self.setCursor(QCursor(TOOL_CURSORS[self.tool]))
            return
        if drag == D_NEW:
            self._commit_new()
            return
        if drag == D_AI:
            self._ai_release(QPointF(event.position()))
            return
        if drag == D_MARQUEE:
            self._commit_marquee(event.modifiers())
            return
        if drag in (D_MOVE, D_RESIZE):
            self._drag = D_NONE
            if self._drag_moved:
                self.boxesChanged.emit("Move box" if drag == D_MOVE else "Resize box")
            self._drag_boxes = []
            self._drag_index = -1
            self._drag_handle = ""
            self.update()
            return
        self._drag = D_NONE

    def mouseDoubleClickEvent(self, event):
        if not self.has_image():
            return
        if self.tool == T_AI:
            if self.ai_preview is not None:
                self.aiAccepted.emit()
            return
        if self.tool != T_SELECT:
            return
        index = self._box_at(QPointF(event.position()))
        if index >= 0:
            self.select_index(index)
            self.editLabelRequested.emit(index)

    def leaveEvent(self, event):
        self._hover_index = -1
        self._hover_handle = ""
        self.update()
        super().leaveEvent(event)

    # ── gestures ──────────────────────────────────────────
    def _update_hover(self, pos: QPointF) -> None:
        handle = None if self.read_only else self._handle_at(pos)
        index = -1 if handle else self._box_at(pos)
        name = handle[1] if handle else ""
        if (name, index) == (self._hover_handle, self._hover_index):
            return
        self._hover_handle, self._hover_index = name, index
        if name:
            self.setCursor(QCursor(HANDLE_CURSORS[name]))
        elif index >= 0:
            self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor
                                   if not self.read_only
                                   else Qt.CursorShape.PointingHandCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.update()

    def _move_selection(self, pos: QPointF) -> None:
        current = self.to_image(pos, clamp=False)
        dx = current.x() - self._drag_start_img.x()
        dy = current.y() - self._drag_start_img.y()
        if not dx and not dy:
            return
        targets = self.selection or {self._drag_index}
        lead = self._drag_boxes[self._drag_index]
        xs, ys = self._snap_targets(exclude=targets)
        tolerance = self._tolerance()
        self._snapped = False
        for edge_values, delta_name in (((lead.x0, lead.x1), "x"),
                                        ((lead.y0, lead.y1), "y")):
            pool = xs if delta_name == "x" else ys
            delta = dx if delta_name == "x" else dy
            best = None
            for edge in edge_values:
                target = self._nearest(edge + delta, pool, tolerance)
                if target is not None:
                    shift = target - (edge + delta)
                    if best is None or abs(shift) < abs(best):
                        best = shift
            if best is not None:
                self._snapped = True
                if delta_name == "x":
                    dx += best
                else:
                    dy += best
        w, h = self.image_size
        for index in targets:
            if 0 <= index < len(self.boxes) and index < len(self._drag_boxes):
                self.boxes[index] = self._drag_boxes[index].translated(dx, dy, w, h).rounded()
        self._drag_moved = True
        self.update()

    def _resize(self, pos: QPointF) -> None:
        index = self._drag_index
        if not (0 <= index < len(self.boxes)) or index >= len(self._drag_boxes):
            return
        base = self._drag_boxes[index]
        x0, y0, x1, y1 = base.bounds
        point = self._snap(self.to_image(pos), exclude={index})
        name = self._drag_handle
        if self._square_active() and name in OPPOSITE:
            corners = {"nw": (x0, y0), "ne": (x1, y0), "se": (x1, y1), "sw": (x0, y1)}
            ax, ay = corners[OPPOSITE[name]]
            point = self._square(QPointF(ax, ay), self.to_image(pos))
            x0, y0, x1, y1 = ax, ay, point.x(), point.y()
        else:
            if "w" in name:
                x0 = point.x()
            if "e" in name:
                x1 = point.x()
            if "n" in name:
                y0 = point.y()
            if "s" in name:
                y1 = point.y()
        if abs(x1 - x0) < MIN_BOX_SIDE or abs(y1 - y0) < MIN_BOX_SIDE:
            return
        w, h = self.image_size
        self.boxes[index] = base.resized(x0, y0, x1, y1, w, h).rounded()
        self._drag_moved = True
        self.update()

    def _commit_new(self) -> None:
        start, end = self._new if self._new else (QPointF(), QPointF())
        self._new = None
        self._drag = D_NONE
        w, h = self.image_size
        x0, x1 = sorted((round(start.x()), round(end.x())))
        y0, y1 = sorted((round(start.y()), round(end.y())))
        x0, x1 = max(0, x0), min(w, x1)
        y0, y1 = max(0, y0), min(h, y1)
        if x1 - x0 < MIN_BOX_SIDE or y1 - y0 < MIN_BOX_SIDE:
            self.statusMessage.emit("Drag to size the box", "warning")
            self.update()
            return
        if len(self.boxes) >= MAX_BOXES_PER_IMAGE:
            self.statusMessage.emit("This image already has %d boxes, which is "
                                    "the limit" % MAX_BOXES_PER_IMAGE, "warning")
            self.update()
            return
        self.update()
        self.boxDrawn.emit(Box("", x0, y0, x1, y1))

    def _commit_marquee(self, mods) -> None:
        self._drag = D_NONE
        rect = self._marquee
        self._marquee = QRectF()
        if rect.width() < 3 and rect.height() < 3:
            self.update()
            return
        area = QRectF(self.to_image(rect.topLeft(), clamp=False),
                      self.to_image(rect.bottomRight(), clamp=False)).normalized()
        additive = bool(mods & (Qt.KeyboardModifier.ShiftModifier
                                | Qt.KeyboardModifier.ControlModifier))
        picked = {i for i, box in enumerate(self.boxes)
                  if self._pickable(i)
                  and area.intersects(QRectF(QPointF(box.x0, box.y0),
                                             QPointF(box.x1, box.y1)))}
        self.selection = (self.selection | picked) if additive else picked
        self.selectionChanged.emit()
        if picked:
            self.statusMessage.emit("%d box(es) selected" % len(self.selection),
                                    "info")
        self.update()

    def _cancel_interaction(self) -> None:
        self._drag = D_NONE
        self._new = None
        self._marquee = QRectF()
        self._drag_boxes = []
        self._drag_index = -1
        self._hover_index = -1
        self._hover_handle = ""

    def cancel(self) -> bool:
        """Escape: drop an AI prompt, then a box being drawn, then the
        selection - the most recent thing first, every time."""
        if self.ai_points or self.ai_box or self.ai_preview is not None:
            self.clear_ai()
            self.statusMessage.emit("AI prompt cleared", "info")
            return True
        if self._new is not None:
            self._cancel_interaction()
            self.statusMessage.emit("Box discarded", "info")
            self.update()
            return True
        if self.selection:
            self.clear_selection()
            return True
        return False

    # ══════════════════════════════════════════════════════
    # AI PROMPTING  (Segment Anything)
    # ══════════════════════════════════════════════════════
    def _ai_press(self, pos, button, mods) -> None:
        if self.read_only:
            self.statusMessage.emit("Read-only batch - the AI tool cannot add boxes",
                                    "warning")
            return
        if button == Qt.MouseButton.RightButton:
            self._add_ai_point(self.to_image(pos), positive=False)
            return
        if button != Qt.MouseButton.LeftButton:
            return
        self._drag = D_AI
        self._drag_origin = QPointF(pos)
        self._drag_moved = False
        self._ai_anchor = self.to_image(pos)
        self._ai_negative = bool(mods & (Qt.KeyboardModifier.ShiftModifier
                                         | Qt.KeyboardModifier.ControlModifier))

    def _ai_release(self, pos) -> None:
        anchor, moved = self._ai_anchor, self._drag_moved
        negative = self._ai_negative
        self._drag = D_NONE
        self._ai_anchor = None
        self._marquee = QRectF()
        if anchor is None:
            self.update()
            return
        if moved:
            end = self.to_image(pos)
            x0, x1 = sorted((anchor.x(), end.x()))
            y0, y1 = sorted((anchor.y(), end.y()))
            if x1 - x0 < MIN_BOX_SIDE or y1 - y0 < MIN_BOX_SIDE:
                self.update()
                return
            self.ai_box = (x0, y0, x1, y1)
            self.aiPromptChanged.emit()
            self.update()
            return
        self._add_ai_point(anchor, positive=not negative)

    def _add_ai_point(self, point, positive=True) -> None:
        if self.read_only or point is None:
            return
        self.ai_points.append((float(point.x()), float(point.y()), bool(positive)))
        self.aiPromptChanged.emit()
        self.update()

    def undo_ai_point(self) -> bool:
        """Backspace: take back the last click without starting over."""
        if self.ai_points:
            self.ai_points.pop()
        elif self.ai_box is not None:
            self.ai_box = None
        else:
            return False
        if self.ai_points or self.ai_box is not None:
            self.aiPromptChanged.emit()
        else:
            self.ai_preview = None
        self.update()
        return True

    def has_ai_prompt(self) -> bool:
        return bool(self.ai_points) or self.ai_box is not None

    def ai_prompt(self):
        """(points, box) for the predictor, in image pixels."""
        return list(self.ai_points), self.ai_box

    def set_ai_preview(self, box, busy=False) -> None:
        self.ai_preview = box
        self.ai_busy = bool(busy)
        self.update()

    def clear_ai(self, quiet: bool = False) -> None:
        had = self.has_ai_prompt() or self.ai_preview is not None
        self.ai_points = []
        self.ai_box = None
        self.ai_preview = None
        self.ai_busy = False
        self._ai_anchor = None
        if self._drag == D_AI:
            self._drag = D_NONE
            self._marquee = QRectF()
        if had and not quiet:
            self.aiPromptChanged.emit()
        self.update()

    # ══════════════════════════════════════════════════════
    # OPERATIONS
    # ══════════════════════════════════════════════════════
    def add_box(self, box: Box, label: str = "Draw box") -> bool:
        w, h = self.image_size
        clean, messages = box.validated(w, h)
        if clean is None:
            self.statusMessage.emit("Box not added: %s" % "; ".join(messages),
                                    "danger")
            self.update()
            return False
        self.boxes.append(clean)
        self.selection = {len(self.boxes) - 1}
        self.boxesChanged.emit(label)
        self.selectionChanged.emit()
        if self.return_to_select and self.tool == T_BOX:
            self.set_tool(T_SELECT)
            self.selection = {len(self.boxes) - 1}
            self.toolFinished.emit(T_SELECT)
        self.update()
        return True

    def add_boxes(self, boxes, label="Add boxes") -> int:
        w, h = self.image_size
        room = MAX_BOXES_PER_IMAGE - len(self.boxes)
        added = []
        for box in list(boxes)[:max(0, room)]:
            clean, _messages = box.copy().validated(w, h)
            if clean is not None:
                self.boxes.append(clean)
                added.append(len(self.boxes) - 1)
        if added:
            self.selection = set(added)
            self.boxesChanged.emit(label)
            self.selectionChanged.emit()
            self.update()
        return len(added)

    def delete_selected(self) -> int:
        if not self.selection:
            self.statusMessage.emit("Select a box first", "warning")
            return 0
        keep = [b for i, b in enumerate(self.boxes) if i not in self.selection]
        removed = len(self.boxes) - len(keep)
        self.boxes = keep
        self.selection.clear()
        self.boxesChanged.emit("Delete box" if removed == 1 else "Delete boxes")
        self.selectionChanged.emit()
        self.update()
        return removed

    def duplicate_selected(self) -> int:
        if not self.selection:
            self.statusMessage.emit("Select a box first", "warning")
            return 0
        w, h = self.image_size
        shift = max(8, int(round(min(w or 100, h or 100) * 0.02)))
        added = []
        for box in self.selected_boxes():
            copy = box.translated(shift, shift, w, h)
            copy.locked = False
            copy.visible = True
            self.boxes.append(copy)
            added.append(len(self.boxes) - 1)
        self.selection = set(added)
        self.boxesChanged.emit("Duplicate box")
        self.selectionChanged.emit()
        self.update()
        return len(added)

    def clear_all(self) -> int:
        count = len(self.boxes)
        if not count:
            return 0
        self.boxes = []
        self.selection.clear()
        self.boxesChanged.emit("Clear all boxes")
        self.selectionChanged.emit()
        self.update()
        return count

    def nudge_selected(self, dx, dy) -> bool:
        movable = [i for i in self.selected_indices() if not self.boxes[i].locked]
        if not movable:
            if not self.selection:
                self.statusMessage.emit("Select a box first", "warning")
            return False
        w, h = self.image_size
        for index in movable:
            self.boxes[index] = self.boxes[index].translated(dx, dy, w, h)
        self.boxesChanged.emit("Nudge box")
        self.update()
        return True

    def relabel(self, indices, label) -> int:
        changed = 0
        for index in indices:
            if 0 <= index < len(self.boxes) and self.boxes[index].label != label:
                self.boxes[index].label = label
                changed += 1
        if changed:
            self.boxesChanged.emit("Change class")
            self.selectionChanged.emit()
            self.update()
        return changed

    def set_difficult(self, indices, value) -> int:
        changed = 0
        for index in indices:
            if 0 <= index < len(self.boxes) and self.boxes[index].difficult != bool(value):
                self.boxes[index].difficult = bool(value)
                changed += 1
        if changed:
            self.boxesChanged.emit("Mark difficult" if value else "Clear difficult")
            self.selectionChanged.emit()
            self.update()
        return changed

    def set_locked(self, indices, value) -> None:
        for index in indices:
            if 0 <= index < len(self.boxes):
                self.boxes[index].locked = bool(value)
        if value:
            self.selection -= set(indices)
        self.selectionChanged.emit()
        self.update()

    def set_visible(self, indices, value) -> None:
        for index in indices:
            if 0 <= index < len(self.boxes):
                self.boxes[index].visible = bool(value)
        if not value:
            self.selection -= set(indices)
        self.selectionChanged.emit()
        self.update()

    # ══════════════════════════════════════════════════════
    # KEYBOARD
    # ══════════════════════════════════════════════════════
    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape and self.cancel():
            return
        if self.tool == T_AI:
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.ai_preview is not None:
                self.aiAccepted.emit()
                return
            if key == Qt.Key.Key_Backspace and self.undo_ai_point():
                return
        super().keyPressEvent(event)

    # ══════════════════════════════════════════════════════
    # PAINTING
    # ══════════════════════════════════════════════════════
    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            self._paint_scene(painter)
        except Exception:                    # a drawing fault must not end the tool
            report_paint_fault("The image canvas")
        finally:
            painter.end()

    def _paint_scene(self, painter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), self._void)
        if not self.has_image():
            self._paint_placeholder(painter)
            return
        self._paint_image(painter)
        self._paint_verified(painter)
        self._paint_boxes(painter)
        self._paint_new(painter)
        self._paint_ai(painter)
        self._paint_marquee(painter)
        self._paint_crosshair(painter)

    def _paint_verified(self, painter) -> None:
        if not self.verified:
            return
        rect = self.image_rect().adjusted(-3, -3, 3, 3)
        pen = QPen(self._good, 3)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

    def _paint_boxes(self, painter) -> None:
        painter.setFont(self._label_font)
        metrics = QFontMetrics(self._label_font)
        chips = []
        for index, box in enumerate(self.boxes):
            if not box.visible:
                continue
            colour = qcolor(self._colour_for(box.label) or CANVAS["shape"])
            selected = index in self.selection
            hovered = index == self._hover_index
            rect = self._box_rect(box)

            shadow = QPen(QColor(0, 0, 0, 120), self.line_width + 2)
            shadow.setCosmetic(True)
            painter.setPen(shadow)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)

            pen = QPen(colour, self.line_width + (1 if selected or hovered else 0))
            pen.setCosmetic(True)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            if box.locked:
                pen.setStyle(Qt.PenStyle.DashLine)
            fill = QColor(colour)
            opacity = self.fill_opacity + (14 if selected else (6 if hovered else 0))
            fill.setAlpha(int(255 * max(0, min(100, opacity)) / 100.0))
            painter.setPen(pen)
            painter.setBrush(QBrush(fill))
            painter.drawRect(rect)

            if box.difficult:
                size = 9.0
                corner = QPolygonF([rect.topRight(),
                                    rect.topRight() + QPointF(-size, 0),
                                    rect.topRight() + QPointF(0, size)])
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(colour))
                painter.drawPolygon(corner)

            if selected and not box.locked:
                self._paint_handles(painter, index)
            if self.show_labels or selected or hovered:
                chips.append((box, rect, colour, selected))

        for box, rect, colour, selected in chips:
            self._paint_chip(painter, metrics, box, rect, colour, selected)

    def _paint_handles(self, painter, index) -> None:
        painter.setPen(QPen(qcolor(self._colours["selected"]), 1.4))
        for name, rect in self._handle_rects(index).items():
            hot = self._hover_handle == name
            painter.setBrush(QBrush(qcolor(self._colours["vertexHot"] if hot
                                           else self._colours["handle"])))
            painter.drawRect(rect.adjusted(-1, -1, 1, 1) if hot else rect)

    def _paint_chip(self, painter, metrics, box, rect, colour, selected) -> None:
        text = box.label or "?"
        if box.difficult:
            text += "  · difficult"
        if box.locked:
            text += "  · locked"
        width = metrics.horizontalAdvance(text) + 10
        height = metrics.height() + 4
        top = rect.top() - height
        if top < 0:
            top = rect.top() + 1
        chip = QRectF(rect.left(), top, width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        background = QColor(colour)
        background.setAlpha(235 if selected else 205)
        painter.setBrush(QBrush(background))
        painter.drawRoundedRect(chip, 3, 3)
        painter.setPen(QPen(qcolor(readable_on(colour.name()))))
        painter.drawText(chip.adjusted(5, 0, -5, 0),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         text)

    def _paint_new(self, painter) -> None:
        if self._new is None:
            return
        start, end = self._new
        rect = QRectF(self.to_widget(start.x(), start.y()),
                      self.to_widget(end.x(), end.y())).normalized()
        colour = qcolor(self._colours["drawing"])
        fill = QColor(colour)
        fill.setAlpha(45)
        pen = QPen(colour, self.line_width)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QBrush(fill))
        painter.drawRect(rect)
        text = "%d x %d" % (abs(int(round(end.x() - start.x()))),
                            abs(int(round(end.y() - start.y()))))
        if self._square_active():
            text += "  square"
        painter.setPen(QPen(qcolor(self._colours["labelShadow"], 190)))
        painter.drawText(rect.bottomRight() + QPointF(9, 15), text)
        painter.setPen(QPen(qcolor(self._colours["label"])))
        painter.drawText(rect.bottomRight() + QPointF(8, 14), text)

    def _paint_ai(self, painter) -> None:
        """The prompt (clicks and a box) and the proposal it produced."""
        if self.tool != T_AI and not self.has_ai_prompt():
            return
        if self.ai_box is not None:
            x0, y0, x1, y1 = self.ai_box
            rect = QRectF(self.to_widget(x0, y0), self.to_widget(x1, y1)).normalized()
            pen = QPen(qcolor(self._colours["guide"]), 1.2, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)

        if self.ai_preview is not None:
            box = self.ai_preview
            rect = QRectF(self.to_widget(box.x0, box.y0),
                          self.to_widget(box.x1, box.y1)).normalized()
            colour = qcolor(self._colour_for(box.label) or CANVAS["shape"])
            fill = QColor(colour)
            fill.setAlpha(60)
            pen = QPen(colour, self.line_width + 1, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(QBrush(fill))
            painter.drawRect(rect)
            painter.setPen(QPen(qcolor(self._colours["label"])))
            painter.drawText(self._hint_point(rect), "Enter to keep  ·  Esc to drop")

        for x, y, positive in self.ai_points:
            centre = self.to_widget(x, y)
            colour = self._good if positive else QColor("#e5534b")
            painter.setPen(QPen(QColor(0, 0, 0, 170), 2.5))
            painter.setBrush(QBrush(colour))
            painter.drawEllipse(centre, 5.0, 5.0)
            painter.setPen(QPen(QColor("#ffffff"), 1.6))
            painter.drawLine(centre + QPointF(-2.6, 0), centre + QPointF(2.6, 0))
            if positive:
                painter.drawLine(centre + QPointF(0, -2.6), centre + QPointF(0, 2.6))

        if self.ai_busy:
            painter.setPen(QPen(qcolor(self._colours["label"])))
            painter.drawText(self.rect().adjusted(12, 10, -12, 0),
                             Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                             "AI thinking…")

    def _hint_point(self, rect) -> QPointF:
        """Just under the proposal, but never off the bottom of the view."""
        x = min(max(rect.left() + 2.0, 4.0), max(4.0, self.width() - 190.0))
        y = rect.bottom() + 15.0
        if y > self.height() - 4:
            y = max(14.0, rect.top() - 6.0)
        return QPointF(x, y)

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
        if not self.show_crosshair or self.tool not in (T_BOX, T_AI):
            return
        cursor = self.mapFromGlobal(QCursor.pos())
        if not self.rect().contains(cursor):
            return
        colour = self._colours["snap"] if self._snapped else self._colours["guide"]
        painter.setPen(QPen(qcolor(colour), 1, Qt.PenStyle.DashLine))
        painter.drawLine(cursor.x(), 0, cursor.x(), self.height())
        painter.drawLine(0, cursor.y(), self.width(), cursor.y())
