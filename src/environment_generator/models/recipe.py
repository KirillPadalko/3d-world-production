"""LocationRecipe: how a LocationBlueprint is turned into a game environment.

A recipe never contains observations about a place; it describes how to
interpret and transform any blueprint: visual style, generation controls,
asset selection, seeds and per-generator options. It is reusable across
locations. Every field has a default, so
``{"schemaVersion": "1.0", "id": "x", "name": "X"}`` is a complete recipe.

Values left ``null`` fall back to the blueprint's ``generation`` section, then
to built-in defaults (see docs/LOCATION_BLUEPRINT.md, "Recipe and overrides").
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from environment_generator.models.base import (
    ContractModel,
    Description,
    Identifier,
    Metadata,
    Name,
    PositiveFloat,
    Seed,
    Tag,
    UnitInterval,
)
from environment_generator.models.blueprint.atmosphere import TimeOfDay, Weather
from environment_generator.models.blueprint.document import Season, Subsystem
from environment_generator.models.blueprint.roads import RoadImportance
from environment_generator.models.blueprint.structures import BuildingType, PropType


class GeneratorName(StrEnum):
    """Generator slots, in canonical execution order."""

    TERRAIN = "terrain"
    ROADS = "roads"
    BUILDINGS = "buildings"
    FENCES = "fences"
    INFRASTRUCTURE = "infrastructure"
    VEGETATION = "vegetation"
    PROPS = "props"
    ATMOSPHERE = "atmosphere"


class FallbackPolicy(StrEnum):
    """What to do when no archetype in the registry fits a request."""

    PLACEHOLDER = "placeholder"
    ERROR = "error"


class StyleSpec(ContractModel):
    theme: Identifier = "default"
    weathering: UnitInterval = Field(
        default=0.0,
        description="0 = pristine, 1 = heavily worn. >= 0.5 prefers archetypes tagged 'weathered'.",
    )


class AssetSelectionSpec(ContractModel):
    required_tags: list[Tag] = Field(default_factory=list, max_length=32)
    preferred_tags: list[Tag] = Field(default_factory=list, max_length=32)
    excluded_tags: list[Tag] = Field(default_factory=list, max_length=32)
    allowed_archetypes: list[Annotated[str, Field(pattern=r"^[a-z0-9_.*?\[\]-]{1,128}$")]] = Field(
        default_factory=list,
        max_length=256,
        description="Registry archetype ID glob patterns allowed; empty = all.",
    )
    fallback: FallbackPolicy = FallbackPolicy.PLACEHOLDER


class FeatureFilter(ContractModel):
    min_confidence: UnitInterval = Field(
        default=0.0, description="Blueprint features below this confidence are ignored."
    )


class TerrainRecipe(ContractModel):
    enabled: bool = True
    cell_size_m: Annotated[float, Field(ge=0.5, le=50.0)] = 4.0
    noise_amplitude_m: Annotated[float, Field(ge=0.0, le=200.0)] | None = Field(
        default=None, description="Defaults to a value derived from the site relief."
    )
    noise_scale_m: Annotated[float, Field(ge=1.0, le=2000.0)] = 60.0
    octaves: Annotated[int, Field(ge=1, le=8)] = 3
    carve_water: bool = True
    water_depth_m: Annotated[float, Field(ge=0.0, le=20.0)] = 1.5


class RoadRecipe(ContractModel):
    enabled: bool = True
    width_scale: Annotated[float, Field(ge=0.25, le=4.0)] = 1.0
    sample_spacing_m: Annotated[float, Field(ge=0.5, le=100.0)] = 4.0
    detect_junctions: bool = True


def _default_fill_weights() -> dict[BuildingType, float]:
    return {BuildingType.HOUSE: 4.0, BuildingType.SHED: 1.0, BuildingType.GARAGE: 1.0}


class ZoneFillRecipe(ContractModel):
    """Procedurally build on ``vacant_lot`` plots, along the roads that border them."""

    enabled: bool = False
    building_weights: dict[BuildingType, PositiveFloat] = Field(
        default_factory=_default_fill_weights, min_length=1
    )
    lot_spacing_m: Annotated[float, Field(ge=4.0, le=200.0)] = 20.0
    setback_m: Annotated[float, Field(ge=0.0, le=100.0)] = 5.0
    spacing_m: Annotated[float, Field(ge=0.0, le=50.0)] = Field(
        default=3.0, description="Minimum gap between infill buildings and existing objects."
    )
    max_per_zone: Annotated[int, Field(ge=0, le=1000)] = 40


class BuildingRecipe(ContractModel):
    enabled: bool = True
    orient_to_roads: bool = True
    road_search_radius_m: Annotated[float, Field(ge=0.0, le=500.0)] = 40.0
    damage_ratio: UnitInterval = Field(
        default=0.0, description="Share of intact buildings turned into damaged ones."
    )
    ruin_fraction: UnitInterval = Field(
        default=0.25, description="Share of the damaged buildings (above) that become ruins."
    )
    zone_fill: ZoneFillRecipe = Field(default_factory=ZoneFillRecipe)


class VegetationRecipe(ContractModel):
    enabled: bool = True
    density_scale: Annotated[float, Field(ge=0.0, le=10.0)] = 1.0
    min_spacing_m: Annotated[float, Field(ge=0.25, le=50.0)] = 3.0
    max_instances_per_feature: Annotated[int, Field(ge=0, le=20_000)] = 1500
    scale_jitter: Annotated[float, Field(ge=0.0, le=0.9)] = 0.15
    understory_ratio: UnitInterval = Field(
        default=0.2, description="Share of forest/woodland instances that become bushes."
    )
    road_clearance_m: Annotated[float, Field(ge=0.0, le=50.0)] = 1.0
    building_clearance_m: Annotated[float, Field(ge=0.0, le=50.0)] = 1.5


class FenceRecipe(ContractModel):
    enabled: bool = True
    gap_at_roads: bool = Field(
        default=True, description="Leave openings where a fence crosses a road."
    )
    height_scale: Annotated[float, Field(ge=0.25, le=4.0)] = 1.0


class StreetLightRecipe(ContractModel):
    enabled: bool = True
    road_importance: list[RoadImportance] = Field(
        default_factory=lambda: [RoadImportance.SECONDARY],
        description="Roads of these importance classes get street lights.",
    )
    spacing_m: Annotated[float, Field(ge=5.0, le=500.0)] = 30.0
    offset_m: Annotated[float, Field(ge=0.0, le=20.0)] = 0.8
    placement: Literal["alternate", "left", "right", "both"] = "alternate"


class InfrastructureRecipe(ContractModel):
    enabled: bool = True
    pole_spacing_m: Annotated[float, Field(ge=5.0, le=500.0)] = 35.0
    street_lights: StreetLightRecipe = Field(default_factory=StreetLightRecipe)


class ClutterRecipe(ContractModel):
    """Small props scattered around buildings."""

    enabled: bool = True
    per_building: Annotated[float, Field(ge=0.0, le=50.0)] = 1.5
    max_distance_m: Annotated[float, Field(ge=0.5, le=50.0)] = 4.0
    kind_weights: dict[PropType, PositiveFloat] | None = Field(
        default=None,
        description="Replaces the built-in per-building-kind prop tables when set.",
    )


class PropRecipe(ContractModel):
    enabled: bool = True
    clutter: ClutterRecipe = Field(default_factory=ClutterRecipe)


class AtmosphereRecipe(ContractModel):
    """Lighting and weather. ``None`` keeps the blueprint's atmosphere and season."""

    enabled: bool = True
    time_of_day: TimeOfDay | None = None
    weather: Weather | None = None
    season: Season | None = None
    fog_density_scale: Annotated[float, Field(ge=0.0, le=10.0)] = 1.0
    wind_speed_mps: Annotated[float, Field(ge=0.0, le=60.0)] | None = None


