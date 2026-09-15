"""Turning a predicted mask into something an annotator can edit.

A segmentation model hands back a grid of booleans.  Neither of the two
labelling tools can store that: LabelImg Master wants a rectangle and
LabelImg Shapes wants a polygon.  This module does the conversion, with no
Qt, no onnxruntime and no numpy required - numpy is used when it is there
because it makes the first step faster, and the pure-Python path produces
exactly the same answer when it is not.

The steps are the classic ones:

    runs        every row of the mask as (start, end) spans
    components  spans joined into connected blobs (8-connected)
    contour     Moore-neighbour tracing around the blob we want
    simplify    Ramer-Douglas-Peucker, so a 4000-point outline
                becomes the few dozen points a human can actually drag

Everything here is total: a mask that is empty, ragged, or a single pixel
returns None or an empty list rather than raising.
"""

from __future__ import annotations

from bisect import bisect_right

# A polygon nobody can edit is worse than no polygon at all.
MAX_POLYGON_POINTS = 240
MIN_COMPONENT_AREA = 12          # mask pixels


# ══════════════════════════════════════════════════════════════
# ROWS AND RUNS
# ══════════════════════════════════════════════════════════════
def _numpy():
    try:
        import numpy                                   # noqa: WPS433
        return numpy
    except Exception:
        return None


def mask_runs(mask):
    """(height, width, runs) - runs[y] is a list of half-open (x0, x1) spans.

    `mask` may be a numpy array, a list of lists, or anything else that
    iterates rows of truthy values.  An unusable mask gives (0, 0, [])."""
    if mask is None:
        return 0, 0, []

    np = _numpy()
    if np is not None and hasattr(mask, "shape") and getattr(mask, "ndim", 0) == 2:
        try:
            grid = np.asarray(mask, dtype=bool)
            height, width = int(grid.shape[0]), int(grid.shape[1])
            if not height or not width:
                return 0, 0, []
            padded = np.zeros((height, width + 2), dtype=bool)
            padded[:, 1:-1] = grid
            edges = np.diff(padded.astype("int8"), axis=1)
            runs = []
            for y in range(height):
                row = edges[y]
                starts = (row == 1).nonzero()[0]
                ends = (row == -1).nonzero()[0]
                runs.append([(int(a), int(b)) for a, b in zip(starts, ends)])
            return height, width, runs
        except Exception:
            pass                                       # fall through to Python

    runs, width = [], 0
    try:
        rows = list(mask)
    except TypeError:
        return 0, 0, []
    for row in rows:
        try:
            values = list(row)
        except TypeError:
            return 0, 0, []
        width = max(width, len(values))
        spans, start = [], -1
        for x, value in enumerate(values):
            if value:
                if start < 0:
                    start = x
            elif start >= 0:
                spans.append((start, x))
                start = -1
        if start >= 0:
            spans.append((start, len(values)))
        runs.append(spans)
    return len(runs), width, runs


# ══════════════════════════════════════════════════════════════
# CONNECTED COMPONENTS
# ══════════════════════════════════════════════════════════════
class Component:
    """One connected blob of a mask, kept as spans rather than pixels."""

    __slots__ = ("rows", "area", "x0", "y0", "x1", "y1")

    def __init__(self):
        self.rows = {}               # y -> sorted [(x0, x1)]
        self.area = 0
        self.x0 = self.y0 = 10 ** 9
        self.x1 = self.y1 = -10 ** 9

    def add(self, y, span) -> None:
        self.rows.setdefault(y, []).append(span)
        self.area += span[1] - span[0]
        self.x0, self.x1 = min(self.x0, span[0]), max(self.x1, span[1])
        self.y0, self.y1 = min(self.y0, y), max(self.y1, y + 1)

    def finish(self) -> "Component":
        for y in self.rows:
            self.rows[y].sort()
        return self

    @property
    def bounds(self):
        """(x0, y0, x1, y1) in pixels, x1/y1 exclusive."""
        if not self.rows:
            return None
        return (self.x0, self.y0, self.x1, self.y1)

    def contains(self, x, y) -> bool:
        spans = self.rows.get(y)
        if not spans:
            return False
        position = bisect_right(spans, (x, 10 ** 9)) - 1
        if position < 0:
            return False
        start, end = spans[position]
        return start <= x < end

    def first_pixel(self):
        """Top-most, then left-most pixel - where contour tracing starts."""
        if not self.rows:
            return None
        y = min(self.rows)
        return (self.rows[y][0][0], y)


def components(mask, connectivity: int = 8):
    """Every connected blob of the mask, largest first."""
    height, width, runs = mask_runs(mask)
    if not height or not width:
        return []
    slack = 1 if connectivity == 8 else 0

    parent = {}

    def find(key):
        root = key
        while parent[root] != root:
            root = parent[root]
        while parent[key] != root:                     # path compression
            parent[key], key = root, parent[key]
        return root

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for y, spans in enumerate(runs):
        for index, span in enumerate(spans):
            parent[(y, index)] = (y, index)
            if y == 0:
                continue
            for above, other in enumerate(runs[y - 1]):
                if other[0] - slack < span[1] and span[0] - slack < other[1]:
                    union((y - 1, above), (y, index))

    grouped = {}
    for y, spans in enumerate(runs):
        for index, span in enumerate(spans):
            grouped.setdefault(find((y, index)), Component()).add(y, span)
    out = [component.finish() for component in grouped.values()]
    out.sort(key=lambda c: -c.area)
    return out


