"""Abstract scene representation and the portable scene manifest.

Coordinate system (see ``docs/GENERATION_PIPELINE.md``): metres, right-handed,
+X east, +Y north, +Z up, origin at the south-west corner of the extent.
``rotation_deg`` is an extrinsic X-Y-Z Euler rotation; ``rotation_deg[2]`` is
the yaw, counter-clockwise viewed from above. At yaw 0 an object's local +Y
("front") faces world +Y.
"""

from __future__ import annotations

import itertools
from typing import Annotated, Literal

from pydantic import Field, model_validator

from environment_generator.core.geometry import Vec2, rectangle_corners, segment_quad
from environment_generator.core.spatial import Footprint
from environment_generator.core.terrain import Heightfield
from environment_generator.models.assets import AssetCategory, Dimensions
from environment_generator.models.base import (
    ArchetypeId,
    ContractModel,
    EntityId,
    Identifier,
    Point3,
    PositiveFloat,
    UnitInterval,
)
from environment_generator.models.blueprint import (
    Extent,
    GroundCover,
    Season,
    TimeOfDay,
    Weather,
)
from environment_generator.models.recipe import GeneratorName

ParameterValue = str | int | float | bool | list[str]
RGB = tuple[UnitInterval, UnitInterval, UnitInterval]
Precipitation = Literal["none", "rain", "snow"]
Foliage = Literal["fresh", "full", "autumn", "bare"]


class EntityPolyline(ContractModel):
    """World-space polyline (road centre line, cable run ...)."""

    type: Literal["polyline"]
    points: list[Point3] = Field(min_length=2)
    width_m: PositiveFloat | None = Field(
        default=None, description="Ground footprint width; omitted for overhead lines."
    )


class EntityPolygon(ContractModel):
    """World-space polygon (water surface ...)."""

    type: Literal["polygon"]
    points: list[Point3] = Field(min_length=3)


EntityGeometry = Annotated[EntityPolyline | EntityPolygon, Field(discriminator="type")]


class Transform(ContractModel):
    position: Point3
    rotation_deg: Point3 = (0.0, 0.0, 0.0)
    scale: Point3 = (1.0, 1.0, 1.0)

    @property
    def yaw_deg(self) -> float:
        return self.rotation_deg[2]


class Provenance(ContractModel):
    """Why an entity exists: which generator, rule, input feature and overrides."""

    generator: GeneratorName
    implementation: str
    rule: str
    source_feature: str | None = Field(
        default=None, description="Blueprint feature reference, e.g. 'buildings/b-1'."
    )
    overrides: list[str] = Field(default_factory=list)


class SceneEntity(ContractModel):
    id: EntityId
    category: AssetCategory
    kind: str
    archetype_id: ArchetypeId
    asset_ref: str
    variant: Annotated[int, Field(ge=0)] = 0
    placeholder: bool = False
    transform: Transform
    dimensions: Dimensions = Field(description="World-space size after scaling.")
    geometry: EntityGeometry | None = None
    parameters: dict[str, ParameterValue] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    provenance: Provenance


class TerrainData(ContractModel):
    """Regular heightfield. ``heights[row][column]``; row 0 is the southern edge."""

    origin: tuple[float, float] = (0.0, 0.0)
    cell_size_m: PositiveFloat
    columns: Annotated[int, Field(ge=2)]
    rows: Annotated[int, Field(ge=2)]
    heights: list[list[float]]
    min_elevation_m: float
    max_elevation_m: float
    ground_cover: GroundCover

    @model_validator(mode="after")
    def _check_shape(self) -> TerrainData:
        if len(self.heights) != self.rows or any(len(r) != self.columns for r in self.heights):
            raise ValueError("heights must contain `rows` lists of `columns` values")
        return self

    def to_heightfield(self) -> Heightfield:
        return Heightfield(
            cell_size=self.cell_size_m,
            columns=self.columns,
            rows=self.rows,
            heights=tuple(tuple(row) for row in self.heights),
            origin=self.origin,
        )


