"""Vegetation zones and significant individual trees."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from environment_generator.models.blueprint.common import (
    ArchetypeName,
    BlueprintModel,
    EntityBase,
    HeightRange,
    Normalized,
    Polygon,
    PositiveMetres,
    Transform,
    Vocabulary,
)

#: Species name used when the source does not allow reliable classification.
UNKNOWN_SPECIES = "unknown"


class VegetationZoneType(StrEnum):
    FOREST_DENSE = "forest_dense"
    FOREST_LIGHT = "forest_light"
    MEADOW = "meadow"
    OVERGROWN_YARD = "overgrown_yard"
    ROAD_EDGE = "road_edge"
    CLEARING = "clearing"
    WET_AREA = "wet_area"
    ORCHARD = "orchard"
    GARDEN_BEDS = "garden_beds"
    SHRUBLAND = "shrubland"
    UNKNOWN = "unknown"


class SpeciesWeight(BlueprintModel):
    """Relative share of a species; consumers use ``weight / sum(weights)``."""

    species: Vocabulary = Field(description="e.g. birch, pine, spruce, lilac, or 'unknown'.")
    weight: Annotated[float, Field(gt=0.0, le=1_000_000.0)]


class VegetationZone(EntityBase):
    """An area of vegetation described statistically (not tree by tree)."""

    zone_type: VegetationZoneType
    polygon: Polygon
    density: Normalized = Field(description="Canopy/plant density, 0 = bare, 1 = closed.")
    species: list[SpeciesWeight] = Field(
        default_factory=list,
        max_length=64,
        description="Relative weights; empty = species unknown.",
    )
    understory_density: Normalized | None = None
    grass_density: Normalized | None = None
    height_range: HeightRange | None = Field(default=None, description="Typical plant heights.")


class Tree(EntityBase):
    """A significant individual tree (landmark, cover, or notable object)."""

    species: Vocabulary = UNKNOWN_SPECIES
    archetype: ArchetypeName | None = None
    transform: Transform
    height_m: PositiveMetres | None = None
    crown_diameter_m: PositiveMetres | None = None
    condition: Normalized = Field(default=1.0, description="0 = dead or broken, 1 = healthy.")
