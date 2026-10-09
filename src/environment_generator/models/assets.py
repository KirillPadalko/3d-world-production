"""Asset registry contract: abstract archetypes the generator can place.

An *archetype* is an engine-agnostic asset kind ("small gable house", "oak
tree") with nominal dimensions and selection metadata. ``asset_ref`` is an
opaque key that an engine integration maps to a concrete prefab, mesh or
addressable. The built-in registry uses logical ``envgen://`` keys.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from environment_generator.models.base import (
    ArchetypeId,
    ContractModel,
    Description,
    Identifier,
    Name,
    PositiveFloat,
    Tag,
)
from environment_generator.models.blueprint import Biome, Condition, RoadSurface, RoofKind


class AssetCategory(StrEnum):
    TERRAIN = "terrain"
    WATER = "water"
    ROAD = "road"
    BUILDING = "building"
    FENCE = "fence"
    INFRASTRUCTURE = "infrastructure"
    VEGETATION = "vegetation"
    PROP = "prop"


class CoverLevel(StrEnum):
    """Tactical hint for the game: how much protection the object offers."""

    NONE = "none"
    PARTIAL = "partial"
    HALF = "half"
    FULL = "full"


class Dimensions(ContractModel):
    """Axis-aligned size in the object's local frame (X width, Y depth, Z height)."""

    width_m: Annotated[float, Field(ge=0.0)]
    depth_m: Annotated[float, Field(ge=0.0)]
    height_m: Annotated[float, Field(ge=0.0)]


class ArchetypeConstraints(ContractModel):
    """Soft constraints; mismatches lower an archetype's fit score."""

    min_floors: Annotated[int, Field(ge=1)] | None = None
    max_floors: Annotated[int, Field(ge=1)] | None = None
    roofs: list[RoofKind] | None = None
    conditions: list[Condition] | None = None
    surfaces: list[RoadSurface] | None = None


class Archetype(ContractModel):
    id: ArchetypeId
    category: AssetCategory
    kinds: list[Annotated[str, Field(pattern=r"^[a-z0-9_]+$")]] = Field(
        min_length=1, description="Semantic kinds this archetype can represent."
    )
    tags: list[Tag] = Field(default_factory=list, max_length=32)
    dimensions: Dimensions
    variants: Annotated[int, Field(ge=1, le=1000)] = 1
    asset_ref: Annotated[str, Field(min_length=1, max_length=512)]
    weight: PositiveFloat = Field(default=1.0, description="Relative selection weight.")
    biomes: list[Biome] = Field(default_factory=list, description="Empty means any biome.")
    cover: CoverLevel | None = None
    scalable: bool = Field(
        default=True, description="Whether non-uniform scaling to fit a footprint is acceptable."
    )
    constraints: ArchetypeConstraints = Field(default_factory=ArchetypeConstraints)
    description: Description | None = None


class AssetRegistryDocument(ContractModel):
    """A set of archetypes (public contract v1.0)."""

    schema_version: Literal["1.0"]
    id: Identifier
    name: Name
    description: Description | None = None
    archetypes: list[Archetype] = Field(min_length=1, max_length=20_000)


class AssetNeed(ContractModel):
    """An archetype kind a generator expects to request."""

    category: AssetCategory
    kinds: list[str] = Field(min_length=1, description="Acceptable kinds in preference order.")
    reason: str


class AssetPalette(ContractModel):
    """Archetypes usable for one generation run, after recipe filtering."""

    registry_id: Identifier
    registry_fingerprint: str
    archetypes: list[Archetype]
    excluded_archetypes: int = Field(ge=0)
    category_counts: dict[AssetCategory, int]
    unmet_needs: list[AssetNeed] = Field(default_factory=list)

    def get(self, archetype_id: str) -> Archetype | None:
        for archetype in self.archetypes:
            if archetype.id == archetype_id:
                return archetype
        return None
