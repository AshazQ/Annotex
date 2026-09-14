"""The in-memory box.

A `Box` is one labelled, axis-aligned rectangle in original image pixels.
Coordinates are floats because that is what LabelImg has always handed its
writers (CreateML in particular writes them as they are), but everything the
UI creates lands on whole pixels.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..config import DUPLICATE_TOLERANCE, MIN_BOX_SIDE


def _clamp(value, low, high):
    if low > high:
        return low
    return low if value < low else (high if value > high else value)


@dataclass
class Box:
    """One labelled bounding box, in image pixel coordinates."""

    label: str = ""
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    difficult: bool = False
    locked: bool = False
    visible: bool = True

    def __post_init__(self):
        self.label = str(self.label or "")
        x0, x1 = sorted((float(self.x0), float(self.x1)))
        y0, y1 = sorted((float(self.y0), float(self.y1)))
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.difficult = bool(self.difficult)

    # ── construction ──────────────────────────────────────
    @classmethod
    def from_points(cls, label, points, difficult=False) -> "Box":
        xs = [float(p[0]) for p in points] or [0.0]
        ys = [float(p[1]) for p in points] or [0.0]
        return cls(label, min(xs), min(ys), max(xs), max(ys), difficult)

    def copy(self) -> "Box":
        return replace(self)

    # ── queries ───────────────────────────────────────────
    @property
    def bounds(self):
        return (self.x0, self.y0, self.x1, self.y1)

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def centroid(self):
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)

    @property
    def points(self):
        """Clockwise from the top-left, the order LabelImg writers expect."""
        return [(self.x0, self.y0), (self.x1, self.y0),
                (self.x1, self.y1), (self.x0, self.y1)]

    def contains(self, x, y) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def describe(self) -> str:
        return "%d x %d" % (int(round(self.width)), int(round(self.height)))

    def same_geometry(self, other, tolerance: float = 0.5) -> bool:
        return all(abs(a - b) <= tolerance
                   for a, b in zip(self.bounds, other.bounds))

    def same_as(self, other) -> bool:
        """Equal as far as a file is concerned (lock and visibility are
        editing state, not annotation)."""
        return (self.label == other.label and self.difficult == other.difficult
                and self.same_geometry(other))

    # ── transforms (all return a new Box) ─────────────────
    def translated(self, dx, dy, width=0, height=0) -> "Box":
        """Move by (dx, dy) without changing size; stays inside the image."""
        x0, y0 = self.x0 + dx, self.y0 + dy
        if width and height:
            x0 = _clamp(x0, 0.0, max(0.0, width - self.width))
            y0 = _clamp(y0, 0.0, max(0.0, height - self.height))
        return replace(self, x0=x0, y0=y0, x1=x0 + self.width,
                       y1=y0 + self.height)

    def resized(self, x0, y0, x1, y1, width=0, height=0) -> "Box":
        x0, x1 = sorted((float(x0), float(x1)))
        y0, y1 = sorted((float(y0), float(y1)))
        if width and height:
            x0, x1 = _clamp(x0, 0.0, width), _clamp(x1, 0.0, width)
            y0, y1 = _clamp(y0, 0.0, height), _clamp(y1, 0.0, height)
        return replace(self, x0=x0, y0=y0, x1=x1, y1=y1)

    def rounded(self) -> "Box":
        return replace(self, x0=float(round(self.x0)), y0=float(round(self.y0)),
                       x1=float(round(self.x1)), y1=float(round(self.y1)))

    def validated(self, width=0, height=0):
        """(clean_box_or_None, messages).

        A box is clamped back inside the image rather than refused; it is only
        rejected when nothing is left of it or it has no class."""
        messages = []
        box = self.copy()
        if width and height:
            clamped = box.resized(box.x0, box.y0, box.x1, box.y1, width, height)
            if not clamped.same_geometry(box, 1e-6):
                messages.append("pulled back inside the image")
            box = clamped
        if box.width < MIN_BOX_SIDE or box.height < MIN_BOX_SIDE:
            return None, messages + ["box is too small (%s)" % box.describe()]
        if not box.label.strip():
            return None, messages + ["box has no class"]
        return box, messages

    # ── file hand-off ─────────────────────────────────────
    def to_writer_shape(self) -> dict:
        """The dict LabelImg's writers take, with float points as the old
        canvas always produced them."""
        return {"label": self.label,
                "points": [(float(x), float(y)) for x, y in self.points],
                "difficult": self.difficult}


def boxes_match(a, b) -> bool:
    """Two box lists describe the same annotation."""
    if len(a) != len(b):
        return False
    return all(x.same_as(y) for x, y in zip(a, b))


def find_duplicates(boxes, tolerance: float = DUPLICATE_TOLERANCE):
    """Indices of boxes that repeat an earlier box of the same class."""
    duplicates = []
    for i, box in enumerate(boxes):
        for earlier in boxes[:i]:
            if earlier.label == box.label and box.same_geometry(earlier, tolerance):
                duplicates.append(i)
                break
    return duplicates


def iou(a: Box, b: Box) -> float:
    ix0, iy0 = max(a.x0, b.x0), max(a.y0, b.y0)
    ix1, iy1 = min(a.x1, b.x1), min(a.y1, b.y1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0
