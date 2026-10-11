"""Built structures: plots, buildings, fences, infrastructure, props."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from environment_generator.models.blueprint.common import (
    ArchetypeName,
    BlueprintModel,
    EntityBase,
    EntityId,
    GameplayHints,
    Normalized,
    Polygon,
    Polyline,
    PositiveMetres,
    Transform,
    Vocabulary,
)

# --------------------------------------------------------------------------- plots


class PlotType(StrEnum):
    DACHA_PLOT = "dacha_plot"
    YARD = "yard"
    GARDEN = "garden"
    VACANT_LOT = "vacant_lot"
    COMMON_AREA = "common_area"
    UNKNOWN = "unknown"


class Plot(EntityBase):
    """A land parcel or yard boundary (the fence around it is a separate entity)."""

    plot_type: PlotType
    polygon: Polygon
    condition: Normalized | None = Field(default=None, description="Upkeep of the plot.")
    abandonment: Normalized | None = None


# --------------------------------------------------------------------------- buildings


class BuildingType(StrEnum):
    HOUSE = "house"
    BATHHOUSE = "bathhouse"
    GARAGE = "garage"
    SHED = "shed"
    BARN = "barn"
    GREENHOUSE = "greenhouse"
    OUTHOUSE = "outhouse"
    GAZEBO = "gazebo"
    WORKSHOP = "workshop"
    SHOP = "shop"
    CHURCH = "church"
    APARTMENT_BLOCK = "apartment_block"
    WAREHOUSE = "warehouse"
    FACTORY = "factory"
    OFFICE = "office"
    OTHER = "other"
    UNKNOWN = "unknown"


class RoofType(StrEnum):
    GABLE = "gable"
    HIP = "hip"
    FLAT = "flat"
    SHED = "shed"
    MANSARD = "mansard"
    COLLAPSED = "collapsed"
    UNKNOWN = "unknown"


class WallMaterial(StrEnum):
    WOOD_LOG = "wood_log"
    WOOD_BOARD = "wood_board"
    BRICK = "brick"
    CONCRETE = "concrete"
    CINDER_BLOCK = "cinder_block"
    STONE = "stone"
    METAL_SHEET = "metal_sheet"
    PLASTER = "plaster"
    GLASS = "glass"
    UNKNOWN = "unknown"


class WindowState(StrEnum):
    INTACT = "intact"
    BROKEN = "broken"
    BOARDED = "boarded"
    MISSING = "missing"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class DoorState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    BROKEN = "broken"
    MISSING = "missing"
    BOARDED = "boarded"
    UNKNOWN = "unknown"


class Openings(BlueprintModel):
    windows: WindowState = WindowState.UNKNOWN
    doors: DoorState = DoorState.UNKNOWN


class Dimensions(BlueprintModel):
    """Size in the entity's local frame: X width, Z depth (front side), Y height."""

    width_m: PositiveMetres
    depth_m: PositiveMetres
    height_m: PositiveMetres


class Building(EntityBase):
    archetype: ArchetypeName
    building_type: BuildingType
    transform: Transform = Field(
        description="Centre of the footprint at ground level; yaw = direction the front faces."
    )
    dimensions: Dimensions
    footprint: Polygon | None = Field(
        default=None,
        description="Exact outline in location coordinates; omitted = rectangle from dimensions.",
    )
    floors: Annotated[int, Field(ge=1, le=60)] | None = None
    condition: Normalized = Field(default=1.0, description="0 = destroyed, 1 = good condition.")
    abandonment: Normalized = Field(
        default=0.0, description="0 = inhabited or maintained, 1 = strongly abandoned."
    )
    roof_type: RoofType = RoofType.UNKNOWN
    wall_material: WallMaterial = WallMaterial.UNKNOWN
    openings: Openings = Field(default_factory=Openings)
    plot_id: EntityId | None = None


# --------------------------------------------------------------------------- fences