class AtmosphereSettings(ContractModel):
    """Engine-agnostic lighting and weather description."""

    time_of_day: TimeOfDay
    weather: Weather
    season: Season
    key_light_azimuth_deg: float = Field(
        description="Compass bearing of the key light, clockwise from local +Y (north)."
    )
    key_light_elevation_deg: float
    key_light_direction: Point3 = Field(
        description="Unit vector pointing from the key light towards the scene."
    )
    key_light_color: RGB
    key_light_intensity: Annotated[float, Field(ge=0.0)]
    ambient_color: RGB
    ambient_intensity: Annotated[float, Field(ge=0.0)]
    fog_color: RGB
    fog_density: Annotated[float, Field(ge=0.0)]
    cloud_cover: UnitInterval
    precipitation: Precipitation
    precipitation_intensity: UnitInterval
    wind_speed_mps: Annotated[float, Field(ge=0.0)]
    wind_direction_deg: float
    foliage: Foliage
    style_theme: str
    weathering: UnitInterval


class Scene(ContractModel):
    """Output of the generation stage, before export."""

    blueprint_id: Identifier
    extent: Extent
    terrain: TerrainData | None
    atmosphere: AtmosphereSettings | None
    entities: list[SceneEntity]


class CoordinateSystem(ContractModel):
    units: Literal["meters"] = "meters"
    handedness: Literal["right"] = "right"
    up_axis: Literal["+z"] = "+z"
    x_axis: Literal["east"] = "east"
    y_axis: Literal["north"] = "north"
    origin: Literal["extent_south_west_corner"] = "extent_south_west_corner"
    rotation: Literal["euler_xyz_extrinsic_degrees_ccw"] = "euler_xyz_extrinsic_degrees_ccw"
    forward_axis: Literal["+y"] = "+y"


class GeneratorInfo(ContractModel):
    name: str
    version: str


class ManifestSource(ContractModel):
    blueprint_id: Identifier
    blueprint_name: str
    recipe_id: Identifier
    overrides_id: Identifier | None
    registry_id: Identifier
    seed: int
    generator_seeds: dict[str, int] = Field(
        description="Seed of each generator task (derived from `seed`, see the plan)."
    )
    input_fingerprint: str


class ManifestStatistics(ContractModel):
    entity_count: int
    by_category: dict[str, int]
    by_generator: dict[str, int]
    placeholder_count: int


class SceneManifest(ContractModel):
    """Portable result of a generation run (public output contract v1.0)."""

    manifest_version: Literal["1.0"] = "1.0"
    generator: GeneratorInfo
    coordinate_system: CoordinateSystem = Field(default_factory=CoordinateSystem)
    source: ManifestSource
    extent: Extent
    terrain: TerrainData | None
    atmosphere: AtmosphereSettings | None
    entities: list[SceneEntity]
    statistics: ManifestStatistics
    content_hash: str = Field(
        description="sha256 of the canonical JSON of this manifest without this field."
    )


# --------------------------------------------------------------------------- footprints

#: Fraction of a vegetation instance's canopy treated as solid (trunk + core).
VEGETATION_SOLID_FRACTION = 0.25


def entity_footprints(entity: SceneEntity) -> list[Footprint]:
    """2D ground footprints of an entity, used for collision checks.

    * Ground polylines (roads) become one quad per segment.
    * Overhead polylines (cables) have no footprint.
    * Polygons (water) are used as-is.
    * Vegetation is a circle covering trunk and inner canopy.
    * Everything else is the oriented box of its world-space dimensions.
    """
    layer = entity.category.value
    geometry = entity.geometry
    if entity.category is AssetCategory.TERRAIN:
        return []
    if isinstance(geometry, EntityPolyline):
        if geometry.width_m is None:
            return []
        flat: list[Vec2] = [(p[0], p[1]) for p in geometry.points]
        return [
            Footprint.from_polygon(entity.id, layer, segment_quad(a, b, geometry.width_m / 2.0))
            for a, b in itertools.pairwise(flat)
        ]
    if isinstance(geometry, EntityPolygon):
        return [Footprint.from_polygon(entity.id, layer, [(p[0], p[1]) for p in geometry.points])]
    position = (entity.transform.position[0], entity.transform.position[1])
    width, depth = entity.dimensions.width_m, entity.dimensions.depth_m
    if entity.category is AssetCategory.VEGETATION:
        radius = max(0.1, VEGETATION_SOLID_FRACTION * min(width, depth))
        return [Footprint.from_circle(entity.id, layer, position, radius)]
    if width <= 0 or depth <= 0:
        return []
    corners = rectangle_corners(position, width, depth, entity.transform.yaw_deg)
    return [Footprint.from_polygon(entity.id, layer, corners)]
