"""Pure geometry, parsing and formatting helpers.

Everything here is a free function over plain tuples and lists, with no Qt
and no I/O, so the whole module is exercised by the offline test suite.
"""

from __future__ import annotations

import ast
import json
import math
import os
import re

from ..config import (CIRCLE_SEGMENTS, MIN_POINTS, MIN_POLY_AREA_PX, NDIGITS,
                      SHAPE_POLYGON, SHAPE_TYPES)


# ══════════════════════════════════════════════════════════════
# TEXT / NAMING
# ══════════════════════════════════════════════════════════════
def safe_text(s) -> str:
    """Strip characters outside the BMP.

    Qt handles them fine, but they still break some spreadsheet readers and
    a few Windows console code pages, so every user string passes through
    here before it is written or displayed."""
    if not isinstance(s, str):
        s = str(s)
    if all(ord(ch) <= 0xFFFF for ch in s):
        return s
    return "".join(ch if ord(ch) <= 0xFFFF else "?" for ch in s)


def natural_key(name):
    """Sort 'img2.jpg' before 'img10.jpg'."""
    parts = []
    num = ""
    for ch in str(name).lower():
        if ch.isdigit():
            num += ch
        else:
            if num:
                parts.append((1, int(num), ""))
                num = ""
            parts.append((0, 0, ch))
    if num:
        parts.append((1, int(num), ""))
    return parts


def extract_site_cam(fname):
    """'UBBRAP0091_cam3_2026-08-14_16-34-48.jpg' -> ('UBBRAP0091', 'cam3').

    Falls back to (basename, '') when the pattern does not match."""
    base = os.path.splitext(os.path.basename(str(fname)))[0]
    parts = base.split("_")
    if len(parts) >= 2 and parts[0]:
        return parts[0], parts[1]
    return base, ""


_DIGITS_RE = re.compile(r"(\d+)")


def cam_digits(cam_token):
    """'cam3' -> '3', '9' -> '9', 'cam03' -> '3', 'left' -> ''."""
    m = _DIGITS_RE.search(str(cam_token or ""))
    if not m:
        return ""
    stripped = m.group(1).lstrip("0")
    return stripped or "0"


def make_roi_key(fname):
    """'UBBRAP0091_cam3_2026-08-14_16-34-48.jpg' -> 'UBBRAP0091_3'.

    When no camera number can be found the site id is returned alone; the
    caller surfaces that as a warning rather than inventing a number."""
    site, cam = extract_site_cam(fname)
    digits = cam_digits(cam)
    if not site:
        return ""
    return "%s_%s" % (site, digits) if digits else site


# ══════════════════════════════════════════════════════════════
# COORDINATE CELLS
# ══════════════════════════════════════════════════════════════
def _is_point(obj) -> bool:
    return (isinstance(obj, (list, tuple)) and len(obj) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    for v in obj))


def _normalize_poly_structure(obj):
    """Collapse any nesting depth into a flat list of polygons.

    Accepts, and returns the same thing for, all of:
        [[[1, 2], [3, 4], [5, 6]]]        current format, one polygon
        [[[1, 2], ...], [[7, 8], ...]]    current format, two polygons
        [(1, 2), (3, 4), (5, 6)]          legacy format, one polygon
        [(1, 2), ...], [(7, 8), ...]      legacy format, two polygons
    """
    if not isinstance(obj, (list, tuple)) or not obj:
        return []
    if all(_is_point(item) for item in obj):
        return [[(item[0], item[1]) for item in obj]]
    polys = []
    for item in obj:
        if not isinstance(item, (list, tuple)) or not item:
            continue
        if all(_is_point(p) for p in item):
            pts = [(p[0], p[1]) for p in item]
            if len(pts) >= 2:
                polys.append(pts)
        else:
            polys.extend(_normalize_poly_structure(item))
    return polys


