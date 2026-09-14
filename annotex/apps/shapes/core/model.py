"""The in-memory shape.

A `Shape` keeps the geometry it was drawn with, so a circle reopens as a
circle and an oriented box as a box with an angle:

    polygon, freehand   points
    obb                 cx, cy, w, h, angle
    ellipse             cx, cy, w, h, angle      (w, h are the full axes)
    circle              cx, cy, w (= h, the diameter)

Everything is in original image pixels.  Exports turn shapes into polygons
or rotated boxes; the file keeps the shape itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from ..config import (CURVE_SEGMENTS, KIND_CIRCLE, KIND_ELLIPSE, KIND_FREEHAND,
                      KIND_LABELS, KIND_OBB, KIND_POLYGON, KINDS, MAX_POINTS,
                      MIN_POINTS, MIN_SIZE, PARAMETRIC_KINDS)
from . import geometry as geo


def _r(value, digits=2):
    value = round(float(value), digits)
    return 0.0 if value == 0 else value


@dataclass
class Shape:
    kind: str = KIND_POLYGON
    label: str = ""
    points: list = field(default_factory=list)
    cx: float = 0.0
    cy: float = 0.0
    w: float = 0.0
    h: float = 0.0
    angle: float = 0.0
    locked: bool = False
    visible: bool = True

    def __post_init__(self):
        if self.kind not in KINDS:
            self.kind = KIND_POLYGON
        self.label = str(self.label or "")
        self.points = [(float(p[0]), float(p[1])) for p in (self.points or [])]
        self.cx, self.cy = float(self.cx), float(self.cy)
        self.w, self.h = abs(float(self.w)), abs(float(self.h))
        self.angle = geo.normalize_angle(self.angle)
        if self.kind == KIND_CIRCLE:
            self.w = self.h = max(self.w, self.h)
            self.angle = 0.0

    # ── construction ──────────────────────────────────────
    @classmethod
    def polygon(cls, label, points, kind=KIND_POLYGON) -> "Shape":
        return cls(kind=kind, label=label, points=list(points))

    @classmethod
    def obb(cls, label, cx, cy, w, h, angle=0.0) -> "Shape":
        return cls(kind=KIND_OBB, label=label, cx=cx, cy=cy, w=w, h=h, angle=angle)

    @classmethod
    def circle(cls, label, cx, cy, radius) -> "Shape":
        return cls(kind=KIND_CIRCLE, label=label, cx=cx, cy=cy, w=radius * 2, h=radius * 2)

    @classmethod
    def ellipse(cls, label, cx, cy, w, h, angle=0.0) -> "Shape":
        return cls(kind=KIND_ELLIPSE, label=label, cx=cx, cy=cy, w=w, h=h, angle=angle)

    def copy(self) -> "Shape":
        return replace(self, points=list(self.points))

    # ── queries ───────────────────────────────────────────
    @property
    def parametric(self) -> bool:
        return self.kind in PARAMETRIC_KINDS

    @property
    def radius(self) -> float:
        return self.w / 2.0

    def outline(self, segments=CURVE_SEGMENTS):
        """The shape as a closed polygon."""
        if self.kind == KIND_OBB:
            return geo.rect_corners(self.cx, self.cy, self.w, self.h, self.angle)
        if self.kind in (KIND_CIRCLE, KIND_ELLIPSE):
            return geo.ellipse_points(self.cx, self.cy, self.w, self.h, self.angle, segments)
        return list(self.points)

    @property
    def bounds(self):
        if self.kind in (KIND_CIRCLE, KIND_ELLIPSE):
            ex, ey = geo.ellipse_extents(self.w, self.h, self.angle)
            return (self.cx - ex, self.cy - ey, self.cx + ex, self.cy + ey)
        return geo.polygon_bounds(self.outline())

    @property
    def centroid(self):
        if self.parametric:
            return (self.cx, self.cy)
        return geo.polygon_centroid(self.points)

    @property
    def area(self) -> float:
        if self.kind == KIND_OBB:
            return self.w * self.h
        if self.kind in (KIND_CIRCLE, KIND_ELLIPSE):
            return math.pi * self.w * self.h / 4.0
        return geo.polygon_area(self.points)

    def to_local(self, x, y):
        """Image point -> the shape's own unrotated frame, origin at its centre."""
        return geo.rotate_point(x - self.cx, y - self.cy, 0.0, 0.0, -self.angle)

    def from_local(self, lx, ly):
        x, y = geo.rotate_point(lx, ly, 0.0, 0.0, self.angle)
        return (x + self.cx, y + self.cy)

    def contains(self, x, y) -> bool:
        if self.kind == KIND_OBB:
            lx, ly = self.to_local(x, y)
            return abs(lx) <= self.w / 2.0 and abs(ly) <= self.h / 2.0
        if self.kind in (KIND_CIRCLE, KIND_ELLIPSE):
            if self.w <= 0 or self.h <= 0:
                return False
            lx, ly = self.to_local(x, y)
            return (lx / (self.w / 2.0)) ** 2 + (ly / (self.h / 2.0)) ** 2 <= 1.0
        return len(self.points) >= 3 and geo.point_in_polygon(x, y, self.points)

    def rotated_box(self):
        """(cx, cy, w, h, angle) - exact for an oriented box, the tightest
        rotated box for everything else."""
        if self.kind == KIND_OBB:
            return (self.cx, self.cy, self.w, self.h, self.angle)
        if self.kind in (KIND_CIRCLE, KIND_ELLIPSE):
            return (self.cx, self.cy, self.w, self.h, self.angle)
        return geo.min_area_rect(self.points)

    def describe(self) -> str:
        if self.kind == KIND_OBB:
            text = "%d x %d" % (round(self.w), round(self.h))
            return text + ("  ·  %.0f°" % self.angle if abs(self.angle) >= 0.5 else "")
        if self.kind == KIND_CIRCLE:
            return "r %d" % round(self.radius)
        if self.kind == KIND_ELLIPSE:
            text = "%d x %d" % (round(self.w), round(self.h))
            return text + ("  ·  %.0f°" % self.angle if abs(self.angle) >= 0.5 else "")
        return "%d points" % len(self.points)

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    # ── transforms (all return a new Shape) ───────────────
    def translated(self, dx, dy, width=0, height=0) -> "Shape":
        if width and height:
            x0, y0, x1, y1 = self.bounds
            dx = geo.clamp(dx, -x0, max(-x0, width - x1))
            dy = geo.clamp(dy, -y0, max(-y0, height - y1))
        if self.parametric:
            return replace(self, cx=self.cx + dx, cy=self.cy + dy, points=[])
        return replace(self, points=[(x + dx, y + dy) for x, y in self.points])

    def rotated(self, degrees, pivot=None) -> "Shape":
        px, py = pivot if pivot is not None else self.centroid
        if self.parametric:
            cx, cy = geo.rotate_point(self.cx, self.cy, px, py, degrees)
            angle = 0.0 if self.kind == KIND_CIRCLE else self.angle + degrees
            return replace(self, cx=cx, cy=cy, angle=geo.normalize_angle(angle), points=[])
        return replace(self, points=[geo.rotate_point(x, y, px, py, degrees)
                                     for x, y in self.points])

    def with_local_box(self, x0, y0, x1, y1) -> "Shape":
        """Resize a parametric shape to local extents (in its unrotated frame,
        relative to its current centre), keeping the angle."""
        w = max(abs(x1 - x0), MIN_SIZE)
        h = max(abs(y1 - y0), MIN_SIZE)
        cx, cy = self.from_local((x0 + x1) / 2.0, (y0 + y1) / 2.0)
        if self.kind == KIND_CIRCLE:
            w = h = max(w, h)
        return replace(self, cx=cx, cy=cy, w=w, h=h, points=[])

    def with_radius(self, radius) -> "Shape":
        diameter = max(float(radius) * 2.0, MIN_SIZE)
        return replace(self, w=diameter, h=diameter)

    def validated(self, width=0, height=0):
        """(clean_shape_or_None, messages).  Points are pulled back inside
        the image; a centre outside it is refused."""
        messages = []
        if self.parametric:
            if self.w < MIN_SIZE or self.h < MIN_SIZE:
                return None, ["shape is too small"]
            if width and height and not (0 <= self.cx <= width and 0 <= self.cy <= height):
                return None, ["centre is outside the image"]
            return self.copy(), messages
        points = geo.dedupe(self.points)
        if width and height:
            clamped = [(geo.clamp(x, 0.0, float(width)), geo.clamp(y, 0.0, float(height)))
                       for x, y in points]
            if clamped != points:
                messages.append("pulled back inside the image")
            points = geo.dedupe(clamped)
        if len(points) < MIN_POINTS:
            return None, messages + ["needs at least %d points" % MIN_POINTS]
        if len(points) > MAX_POINTS:
            return None, messages + ["more than %d points" % MAX_POINTS]
        if geo.polygon_area(points) < MIN_SIZE * MIN_SIZE:
            return None, messages + ["shape has no area"]
        return replace(self, points=points), messages

    # ── files ─────────────────────────────────────────────
    def to_dict(self) -> dict:
        data = {"label": self.label, "kind": self.kind}
        if self.kind in (KIND_POLYGON, KIND_FREEHAND):
            data["points"] = [[_r(x), _r(y)] for x, y in self.points]
        elif self.kind == KIND_CIRCLE:
            data.update(cx=_r(self.cx), cy=_r(self.cy), r=_r(self.radius))
        else:
            data.update(cx=_r(self.cx), cy=_r(self.cy), w=_r(self.w), h=_r(self.h),
                        angle=_r(self.angle))
        return data

    @classmethod
    def from_dict(cls, data) -> "Shape":
        if not isinstance(data, dict):
            raise ValueError("a shape must be an object")
        kind = data.get("kind", KIND_POLYGON)
        if kind not in KINDS:
            raise ValueError("unknown shape kind %r" % kind)
        label = str(data.get("label", ""))
        if kind in (KIND_POLYGON, KIND_FREEHAND):
            points = [(float(p[0]), float(p[1])) for p in data.get("points", [])]
            return cls(kind=kind, label=label, points=points)
        if kind == KIND_CIRCLE:
            radius = float(data.get("r", float(data.get("w", 0.0)) / 2.0))
            return cls.circle(label, float(data["cx"]), float(data["cy"]), radius)
        return cls(kind=kind, label=label, cx=float(data["cx"]), cy=float(data["cy"]),
                   w=float(data["w"]), h=float(data["h"]), angle=float(data.get("angle", 0.0)))

    def same_as(self, other) -> bool:
        return self.to_dict() == other.to_dict()


def shapes_match(a, b) -> bool:
    return len(a) == len(b) and all(x.same_as(y) for x, y in zip(a, b))
