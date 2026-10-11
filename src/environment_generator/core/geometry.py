"""Planar geometry helpers.

All functions work on plain ``(x, y)`` tuples in the generator's local frame
(metres, +X east, +Y north). Angles are degrees, counter-clockwise from +X when
viewed from above. Nothing here knows about game engines.
"""

from __future__ import annotations

import bisect
import itertools
import math
from collections.abc import Iterator, Sequence

Vec2 = tuple[float, float]
Bounds = tuple[float, float, float, float]

EPSILON = 1e-9


def add(a: Vec2, b: Vec2) -> Vec2:
    return (a[0] + b[0], a[1] + b[1])


def sub(a: Vec2, b: Vec2) -> Vec2:
    return (a[0] - b[0], a[1] - b[1])


def scale(a: Vec2, factor: float) -> Vec2:
    return (a[0] * factor, a[1] * factor)


def dot(a: Vec2, b: Vec2) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Vec2, b: Vec2) -> float:
    return a[0] * b[1] - a[1] * b[0]


def length(a: Vec2) -> float:
    return math.hypot(a[0], a[1])


def distance(a: Vec2, b: Vec2) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def normalize(a: Vec2) -> Vec2:
    norm = length(a)
    if norm < EPSILON:
        return (0.0, 0.0)
    return (a[0] / norm, a[1] / norm)


def left_normal(direction: Vec2) -> Vec2:
    """Rotate a direction 90 degrees counter-clockwise."""
    return (-direction[1], direction[0])


def rotate(vector: Vec2, angle_deg: float) -> Vec2:
    rad = math.radians(angle_deg)
    c, s = math.cos(rad), math.sin(rad)
    return (vector[0] * c - vector[1] * s, vector[0] * s + vector[1] * c)


def lerp(a: Vec2, b: Vec2, t: float) -> Vec2:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def normalize_angle_deg(angle: float) -> float:
    """Map an angle to ``[0, 360)``."""
    result = math.fmod(angle, 360.0)
    if result < 0.0:
        result += 360.0
    if result >= 360.0:  # guards against -tiny + 360 rounding up
        result = 0.0
    return result + 0.0  # turns -0.0 into 0.0


def heading_deg(direction: Vec2) -> float:
    """Angle of a direction vector, counter-clockwise from +X, in ``[0, 360)``."""
    return normalize_angle_deg(math.degrees(math.atan2(direction[1], direction[0])))


def forward_vector(yaw_deg: float) -> Vec2:
    """World direction of an object's local +Y ("front") after a yaw rotation."""
    rad = math.radians(yaw_deg)
    return (-math.sin(rad), math.cos(rad))


def yaw_facing(direction: Vec2) -> float:
    """Yaw that turns an object's local +Y ("front") towards ``direction``."""
    return normalize_angle_deg(math.degrees(math.atan2(-direction[0], direction[1])))


# --------------------------------------------------------------------------- bounds


def bounds_of(points: Sequence[Vec2]) -> Bounds:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def bounds_overlap(a: Bounds, b: Bounds) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


# --------------------------------------------------------------------------- polygons


def signed_area(polygon: Sequence[Vec2]) -> float:
    total = 0.0
    count = len(polygon)
    for i in range(count):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % count]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def polygon_area(polygon: Sequence[Vec2]) -> float:
    return abs(signed_area(polygon))


def polygon_centroid(polygon: Sequence[Vec2]) -> Vec2:
    area = signed_area(polygon)
    if abs(area) < EPSILON:
        count = len(polygon)
        return (sum(p[0] for p in polygon) / count, sum(p[1] for p in polygon) / count)
    cx = cy = 0.0
    count = len(polygon)
    for i in range(count):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % count]
        factor = x1 * y2 - x2 * y1
        cx += (x1 + x2) * factor
        cy += (y1 + y2) * factor
    return (cx / (6.0 * area), cy / (6.0 * area))