def parse_multi_polys(coord_str):
    """Parse a coordinate cell in either the current or the legacy format.

    Never raises; an unreadable cell yields [] so one bad row cannot stop a
    whole folder from loading."""
    if coord_str is None:
        return []
    s = str(coord_str).strip()
    if not s or s.lower() in ("nan", "none", "null", "[]", "[[]]"):
        return []
    if s.startswith("'"):                       # Excel text-cell apostrophe
        s = s[1:].strip()
    for attempt in (s, "[" + s + "]"):
        for loader in (json.loads, ast.literal_eval):
            try:
                parsed = loader(attempt)
            except Exception:
                continue
            polys = _normalize_poly_structure(parsed)
            if polys:
                return polys
    return []


def _clean_number(v):
    """Keep ints as ints so pixel cells stay [[231, 203]] not [[231.0, 203.0]]."""
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e15:
            return int(v)
        return round(v, NDIGITS)
    return v


def fmt_polys(polys) -> str:
    """Render polygons as a JSON-style nested list: [[[x, y], ...], ...].

    The outer list is ALWAYS the polygon list, so a single ROI is
    [[[x, y], ...]] and two ROIs are [[[...], ...], [[...], ...]].  Every
    produced cell is directly json.loads()-able."""
    if not polys:
        return ""
    out = [[[_clean_number(p[0]), _clean_number(p[1])] for p in poly]
           for poly in polys if poly]
    if not out:
        return ""
    return json.dumps(out, separators=(", ", ", "))


def fmt_shape_types(kinds) -> str:
    """['rect', 'circle'] -> '["rect", "circle"]'."""
    clean = [k if k in SHAPE_TYPES else SHAPE_POLYGON for k in (kinds or [])]
    if not clean:
        return ""
    return json.dumps(clean, separators=(", ", ", "))


def parse_shape_types(cell, count=0):
    """Read the shape_types cell back, padded to `count` with 'polygon'.

    A missing or unreadable cell is not an error - files written before this
    column existed simply describe polygons."""
    kinds = []
    if cell:
        s = str(cell).strip()
        if s.startswith("'"):
            s = s[1:].strip()
        for loader in (json.loads, ast.literal_eval):
            try:
                parsed = loader(s)
            except Exception:
                continue
            if isinstance(parsed, (list, tuple)):
                kinds = [str(k) for k in parsed]
                break
    kinds = [k if k in SHAPE_TYPES else SHAPE_POLYGON for k in kinds]
    if count and len(kinds) < count:
        kinds += [SHAPE_POLYGON] * (count - len(kinds))
    return kinds[:count] if count else kinds


# ══════════════════════════════════════════════════════════════
# PRIMITIVES
# ══════════════════════════════════════════════════════════════
def clamp(value, low, high):
    if low > high:
        return low
    return low if value < low else (high if value > high else value)


def point_in_poly(x, y, poly) -> bool:
    """Even-odd ray casting test."""
    n = len(poly)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            denom = (yj - yi) or 1e-9
            if x < (xj - xi) * (y - yi) / denom + xi:
                inside = not inside
        j = i
    return inside


def polygon_area(poly) -> float:
    """Absolute shoelace area.  Used to reject collapsed shapes."""
    n = len(poly)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def polygon_bounds(poly):
    """(min_x, min_y, max_x, max_y); (0, 0, 0, 0) for an empty polygon."""
    if not poly:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


def polygon_centroid(poly):
    if not poly:
        return (0.0, 0.0)
    return (sum(p[0] for p in poly) / float(len(poly)),
            sum(p[1] for p in poly) / float(len(poly)))


def point_segment_distance(px, py, ax, ay, bx, by) -> float:
    """Shortest distance from a point to a line segment."""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / float(dx * dx + dy * dy)
    t = clamp(t, 0.0, 1.0)
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def dedupe_consecutive(poly):
    """Drop repeated clicks on the same pixel, including a closing duplicate."""
    out = []
    for pt in poly:
        cur = (int(round(pt[0])), int(round(pt[1])))
        if not out or cur != out[-1]:
            out.append(cur)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def _seg_intersect(a, b, c, d) -> bool:
    def orient(p, q, r):
        val = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])
        if abs(val) < 1e-9:
            return 0
        return 1 if val > 0 else 2
    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    return o1 != o2 and o3 != o4


