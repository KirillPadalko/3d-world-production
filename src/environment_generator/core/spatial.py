"""Uniform-grid spatial index for 2D occupancy queries.

Generators register the footprints of what they place so later generators can
avoid collisions; the layout validator builds its own index from the finished
scene. Layers are plain strings so this module stays independent of the domain
model (the generator uses asset category names).
"""

from __future__ import annotations

import math
from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass, field

from environment_generator.core.geometry import (
    Bounds,
    Vec2,
    bounds_of,
    bounds_overlap,
    circle_polygon_overlap,
    circles_overlap,
    convex_hull,
    inflate_convex_polygon,
    is_convex,
    polygons_overlap,
)


@dataclass(frozen=True, slots=True)
class Footprint:
    """A 2D shape owned by an entity: either a polygon or a circle."""

    owner_id: str
    layer: str
    polygon: tuple[Vec2, ...] | None = None
    center: Vec2 | None = None
    radius: float = 0.0
    bounds: Bounds = field(default=(0.0, 0.0, 0.0, 0.0), compare=False)

    @classmethod
    def from_polygon(cls, owner_id: str, layer: str, points: Sequence[Vec2]) -> Footprint:
        if len(points) < 3:
            raise ValueError("a polygon footprint needs at least three points")
        return cls(owner_id, layer, polygon=tuple(points), bounds=bounds_of(points))

    @classmethod
    def from_circle(cls, owner_id: str, layer: str, center: Vec2, radius: float) -> Footprint:
        if radius <= 0:
            raise ValueError("a circle footprint needs a positive radius")
        bounds = (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius)
        return cls(owner_id, layer, center=center, radius=radius, bounds=bounds)

    @property
    def is_circle(self) -> bool:
        return self.center is not None

    def intersects(self, other: Footprint) -> bool:
        if not bounds_overlap(self.bounds, other.bounds):
            return False
        if self.center is not None:
            if other.center is not None:
                return circles_overlap(self.center, self.radius, other.center, other.radius)
            assert other.polygon is not None
            return circle_polygon_overlap(self.center, self.radius, other.polygon)
        assert self.polygon is not None
        if other.center is not None:
            return circle_polygon_overlap(other.center, other.radius, self.polygon)
        assert other.polygon is not None
        return polygons_overlap(self.polygon, other.polygon)

    def inflated(self, amount: float) -> Footprint:
        """A copy grown by ``amount`` metres (concave polygons use their hull)."""
        if amount <= 0:
            return self
        if self.center is not None:
            return Footprint.from_circle(
                self.owner_id, self.layer, self.center, self.radius + amount
            )
        assert self.polygon is not None
        base = self.polygon if is_convex(self.polygon) else tuple(convex_hull(self.polygon))
        return Footprint.from_polygon(
            self.owner_id, self.layer, inflate_convex_polygon(base, amount)
        )


class SpatialIndex:
    """Bucket footprints into square cells for fast overlap queries."""

    def __init__(self, cell_size: float = 8.0) -> None:
        if cell_size <= 0:
            raise ValueError("cell_size must be positive")
        self._cell_size = cell_size
        self._items: list[Footprint] = []
        self._cells: dict[tuple[int, int], list[int]] = {}

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[Footprint]:
        return iter(self._items)

    def _cell_range(self, bounds: Bounds) -> Iterator[tuple[int, int]]:
        size = self._cell_size
        x0, y0 = math.floor(bounds[0] / size), math.floor(bounds[1] / size)
        x1, y1 = math.floor(bounds[2] / size), math.floor(bounds[3] / size)
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                yield (cx, cy)

    def insert(self, footprint: Footprint) -> None:
        index = len(self._items)
        self._items.append(footprint)
        for cell in self._cell_range(footprint.bounds):
            self._cells.setdefault(cell, []).append(index)

    def extend(self, footprints: Collection[Footprint]) -> None:
        for footprint in footprints:
            self.insert(footprint)

    def _candidates(self, shape: Footprint) -> list[int]:
        found: set[int] = set()
        for cell in self._cell_range(shape.bounds):
            found.update(self._cells.get(cell, ()))
        return sorted(found)

    def query(
        self,
        shape: Footprint,
        layers: Collection[str] | None = None,
        exclude_owner: str | None = None,
    ) -> list[Footprint]:
        """All stored footprints overlapping ``shape`` (insertion order)."""
        result: list[Footprint] = []
        for index in self._candidates(shape):
            item = self._items[index]
            if layers is not None and item.layer not in layers:
                continue
            if exclude_owner is not None and item.owner_id == exclude_owner:
                continue
            if shape.intersects(item):
                result.append(item)
        return result

    def collides(
        self,
        shape: Footprint,
        layers: Collection[str] | None = None,
        exclude_owner: str | None = None,
    ) -> bool:
        for index in self._candidates(shape):
            item = self._items[index]
            if layers is not None and item.layer not in layers:
                continue
            if exclude_owner is not None and item.owner_id == exclude_owner:
                continue
            if shape.intersects(item):
                return True
        return False
