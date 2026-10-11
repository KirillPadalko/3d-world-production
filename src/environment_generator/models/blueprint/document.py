"""Top-level LocationBlueprint document, metadata, coordinate system, generation."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, Field

from environment_generator.models.blueprint.atmosphere import Atmosphere
from environment_generator.models.blueprint.common import (
    BlueprintModel,
    EntityId,
    Extensions,
    Label,
    Normalized,
    Seed,
    Tag,
    Text,
    sorted_keys,
)
from environment_generator.models.blueprint.gameplay import Gameplay, Landmark
from environment_generator.models.blueprint.nature import Tree, VegetationZone
from environment_generator.models.blueprint.roads import RoadNetwork
from environment_generator.models.blueprint.source import Source, ToolInfo
from environment_generator.models.blueprint.structures import (
    Building,
    Fence,
    InfrastructureItem,
    Plot,
    Prop,
)
from environment_generator.models.blueprint.terrain import Terrain


class LocationStatus(StrEnum):
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class Biome(StrEnum):
    TEMPERATE = "temperate"
    BOREAL = "boreal"
    STEPPE = "steppe"
    MEDITERRANEAN = "mediterranean"
    ARID = "arid"
    TROPICAL = "tropical"
    ALPINE = "alpine"
    UNKNOWN = "unknown"


class Season(StrEnum):
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"
    UNKNOWN = "unknown"


class Metadata(BlueprintModel):
    """Document metadata. The schema version lives only in ``schemaVersion``."""

    created_at: AwareDatetime = Field(description="ISO 8601 timestamp with time zone.")
    updated_at: AwareDatetime | None = None
    created_by: ToolInfo | None = Field(
        default=None, description="Tool or person that produced this document."
    )
    generator_version: Annotated[str, Field(max_length=64)] | None = Field(
        default=None,
        description="Environment Generator version this blueprint was last checked with.",
    )
    authors: list[Label] = Field(default_factory=list, max_length=50)
    tags: list[Tag] = Field(default_factory=list, max_length=64)
    biome: Biome = Biome.UNKNOWN
    season: Season = Season.UNKNOWN
    region: Label | None = Field(
        default=None, description="Approximate, informative region description."
    )


class Bounds(BlueprintModel):
    """Horizontal extent: x in [0, widthM] (east), z in [0, depthM] (north)."""

    width_m: Annotated[float, Field(gt=0.0, le=10_000.0)]
    depth_m: Annotated[float, Field(gt=0.0, le=10_000.0)]


class GeoReference(BlueprintModel):
    """Approximate real-world anchor of the origin. Informative only."""

    latitude: Annotated[float, Field(ge=-90.0, le=90.0)]
    longitude: Annotated[float, Field(ge=-180.0, le=180.0)]
    heading_deg: Annotated[float, Field(ge=0.0, lt=360.0)] = Field(
        default=0.0, description="Compass bearing of local +Z (0 = local north is true north)."
    )
    accuracy_m: Annotated[float, Field(ge=0.0)] | None = None


class CoordinateSystem(BlueprintModel):
    """Declared spatial convention. Only this convention is valid in v1.0.

    The fields are explicit (not implied) so that a document produced for a
    different convention fails validation instead of being silently
    reinterpreted.
    """

    unit: Literal["meter"]
    up_axis: Literal["+y"]
    east_axis: Literal["+x"]
    north_axis: Literal["+z"]
    handedness: Literal["left"]
    yaw_convention: Literal["degrees_clockwise_from_north"]
    origin: Literal["southwest_corner"]
    bounds: Bounds
    geo_reference: GeoReference | None = None


class Subsystem(StrEnum):
    """Generation subsystems that may receive their own seed."""

    TERRAIN = "terrain"
    ROADS = "roads"
    BUILDINGS = "buildings"
    FENCES = "fences"
    INFRASTRUCTURE = "infrastructure"
    VEGETATION = "vegetation"
    PROPS = "props"
    ATMOSPHERE = "atmosphere"
    ASSETS = "assets"


class Generation(BlueprintModel):
    """Generation controls stored with the location (not observations).

    A LocationRecipe may override every value; see docs for precedence.
    """

    master_seed: Seed = 0
    structural_similarity: Normalized = Field(
        default=1.0,
        description="1 = keep the observed structure exactly; lower values allow deviation.",
    )
    visual_variation: Normalized = Field(
        default=0.5, description="0 = uniform look; 1 = maximum variety of assets and details."
    )
    subsystem_seeds: Annotated[dict[Subsystem, Seed], AfterValidator(sorted_keys)] = Field(
        default_factory=dict,
        description="Explicit per-subsystem seeds; others are derived from masterSeed.",
    )


class LocationBlueprint(BlueprintModel):
    """Estimated spatial and semantic structure of a real-world location (v1.0).

    Describes what is known about a place, not how it must be rendered.
    """

    schema_version: Literal["1.0"]
    location_id: EntityId
    name: Label
    description: Text | None = None
    status: LocationStatus = LocationStatus.DRAFT
    metadata: Metadata
    coordinate_system: CoordinateSystem
    generation: Generation = Field(default_factory=Generation)
    source: Source | None = None
    terrain: Terrain = Field(default_factory=Terrain)
    roads: RoadNetwork = Field(default_factory=RoadNetwork)
    plots: list[Plot] = Field(default_factory=list, max_length=5000)
    buildings: list[Building] = Field(default_factory=list, max_length=10_000)
    vegetation_zones: list[VegetationZone] = Field(default_factory=list, max_length=5000)
    trees: list[Tree] = Field(default_factory=list, max_length=10_000)
    fences: list[Fence] = Field(default_factory=list, max_length=10_000)
    infrastructure: list[InfrastructureItem] = Field(default_factory=list, max_length=10_000)
    props: list[Prop] = Field(default_factory=list, max_length=50_000)
    landmarks: list[Landmark] = Field(default_factory=list, max_length=1000)
    gameplay: Gameplay = Field(default_factory=Gameplay)
    atmosphere: Atmosphere = Field(default_factory=Atmosphere)
    extensions: Extensions = Field(default_factory=dict)


#: Top-level collections whose items are addressable by overrides.
ENTITY_COLLECTIONS: tuple[str, ...] = (
    "plots",
    "buildings",
    "vegetation_zones",
    "trees",
    "fences",
    "infrastructure",
    "props",
    "landmarks",
)

__all__ = [
    "ENTITY_COLLECTIONS",
    "Biome",
    "Bounds",
    "CoordinateSystem",
    "Generation",
    "GeoReference",
    "LocationBlueprint",
    "LocationStatus",
    "Metadata",
    "Season",
    "Subsystem",
]