def poly_self_intersects(poly) -> bool:
    """True when two non-adjacent edges cross.  Reported as a warning only -
    a self-intersecting ROI is legal, it is just usually a misclick."""
    n = len(poly)
    if n < 4:
        return False
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or (j + 1) % n == i or j == (i + 1) % n:
                continue
            c, d = poly[j], poly[(j + 1) % n]
            if _seg_intersect(a, b, c, d):
                return True
    return False


def validate_polygon(poly, width=0, height=0):
    """Return (cleaned_poly_or_None, list_of_messages).

    A polygon is rejected outright only when it cannot describe a region:
    too few distinct points, or effectively zero area."""
    msgs = []
    cleaned = dedupe_consecutive(poly)
    if len(cleaned) != len(poly):
        msgs.append("removed %d duplicate point(s)" % (len(poly) - len(cleaned)))
    if len(cleaned) < MIN_POINTS:
        return None, msgs + ["needs at least %d distinct points" % MIN_POINTS]
    if width and height:
        clamped = [(int(clamp(x, 0, width - 1)), int(clamp(y, 0, height - 1)))
                   for x, y in cleaned]
        if clamped != cleaned:
            msgs.append("clamped point(s) back inside the image")
        cleaned = clamped
    if polygon_area(cleaned) < MIN_POLY_AREA_PX:
        return None, msgs + ["shape has no area"]
    if poly_self_intersects(cleaned):
        msgs.append("edges cross - check the shape")
    return cleaned, msgs


def polys_to_norm(polys_px, width, height, ndigits=NDIGITS):
    """Image pixels -> 0..1 normalised, clamped inside the image."""
    if not width or not height:
        return []
    out = []
    for poly in polys_px:
        out.append([(round(clamp(px / float(width), 0.0, 1.0), ndigits),
                     round(clamp(py / float(height), 0.0, 1.0), ndigits))
                    for px, py in poly])
    return out


def norm_to_polys(polys_norm, width, height):
    """0..1 normalised -> image pixels."""
    return [[(int(round(nx * width)), int(round(ny * height)))
             for nx, ny in poly] for poly in polys_norm]


# ══════════════════════════════════════════════════════════════
# SHAPE CONSTRUCTION
# ══════════════════════════════════════════════════════════════
def rect_to_polygon(x0, y0, x1, y1):
    """Axis-aligned rectangle as four points, clockwise from top-left."""
    left, right = (x0, x1) if x0 <= x1 else (x1, x0)
    top, bottom = (y0, y1) if y0 <= y1 else (y1, y0)
    return [(int(round(left)), int(round(top))),
            (int(round(right)), int(round(top))),
            (int(round(right)), int(round(bottom))),
            (int(round(left)), int(round(bottom)))]


def circle_to_polygon(cx, cy, rx, ry=None, segments=CIRCLE_SEGMENTS):
    """Ellipse as an N-gon.  ry defaults to rx, giving a true circle."""
    ry = rx if ry is None else ry
    pts = []
    for i in range(segments):
        a = 2.0 * math.pi * i / segments
        pts.append((int(round(cx + rx * math.cos(a))),
                    int(round(cy + ry * math.sin(a)))))
    return dedupe_consecutive(pts)


def ellipse_from_polygon(poly):
    """Recover (cx, cy, rx, ry) from a polygon drawn as a circle."""
    x0, y0, x1, y1 = polygon_bounds(poly)
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0,
            max((x1 - x0) / 2.0, 0.5), max((y1 - y0) / 2.0, 0.5))


def rect_from_polygon(poly):
    """Recover (x0, y0, x1, y1) from a polygon drawn as a rectangle."""
    return polygon_bounds(poly)


