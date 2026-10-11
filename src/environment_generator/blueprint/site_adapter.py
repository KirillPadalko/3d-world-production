"""Convert a LocationBlueprint into the generator's internal SiteDescription.

All frame conversion happens here (see :mod:`environment_generator.core.frames`):
blueprint ``[x, y, z]`` (Y up, Z north) becomes generator ``(x, y, z)`` with
Y north and Z up, and clockwise headings become counter-clockwise yaws.

Data the built-in generators do not interpret yet is reported as ``info``
diagnostics (category ``interpretation``) rather than dropped silently.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from environment_generator.blueprint.diagnostics import Category, diagnostic
from environment_generator.blueprint.files import read_heightmap
from environment_generator.core.curves import sample_curve
from environment_generator.core.errors import ExternalDataError
from environment_generator.core.frames import location_yaw_to_generator
from environment_generator.core.geometry import Vec2, cumulative_lengths
from environment_generator.core.issues import ValidationIssue
from environment_generator.models.base import MetadataValue
from environment_generator.models.blueprint import Biome as BlueprintBiome
from environment_generator.models.blueprint import (
    Building as BlueprintBuilding,
)
from environment_generator.models.blueprint import (
    Fence as BlueprintFence,
)
from environment_generator.models.blueprint import (
    InfrastructurePoint as BlueprintInfrastructurePoint,
)
from environment_generator.models.blueprint import (
    LocationBlueprint,
    Provenance,
    RoadSegment,
    Season,
    Wire,
)
from environment_generator.models.geometry import (
    PointGeometry,
    PolygonGeometry,
    PolylineGeometry,
    RectangleGeometry,
)
from environment_generator.models.site import (
    AtmosphereObservation,
    Biome,
    Building,
    Condition,
    Extent,
    Fence,
    FenceGap,
    FenceKind,
    GeoReference,
    GroundCover,
    HeightGrid,
    InfrastructureLine,
    InfrastructurePoint,
    Prop,
    Relief,
    Road,
    RoadKind,
    RoadSurface,
    RoofKind,
    SiteDescription,
    SpeciesWeight,
    TerrainSpec,
    VegetationArea,
    VegetationLine,
    VegetationPoint,
    WallMaterial,
    WaterBody,
    WaterKind,
    Zone,
    ZoneKind,
)

#: Spacing used to sample road curves for the generator.
ROAD_SAMPLE_SPACING_M = 2.0
#: Condition thresholds for the generator's three building states.
INTACT_FROM = 0.6
DAMAGED_FROM = 0.25
#: Cable height when wire poles have no declared height.
DEFAULT_ATTACH_HEIGHT_M = 7.5

BIOMES = {
    BlueprintBiome.TEMPERATE: Biome.TEMPERATE,
    BlueprintBiome.BOREAL: Biome.BOREAL,
    BlueprintBiome.STEPPE: Biome.ARID,
    BlueprintBiome.MEDITERRANEAN: Biome.MEDITERRANEAN,
    BlueprintBiome.ARID: Biome.ARID,
    BlueprintBiome.TROPICAL: Biome.TROPICAL,
    BlueprintBiome.ALPINE: Biome.ALPINE,
    BlueprintBiome.UNKNOWN: Biome.TEMPERATE,
}
GROUND = {
    "grass": GroundCover.GRASS,
    "dirt": GroundCover.DIRT,
    "gravel": GroundCover.GRAVEL,
    "sand": GroundCover.SAND,
    "mud": GroundCover.MUD,
    "asphalt": GroundCover.PAVED,
    "concrete": GroundCover.PAVED,
    "moss": GroundCover.GRASS,
    "leaf_litter": GroundCover.DIRT,
    "rock": GroundCover.ROCK,
    "snow": GroundCover.SNOW,
    "unknown": GroundCover.GRASS,
}
WATER = {
    "pond": WaterKind.POND,
    "lake": WaterKind.LAKE,
    "stream": WaterKind.STREAM,
    "river": WaterKind.RIVER,
    "ditch": WaterKind.DITCH,
    "puddle": WaterKind.POND,
    "marsh": WaterKind.MARSH,
}
ROAD_SURFACE = {
    "asphalt": RoadSurface.ASPHALT,
    "concrete": RoadSurface.CONCRETE,
    "gravel": RoadSurface.GRAVEL,
    "dirt": RoadSurface.DIRT,
    "grass": RoadSurface.DIRT,
    "sand": RoadSurface.DIRT,
    "unknown": RoadSurface.DIRT,
}
ROOFS = {
    "gable": RoofKind.GABLE,
    "hip": RoofKind.HIP,
    "flat": RoofKind.FLAT,
    "shed": RoofKind.MONO_PITCH,
    "mansard": RoofKind.GABLE,
}
WALLS = {
    "wood_log": WallMaterial.WOOD,
    "wood_board": WallMaterial.WOOD,
    "brick": WallMaterial.BRICK,
    "concrete": WallMaterial.CONCRETE,
    "cinder_block": WallMaterial.CONCRETE,
    "stone": WallMaterial.STONE,
    "metal_sheet": WallMaterial.METAL,
    "plaster": WallMaterial.PLASTER,
}
FENCES = {
    "wooden_picket": FenceKind.PICKET,
    "wooden_board": FenceKind.WOODEN,
    "chain_link": FenceKind.CHAIN_LINK,
    "metal_sheet": FenceKind.METAL_SHEET,
    "wire": FenceKind.WIRE,
    "brick": FenceKind.BRICK_WALL,
    "concrete": FenceKind.CONCRETE_WALL,
    "stone": FenceKind.STONE_WALL,
    "metal_railing": FenceKind.METAL_RAILING,
    "unknown": FenceKind.WOODEN,
}
INFRASTRUCTURE = {
    "utility_pole": "utility_pole",
    "well": "well",
    "light": "street_light",
    "sign": "sign",
    "water_tower": "water_tower",
    "container": "container",
    "transformer": "transformer",
    "pump": "pump",
    "other": "other",
}
#: Vegetation zone type -> (generator area kind, density source).
VEGETATION = {
    "forest_dense": "forest",
    "forest_light": "woodland",
    "meadow": "meadow",
    "overgrown_yard": "scrub",
    "road_edge": "scrub",
    "clearing": "meadow",
    "wet_area": "scrub",
    "orchard": "orchard",
    "shrubland": "scrub",
    "unknown": "woodland",
}
GRASSY = {"meadow", "clearing"}
#: Zone types the built-in generators do not populate.
NOT_GENERATED = {"garden_beds"}


@dataclass(frozen=True)
class SiteConversion:
    site: SiteDescription
    dropped: tuple[str, ...]
    notes: tuple[ValidationIssue, ...]


def _note(code: str, message: str, path: str | None = None) -> ValidationIssue:
    return diagnostic("info", code, message, category=Category.INTERPRETATION, path=path)


def _confidence(provenance: Provenance | None) -> float:
    if provenance is None or provenance.confidence is None:
        return 1.0
    return provenance.confidence


def _xz(points: Sequence[Sequence[float]]) -> list[Vec2]:
    return [(float(p[0]), float(p[1])) for p in points]


def _condition(value: float) -> Condition:
    if value >= INTACT_FROM:
        return Condition.INTACT
    if value >= DAMAGED_FROM:
        return Condition.DAMAGED
    return Condition.RUINED


def _attrs(**values: MetadataValue | None) -> dict[str, MetadataValue]:
    return {k: v for k, v in sorted(values.items()) if v is not None}


def _road(segment: RoadSegment, nodes: dict[str, Vec2]) -> Road:
    points = [
        nodes[segment.source_node_id],
        *_xz(segment.curve.control_points),
        nodes[segment.target_node_id],
    ]
    sampled = sample_curve(segment.curve.type.value, points, ROAD_SAMPLE_SPACING_M)
    importance = segment.importance.value
    surface = ROAD_SURFACE[segment.surface.value]
    if importance == "path":
        kind = RoadKind.FOOTPATH
    elif importance == "track" or surface is RoadSurface.DIRT:
        kind = RoadKind.DIRT_TRACK
    elif importance == "primary":
        kind = RoadKind.RURAL_ROAD
    else:
        kind = RoadKind.STREET
    return Road(
        id=segment.id,
        kind=kind,
        geometry=PolylineGeometry(type="polyline", points=sampled),
        width_m=segment.width_m,
        surface=surface,
        importance=segment.importance,
        confidence=_confidence(segment.provenance),
        tags=segment.tags,
        attributes=_attrs(
            conditionScore=segment.condition,
            vegetationIntrusion=segment.vegetation_intrusion,
            sourceSurface=segment.surface.value,
        ),
    )


def _building(b: BlueprintBuilding) -> Building:
    x, _, z = b.transform.position
    return Building(
        id=b.id,
        kind=b.building_type,
        geometry=RectangleGeometry(
            type="rectangle",
            center=(x, z),
            size=(b.dimensions.width_m, b.dimensions.depth_m),
            rotation_deg=location_yaw_to_generator(b.transform.yaw_deg),
        ),
        facing_known=True,
        floors=b.floors or 1,
        roof=ROOFS.get(b.roof_type.value),
        condition=_condition(b.condition),
        wall_material=WALLS.get(b.wall_material.value),
        archetype=b.archetype,
        confidence=_confidence(b.provenance),
        tags=b.tags,
        attributes=_attrs(
            conditionScore=b.condition,
            abandonment=b.abandonment,
            windows=b.openings.windows.value,
            doors=b.openings.doors.value,
            roofType=b.roof_type.value,
            wallMaterial=b.wall_material.value,
            plotId=b.plot_id,
            heightM=b.dimensions.height_m,
        ),
    )


def _fence(f: BlueprintFence) -> Fence:
    points = _xz(f.path)
    ring = [*points, points[0]] if f.closed else points
    total = cumulative_lengths(ring)[-1]
    gaps = [
        FenceGap(offset_m=section.start * total, width_m=(section.end - section.start) * total)
        for section in sorted(f.missing_sections, key=lambda s: s.start)
        if section.end > section.start
    ]
    hints = f.gameplay
    return Fence(
        id=f.id,
        kind=FENCES[f.fence_type.value],
        geometry=PolylineGeometry(type="polyline", points=points),
        height_m=f.height_m,
        closed=f.closed,
        gaps=gaps,
        archetype=f.archetype,
        confidence=_confidence(f.provenance),
        tags=f.tags,
        attributes=_attrs(
            conditionScore=f.condition,
            materialHint=f.material_hint,
            plotId=f.plot_id,
            movement=hints.movement.value if hints and hints.movement else None,
            projectileCover=hints.projectile_cover.value
            if hints and hints.projectile_cover
            else None,
            vision=hints.vision.value if hints and hints.vision else None,
        ),
    )


def _point(position: tuple[float, float, float], yaw: float) -> PointGeometry:
    return PointGeometry(
        type="point",
        position=(position[0], position[2]),
        rotation_deg=location_yaw_to_generator(yaw),
    )


def blueprint_to_site(
    blueprint: LocationBlueprint,
    *,
    package_root: Path | None = None,
    min_confidence: float = 0.0,
) -> SiteConversion:
    """Build the generator view of ``blueprint``.

    Features whose provenance confidence is below ``min_confidence`` are
    dropped (listed in ``dropped``). A heightmap is read from the package
    root; without a root it cannot be honoured and an error is raised.
    """
    notes: list[ValidationIssue] = []
    dropped: list[str] = []

    def keep(collection: str, entity_id: str, provenance: Provenance | None) -> bool:
        if _confidence(provenance) < min_confidence:
            dropped.append(f"{collection}/{entity_id}")
            return False
        return True

    cs = blueprint.coordinate_system
    geo = cs.geo_reference
    terrain = blueprint.terrain
    elevation = terrain.elevation

    height_grid: HeightGrid | None = None
    base = 0.0
    relief = Relief.GENTLE
    if terrain.heightmap is not None:
        if package_root is None:
            raise ExternalDataError(
                "The blueprint references a heightmap but no package root is known; load it "
                "from a file or pass the package root."
            )
        samples = read_heightmap(terrain.heightmap, package_root)
        height_grid = HeightGrid(
            columns=samples.columns, rows=samples.rows, heights=samples.heights
        )
        base = samples.minimum
        relief = Relief.FLAT  # measured heights replace synthetic relief
    elif elevation is not None:
        base = (elevation.min_m + elevation.max_m) / 2.0
        span = elevation.max_m - elevation.min_m
        relief = (
            Relief.FLAT
            if span < 0.5
            else Relief.GENTLE
            if span < 4
            else Relief.HILLY
            if span < 12
            else Relief.RUGGED
        )
    if blueprint.metadata.biome is BlueprintBiome.UNKNOWN:
        notes.append(_note("BIOME_UNKNOWN", "Biome is unknown; using temperate vegetation."))
    for label, count, path in (
        ("surface zones", len(terrain.surface_zones), "terrain.surfaceZones"),
        ("slope zones", len(terrain.slope_zones), "terrain.slopeZones"),
        ("terrain masks", len(terrain.masks), "terrain.masks"),
    ):
        if count:
            notes.append(
                _note(
                    "NOT_INTERPRETED",
                    f"{count} {label} are kept in the blueprint but not used by the built-in "
                    "terrain generator (it applies terrain.defaultSurface).",
                    path,
                )
            )

    water = [
        WaterBody(
            id=w.id,
            kind=WATER[w.water_type.value],
            geometry=PolygonGeometry(type="polygon", points=_xz(w.polygon)),
            confidence=_confidence(w.provenance),
            tags=w.tags,
        )
        for w in terrain.water_bodies
        if keep("waterBodies", w.id, w.provenance)
    ]

    nodes = {n.id: (float(n.position[0]), float(n.position[1])) for n in blueprint.roads.nodes}
    roads = [
        _road(s, nodes)
        for s in blueprint.roads.segments
        if keep("roadSegments", s.id, s.provenance)
    ]

    zones = [
        Zone(
            id=p.id,
            kind=ZoneKind.RESIDENTIAL,
            geometry=PolygonGeometry(type="polygon", points=_xz(p.polygon)),
            density=1.0,
            confidence=_confidence(p.provenance),
            tags=p.tags,
        )
        for p in blueprint.plots
        if p.plot_type.value == "vacant_lot" and keep("plots", p.id, p.provenance)
    ]

    buildings = [_building(b) for b in blueprint.buildings if keep("buildings", b.id, b.provenance)]

    vegetation: list[VegetationArea | VegetationLine | VegetationPoint] = []
    skipped_types: Counter[str] = Counter()
    for zone in blueprint.vegetation_zones:
        if not keep("vegetationZones", zone.id, zone.provenance):
            continue
        zone_type = zone.zone_type.value
        if zone_type in NOT_GENERATED:
            skipped_types[zone_type] += 1
            continue
        kind = VEGETATION[zone_type]
        density = zone.density
        if zone_type in GRASSY and zone.grass_density is not None:
            density = max(density, zone.grass_density)
        vegetation.append(
            VegetationArea(
                id=zone.id,
                kind=kind,  # type: ignore[arg-type]
                geometry=PolygonGeometry(type="polygon", points=_xz(zone.polygon)),
                density=density,
                species=[
                    SpeciesWeight(species=s.species, weight=s.weight)
                    for s in zone.species
                    if s.species != "unknown"
                ],
                understory=zone.understory_density,
                confidence=_confidence(zone.provenance),
                tags=zone.tags,
                attributes=_attrs(
                    zoneType=zone_type,
                    grassDensity=zone.grass_density,
                    minHeightM=zone.height_range.min_m if zone.height_range else None,
                    maxHeightM=zone.height_range.max_m if zone.height_range else None,
                ),
            )
        )
    for zone_type, count in sorted(skipped_types.items()):
        notes.append(
            _note(
                "NOT_INTERPRETED",
                f"{count} vegetation zone(s) of type {zone_type} are not populated by the "
                "built-in vegetation generator.",
                "vegetationZones",
            )
        )
    for tree in blueprint.trees:
        if not keep("trees", tree.id, tree.provenance):
            continue
        vegetation.append(
            VegetationPoint(
                id=tree.id,
                kind="tree",
                geometry=_point(tree.transform.position, tree.transform.yaw_deg),
                height_m=tree.height_m,
                archetype=tree.archetype or (tree.species if tree.species != "unknown" else None),
                confidence=_confidence(tree.provenance),
                tags=tree.tags,
                attributes=_attrs(species=tree.species, conditionScore=tree.condition),
            )
        )

    fences = [_fence(f) for f in blueprint.fences if keep("fences", f.id, f.provenance)]

    infrastructure: list[InfrastructurePoint | InfrastructureLine] = []
    poles: dict[str, BlueprintInfrastructurePoint] = {}
    for item in blueprint.infrastructure:
        if isinstance(item, BlueprintInfrastructurePoint):
            poles[item.id] = item
    for item in blueprint.infrastructure:
        if not keep("infrastructure", item.id, item.provenance):
            continue
        if isinstance(item, BlueprintInfrastructurePoint):
            infrastructure.append(
                InfrastructurePoint(
                    id=item.id,
                    kind=INFRASTRUCTURE[item.infrastructure_type],  # type: ignore[arg-type]
                    geometry=_point(item.transform.position, item.transform.yaw_deg),
                    archetype=item.archetype,
                    confidence=_confidence(item.provenance),
                    tags=item.tags,
                    attributes=_attrs(
                        conditionScore=item.condition,
                        parentId=item.parent_id,
                        heightM=item.height_m,
                        infrastructureType=item.infrastructure_type,
                    ),
                )
            )
        elif isinstance(item, Wire):
            supports = [poles[p] for p in item.pole_ids if p in poles]
            heights = [p.height_m for p in supports if p.height_m is not None]
            attach = min(heights) * 0.92 if heights else DEFAULT_ATTACH_HEIGHT_M
            infrastructure.append(
                InfrastructureLine(
                    id=item.id,
                    kind="telephone_line" if item.wire_kind == "telephone" else "power_line",
                    geometry=PolylineGeometry(
                        type="polyline",
                        points=[
                            (p.transform.position[0], p.transform.position[2]) for p in supports
                        ],
                    ),
                    place_poles=False,
                    attach_height_m=attach,
                    support_ids=[p.id for p in supports],
                    confidence=_confidence(item.provenance),
                    tags=item.tags,
                    attributes=_attrs(
                        conditionScore=item.condition,
                        wireKind=item.wire_kind,
                        sagM=item.sag_m,
                    ),
                )
            )

    props = [
        Prop(
            id=p.id,
            kind=p.prop_type,
            geometry=_point(p.transform.position, p.transform.yaw_deg),
            archetype=p.archetype,
            confidence=_confidence(p.provenance),
            tags=p.tags,
            attributes=_attrs(conditionScore=p.condition, parentId=p.parent_id),
        )
        for p in blueprint.props
        if keep("props", p.id, p.provenance)
    ]

    atmosphere = blueprint.atmosphere
    season = blueprint.metadata.season
    site = SiteDescription(
        id=blueprint.location_id,
        name=blueprint.name,
        extent=Extent(width_m=cs.bounds.width_m, depth_m=cs.bounds.depth_m),
        biome=BIOMES[blueprint.metadata.biome],
        geo_reference=(
            GeoReference(
                latitude=geo.latitude, longitude=geo.longitude, heading_deg=geo.heading_deg
            )
            if geo is not None
            else None
        ),
        terrain=TerrainSpec(
            base_elevation_m=base,
            relief=relief,
            ground_cover=GROUND[terrain.default_surface.value],
            height_grid=height_grid,
        ),
        atmosphere=AtmosphereObservation(
            time_of_day=atmosphere.time_of_day,
            weather=atmosphere.weather,
            season=None if season is Season.UNKNOWN else season,
            ground_wetness=atmosphere.ground_wetness,
            fog_density=atmosphere.fog_density,
            saturation=atmosphere.saturation,
            contrast=atmosphere.contrast,
            abandonment=atmosphere.abandonment,
            vegetation_condition=atmosphere.vegetation_condition,
            palette=list(atmosphere.palette),
        ),
        zones=zones,
        roads=roads,
        buildings=buildings,
        vegetation=vegetation,
        water=water,
        fences=fences,
        infrastructure=infrastructure,
        props=props,
    )
    if blueprint.landmarks or blueprint.gameplay != type(blueprint.gameplay)():
        notes.append(
            _note(
                "PASSED_THROUGH",
                "Landmarks and gameplay annotations are copied to the manifest unchanged.",
            )
        )
    return SiteConversion(site, tuple(dropped), tuple(notes))