def largest_component(mask, min_area: int = MIN_COMPONENT_AREA):
    found = components(mask)
    if not found or found[0].area < max(1, int(min_area)):
        return None
    return found[0]


# ══════════════════════════════════════════════════════════════
# CONTOUR
# ══════════════════════════════════════════════════════════════
# Clockwise on screen (y grows downwards), starting due east.
_NEIGHBOURS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
_INDEX = {offset: i for i, offset in enumerate(_NEIGHBOURS)}


def trace_contour(component: Component):
    """The outer boundary of a blob, as pixel coordinates in order.

    Moore-neighbour tracing with Jacob's stopping criterion, plus a hard
    ceiling on the number of steps so a pathological mask can never spin
    here forever."""
    if component is None or not component.rows:
        return []
    start = component.first_pixel()
    if start is None:
        return []
    if component.area == 1:
        return [start]

    contains = component.contains
    backtrack = (start[0] - 1, start[1])               # known background
    point, back = start, backtrack
    contour = [start]
    limit = 8 * (component.area + (component.x1 - component.x0)
                 + (component.y1 - component.y0)) + 64

    for _step in range(limit):
        offset = (back[0] - point[0], back[1] - point[1])
        begin = _INDEX.get(offset, 4)
        found = None
        previous = back
        for turn in range(1, 9):
            dx, dy = _NEIGHBOURS[(begin + turn) % 8]
            candidate = (point[0] + dx, point[1] + dy)
            if contains(candidate[0], candidate[1]):
                found = candidate
                break
            previous = candidate
        if found is None:
            break
        back, point = previous, found
        if point == start and back == backtrack:
            break
        contour.append(point)
    return contour


# ══════════════════════════════════════════════════════════════
# SIMPLIFY
# ══════════════════════════════════════════════════════════════
def _perpendicular(point, start, end) -> float:
    (px, py), (ax, ay), (bx, by) = point, start, end
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    return abs(dy * px - dx * py + bx * ay - by * ax) / ((dx * dx + dy * dy) ** 0.5)


def simplify(points, tolerance: float = 1.0):
    """Ramer-Douglas-Peucker, iterative so a long outline cannot blow the
    Python recursion limit."""
    points = list(points)
    if len(points) < 3 or tolerance <= 0:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        worst, worst_at = 0.0, -1
        for index in range(first + 1, last):
            distance = _perpendicular(points[index], points[first], points[last])
            if distance > worst:
                worst, worst_at = distance, index
        if worst > tolerance and worst_at > 0:
            keep[worst_at] = True
            stack.append((first, worst_at))
            stack.append((worst_at, last))
    return [point for point, wanted in zip(points, keep) if wanted]


# ══════════════════════════════════════════════════════════════
# PUBLIC CONVERSIONS
# ══════════════════════════════════════════════════════════════
def mask_to_box(mask, min_area: int = MIN_COMPONENT_AREA, whole: bool = False):
    """(x0, y0, x1, y1) around the mask, or None when there is nothing in it.

    `whole=True` boxes every blob together; the default boxes the largest
    one, which is what a click prompt means."""
    if whole:
        found = components(mask)
        found = [c for c in found if c.area >= max(1, int(min_area))] or found
        if not found:
            return None
        return (float(min(c.x0 for c in found)), float(min(c.y0 for c in found)),
                float(max(c.x1 for c in found)), float(max(c.y1 for c in found)))
    component = largest_component(mask, min_area)
    if component is None:
        return None
    return (float(component.x0), float(component.y0),
            float(component.x1), float(component.y1))


def mask_to_polygon(mask, tolerance: float = 1.2,
                    min_area: int = MIN_COMPONENT_AREA,
                    max_points: int = MAX_POLYGON_POINTS):
    """The outline of the biggest blob, as [(x, y), …] in mask pixels.

    Returns [] when the mask holds nothing worth tracing.  The tolerance is
    raised automatically until the polygon fits inside `max_points`, so the
    caller always gets something a person can edit."""
    component = largest_component(mask, min_area)
    if component is None:
        return []
    contour = trace_contour(component)
    if len(contour) < 3:
        return []
    points = [(float(x) + 0.5, float(y) + 0.5) for x, y in contour]
    # The trace stops one step short of its own start.  Closing the ring
    # before simplifying is what lets a rectangle come back as four corners
    # instead of five - the last corner is otherwise pinned as an endpoint.
    closed = points + [points[0]]

    tolerance = max(0.0, float(tolerance))
    simplified = simplify(closed, tolerance) if tolerance else closed
    guard = 0
    while len(simplified) > max(4, int(max_points)) + 1 and guard < 24:
        tolerance = max(0.5, tolerance * 1.6)
        simplified = simplify(closed, tolerance)
        guard += 1
    if len(simplified) < 4:
        simplified = closed[:max(4, min(len(closed), int(max_points) + 1))]
    if len(simplified) > 3 and simplified[0] == simplified[-1]:
        simplified = simplified[:-1]       # a polygon does not repeat its start
    return simplified if len(simplified) >= 3 else []


def scale_points(points, factor_x, factor_y):
    return [(x * float(factor_x), y * float(factor_y)) for x, y in points]
