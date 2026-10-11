"""Builders for small LocationBlueprint v1.0 documents (camelCase JSON dicts).

Every builder returns plain JSON data so tests can also produce invalid
documents; :func:`make_location` validates strictly like the public loader.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any

from environment_generator.models.blueprint import LocationBlueprint

Point = Sequence[float]


def location_data(**changes: Any) -> dict[str, Any]:
    """A minimal valid blueprint (100 m x 80 m); keywords replace top-level keys."""
    data: dict[str, Any] = {
        "schemaVersion": "1.0",
        "locationId": "test-location",
        "name": "Test location",
        "metadata": {"createdAt": "2026-01-01T00:00:00Z"},
        "coordinateSystem": {
            "unit": "meter",
            "upAxis": "+y",
            "eastAxis": "+x",
            "northAxis": "+z",
            "handedness": "left",
            "yawConvention": "degrees_clockwise_from_north",
            "origin": "southwest_corner",
            "bounds": {"widthM": 100, "depthM": 80},
        },
    }
    data.update(copy.deepcopy(changes))
    return data


def make_location(**changes: Any) -> LocationBlueprint:
    return LocationBlueprint.model_validate(location_data(**changes), by_alias=True, by_name=False)


def node(node_id: str, x: float, z: float, node_type: str = "endpoint") -> dict[str, Any]:
    return {"id": node_id, "position": [x, z], "nodeType": node_type}


def segment(
    segment_id: str,
    source: str,
    target: str,
    *,
    width: float = 6.0,
    surface: str = "asphalt",
    importance: str = "secondary",
    control: Sequence[Point] = (),
    curve: str = "polyline",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": segment_id,
        "sourceNodeId": source,
        "targetNodeId": target,
        "curve": {"type": curve, "controlPoints": [list(p) for p in control]},
        "widthM": width,
        "surface": surface,
        "importance": importance,
        **extra,
    }


def straight_road(
    segment_id: str = "s-1", start: Point = (0, 40), end: Point = (100, 40), **extra: Any
) -> dict[str, Any]:
    """A road network with one segment between two boundary nodes."""
    return {
        "nodes": [
            node(f"{segment_id}-a", start[0], start[1], "boundary"),
            node(f"{segment_id}-b", end[0], end[1], "boundary"),
        ],
        "segments": [segment(segment_id, f"{segment_id}-a", f"{segment_id}-b", **extra)],
    }


def transform(x: float, z: float, yaw: float = 0.0, y: float = 0.0) -> dict[str, Any]:
    return {"position": [x, y, z], "yawDeg": yaw}


def building(
    building_id: str,
    x: float,
    z: float,
    *,
    yaw: float = 0.0,
    width: float = 8.0,
    depth: float = 6.0,
    height: float = 6.0,
    building_type: str = "house",
    archetype: str = "house",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": building_id,
        "archetype": archetype,
        "buildingType": building_type,
        "transform": transform(x, z, yaw),
        "dimensions": {"widthM": width, "depthM": depth, "heightM": height},
        **extra,
    }


def tree(tree_id: str, x: float, z: float, **extra: Any) -> dict[str, Any]:
    return {"id": tree_id, "transform": transform(x, z), **extra}


def fence(
    fence_id: str,
    path: Sequence[Point],
    *,
    fence_type: str = "wooden_board",
    height: float = 1.5,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": fence_id,
        "fenceType": fence_type,
        "path": [list(p) for p in path],
        "heightM": height,
        **extra,
    }


def pole(pole_id: str, x: float, z: float, height: float = 8.0, **extra: Any) -> dict[str, Any]:
    return {
        "id": pole_id,
        "infrastructureType": "utility_pole",
        "transform": transform(x, z),
        "heightM": height,
        **extra,
    }


def wire(wire_id: str, pole_ids: Sequence[str], **extra: Any) -> dict[str, Any]:
    return {
        "id": wire_id,
        "infrastructureType": "wire",
        "wireKind": "power",
        "poleIds": list(pole_ids),
        **extra,
    }


def prop(
    prop_id: str, x: float, z: float, prop_type: str = "barrel", **extra: Any
) -> dict[str, Any]:
    return {"id": prop_id, "propType": prop_type, "transform": transform(x, z), **extra}


def vegetation_zone(
    zone_id: str,
    polygon: Sequence[Point],
    *,
    zone_type: str = "forest_dense",
    density: float = 0.6,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": zone_id,
        "zoneType": zone_type,
        "polygon": [list(p) for p in polygon],
        "density": density,
        **extra,
    }


def rect(x0: float, z0: float, x1: float, z1: float) -> list[list[float]]:
    return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]
