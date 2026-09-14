"""The in-memory annotation model.

A `Shape` is the one source of truth for a region: its points always live in
original image pixel coordinates, and the `kind` records how it was drawn so
a rectangle stays a rectangle when the file is reopened.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..config import (SHAPE_CIRCLE, SHAPE_POLYGON, SHAPE_RECT, SHAPE_TYPES)
from . import geometry as geo


@dataclass
class Shape:
    """One region of interest, in image pixel coordinates."""

    points: list = field(default_factory=list)
    kind: str = SHAPE_POLYGON
    locked: bool = False
    visible: bool = True

    def __post_init__(self):
        self.points = [(int(round(p[0])), int(round(p[1]))) for p in self.points]
        if self.kind not in SHAPE_TYPES:
            self.kind = SHAPE_POLYGON

    # ── construction ──────────────────────────────────────
    @classmethod
    def polygon(cls, points) -> "Shape":
        return cls(points=list(points), kind=SHAPE_POLYGON)

    @classmethod
    def rect(cls, x0, y0, x1, y1) -> "Shape":
        return cls(points=geo.rect_to_polygon(x0, y0, x1, y1), kind=SHAPE_RECT)

    @classmethod
    def circle(cls, cx, cy, rx, ry=None) -> "Shape":
        return cls(points=geo.circle_to_polygon(cx, cy, rx, ry),
                   kind=SHAPE_CIRCLE)

    def copy(self) -> "Shape":
        return replace(self, points=list(self.points))

    # ── queries ───────────────────────────────────────────
    def __len__(self) -> int:
        return len(self.points)

    @property
    def area(self) -> float:
        return geo.polygon_area(self.points)

    @property
    def bounds(self):
        return geo.polygon_bounds(self.points)

    @property
    def centroid(self):
        return geo.polygon_centroid(self.points)

    def contains(self, x, y) -> bool:
        return geo.point_in_poly(x, y, self.points)

    def is_editable_as_box(self) -> bool:
        """Rectangles and circles are edited with corner handles rather than
        per-vertex, so the canvas asks this rather than testing `kind`."""
        return self.kind in (SHAPE_RECT, SHAPE_CIRCLE)

    def describe(self) -> str:
        if self.kind == SHAPE_RECT:
            x0, y0, x1, y1 = self.bounds
            return "rectangle %d x %d" % (int(x1 - x0), int(y1 - y0))
        if self.kind == SHAPE_CIRCLE:
            _cx, _cy, rx, ry = geo.ellipse_from_polygon(self.points)
            if abs(rx - ry) < 1.5:
                return "circle r=%d" % int(rx)
            return "ellipse %d x %d" % (int(rx * 2), int(ry * 2))
        return "polygon, %d points" % len(self.points)

    # ── transforms (all return a new Shape) ───────────────
    def translated(self, dx, dy, width=0, height=0) -> "Shape":
        return replace(self, points=geo.translate(self.points, dx, dy,
                                                  width, height))

    def scaled(self, cx, cy, fx, fy, width=0, height=0) -> "Shape":
        pts = geo.scale_about(self.points, cx, cy, fx, fy, width, height)
        return replace(self, points=pts)

    def rotated(self, degrees, width=0, height=0) -> "Shape":
        cx, cy = self.centroid
        pts = geo.rotate_about(self.points, cx, cy, degrees, width, height)
        # a rotated rectangle is no longer axis-aligned, so it becomes a polygon
        kind = self.kind if self.kind == SHAPE_CIRCLE else (
            SHAPE_POLYGON if self.kind == SHAPE_RECT and degrees % 90 else self.kind)
        return replace(self, points=pts, kind=kind)

    def resized_box(self, x0, y0, x1, y1, width=0, height=0) -> "Shape":
        """Rebuild a rect or circle from a new bounding box."""
        if self.kind == SHAPE_CIRCLE:
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            pts = geo.circle_to_polygon(cx, cy, max(abs(x1 - x0) / 2.0, 1.0),
                                        max(abs(y1 - y0) / 2.0, 1.0))
        else:
            pts = geo.rect_to_polygon(x0, y0, x1, y1)
        if width and height:
            pts = [(int(geo.clamp(x, 0, width - 1)),
                    int(geo.clamp(y, 0, height - 1))) for x, y in pts]
        return replace(self, points=pts)

    def validated(self, width=0, height=0):
        """(clean_shape_or_None, messages)."""
        cleaned, msgs = geo.validate_polygon(self.points, width, height)
        if cleaned is None:
            return None, msgs
        return replace(self, points=cleaned), msgs


def shapes_to_polys(shapes):
    return [list(s.points) for s in shapes]


def shapes_to_kinds(shapes):
    return [s.kind for s in shapes]


def polys_to_shapes(polys, kinds=None):
    """Rebuild shapes from a stored row.

    A file written before shape_types existed simply yields polygons, except
    that an exact four-point axis-aligned box is recognised as a rectangle so
    older batches still get the nicer handles."""
    kinds = list(kinds or [])
    out = []
    for i, poly in enumerate(polys):
        kind = kinds[i] if i < len(kinds) else SHAPE_POLYGON
        if kind == SHAPE_POLYGON and geo.is_axis_aligned_rect(poly):
            kind = SHAPE_RECT
        out.append(Shape(points=list(poly), kind=kind))
    return out
