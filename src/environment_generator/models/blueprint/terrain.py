"""Terrain: elevation, external height data, surface and slope zones, water."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from environment_generator.models.blueprint.common import (
    BlueprintModel,
    Elevation,
    EntityBase,
    EntityId,
    FileReference,
    Polygon,
    Text,
    Vocabulary,
)


class RasterEncoding(StrEnum):
    """Supported raw raster encodings (headerless, little-endian)."""

    RAW_U8 = "raw_u8"
    RAW_U16_LE = "raw_u16_le"
    RAW_F32_LE = "raw_f32_le"


#: Bytes per sample for each encoding.
ENCODING_BYTES: dict[RasterEncoding, int] = {
    RasterEncoding.RAW_U8: 1,
    RasterEncoding.RAW_U16_LE: 2,
    RasterEncoding.RAW_F32_LE: 4,
}


class RowOrder(StrEnum):
    """Which edge the first row of a raster lies on (columns always run west to east)."""

    SOUTH_TO_NORTH = "south_to_north"
    NORTH_TO_SOUTH = "north_to_south"


class RasterGrid(BlueprintModel):
    """A raster covering exactly the horizontal bounds, corner-aligned.

    Sample ``(column 0, first row)`` lies on the west edge and the edge named
    by ``rowOrder``; the last column lies on the east edge. Spacing is
    ``widthM / (columns - 1)`` by ``depthM / (rows - 1)``.
    """

    file: FileReference
    encoding: RasterEncoding
    columns: Annotated[int, Field(ge=2, le=16_385)]
    rows: Annotated[int, Field(ge=2, le=16_385)]
    row_order: RowOrder


class Heightmap(RasterGrid):
    """Elevation raster: ``elevation_m = heightOffsetM + value * heightScaleM``."""

    encoding: Literal[RasterEncoding.RAW_U16_LE, RasterEncoding.RAW_F32_LE]
    height_scale_m: Annotated[float, Field(gt=0.0, le=1000.0)]
    height_offset_m: Elevation = 0.0


class TerrainMask(RasterGrid):
    """A single-channel mask, e.g. wetness or grass density (value / 255 -> 0..1)."""

    id: EntityId
    encoding: Literal[RasterEncoding.RAW_U8]
    meaning: Vocabulary = Field(description="What the mask encodes, e.g. ground_wetness.")


class ElevationRange(BlueprintModel):
    min_m: Elevation
    max_m: Elevation


class SurfaceType(StrEnum):
    GRASS = "grass"
    DIRT = "dirt"
    GRAVEL = "gravel"
    SAND = "sand"
    MUD = "mud"
    ASPHALT = "asphalt"
    CONCRETE = "concrete"
    MOSS = "moss"
    LEAF_LITTER = "leaf_litter"
    ROCK = "rock"
    SNOW = "snow"
    UNKNOWN = "unknown"


class SurfaceZone(EntityBase):
    """Ground material inside a polygon (geometry and passability are separate)."""

    surface: SurfaceType
    polygon: Polygon


class SlopeClass(StrEnum):
    FLAT = "flat"  # < 3 degrees
    GENTLE = "gentle"  # 3-8
    MODERATE = "moderate"  # 8-15
    STEEP = "steep"  # 15-30
    CLIFF = "cliff"  # > 30


class SlopeZone(EntityBase):
    slope_class: SlopeClass
    polygon: Polygon
    average_slope_deg: Annotated[float, Field(ge=0.0, le=90.0)] | None = None
    aspect_deg: Annotated[float, Field(ge=0.0, lt=360.0)] | None = Field(
        default=None, description="Downhill direction, clockwise from north."
    )


class WaterType(StrEnum):
    POND = "pond"
    LAKE = "lake"
    STREAM = "stream"
    RIVER = "river"
    DITCH = "ditch"
    PUDDLE = "puddle"
    MARSH = "marsh"


class WaterBody(EntityBase):
    water_type: WaterType
    polygon: Polygon
    surface_elevation_m: Elevation | None = None
    depth_m: Annotated[float, Field(ge=0.0, le=500.0)] | None = None


class Terrain(BlueprintModel):
    """Ground of the location. It always covers the full coordinateSystem.bounds."""

    elevation: ElevationRange | None = Field(
        default=None, description="Lowest and highest ground elevation, metres."
    )
    heightmap: Heightmap | None = None
    masks: list[TerrainMask] = Field(default_factory=list, max_length=64)
    default_surface: SurfaceType = SurfaceType.GRASS
    surface_zones: list[SurfaceZone] = Field(default_factory=list, max_length=5000)
    slope_zones: list[SlopeZone] = Field(default_factory=list, max_length=5000)
    water_bodies: list[WaterBody] = Field(default_factory=list, max_length=1000)
    notes: Text | None = None
