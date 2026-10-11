"""SiteDescription: the generator's internal, normalised view of a location.

This model is **internal**. Public input is the
:class:`~environment_generator.models.blueprint.LocationBlueprint` contract;
:mod:`environment_generator.blueprint.site_adapter` converts an (overridden)
blueprint into a ``SiteDescription`` in the generator frame:

* +X east, +Y north, +Z up (right-handed), metres;
* yaw counter-clockwise seen from above; at yaw 0 an object's front (local +Y)
  faces north.

The plan (``generation-plan.json``) embeds this model; it is not a stable
public contract and may change with the generator version.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, get_args

from pydantic import Field, model_validator

from environment_generator.models.base import (
    ContractModel,
    Identifier,
    Metadata,
    Name,
    Point2,
    PositiveFloat,
    Tag,
    UnitInterval,
)
from environment_generator.models.blueprint.atmosphere import PaletteColor, TimeOfDay, Weather
from environment_generator.models.blueprint.document import Season
from environment_generator.models.blueprint.roads import RoadImportance
from environment_generator.models.blueprint.structures import BuildingType as BuildingKind
from environment_generator.models.blueprint.structures import PropType as PropKind
from environment_generator.models.geometry import (
    AreaGeometry,
    PointGeometry,
    PolylineGeometry,
)

# --------------------------------------------------------------------------- enums
# Building, prop, weather, time-of-day and season vocabularies are shared with the
# public LocationBlueprint contract (imported above).


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
    STREAM = "stream"
    CANAL = "canal"
    DITCH = "ditch"
    MARSH = "marsh"


class FenceKind(StrEnum):
    WOODEN = "wooden"
    PICKET = "picket"
    CHAIN_LINK = "chain_link"
    WIRE = "wire"
    METAL_SHEET = "metal_sheet"
    STONE_WALL = "stone_wall"
    BRICK_WALL = "brick_wall"
    CONCRETE_WALL = "concrete_wall"
    METAL_RAILING = "metal_railing"


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
    "sign",
    "container",
    "pump",
    "other",
]
InfrastructureLineKind = Literal["power_line", "telephone_line", "pipeline"]

VEGETATION_AREA_KINDS: tuple[str, ...] = get_args(VegetationAreaKind)
VEGETATION_LINE_KINDS: tuple[str, ...] = get_args(VegetationLineKind)
VEGETATION_POINT_KINDS: tuple[str, ...] = get_args(VegetationPointKind)
INFRASTRUCTURE_POINT_KINDS: tuple[str, ...] = get_args(InfrastructurePointKind)
INFRASTRUCTURE_LINE_KINDS: tuple[str, ...] = get_args(InfrastructureLineKind)

# --------------------------------------------------------------------------- site parts


class GeoReference(ContractModel):
    """Approximate real-world anchor; only used for sun direction."""

    latitude: Annotated[float, Field(ge=-90.0, le=90.0)]
    longitude: Annotated[float, Field(ge=-180.0, le=180.0)]
    heading_deg: Annotated[float, Field(ge=0.0, lt=360.0)] = 0.0


class Extent(ContractModel):
    """Size of the playable area; the origin is its south-west corner."""

    width_m: Annotated[float, Field(gt=0.0, le=5000.0)]
    depth_m: Annotated[float, Field(gt=0.0, le=5000.0)]


class ElevationPoint(ContractModel):
    position: Point2
    elevation_m: Annotated[float, Field(ge=-1000.0, le=9000.0)]


class HeightGrid(ContractModel):
    """Measured heights covering the whole extent; ``heights[row][column]``, row 0 south."""

    columns: Annotated[int, Field(ge=2)]
    rows: Annotated[int, Field(ge=2)]
    heights: list[list[float]]

    @model_validator(mode="after")
    def _check_shape(self) -> HeightGrid:
        if len(self.heights) != self.rows or any(len(r) != self.columns for r in self.heights):
            raise ValueError("heights must contain `rows` lists of `columns` values")
        return self


class TerrainSpec(ContractModel):
    base_elevation_m: Annotated[float, Field(ge=-1000.0, le=9000.0)] = 0.0
    relief: Relief = Relief.GENTLE
    ground_cover: GroundCover = GroundCover.GRASS
    elevation_points: list[ElevationPoint] = Field(default_factory=list, max_length=1000)
    height_grid: HeightGrid | None = Field(
        default=None, description="When present it replaces interpolation and noise."
    )


class AtmosphereObservation(ContractModel):
    """Observed conditions; ``None`` means unknown (generator defaults apply)."""

    time_of_day: TimeOfDay | None = None
    weather: Weather | None = None
    season: Season | None = Field(default=None, description="Never ``unknown`` (use None).")
    ground_wetness: UnitInterval | None = None
    fog_density: UnitInterval | None = None
    saturation: Annotated[float, Field(ge=0.0, le=2.0)] | None = None
    contrast: Annotated[float, Field(ge=0.0, le=2.0)] | None = None
    abandonment: UnitInterval | None = None
    vegetation_condition: UnitInterval | None = None
    palette: list[PaletteColor] = Field(default_factory=list)


# --------------------------------------------------------------------------- features


class Feature(ContractModel):
    """Common fields; ``id`` is the blueprint entity ID it was derived from."""

    id: Identifier
    confidence: UnitInterval = 1.0
    tags: list[Tag] = Field(default_factory=list, max_length=32)
    archetype: str | None = Field(
        default=None, description="Semantic archetype hint requested before the generic kind."
    )
    attributes: Metadata = Field(
        default_factory=dict, description="Blueprint values passed through to entity parameters."
    )


class Zone(Feature):
    """A land-use area. Zones drive procedural infill (e.g. extra houses)."""

    kind: ZoneKind
    geometry: AreaGeometry
    density: UnitInterval = 0.5


#: Importance of a road whose blueprint did not state one.
DEFAULT_IMPORTANCE: dict[RoadKind, RoadImportance] = {
    RoadKind.HIGHWAY: RoadImportance.PRIMARY,
    RoadKind.RURAL_ROAD: RoadImportance.PRIMARY,
    RoadKind.STREET: RoadImportance.SECONDARY,
    RoadKind.DIRT_TRACK: RoadImportance.TRACK,
    RoadKind.FOOTPATH: RoadImportance.PATH,
}


class Road(Feature):
    kind: RoadKind
    geometry: PolylineGeometry
    width_m: Annotated[float, Field(gt=0.3, le=60.0)] | None = None
    surface: RoadSurface | None = None
    importance: RoadImportance | None = None

    @property
    def effective_importance(self) -> RoadImportance:
        return self.importance or DEFAULT_IMPORTANCE[self.kind]


class Building(Feature):
    kind: BuildingKind
    geometry: AreaGeometry
    floors: Annotated[int, Field(ge=1, le=60)] = 1
    roof: RoofKind | None = None
    condition: Condition = Condition.INTACT
    wall_material: WallMaterial | None = None
    facing_known: bool = Field(
        default=False,
        description="Rectangle rotation already points the front (local +Y); keep it as is.",
    )


class SpeciesWeight(ContractModel):
    species: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")]
    weight: PositiveFloat


class VegetationArea(Feature):
    kind: VegetationAreaKind
    geometry: AreaGeometry
    density: UnitInterval = 0.6
    species: list[SpeciesWeight] = Field(default_factory=list)
    understory: UnitInterval | None = None


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
    closed: bool = False
    gaps: list[FenceGap] = Field(default_factory=list, max_length=200)


class InfrastructurePoint(Feature):
    kind: InfrastructurePointKind
    geometry: PointGeometry


class InfrastructureLine(Feature):
    kind: InfrastructureLineKind
    geometry: PolylineGeometry
    pole_spacing_m: Annotated[float, Field(ge=5.0, le=500.0)] | None = None
    place_poles: bool = Field(
        default=True, description="False: poles exist as separate features; emit only the line."
    )
    attach_height_m: Annotated[float, Field(gt=0.0, le=100.0)] | None = Field(
        default=None, description="Cable height above ground when poles are not placed."
    )
    support_ids: list[Identifier] = Field(
        default_factory=list, description="Features carrying the line when place_poles is False."
    )


InfrastructureFeature = Annotated[
    InfrastructurePoint | InfrastructureLine, Field(discriminator="kind")
]


class Prop(Feature):
    kind: PropKind
    geometry: PointGeometry


class FeatureCollection(StrEnum):
    """Names of the feature lists of a site."""

    ZONES = "zones"
    ROADS = "roads"
    BUILDINGS = "buildings"
    VEGETATION = "vegetation"
    WATER = "water"
    FENCES = "fences"
    INFRASTRUCTURE = "infrastructure"
    PROPS = "props"


class SiteDescription(ContractModel):
    """Internal generator input derived from a LocationBlueprint."""

    id: Identifier
    name: Name
    extent: Extent
    biome: Biome = Biome.TEMPERATE
    geo_reference: GeoReference | None = None
    terrain: TerrainSpec = Field(default_factory=TerrainSpec)
    atmosphere: AtmosphereObservation = Field(default_factory=AtmosphereObservation)
    zones: list[Zone] = Field(default_factory=list)
    roads: list[Road] = Field(default_factory=list)
    buildings: list[Building] = Field(default_factory=list)
    vegetation: list[VegetationFeature] = Field(default_factory=list)
    water: list[WaterBody] = Field(default_factory=list)
    fences: list[Fence] = Field(default_factory=list)
    infrastructure: list[InfrastructureFeature] = Field(default_factory=list)
    props: list[Prop] = Field(default_factory=list)

    def collection(self, name: FeatureCollection) -> list[Feature]:
        """Features of one collection, typed as the common base class."""
        return list(getattr(self, name.value))

    def feature_count(self) -> int:
        return sum(len(self.collection(name)) for name in FeatureCollection)


__all__ = [
    "INFRASTRUCTURE_LINE_KINDS",
    "INFRASTRUCTURE_POINT_KINDS",
    "VEGETATION_AREA_KINDS",
    "VEGETATION_LINE_KINDS",
    "VEGETATION_POINT_KINDS",
    "AtmosphereObservation",
    "Biome",
    "Building",
    "BuildingKind",
    "Condition",
    "ElevationPoint",
    "Extent",
    "Feature",
    "FeatureCollection",
    "Fence",
    "FenceGap",
    "FenceKind",
    "GeoReference",
    "GroundCover",
    "HeightGrid",
    "InfrastructureLine",
    "InfrastructurePoint",
    "Prop",
    "PropKind",
    "Relief",
    "Road",
    "RoadKind",
    "RoadSurface",
    "RoofKind",
    "Season",
    "SiteDescription",
    "SpeciesWeight",
    "TerrainSpec",
    "TimeOfDay",
    "VegetationArea",
    "VegetationLine",
    "VegetationPoint",
    "WallMaterial",
    "WaterBody",
    "WaterKind",
    "Weather",
    "Zone",
    "ZoneKind",
]
