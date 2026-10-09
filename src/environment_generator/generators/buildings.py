"""Buildings from blueprint footprints plus optional zone infill along roads."""

from __future__ import annotations

from environment_generator.assets.resolver import AssetRequest, AssetSelection
from environment_generator.core.geometry import (
    Vec2,
    add,
    closest_point_on_polyline,
    dot,
    forward_vector,
    left_normal,
    minimum_area_rectangle,
    normalize_angle_deg,
    point_in_polygon,
    polyline_length,
    rectangle_corners,
    sample_polyline,
    scale,
    sub,
    yaw_facing,
)
from environment_generator.core.issues import ValidationIssue
from environment_generator.core.spatial import Footprint, SpatialIndex
from environment_generator.generators.base import (
    BuildingGenerator,
    GenerationContext,
    GeneratorOutput,
    WorkEstimate,
    feature_ref,
    make_entity,
    numeric_parameter,
)
from environment_generator.models.assets import AssetCategory, AssetNeed
from environment_generator.models.blueprint import (
    Building,
    BuildingKind,
    Condition,
    LocationBlueprint,
    RoofKind,
    Zone,
)
from environment_generator.models.geometry import (
    AreaGeometry,
    PointGeometry,
    RectangleGeometry,
    area_outline,
)
from environment_generator.models.recipe import LocationRecipe
from environment_generator.models.scene import EntityPolyline, SceneEntity

#: Layers infill buildings must keep clear of.
INFILL_BLOCKERS = frozenset(
    {
        AssetCategory.ROAD.value,
        AssetCategory.BUILDING.value,
        AssetCategory.WATER.value,
        AssetCategory.FENCE.value,
    }
)

#: Scale factors beyond this ratio are reported (asset does not fit its footprint).
SCALE_WARNING_RATIO = 1.5

#: Clearance radius kept around surveyed point features that later generators place.
RESERVED_POINT_RADIUS_M = 2.0
RESERVED_LAYER = "reserved"


def reserved_points(blueprint: LocationBlueprint) -> list[Footprint]:
    """Surveyed point features (trees, poles, props ...) that infill must not cover.

    They are placed by generators that run after buildings, so they are not in
    the occupancy index yet.
    """
    reserved: list[Footprint] = []
    for collection in (blueprint.vegetation, blueprint.infrastructure, blueprint.props):
        for feature in collection:
            if isinstance(feature.geometry, PointGeometry):
                reserved.append(
                    Footprint.from_circle(
                        feature.id,
                        RESERVED_LAYER,
                        feature.geometry.position,
                        RESERVED_POINT_RADIUS_M,
                    )
                )
    return reserved


def footprint_rectangle(geometry: AreaGeometry) -> tuple[Vec2, float, float, float]:
    """``(center, width, depth, yaw)`` with ``width >= depth``."""
    if isinstance(geometry, RectangleGeometry):
        center = (float(geometry.center[0]), float(geometry.center[1]))
        width, depth, yaw = geometry.size[0], geometry.size[1], geometry.rotation_deg
    else:
        center, width, depth, yaw = minimum_area_rectangle(area_outline(geometry))
    if width < depth:
        width, depth, yaw = depth, width, yaw + 90.0
    return center, width, depth, normalize_angle_deg(yaw)


