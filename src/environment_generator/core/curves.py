"""Reference interpretation of road curves.

A curve is the point list ``[source node, *controlPoints, target node]``:

* ``polyline`` - straight pieces between consecutive points;
* ``catmull_rom`` - centripetal Catmull-Rom spline (alpha = 0.5) passing
  through every point. Phantom end points are reflections
  ``P[-1] = 2 P[0] - P[1]`` and ``P[n+1] = 2 P[n] - P[n-1]``. Each piece
  between ``P[i]`` and ``P[i+1]`` is evaluated with the Barry-Goldman
  pyramidal formulation over knots ``t[j+1] = t[j] + |P[j+1] - P[j]| ** alpha``.

The curve itself is exact; sampling density is a consumer choice.
:func:`sample_curve` is the reference sampler (each piece split into
``ceil(chord / max_segment_m)`` equal parameter steps).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence

from environment_generator.core.geometry import EPSILON, Vec2, densify_polyline, distance

CENTRIPETAL_ALPHA = 0.5


def _lerp(a: Vec2, b: Vec2, wa: float, wb: float) -> Vec2:
    return (a[0] * wa + b[0] * wb, a[1] * wa + b[1] * wb)


def catmull_rom_point(
    p0: Vec2, p1: Vec2, p2: Vec2, p3: Vec2, u: float, alpha: float = CENTRIPETAL_ALPHA
) -> Vec2:
    """Point on the piece from ``p1`` (u = 0) to ``p2`` (u = 1)."""
    t0 = 0.0
    t1 = t0 + max(distance(p0, p1), EPSILON) ** alpha
    t2 = t1 + max(distance(p1, p2), EPSILON) ** alpha
    t3 = t2 + max(distance(p2, p3), EPSILON) ** alpha
    t = t1 + (t2 - t1) * u
    a1 = _lerp(p0, p1, (t1 - t) / (t1 - t0), (t - t0) / (t1 - t0))
    a2 = _lerp(p1, p2, (t2 - t) / (t2 - t1), (t - t1) / (t2 - t1))
    a3 = _lerp(p2, p3, (t3 - t) / (t3 - t2), (t - t2) / (t3 - t2))
    b1 = _lerp(a1, a2, (t2 - t) / (t2 - t0), (t - t0) / (t2 - t0))
    b2 = _lerp(a2, a3, (t3 - t) / (t3 - t1), (t - t1) / (t3 - t1))
    return _lerp(b1, b2, (t2 - t) / (t2 - t1), (t - t1) / (t2 - t1))


def sample_catmull_rom(points: Sequence[Vec2], max_segment_m: float) -> list[Vec2]:
    """Reference sampling of a centripetal Catmull-Rom curve through ``points``."""
    if max_segment_m <= 0:
        raise ValueError("max_segment_m must be positive")
    pts = [(float(x), float(y)) for x, y in points]
    if len(pts) < 2:
        raise ValueError("a curve needs at least two points")
    if any(distance(a, b) < EPSILON for a, b in itertools.pairwise(pts)):
        raise ValueError("consecutive curve points must be distinct")
    if len(pts) == 2:
        return densify_polyline(pts, max_segment_m)
    first = (2 * pts[0][0] - pts[1][0], 2 * pts[0][1] - pts[1][1])
    last = (2 * pts[-1][0] - pts[-2][0], 2 * pts[-1][1] - pts[-2][1])
    extended = [first, *pts, last]
    result = [pts[0]]
    for i in range(1, len(extended) - 2):
        p0, p1, p2, p3 = extended[i - 1], extended[i], extended[i + 1], extended[i + 2]
        steps = max(1, math.ceil(distance(p1, p2) / max_segment_m))
        for k in range(1, steps):
            result.append(catmull_rom_point(p0, p1, p2, p3, k / steps))
        result.append(p2)  # exact control points, no accumulated error
    return result


def sample_curve(curve_type: str, points: Sequence[Vec2], max_segment_m: float) -> list[Vec2]:
    """Sample a ``polyline`` or ``catmull_rom`` curve; vertices are kept exactly."""
    if curve_type == "polyline":
        return densify_polyline([(float(x), float(y)) for x, y in points], max_segment_m)
    if curve_type == "catmull_rom":
        return sample_catmull_rom(points, max_segment_m)
    raise ValueError(f"unknown curve type: {curve_type}")