def ensure_ccw(polygon: Sequence[Vec2]) -> list[Vec2]:
    points = list(polygon)
    if signed_area(points) < 0:
        points.reverse()
    return points


def polygon_edges(polygon: Sequence[Vec2]) -> Iterator[tuple[Vec2, Vec2]]:
    count = len(polygon)
    for i in range(count):
        yield polygon[i], polygon[(i + 1) % count]


def point_in_polygon(point: Vec2, polygon: Sequence[Vec2]) -> bool:
    """Even-odd rule containment test. Works for concave polygons."""
    x, y = point
    inside = False
    count = len(polygon)
    j = count - 1
    for i in range(count):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def _orientation(a: Vec2, b: Vec2, c: Vec2) -> float:
    return cross(sub(b, a), sub(c, a))


def _on_segment(a: Vec2, b: Vec2, p: Vec2) -> bool:
    return (
        min(a[0], b[0]) - EPSILON <= p[0] <= max(a[0], b[0]) + EPSILON
        and min(a[1], b[1]) - EPSILON <= p[1] <= max(a[1], b[1]) + EPSILON
    )


def segments_intersect(p1: Vec2, p2: Vec2, q1: Vec2, q2: Vec2) -> bool:
    """True when two closed segments share at least one point."""
    d1 = _orientation(q1, q2, p1)
    d2 = _orientation(q1, q2, p2)
    d3 = _orientation(p1, p2, q1)
    d4 = _orientation(p1, p2, q2)
    if ((d1 > EPSILON and d2 < -EPSILON) or (d1 < -EPSILON and d2 > EPSILON)) and (
        (d3 > EPSILON and d4 < -EPSILON) or (d3 < -EPSILON and d4 > EPSILON)
    ):
        return True
    return (
        (abs(d1) <= EPSILON and _on_segment(q1, q2, p1))
        or (abs(d2) <= EPSILON and _on_segment(q1, q2, p2))
        or (abs(d3) <= EPSILON and _on_segment(p1, p2, q1))
        or (abs(d4) <= EPSILON and _on_segment(p1, p2, q2))
    )


def segment_intersection(
    p1: Vec2, p2: Vec2, q1: Vec2, q2: Vec2, tolerance: float = 1e-6
) -> Vec2 | None:
    """Intersection point of two non-parallel segments, or ``None``.

    Parallel or collinear segments return ``None``; callers that need overlap
    detection should use :func:`segments_intersect`.
    """
    r = sub(p2, p1)
    s = sub(q2, q1)
    denom = cross(r, s)
    if abs(denom) < EPSILON:
        return None
    qp = sub(q1, p1)
    t = cross(qp, s) / denom
    u = cross(qp, r) / denom
    if -tolerance <= t <= 1 + tolerance and -tolerance <= u <= 1 + tolerance:
        return (p1[0] + t * r[0], p1[1] + t * r[1])
    return None


def point_segment_distance(point: Vec2, a: Vec2, b: Vec2) -> float:
    return distance(point, closest_point_on_segment(point, a, b))


def closest_point_on_segment(point: Vec2, a: Vec2, b: Vec2) -> Vec2:
    ab = sub(b, a)
    denom = dot(ab, ab)
    if denom < EPSILON:
        return a
    t = max(0.0, min(1.0, dot(sub(point, a), ab) / denom))
    return (a[0] + ab[0] * t, a[1] + ab[1] * t)


def polygon_is_simple(polygon: Sequence[Vec2]) -> bool:
    """True when no two non-adjacent edges intersect and no edge is degenerate."""
    count = len(polygon)
    if count < 3:
        return False
    edges = list(polygon_edges(polygon))
    if any(distance(a, b) < EPSILON for a, b in edges):
        return False
    for i in range(count):
        for j in range(i + 1, count):
            if j == i + 1 or (i == 0 and j == count - 1):
                continue
            if segments_intersect(edges[i][0], edges[i][1], edges[j][0], edges[j][1]):
                return False
    return True


