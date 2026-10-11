"""Road network as a graph of nodes and curved segments."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from environment_generator.models.blueprint.common import (
    BlueprintModel,
    Elevation,
    EntityBase,
    EntityId,
    Normalized,
    PointXZ,
)


class RoadNodeType(StrEnum):
    ENDPOINT = "endpoint"
    JUNCTION = "junction"
    ENTRANCE = "entrance"
    DEAD_END = "dead_end"
    BOUNDARY = "boundary"
    BRIDGE_END = "bridge_end"


class RoadNode(EntityBase):
    position: PointXZ
    elevation_m: Elevation | None = Field(default=None, description="Estimated, optional.")
    node_type: RoadNodeType = RoadNodeType.ENDPOINT


class CurveType(StrEnum):
    POLYLINE = "polyline"
    CATMULL_ROM = "catmull_rom"


class RoadCurve(BlueprintModel):
    """Centre line from the source node through ``controlPoints`` to the target node.

    * ``polyline``: straight pieces between consecutive points.
    * ``catmull_rom``: centripetal Catmull-Rom spline (alpha = 0.5) through all
      points; the first and last points are duplicated as end tangents. See
      docs/LOCATION_BLUEPRINT.md for the exact formula.
    """

    type: CurveType = CurveType.POLYLINE
    control_points: list[PointXZ] = Field(default_factory=list, max_length=10_000)


class RoadSurface(StrEnum):
    ASPHALT = "asphalt"
    CONCRETE = "concrete"
    GRAVEL = "gravel"
    DIRT = "dirt"
    GRASS = "grass"
    SAND = "sand"
    UNKNOWN = "unknown"


class RoadImportance(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    ACCESS = "access"
    TRACK = "track"
    PATH = "path"


class RoadSegment(EntityBase):
    source_node_id: EntityId
    target_node_id: EntityId
    curve: RoadCurve = Field(default_factory=RoadCurve)
    width_m: Annotated[float, Field(gt=0.3, le=60.0)]
    surface: RoadSurface
    importance: RoadImportance
    condition: Normalized = Field(default=1.0, description="0 = destroyed, 1 = good.")
    vegetation_intrusion: Normalized = Field(
        default=0.0, description="0 = clear, 1 = overgrown edges and centre."
    )


class RoadNetwork(BlueprintModel):
    nodes: list[RoadNode] = Field(default_factory=list, max_length=20_000)
    segments: list[RoadSegment] = Field(default_factory=list, max_length=20_000)
