"""Plane geometry for LabelImg Shapes.  No Qt.

Image coordinates: x to the right, y down.  Angles are degrees, positive
clockwise on screen (the same sense as rotating with y pointing down).
"""

from __future__ import annotations

import math


def clamp(value, low, high):
    if low > high:
        return low
    return low if value < low else (high if value > high else value)


def normalize_angle(degrees) -> float:
    """Into (-180, 180]."""
    value = math.fmod(float(degrees), 360.0)
    if value <= -180.0:
        value += 360.0
    elif value > 180.0:
        value -= 360.0
    return value


def rotate_point(x, y, cx, cy, degrees):
    rad = math.radians(degrees)
    c, s = math.cos(rad), math.sin(rad)
    dx, dy = x - cx, y - cy
    return (cx + dx * c - dy * s, cy + dx * s + dy * c)


def rect_corners(cx, cy, w, h, degrees):
    """Four corners, clockwise from the (unrotated) top-left."""
    hw, hh = w / 2.0, h / 2.0
    return [rotate_point(cx + dx, cy + dy, cx, cy, degrees)
            for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]


def ellipse_points(cx, cy, w, h, degrees, segments):
    """`segments` points around an ellipse with full axes w x h, clockwise
    from the rightmost point of the unrotated ellipse."""
    segments = max(8, int(segments))
    rx, ry = w / 2.0, h / 2.0
    rad = math.radians(degrees)
    c, s = math.cos(rad), math.sin(rad)
    points = []
    for i in range(segments):
        t = 2.0 * math.pi * i / segments
        lx, ly = rx * math.cos(t), ry * math.sin(t)
        points.append((cx + lx * c - ly * s, cy + lx * s + ly * c))
    return points


def ellipse_extents(w, h, degrees):
    """Half width and half height of a rotated ellipse's bounding box."""
    rx, ry = w / 2.0, h / 2.0
    rad = math.radians(degrees)
    c, s = math.cos(rad), math.sin(rad)
    return (math.hypot(rx * c, ry * s), math.hypot(rx * s, ry * c))


def polygon_area(points) -> float:
    n = len(points)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


def polygon_bounds(points):
    if not points:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def polygon_centroid(points):
    n = len(points)
    if n == 0:
        return (0.0, 0.0)
    signed = cx = cy = 0.0
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        signed += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(signed) < 1e-9:
        return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)
    return (cx / (3.0 * signed), cy / (3.0 * signed))


def point_in_polygon(x, y, points) -> bool:
    inside = False
    n = len(points)
    j = n - 1
    for i in range(n):
        xi, yi = points[i]
        xj, yj = points[j]
        if (yi > y) != (yj > y):
            cross = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < cross:
                inside = not inside
        j = i
    return inside


def point_segment_distance(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    if length <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = clamp(((px - ax) * dx + (py - ay) * dy) / length, 0.0, 1.0)
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def dedupe(points, tolerance=0.5):
    """Drop consecutive repeats, including a last point equal to the first."""
    out = []
    for p in points:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > tolerance:
            out.append((float(p[0]), float(p[1])))
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= tolerance:
        out.pop()
    return out


def simplify(points, tolerance=1.5):
    """Ramer-Douglas-Peucker on an open polyline."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        ax, ay = points[first]
        bx, by = points[last]
        best, index = -1.0, -1
        for i in range(first + 1, last):
            d = point_segment_distance(points[i][0], points[i][1], ax, ay, bx, by)
            if d > best:
                best, index = d, i
        if index > 0 and best > tolerance:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, k in zip(points, keep) if k]


def convex_hull(points):
    """Andrew's monotone chain; counter-clockwise in maths axes."""
    pts = sorted(set((float(x), float(y)) for x, y in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def min_area_rect(points):
    """The smallest rotated rectangle around the points: (cx, cy, w, h, angle)."""
    hull = convex_hull(points)
    if not hull:
        return (0.0, 0.0, 0.0, 0.0, 0.0)
    if len(hull) < 3:
        x0, y0, x1, y1 = polygon_bounds(hull)
        return ((x0 + x1) / 2.0, (y0 + y1) / 2.0, x1 - x0, y1 - y0, 0.0)
    best = None
    n = len(hull)
    for i in range(n):
        ax, ay = hull[i]
        bx, by = hull[(i + 1) % n]
        theta = math.atan2(by - ay, bx - ax)
        c, s = math.cos(-theta), math.sin(-theta)
        xs = [x * c - y * s for x, y in hull]
        ys = [x * s + y * c for x, y in hull]
        area = (max(xs) - min(xs)) * (max(ys) - min(ys))
        if best is None or area < best[0] - 1e-9:
            best = (area, theta, min(xs), max(xs), min(ys), max(ys))
    _area, theta, x0, x1, y0, y1 = best
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    c, s = math.cos(theta), math.sin(theta)
    cx, cy = mx * c - my * s, mx * s + my * c
    w, h = x1 - x0, y1 - y0
    angle = math.degrees(theta)
    # keep the angle small and the width along it
    while angle > 45.0:
        angle -= 90.0
        w, h = h, w
    while angle <= -45.0:
        angle += 90.0
        w, h = h, w
    return (cx, cy, w, h, angle)