def polygons_overlap(a: Sequence[Vec2], b: Sequence[Vec2]) -> bool:
    """Overlap test for arbitrary simple polygons (touching counts as overlap)."""
    if not bounds_overlap(bounds_of(a), bounds_of(b)):
        return False
    for a1, a2 in polygon_edges(a):
        for b1, b2 in polygon_edges(b):
            if segments_intersect(a1, a2, b1, b2):
                return True
    return point_in_polygon(a[0], b) or point_in_polygon(b[0], a)


def circle_polygon_overlap(center: Vec2, radius: float, polygon: Sequence[Vec2]) -> bool:
    if point_in_polygon(center, polygon):
        return True
    return any(point_segment_distance(center, p, q) < radius for p, q in polygon_edges(polygon))


def circles_overlap(c1: Vec2, r1: float, c2: Vec2, r2: float) -> bool:
    return distance(c1, c2) < r1 + r2


def is_convex(polygon: Sequence[Vec2]) -> bool:
    count = len(polygon)
    sign = 0
    for i in range(count):
        turn = _orientation(polygon[i], polygon[(i + 1) % count], polygon[(i + 2) % count])
        if abs(turn) <= EPSILON:
            continue
        current = 1 if turn > 0 else -1
        if sign == 0:
            sign = current
        elif current != sign:
            return False
    return True


def convex_hull(points: Sequence[Vec2]) -> list[Vec2]:
    """Counter-clockwise convex hull (Andrew's monotone chain)."""
    unique = sorted(set(points))
    if len(unique) <= 2:
        return unique

    def build(sequence: Sequence[Vec2]) -> list[Vec2]:
        hull: list[Vec2] = []
        for p in sequence:
            while len(hull) >= 2 and _orientation(hull[-2], hull[-1], p) <= EPSILON:
                hull.pop()
            hull.append(p)
        return hull

    lower = build(unique)
    upper = build(list(reversed(unique)))
    return lower[:-1] + upper[:-1]


def inflate_convex_polygon(polygon: Sequence[Vec2], amount: float) -> list[Vec2]:
    """Offset a convex polygon outwards by ``amount`` (mitred corners)."""
    if amount == 0.0:
        return list(polygon)
    points = ensure_ccw(polygon)
    count = len(points)
    lines: list[tuple[Vec2, Vec2, Vec2]] = []
    for i in range(count):
        a, b = points[i], points[(i + 1) % count]
        direction = normalize(sub(b, a))
        outward = (direction[1], -direction[0])
        lines.append((add(a, scale(outward, amount)), direction, outward))
    result: list[Vec2] = []
    for i in range(count):
        p1, t1, _ = lines[i - 1]
        p2, t2, n2 = lines[i]
        denom = cross(t1, t2)
        if abs(denom) < EPSILON:
            result.append(add(points[i], scale(n2, amount)))
        else:
            u = cross(sub(p2, p1), t2) / denom
            result.append(add(p1, scale(t1, u)))
    return result


def rectangle_corners(center: Vec2, width: float, depth: float, yaw_deg: float) -> list[Vec2]:
    """Counter-clockwise corners of an oriented rectangle.

    ``width`` runs along the rectangle's local X axis, ``depth`` along local Y.
    """
    hw, hd = width / 2.0, depth / 2.0
    local = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
    return [add(center, rotate(p, yaw_deg)) for p in local]


