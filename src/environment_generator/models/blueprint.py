"""LocationBlueprint: the public, engine-agnostic description of a real location.

A blueprint states *what is there* (roads, buildings, vegetation, ...) as
observed or surveyed. It deliberately contains no stylisation or game rules;
those live in :mod:`environment_generator.models.recipe`. Future location
analysis tooling (drone footage -> frames -> analysis) produces blueprints that
conform to ``schemas/location-blueprint.schema.json``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, get_args

from pydantic import Field

from environment_generator.models.base import (
    ContractModel,
    Description,
    Identifier,
    Metadata,
    Name,
    Point2,
    PositiveFloat,
    Tag,
    UnitInterval,
)
from environment_generator.models.geometry import (
    AreaGeometry,
    PointGeometry,
    PolylineGeometry,
)

# --------------------------------------------------------------------------- enums


class SourceKind(StrEnum):
    MANUAL = "manual"
    DRONE_SURVEY = "drone_survey"
    SATELLITE = "satellite"
    SYNTHETIC = "synthetic"


class Biome(StrEnum):
    TEMPERATE = "temperate"
    BOREAL = "boreal"
    MEDITERRANEAN = "mediterranean"
    ARID = "arid"
    TROPICAL = "tropical"
    ALPINE = "alpine"


class Relief(StrEnum):
    FLAT = "flat"
    GENTLE = "gentle"
    HILLY = "hilly"
    RUGGED = "rugged"


class GroundCover(StrEnum):
    GRASS = "grass"
    DIRT = "dirt"
    SAND = "sand"
    GRAVEL = "gravel"
    SNOW = "snow"
    MUD = "mud"
    ROCK = "rock"
    PAVED = "paved"


class ZoneKind(StrEnum):
    RESIDENTIAL = "residential"
    COMMERCIAL = "commercial"
    INDUSTRIAL = "industrial"
    AGRICULTURAL = "agricultural"
    MILITARY = "military"
    PARK = "park"
    FOREST = "forest"
    OPEN_FIELD = "open_field"
    WASTELAND = "wasteland"


class RoadKind(StrEnum):
    HIGHWAY = "highway"
    STREET = "street"
    RURAL_ROAD = "rural_road"
    DIRT_TRACK = "dirt_track"
    FOOTPATH = "footpath"


class RoadSurface(StrEnum):
    ASPHALT = "asphalt"
    CONCRETE = "concrete"
    GRAVEL = "gravel"
    DIRT = "dirt"
    COBBLESTONE = "cobblestone"


class BuildingKind(StrEnum):
    HOUSE = "house"
    APARTMENT_BLOCK = "apartment_block"
    BARN = "barn"
    SHED = "shed"
    GARAGE = "garage"
    WAREHOUSE = "warehouse"
    FACTORY = "factory"
    SHOP = "shop"
    OFFICE = "office"
    CHURCH = "church"


class RoofKind(StrEnum):
    FLAT = "flat"
    GABLE = "gable"
    HIP = "hip"
    MONO_PITCH = "mono_pitch"


class WallMaterial(StrEnum):
    BRICK = "brick"
    WOOD = "wood"
    CONCRETE = "concrete"
    STONE = "stone"
    PLASTER = "plaster"
    METAL = "metal"


class Condition(StrEnum):
    INTACT = "intact"
    DAMAGED = "damaged"
    RUINED = "ruined"


class WaterKind(StrEnum):
    POND = "pond"
    LAKE = "lake"
    RIVER = "river"
    CANAL = "canal"
    MARSH = "marsh"


class FenceKind(StrEnum):
    WOODEN = "wooden"
    PICKET = "picket"
    CHAIN_LINK = "chain_link"
    WIRE = "wire"
    STONE_WALL = "stone_wall"
    BRICK_WALL = "brick_wall"
    CONCRETE_WALL = "concrete_wall"
    METAL_RAILING = "metal_railing"


class PropKind(StrEnum):
    VEHICLE = "vehicle"
    WRECK = "wreck"
    CRATE = "crate"
    BARREL = "barrel"
    PALLET = "pallet"
    SANDBAGS = "sandbags"
    HAY_BALE = "hay_bale"
    BENCH = "bench"
    DUMPSTER = "dumpster"
    CART = "cart"
    FIREWOOD = "firewood"
    TIRES = "tires"
    GENERIC = "generic"


class TimeOfDay(StrEnum):
    DAWN = "dawn"
    MORNING = "morning"
    NOON = "noon"
    AFTERNOON = "afternoon"
    DUSK = "dusk"
    NIGHT = "night"


class Weather(StrEnum):
    CLEAR = "clear"
    PARTLY_CLOUDY = "partly_cloudy"
    OVERCAST = "overcast"
    FOG = "fog"
    RAIN = "rain"
    STORM = "storm"
    SNOW = "snow"


class Season(StrEnum):
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"


VegetationAreaKind = Literal["forest", "woodland", "orchard", "scrub", "meadow"]
VegetationLineKind = Literal["hedgerow", "tree_line"]
VegetationPointKind = Literal["tree", "bush"]
InfrastructurePointKind = Literal[
    "street_light",
    "utility_pole",
    "transformer",
    "water_tower",
    "antenna_mast",
    "bus_stop",
    "well",
    "billboard",
]
InfrastructureLineKind = Literal["power_line", "telephone_line", "pipeline"]

VEGETATION_AREA_KINDS: tuple[str, ...] = get_args(VegetationAreaKind)
VEGETATION_LINE_KINDS: tuple[str, ...] = get_args(VegetationLineKind)
VEGETATION_POINT_KINDS: tuple[str, ...] = get_args(VegetationPointKind)
INFRASTRUCTURE_POINT_KINDS: tuple[str, ...] = get_args(InfrastructurePointKind)
INFRASTRUCTURE_LINE_KINDS: tuple[str, ...] = get_args(InfrastructureLineKind)

# --------------------------------------------------------------------------- document parts


class BlueprintSource(ContractModel):
    """Where the blueprint came from; informative, recorded in provenance."""

    kind: SourceKind = SourceKind.MANUAL
    reference: Annotated[str, Field(max_length=500)] | None = None
    captured_at: datetime | None = None
    analyzer: Annotated[str, Field(max_length=200)] | None = Field(
        default=None, description="Tool and version that produced the blueprint."
    )
    notes: Description | None = None


class GeoReference(ContractModel):
    """Optional real-world anchor of the local origin. Never required."""

    latitude: Annotated[float, Field(ge=-90.0, le=90.0)]
    longitude: Annotated[float, Field(ge=-180.0, le=180.0)]
    heading_deg: Annotated[float, Field(ge=0.0, lt=360.0)] = Field(
        default=0.0,
        description="Compass bearing of the local +Y axis (0 = local north is true north).",
    )
    altitude_m: float | None = None


class Extent(ContractModel):
    """Size of the playable area; the origin is its south-west corner."""

    width_m: Annotated[float, Field(gt=0.0, le=5000.0)]
    depth_m: Annotated[float, Field(gt=0.0, le=5000.0)]


class ElevationPoint(ContractModel):
    position: Point2
    elevation_m: Annotated[float, Field(ge=-1000.0, le=9000.0)]


class TerrainSpec(ContractModel):
    base_elevation_m: Annotated[float, Field(ge=-1000.0, le=9000.0)] = 0.0
    relief: Relief = Relief.GENTLE
    ground_cover: GroundCover = GroundCover.GRASS
    elevation_points: list[ElevationPoint] = Field(
        default_factory=list,
        max_length=1000,
        description="Surveyed spot heights; the terrain interpolates through them.",
    )


class AtmosphereObservation(ContractModel):
    """Conditions observed in the source material. The recipe may override them."""

    time_of_day: TimeOfDay | None = None
    weather: Weather | None = None
    season: Season | None = None


# --------------------------------------------------------------------------- features


class Feature(ContractModel):
    """Common fields of every blueprint feature."""

    id: Identifier
    confidence: UnitInterval = Field(
        default=1.0, description="Certainty of the analysis that produced this feature."
    )
    tags: list[Tag] = Field(default_factory=list, max_length=32)
    notes: Description | None = None


class Zone(Feature):
    """A land-use area. Zones drive procedural infill (e.g. extra houses)."""

    kind: ZoneKind
    geometry: AreaGeometry
    density: UnitInterval = 0.5


class Road(Feature):
    kind: RoadKind
    geometry: PolylineGeometry
    width_m: Annotated[float, Field(gt=0.5, le=60.0)] | None = None
    surface: RoadSurface | None = None


class Building(Feature):
    kind: BuildingKind
    geometry: AreaGeometry
    floors: Annotated[int, Field(ge=1, le=60)] = 1
    roof: RoofKind | None = None
    condition: Condition = Condition.INTACT
    wall_material: WallMaterial | None = None


class VegetationArea(Feature):
    kind: VegetationAreaKind
    geometry: AreaGeometry
    density: UnitInterval = 0.6


class VegetationLine(Feature):
    kind: VegetationLineKind
    geometry: PolylineGeometry
    spacing_m: Annotated[float, Field(ge=0.5, le=100.0)] | None = None


class VegetationPoint(Feature):
    kind: VegetationPointKind
    geometry: PointGeometry
    height_m: Annotated[float, Field(gt=0.0, le=120.0)] | None = None


VegetationFeature = Annotated[
    VegetationArea | VegetationLine | VegetationPoint, Field(discriminator="kind")
]


class WaterBody(Feature):
    kind: WaterKind
    geometry: AreaGeometry


class FenceGap(ContractModel):
    """An opening (gate, breach) measured along the fence polyline."""

    offset_m: Annotated[float, Field(ge=0.0)]
    width_m: PositiveFloat


class Fence(Feature):
    kind: FenceKind
    geometry: PolylineGeometry
    height_m: Annotated[float, Field(gt=0.0, le=10.0)] | None = None
    closed: bool = Field(default=False, description="Connect the last point back to the first.")
    gaps: list[FenceGap] = Field(default_factory=list, max_length=100)


class InfrastructurePoint(Feature):
    kind: InfrastructurePointKind
    geometry: PointGeometry


class InfrastructureLine(Feature):
    kind: InfrastructureLineKind
    geometry: PolylineGeometry
    pole_spacing_m: Annotated[float, Field(ge=5.0, le=500.0)] | None = None


InfrastructureFeature = Annotated[
    InfrastructurePoint | InfrastructureLine, Field(discriminator="kind")
]


class Prop(Feature):
    kind: PropKind
    geometry: PointGeometry


# --------------------------------------------------------------------------- document


class FeatureCollection(StrEnum):
    """Names of the feature lists of a blueprint (used by overrides)."""

    ZONES = "zones"
    ROADS = "roads"
    BUILDINGS = "buildings"
    VEGETATION = "vegetation"
    WATER = "water"
    FENCES = "fences"
    INFRASTRUCTURE = "infrastructure"
    PROPS = "props"


class LocationBlueprint(ContractModel):
    """Structured description of a real-world location (public contract v1.0)."""

    schema_version: Literal["1.0"]
    id: Identifier
    name: Name
    description: Description | None = None
    source: BlueprintSource = Field(default_factory=BlueprintSource)
    geo_reference: GeoReference | None = None
    extent: Extent
    biome: Biome = Biome.TEMPERATE
    terrain: TerrainSpec = Field(default_factory=TerrainSpec)
    atmosphere: AtmosphereObservation = Field(default_factory=AtmosphereObservation)
    zones: list[Zone] = Field(default_factory=list, max_length=500)
    roads: list[Road] = Field(default_factory=list, max_length=2000)
    buildings: list[Building] = Field(default_factory=list, max_length=5000)
    vegetation: list[VegetationFeature] = Field(default_factory=list, max_length=5000)
    water: list[WaterBody] = Field(default_factory=list, max_length=500)
    fences: list[Fence] = Field(default_factory=list, max_length=2000)
    infrastructure: list[InfrastructureFeature] = Field(default_factory=list, max_length=5000)
    props: list[Prop] = Field(default_factory=list, max_length=10_000)
    metadata: Metadata = Field(default_factory=dict)

    def collection(self, name: FeatureCollection) -> list[Feature]:
        """Features of one collection, typed as the common base class."""
        return list(getattr(self, name.value))

    def feature_count(self) -> int:
        return sum(len(self.collection(name)) for name in FeatureCollection)
