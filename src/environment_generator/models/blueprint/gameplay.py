"""Landmarks and engine-independent gameplay annotations."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from environment_generator.models.blueprint.common import (
    BlueprintModel,
    CoverLevel,
    EntityBase,
    EntityId,
    Label,
    MovementEffect,
    Normalized,
    PointXZ,
    Polygon,
    Position3,
    Text,
    Vocabulary,
)


class LandmarkType(StrEnum):
    WATER_TOWER = "water_tower"
    CHURCH = "church"
    SHOP = "shop"
    LARGE_TREE = "large_tree"
    CROSSROADS = "crossroads"
    WELL = "well"
    GATE = "gate"
    RUIN = "ruin"
    SIGN = "sign"
    BUS_STOP = "bus_stop"
    BUILDING = "building"
    OTHER = "other"


class Visibility(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Landmark(EntityBase):
    """A navigation-relevant feature. It never creates a rendered object itself."""

    landmark_type: LandmarkType
    position: Position3
    importance: Normalized = 0.5
    visibility: Visibility = Visibility.MEDIUM
    visibility_radius_m: Annotated[float, Field(gt=0.0, le=10_000.0)] | None = None
    linked_entity_id: EntityId | None = Field(
        default=None,
        description="Building, tree, road node or infrastructure entity this landmark marks.",
    )
    gameplay_roles: list[Vocabulary] = Field(
        default_factory=list, description="e.g. navigation, objective, rally_point."
    )


class NavigationArea(EntityBase):
    """Desired walkable or blocked space, as a polygon and/or entity references."""

    area_type: Literal["walkable", "blocked"]
    polygon: Polygon | None = None
    entity_ids: list[EntityId] = Field(default_factory=list)
    reason: Text | None = None


class CoverZone(EntityBase):
    """Where cover is intended; movement, projectiles and vision are separate."""

    polygon: Polygon
    movement: MovementEffect = MovementEffect.NONE
    projectile_cover: CoverLevel = CoverLevel.PARTIAL
    vision: CoverLevel = CoverLevel.PARTIAL
    linked_entity_ids: list[EntityId] = Field(default_factory=list)
    notes: Text | None = None


class CombatZone(EntityBase):
    polygon: Polygon
    intensity: Literal["low", "medium", "high"] = "medium"
    engagement_range: Literal["close", "medium", "long", "mixed"] = "mixed"
    notes: Text | None = None


class SpawnClearance(EntityBase):
    """A circle that must stay free of blocking objects (e.g. a squad spawn)."""

    position: PointXZ
    radius_m: Annotated[float, Field(gt=0.0, le=1000.0)]
    role: Vocabulary = "spawn"


class Connectivity(BlueprintModel):
    """Validation preferences for downstream navigation checks."""

    require_road_network_connected: bool = True
    require_entrances_reachable: bool = True
    entrance_ids: list[EntityId] = Field(
        default_factory=list, description="Road nodes or plots that must be reachable."
    )


class LineOfSight(EntityBase):
    from_position: Position3
    to_position: Position3
    expected: Literal["clear", "partial", "blocked"]
    notes: Text | None = None


class Gameplay(BlueprintModel):
    """Gameplay constraints and annotations, resolved by engine-specific tools."""

    navigation_areas: list[NavigationArea] = Field(default_factory=list, max_length=5000)
    cover_zones: list[CoverZone] = Field(default_factory=list, max_length=5000)
    combat_zones: list[CombatZone] = Field(default_factory=list, max_length=1000)
    spawn_clearances: list[SpawnClearance] = Field(default_factory=list, max_length=1000)
    connectivity: Connectivity = Field(default_factory=Connectivity)
    line_of_sight: list[LineOfSight] = Field(default_factory=list, max_length=5000)
    notes: Label | None = None