def minimum_area_rectangle(points: Sequence[Vec2]) -> tuple[Vec2, float, float, float]:
    """Smallest enclosing oriented rectangle as ``(center, width, depth, yaw_deg)``.

    ``width`` is measured along the yaw direction. Uses rotating calipers over
    the convex hull edges.
    """
    hull = convex_hull(points)
    if len(hull) < 3:
        raise ValueError("cannot fit a rectangle to fewer than three non-collinear points")
    best: tuple[float, float, float, float, float, float] | None = None
    for i in range(len(hull)):
        edge = sub(hull[(i + 1) % len(hull)], hull[i])
        if length(edge) < EPSILON:
            continue
        angle = math.atan2(edge[1], edge[0])
        c, s = math.cos(angle), math.sin(angle)
        xs = [p[0] * c + p[1] * s for p in hull]
        ys = [-p[0] * s + p[1] * c for p in hull]
        min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
        area = (max_x - min_x) * (max_y - min_y)
        if best is None or area < best[0] - 1e-9:
            best = (area, angle, min_x, max_x, min_y, max_y)
    if best is None:
        raise ValueError("degenerate point set")
    _, angle, min_x, max_x, min_y, max_y = best
    c, s = math.cos(angle), math.sin(angle)
    mx, my = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0
    center = (mx * c - my * s, mx * s + my * c)
    return center, max_x - min_x, max_y - min_y, normalize_angle_deg(math.degrees(angle))


def segment_quad(a: Vec2, b: Vec2, half_width: float) -> list[Vec2]:
    """Counter-clockwise rectangle covering segment ``a``-``b`` with a half width."""
    direction = normalize(sub(b, a))
    offset = scale(left_normal(direction), half_width)
    return [sub(a, offset), sub(b, offset), add(b, offset), add(a, offset)]


# --------------------------------------------------------------------------- polylines


def polyline_length(points: Sequence[Vec2]) -> float:
    return sum(distance(points[i], points[i + 1]) for i in range(len(points) - 1))


def cumulative_lengths(points: Sequence[Vec2]) -> list[float]:
    result = [0.0]
    for i in range(len(points) - 1):
        result.append(result[-1] + distance(points[i], points[i + 1]))
    return result


def point_along_polyline(
    points: Sequence[Vec2], cumulative: Sequence[float], offset: float
) -> tuple[Vec2, Vec2]:
    """Point and unit tangent at arc length ``offset`` (clamped to the polyline)."""
    total = cumulative[-1]
    offset = max(0.0, min(total, offset))
    index = bisect.bisect_right(cumulative, offset) - 1
    index = max(0, min(index, len(points) - 2))
    seg_len = cumulative[index + 1] - cumulative[index]
    t = 0.0 if seg_len < EPSILON else (offset - cumulative[index]) / seg_len
    a, b = points[index], points[index + 1]
    return lerp(a, b, t), normalize(sub(b, a))


def sample_polyline(
    points: Sequence[Vec2], spacing: float, start_offset: float = 0.0
) -> list[tuple[float, Vec2, Vec2]]:
    """Samples ``(offset, point, tangent)`` every ``spacing`` metres along a polyline."""
    if spacing <= 0:
        raise ValueError("spacing must be positive")
    cumulative = cumulative_lengths(points)
    total = cumulative[-1]
    samples: list[tuple[float, Vec2, Vec2]] = []
    offset = start_offset
    while offset <= total + EPSILON:
        point, tangent = point_along_polyline(points, cumulative, offset)
        samples.append((offset, point, tangent))
        offset += spacing
    return samples


def densify_polyline(points: Sequence[Vec2], max_segment: float) -> list[Vec2]:
    """Insert intermediate points so that no segment exceeds ``max_segment``."""
    if max_segment <= 0:
        raise ValueError("max_segment must be positive")
    result = [points[0]]
    for a, b in itertools.pairwise(points):
        pieces = max(1, math.ceil(distance(a, b) / max_segment))
        for k in range(1, pieces + 1):
            result.append(lerp(a, b, k / pieces))
    return result


def closest_point_on_polyline(point: Vec2, points: Sequence[Vec2]) -> tuple[Vec2, float]:
    """Closest point on a polyline and its distance from ``point``."""
    best_point = points[0]
    best_distance = math.inf
    for a, b in itertools.pairwise(points):
        candidate = closest_point_on_segment(point, a, b)
        d = distance(point, candidate)
        if d < best_distance:
            best_point, best_distance = candidate, d
    return best_point, best_distance