def is_axis_aligned_rect(poly, tolerance=1.0) -> bool:
    """True when four points form an axis-aligned box within `tolerance`."""
    if len(poly) != 4:
        return False
    xs = sorted({round(p[0]) for p in poly})
    ys = sorted({round(p[1]) for p in poly})
    if len(xs) != 2 or len(ys) != 2:
        return False
    corners = {(round(p[0]), round(p[1])) for p in poly}
    expected = {(xs[0], ys[0]), (xs[1], ys[0]), (xs[1], ys[1]), (xs[0], ys[1])}
    return corners == expected


# ══════════════════════════════════════════════════════════════
# TRANSFORMS
# ══════════════════════════════════════════════════════════════
def translate(poly, dx, dy, width=0, height=0):
    if width and height:
        return [(int(clamp(x + dx, 0, width - 1)),
                 int(clamp(y + dy, 0, height - 1))) for x, y in poly]
    return [(int(round(x + dx)), int(round(y + dy))) for x, y in poly]


def scale_about(poly, cx, cy, fx, fy, width=0, height=0):
    out = [(cx + (x - cx) * fx, cy + (y - cy) * fy) for x, y in poly]
    if width and height:
        return [(int(clamp(x, 0, width - 1)), int(clamp(y, 0, height - 1)))
                for x, y in out]
    return [(int(round(x)), int(round(y))) for x, y in out]


def rotate_about(poly, cx, cy, degrees, width=0, height=0):
    rad = math.radians(degrees)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    out = []
    for x, y in poly:
        dx, dy = x - cx, y - cy
        out.append((cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a))
    if width and height:
        return [(int(clamp(x, 0, width - 1)), int(clamp(y, 0, height - 1)))
                for x, y in out]
    return [(int(round(x)), int(round(y))) for x, y in out]


# ══════════════════════════════════════════════════════════════
# SIMPLIFY  (used by the freehand lasso)
# ══════════════════════════════════════════════════════════════
def simplify_polygon(poly, tolerance=2.0):
    """Ramer-Douglas-Peucker.  Turns a dense freehand trace into a polygon
    with a workable number of vertices."""
    if len(poly) < 3:
        return list(poly)

    def rdp(points):
        if len(points) < 3:
            return list(points)
        ax, ay = points[0]
        bx, by = points[-1]
        worst, index = 0.0, 0
        for i in range(1, len(points) - 1):
            d = point_segment_distance(points[i][0], points[i][1],
                                       ax, ay, bx, by)
            if d > worst:
                worst, index = d, i
        if worst <= tolerance:
            return [points[0], points[-1]]
        return rdp(points[:index + 1])[:-1] + rdp(points[index:])

    simplified = rdp(list(poly))
    if len(simplified) > MIN_POINTS:
        simplified = dedupe_consecutive(simplified)
    return simplified if len(simplified) >= MIN_POINTS else dedupe_consecutive(poly)


# ══════════════════════════════════════════════════════════════
# SNAPPING
# ══════════════════════════════════════════════════════════════
def snap_point(x, y, width, height, others=(), tolerance=6.0,
               to_edges=True, to_shapes=True):
    """Pull a point onto image edges and onto nearby existing vertices.

    Returns (x, y, snapped_flag)."""
    sx, sy, hit = float(x), float(y), False
    if to_edges and width and height:
        for edge in (0, width - 1):
            if abs(sx - edge) <= tolerance:
                sx, hit = float(edge), True
        for edge in (0, height - 1):
            if abs(sy - edge) <= tolerance:
                sy, hit = float(edge), True
    if to_shapes:
        best_d, best = tolerance, None
        for poly in others:
            for vx, vy in poly:
                d = math.hypot(sx - vx, sy - vy)
                if d < best_d:
                    best_d, best = d, (float(vx), float(vy))
        if best is not None:
            sx, sy, hit = best[0], best[1], True
    return sx, sy, hit