class FenceType(StrEnum):
    WOODEN_PICKET = "wooden_picket"
    WOODEN_BOARD = "wooden_board"
    CHAIN_LINK = "chain_link"
    METAL_SHEET = "metal_sheet"
    WIRE = "wire"
    BRICK = "brick"
    CONCRETE = "concrete"
    STONE = "stone"
    METAL_RAILING = "metal_railing"
    UNKNOWN = "unknown"


class MissingSection(BlueprintModel):
    """A gap given as normalised arc length along the path (0 = start, 1 = end)."""

    start: Normalized
    end: Normalized


class Fence(EntityBase):
    fence_type: FenceType
    path: Polyline
    closed: bool = Field(default=False, description="The path returns to its first point.")
    height_m: Annotated[float, Field(gt=0.0, le=10.0)]
    condition: Normalized = 1.0
    missing_sections: list[MissingSection] = Field(default_factory=list, max_length=500)
    archetype: ArchetypeName | None = None
    material_hint: Vocabulary | None = None
    plot_id: EntityId | None = None
    gameplay: GameplayHints | None = None


# --------------------------------------------------------------------------- infrastructure

PointInfrastructureType = Literal[
    "utility_pole",
    "well",
    "light",
    "sign",
    "water_tower",
    "container",
    "transformer",
    "pump",
    "other",
]


class InfrastructurePoint(EntityBase):
    """A persistent structure at one place (pole, well, light, sign ...)."""

    infrastructure_type: PointInfrastructureType
    archetype: ArchetypeName | None = None
    transform: Transform
    height_m: PositiveMetres | None = None
    condition: Normalized = 1.0
    parent_id: EntityId | None = Field(
        default=None, description="Structure it is attached to (e.g. a light on a pole)."
    )
    gameplay: GameplayHints | None = None


class Wire(EntityBase):
    """Overhead wire strung along an ordered chain of utility poles."""

    infrastructure_type: Literal["wire"]
    wire_kind: Literal["power", "telephone", "unknown"] = "unknown"
    pole_ids: Annotated[list[EntityId], Field(min_length=2, max_length=1000)]
    sag_m: Annotated[float, Field(ge=0.0, le=20.0)] | None = None
    condition: Normalized = 1.0


InfrastructureItem = Annotated[
    InfrastructurePoint | Wire, Field(discriminator="infrastructure_type")
]


# --------------------------------------------------------------------------- props


class PropType(StrEnum):
    BARREL = "barrel"
    TIRES = "tires"
    PALLET = "pallet"
    WOODPILE = "woodpile"
    TOOLS = "tools"
    BICYCLE = "bicycle"
    WHEELBARROW = "wheelbarrow"
    DEBRIS = "debris"
    BUCKET = "bucket"
    BENCH = "bench"
    CRATE = "crate"
    GAS_CYLINDER = "gas_cylinder"
    CAR = "car"
    CAR_WRECK = "car_wreck"
    BOAT = "boat"
    CART = "cart"
    DUMPSTER = "dumpster"
    HAY_BALE = "hay_bale"
    SANDBAGS = "sandbags"
    OTHER = "other"


class Prop(EntityBase):
    """An individual object or piece of clutter."""

    prop_type: PropType
    archetype: ArchetypeName | None = None
    transform: Transform
    condition: Normalized = 1.0
    parent_id: EntityId | None = Field(
        default=None, description="Plot, building, structure or prop it belongs to or rests on."
    )


__all__ = [
    "Building",
    "BuildingType",
    "Dimensions",
    "DoorState",
    "Fence",
    "FenceType",
    "InfrastructureItem",
    "InfrastructurePoint",
    "MissingSection",
    "Openings",
    "Plot",
    "PlotType",
    "PointInfrastructureType",
    "Prop",
    "PropType",
    "RoofType",
    "WallMaterial",
    "WindowState",
    "Wire",
]