class FootprintBuildingGenerator(BuildingGenerator):
    """Places one archetype per building footprint.

    * Polygon footprints are reduced to their minimum-area rectangle.
    * With ``orient_to_roads`` the front (local +Y) faces the nearest road.
    * ``damage_ratio`` deterministically degrades intact buildings.
    * Zone infill samples lots along roads inside matching zones and keeps the
      ones that fit without collisions.
    """

    implementation = "footprint_buildings"
    version = "1.0.0"

    def estimate(self, blueprint: LocationBlueprint, recipe: LocationRecipe) -> WorkEstimate:
        sources = [feature_ref("buildings", b.id) for b in blueprint.buildings]
        needs = [
            AssetNeed(
                category=AssetCategory.BUILDING,
                kinds=[b.kind.value],
                reason=feature_ref("buildings", b.id),
            )
            for b in blueprint.buildings
        ]
        estimate = len(blueprint.buildings)
        fill = recipe.buildings.zone_fill
        if fill.enabled:
            for zone in self._fill_zones(blueprint, recipe):
                sources.append(feature_ref("zones", zone.id))
                lots = sum(
                    2 * int(polyline_length(r.geometry.points) // fill.lot_spacing_m)
                    for r in blueprint.roads
                )
                estimate += min(fill.max_per_zone, int(lots * zone.density))
            needs.extend(
                AssetNeed(
                    category=AssetCategory.BUILDING,
                    kinds=[kind.value],
                    reason="recipe.buildings.zone_fill",
                )
                for kind in sorted(fill.building_weights)
            )
        return WorkEstimate(tuple(sources), estimate, tuple(needs))

    @staticmethod
    def _fill_zones(blueprint: LocationBlueprint, recipe: LocationRecipe) -> list[Zone]:
        kinds = set(recipe.buildings.zone_fill.zone_kinds)
        return sorted((z for z in blueprint.zones if z.kind in kinds), key=lambda z: z.id)

    def generate(self, context: GenerationContext) -> GeneratorOutput:
        output = GeneratorOutput()
        config = context.recipe.buildings
        for building in sorted(context.blueprint.buildings, key=lambda b: b.id):
            entity = self._explicit(context, building, output)
            output.entities.append(entity)
            context.occupy(entity)
        if config.zone_fill.enabled:
            reserved = SpatialIndex()
            reserved.extend(reserved_points(context.blueprint))
            for zone in self._fill_zones(context.blueprint, context.recipe):
                self._fill_zone(context, zone, output, reserved)
        return output

    # ------------------------------------------------------------------ explicit

    def _explicit(
        self, context: GenerationContext, building: Building, output: GeneratorOutput
    ) -> SceneEntity:
        entity_id = f"building.{building.id}"
        center, width, depth, yaw = footprint_rectangle(building.geometry)
        if context.recipe.buildings.orient_to_roads:
            yaw = self._face_nearest_road(context, center, yaw)
        return self._place(
            context,
            output,
            entity_id=entity_id,
            kind=building.kind,
            center=center,
            width=width,
            depth=depth,
            yaw=yaw,
            floors=building.floors,
            roof=building.roof,
            condition=self._condition(context, entity_id, building.condition),
            wall_material=building.wall_material.value if building.wall_material else None,
            rule="explicit_footprint",
            source_feature=feature_ref("buildings", building.id),
            tags=building.tags,
        )

    def _face_nearest_road(self, context: GenerationContext, center: Vec2, yaw: float) -> float:
        radius = context.recipe.buildings.road_search_radius_m
        best: tuple[float, Vec2] | None = None
        for road in context.entities_of(AssetCategory.ROAD):
            if not isinstance(road.geometry, EntityPolyline):
                continue
            points = [(p[0], p[1]) for p in road.geometry.points]
            point, dist = closest_point_on_polyline(center, points)
            if dist <= radius and (best is None or dist < best[0]):
                best = (dist, point)
        if best is None:
            return yaw
        if dot(forward_vector(yaw), sub(best[1], center)) < 0:
            yaw += 180.0
        return normalize_angle_deg(yaw)

    @staticmethod
    def _condition(context: GenerationContext, entity_id: str, base: Condition) -> Condition:
        if base is not Condition.INTACT:
            return base
        config = context.recipe.buildings
        roll = context.unit("damage", entity_id)
        if roll < config.damage_ratio * config.ruin_fraction:
            return Condition.RUINED
        if roll < config.damage_ratio:
            return Condition.DAMAGED
        return Condition.INTACT

    def _place(
        self,
        context: GenerationContext,
        output: GeneratorOutput,
        *,
        entity_id: str,
        kind: BuildingKind,
        center: Vec2,
        width: float,
        depth: float,
        yaw: float,
        floors: int,
        roof: RoofKind | None,
        condition: Condition,
        wall_material: str | None,
        rule: str,
        source_feature: str,
        tags: list[str] | tuple[str, ...] = (),
        selection: AssetSelection | None = None,
    ) -> SceneEntity:
        if selection is None:
            selection = context.assets.resolve(
                AssetRequest(
                    AssetCategory.BUILDING,
                    (kind.value,),
                    entity_id=entity_id,
                    size=(width, depth),
                    floors=floors,
                    roof=roof.value if roof else None,
                    condition=condition.value,
                )
            )
        # Footprints are matched exactly; the archetype keeps its designed height
        # (``floors`` stays available to modular engine-side prefabs).
        nominal = selection.archetype.dimensions
        if selection.archetype.scalable:
            factors = (width / nominal.width_m, depth / nominal.depth_m, 1.0)
        else:
            factors = (1.0, 1.0, 1.0)
        if any(max(f, 1.0 / f) > SCALE_WARNING_RATIO for f in factors):
            output.issues.append(
                ValidationIssue.warning(
                    "BUILDING_SCALE_DEVIATION",
                    f"Archetype {selection.archetype.id} scaled by "
                    f"{', '.join(f'{f:.2f}' for f in factors)} to fit the footprint.",
                    location=source_feature,
                    entity_ids=[entity_id],
                )
            )
        corners = rectangle_corners(center, width, depth, yaw)
        ground = [context.terrain.height_at(x, y) for x, y in corners]
        return make_entity(
            self,
            entity_id=entity_id,
            category=AssetCategory.BUILDING,
            kind=kind.value,
            selection=selection,
            position=(center[0], center[1], min(ground)),
            yaw_deg=yaw,
            scale=factors,
            rule=rule,
            source_feature=source_feature,
            parameters={
                "floors": floors,
                "roof": roof.value if roof else None,
                "condition": condition.value,
                "wall_material": wall_material,
                "foundation_m": max(ground) - min(ground),
            },
            tags=[*tags, condition.value],
        )

    # ------------------------------------------------------------------ infill

    def _fill_zone(
        self,
        context: GenerationContext,
        zone: Zone,
        output: GeneratorOutput,
        reserved: SpatialIndex,
    ) -> None:
        config = context.recipe.buildings.zone_fill
        outline = area_outline(zone.geometry)
        extent = context.blueprint.extent
        kinds = sorted(config.building_weights)
        weights = [config.building_weights[k] for k in kinds]
        road_widths = {
            e.provenance.source_feature: numeric_parameter(e, "width_m")
            for e in context.entities_of(AssetCategory.ROAD)
            if e.kind != "junction"
        }
        placed = 0
        for road in sorted(context.blueprint.roads, key=lambda r: r.id):
            half_width = road_widths.get(feature_ref("roads", road.id), 0.0) / 2.0
            samples = sample_polyline(
                road.geometry.points, config.lot_spacing_m, start_offset=config.lot_spacing_m / 2.0
            )
            for index, (_, point, tangent) in enumerate(samples):
                for side, sign in (("l", 1.0), ("r", -1.0)):
                    if placed >= config.max_per_zone:
                        return
                    lot_id = f"building.fill.{zone.id}.{road.id}.{side}{index:03d}"
                    if context.unit("lot", lot_id) >= zone.density:
                        continue
                    rng = context.rng("lot", lot_id)
                    kind = kinds[rng.weighted_index(weights)]
                    floors = rng.choice((1, 1, 2)) if kind is BuildingKind.HOUSE else 1
                    condition = self._condition(context, lot_id, Condition.INTACT)
                    selection = context.assets.resolve(
                        AssetRequest(
                            AssetCategory.BUILDING,
                            (kind.value,),
                            entity_id=lot_id,
                            floors=floors,
                            condition=condition.value,
                        )
                    )
                    nominal = selection.archetype.dimensions
                    jitter = rng.uniform(0.9, 1.1)
                    width, depth = nominal.width_m * jitter, nominal.depth_m * jitter
                    normal = scale(left_normal(tangent), sign)
                    center = add(point, scale(normal, half_width + config.setback_m + depth / 2.0))
                    yaw = yaw_facing(scale(normal, -1.0))
                    corners = rectangle_corners(center, width, depth, yaw)
                    if not all(point_in_polygon(c, outline) for c in corners):
                        continue
                    if not all(
                        0.0 <= x <= extent.width_m and 0.0 <= y <= extent.depth_m
                        for x, y in corners
                    ):
                        continue
                    probe = Footprint.from_polygon(lot_id, "probe", corners).inflated(
                        config.spacing_m
                    )
                    if context.occupancy.collides(probe, layers=INFILL_BLOCKERS):
                        continue
                    if reserved.collides(probe):
                        continue
                    entity = self._place(
                        context,
                        output,
                        entity_id=lot_id,
                        kind=kind,
                        center=center,
                        width=width,
                        depth=depth,
                        yaw=yaw,
                        floors=floors,
                        roof=None,
                        condition=condition,
                        wall_material=None,
                        rule="zone_infill",
                        source_feature=feature_ref("zones", zone.id),
                        tags=["infill"],
                        selection=selection,
                    )
                    output.entities.append(entity)
                    context.occupy(entity)
                    placed += 1