class LayoutValidationRecipe(ContractModel):
    fail_on_error: bool = True
    max_entities: Annotated[int, Field(ge=1, le=1_000_000)] = 50_000
    min_building_spacing_m: Annotated[float, Field(ge=0.0, le=50.0)] = 0.5
    check_road_obstruction: bool = True
    check_water_obstruction: bool = True
    ground_tolerance_m: Annotated[float, Field(ge=0.0, le=100.0)] = 2.0


class LocationRecipe(ContractModel):
    """Stylisation and generation settings (public contract v1.0)."""

    schema_version: Literal["1.0"]
    id: Identifier
    name: Name
    description: Description | None = None
    applies_to: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list,
        description="locationId glob patterns this recipe is meant for; empty = any.",
    )
    seed: Seed | None = Field(
        default=None, description="Master seed; null = blueprint generation.masterSeed."
    )
    subsystem_seeds: dict[Subsystem, Seed] = Field(
        default_factory=dict,
        description="Per-subsystem seeds; they win over the blueprint's subsystemSeeds.",
    )
    structural_similarity: UnitInterval | None = Field(
        default=None, description="null = blueprint generation.structuralSimilarity."
    )
    visual_variation: UnitInterval | None = Field(
        default=None, description="null = blueprint generation.visualVariation."
    )
    detail_density: Annotated[float, Field(ge=0.0, le=4.0)] = Field(
        default=1.0, description="Multiplier for procedural detail (clutter, vegetation)."
    )
    abandonment: UnitInterval | None = Field(
        default=None, description="Overall abandonment; null = blueprint atmosphere.abandonment."
    )
    style: StyleSpec = Field(default_factory=StyleSpec)
    assets: AssetSelectionSpec = Field(default_factory=AssetSelectionSpec)
    filters: FeatureFilter = Field(default_factory=FeatureFilter)
    terrain: TerrainRecipe = Field(default_factory=TerrainRecipe)
    roads: RoadRecipe = Field(default_factory=RoadRecipe)
    buildings: BuildingRecipe = Field(default_factory=BuildingRecipe)
    fences: FenceRecipe = Field(default_factory=FenceRecipe)
    infrastructure: InfrastructureRecipe = Field(default_factory=InfrastructureRecipe)
    vegetation: VegetationRecipe = Field(default_factory=VegetationRecipe)
    props: PropRecipe = Field(default_factory=PropRecipe)
    atmosphere: AtmosphereRecipe = Field(default_factory=AtmosphereRecipe)
    validation: LayoutValidationRecipe = Field(default_factory=LayoutValidationRecipe)
    metadata: Metadata = Field(default_factory=dict)

    @classmethod
    def default(cls) -> LocationRecipe:
        """The recipe used when none is supplied."""
        return cls(schema_version="1.0", id="default", name="Default recipe")

    def generator_enabled(self, name: GeneratorName) -> bool:
        """Whether the recipe section of a generator slot is enabled."""
        enabled = getattr(getattr(self, name.value), "enabled", None)
        if not isinstance(enabled, bool):  # pragma: no cover - every section has the flag
            raise KeyError(name)
        return enabled

    def effective_preferred_tags(self) -> list[str]:
        """Preferred asset tags including those implied by the style."""
        tags = list(self.assets.preferred_tags)
        if self.style.weathering >= 0.5 and "weathered" not in tags:
            tags.append("weathered")
        return tags
