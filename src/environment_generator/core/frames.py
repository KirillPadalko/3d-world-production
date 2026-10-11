"""Conversion between the public location frame and the generator frame.

* **Location frame** (LocationBlueprint, overrides, scene manifest): metres,
  +X east, +Y up, +Z north (left-handed); yaw in degrees clockwise from north
  around +Y; an object's front is local +Z.
* **Generator frame** (internal ``SiteDescription`` and generators): +X east,
  +Y north, +Z up (right-handed); yaw counter-clockwise seen from above; an
  object's front is local +Y.

Both frames share the horizontal origin and east/north directions, so the
conversion swaps the second and third components and negates the yaw. Every
crossing between the frames goes through these functions.
"""

from __future__ import annotations

from environment_generator.core.geometry import normalize_angle_deg

Vec3 = tuple[float, float, float]


def location_to_generator(point: Vec3) -> Vec3:
    """``[x, y_up, z_north]`` -> ``(x, y_north, z_up)``."""
    x, y, z = point
    return (x, z, y)


def generator_to_location(point: Vec3) -> Vec3:
    """``(x, y_north, z_up)`` -> ``[x, y_up, z_north]``."""
    x, y, z = point
    return (x, z, y)


def location_yaw_to_generator(yaw_deg: float) -> float:
    """Clockwise-from-north heading -> counter-clockwise generator yaw."""
    return normalize_angle_deg(-yaw_deg)


def generator_yaw_to_location(yaw_deg: float) -> float:
    """Counter-clockwise generator yaw -> clockwise-from-north heading."""
    return normalize_angle_deg(-yaw_deg)


def generator_scale_to_location(scale: Vec3) -> Vec3:
    """Local (width, depth, height) scale -> location local (x, y_up, z_depth)."""
    sx, sy, sz = scale
    return (sx, sz, sy)


def location_scale_to_generator(scale: Vec3) -> Vec3:
    sx, sy, sz = scale
    return (sx, sz, sy)
