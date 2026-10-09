"""GeoJSON-like 2D geometry used by blueprint features.

Coordinates are local metres: +X east, +Y north, origin at the south-west
corner of the blueprint extent. Rotations are degrees counter-clockwise when
viewed from above.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from environment_generator.core.geometry import Vec2, distance, rectangle_corners
from environment_generator.models.base import Angle, ContractModel, Point2, PositiveFloat


def _drop_repeated_points(points: list[Point2]) -> list[Point2]:
    result: list[Point2] = []
    for point in points:
        if not result or distance(result[-1], point) > 1e-6:
            result.append(point)
    return result


class PointGeometry(ContractModel):
    """A single position with an optional heading."""

    type: Literal["point"]
    position: Point2
    rotation_deg: Angle = 0.0


class PolylineGeometry(ContractModel):
    """An open line through two or more points (roads, fences, hedgerows ...)."""

    type: Literal["polyline"]
    points: list[Point2] = Field(min_length=2, max_length=10_000)

    @field_validator("points")
    @classmethod
    def _distinct_points(cls, points: list[Point2]) -> list[Point2]:
        cleaned = _drop_repeated_points(points)
        if len(cleaned) < 2:
            raise ValueError("a polyline needs at least two distinct points")
        return cleaned


class PolygonGeometry(ContractModel):
    """A closed area. The closing point may be repeated or omitted."""

    type: Literal["polygon"]
    points: list[Point2] = Field(min_length=3, max_length=10_000)

    @field_validator("points")
    @classmethod
    def _distinct_points(cls, points: list[Point2]) -> list[Point2]:
        cleaned = _drop_repeated_points(points)
        if len(cleaned) > 1 and distance(cleaned[0], cleaned[-1]) <= 1e-6:
            cleaned.pop()
        if len(cleaned) < 3:
            raise ValueError("a polygon needs at least three distinct points")
        return cleaned


class RectangleGeometry(ContractModel):
    """An oriented rectangle; ``size`` is ``[width, depth]`` along local X/Y."""

    type: Literal["rectangle"]
    center: Point2
    size: tuple[PositiveFloat, PositiveFloat]
    rotation_deg: Angle = 0.0


AreaGeometry = Annotated[PolygonGeometry | RectangleGeometry, Field(discriminator="type")]
AnyGeometry = Annotated[
    PointGeometry | PolylineGeometry | PolygonGeometry | RectangleGeometry,
    Field(discriminator="type"),
]


def area_outline(geometry: PolygonGeometry | RectangleGeometry) -> list[Vec2]:
    """Outline of an area geometry as a list of points."""
    if isinstance(geometry, RectangleGeometry):
        return rectangle_corners(
            geometry.center, geometry.size[0], geometry.size[1], geometry.rotation_deg
        )
    return [(float(x), float(y)) for x, y in geometry.points]


def geometry_points(
    geometry: PointGeometry | PolylineGeometry | PolygonGeometry | RectangleGeometry,
) -> list[Vec2]:
    """All defining points of a geometry (rectangles expand to their corners)."""
    if isinstance(geometry, PointGeometry):
        return [geometry.position]
    if isinstance(geometry, RectangleGeometry):
        return area_outline(geometry)
    return [(float(x), float(y)) for x, y in geometry.points]
