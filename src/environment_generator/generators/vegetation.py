"""Vegetation: area scatter, orchard grids, line planting and single plants."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from environment_generator.assets.resolver import AssetRequest
from environment_generator.core.geometry import (
    Vec2,
    add,
    bounds_of,
    left_normal,
    minimum_area_rectangle,
    point_in_polygon,
    polygon_area,
    polyline_length,
    rotate,
    sample_polyline,
    scale,
)
from environment_generator.core.issues import ValidationIssue
from environment_generator.core.rng import DeterministicRng
from environment_generator.core.spatial import Footprint
from environment_generator.generators.base import (
    GenerationContext,
    GeneratorOutput,
    VegetationGenerator,
    WorkEstimate,
    feature_ref,
    make_entity,
)
from environment_generator.models.assets import AssetCategory, AssetNeed
from environment_generator.models.blueprint import (
    LocationBlueprint,
    VegetationArea,
    VegetationLine,
    VegetationPoint,
)
from environment_generator.models.geometry import area_outline
from environment_generator.models.recipe import LocationRecipe
from environment_generator.models.scene import VEGETATION_SOLID_FRACTION


@dataclass(frozen=True)
class AreaRule:
    """Instances per 100 m^2 at density 1.0 and the plant kinds to request."""

    per_100m2: float
    kinds: tuple[str, ...]
    understory: bool = False


AREA_RULES: dict[str, AreaRule] = {
    "forest": AreaRule(4.0, ("tree",), understory=True),
    "woodland": AreaRule(1.6, ("tree",), understory=True),
    "scrub": AreaRule(5.0, ("bush",)),
    "meadow": AreaRule(3.0, ("grass_clump",)),
}
ORCHARD_KINDS = ("fruit_tree", "tree")
ORCHARD_MIN_SPACING_M = 6.0
LINE_RULES: dict[str, tuple[float, tuple[str, ...]]] = {
    "hedgerow": (1.6, ("hedge", "bush")),
    "tree_line": (7.0, ("tree",)),
}
POINT_KINDS: dict[str, tuple[str, ...]] = {"tree": ("tree",), "bush": ("bush",)}

#: Spacing multiplier per plant kind (relative to ``min_spacing_m``).
SPACING_FACTOR: dict[str, float] = {
    "tree": 1.0,
    "fruit_tree": 1.0,
    "bush": 0.6,
    "hedge": 0.5,
    "grass_clump": 0.4,
}
VEGETATION_LAYER = AssetCategory.VEGETATION.value


class ScatterVegetationGenerator(VegetationGenerator):
    """Dart-throwing scatter with spacing and clearance from solid objects.

    Instance ids include the candidate index (``vegetation.<feature>.<n>``), so
    a blocked candidate never renumbers the survivors.
    """

    implementation = "scatter_vegetation"
    version = "1.0.0"

    def estimate(self, blueprint: LocationBlueprint, recipe: LocationRecipe) -> WorkEstimate:
        config = recipe.vegetation
        sources: list[str] = []
        needs: list[AssetNeed] = []
        count = 0
        for feature in blueprint.vegetation:
            ref = feature_ref("vegetation", feature.id)
            sources.append(ref)
            if isinstance(feature, VegetationArea):
                outline = area_outline(feature.geometry)
                if feature.kind == "orchard":
                    kinds: tuple[str, ...] = ORCHARD_KINDS
                    spacing = max(config.min_spacing_m, ORCHARD_MIN_SPACING_M)
                    count += int(polygon_area(outline) / spacing**2 * feature.density)
                else:
                    rule = AREA_RULES[feature.kind]
                    kinds = rule.kinds
                    count += self._area_target(rule, polygon_area(outline), feature.density, recipe)
                    if rule.understory:
                        needs.append(
                            AssetNeed(category=AssetCategory.VEGETATION, kinds=["bush"], reason=ref)
                        )
            elif isinstance(feature, VegetationLine):
                spacing, kinds = LINE_RULES[feature.kind]
                count += (
                    int(polyline_length(feature.geometry.points) / (feature.spacing_m or spacing))
                    + 1
                )
            else:
                kinds = POINT_KINDS[feature.kind]
                count += 1
            needs.append(
                AssetNeed(category=AssetCategory.VEGETATION, kinds=list(kinds), reason=ref)
            )
        return WorkEstimate(tuple(sources), count, tuple(needs))

    @staticmethod
    def _area_target(rule: AreaRule, area: float, density: float, recipe: LocationRecipe) -> int:
        config = recipe.vegetation
        target = round(area / 100.0 * rule.per_100m2 * density * config.density_scale)
        return min(int(target), config.max_instances_per_feature)

    def generate(self, context: GenerationContext) -> GeneratorOutput:
        output = GeneratorOutput()
        for feature in sorted(context.blueprint.vegetation, key=lambda f: f.id):
            if isinstance(feature, VegetationArea):
                if feature.kind == "orchard":
                    self._orchard(context, feature, output)
                else:
                    self._scatter(context, feature, output)
            elif isinstance(feature, VegetationLine):
                self._line(context, feature, output)
            else:
                self._point(context, feature, output)
        return output

    # ------------------------------------------------------------------ placement

    def _blocked(self, context: GenerationContext, point: Vec2, radius: float) -> bool:
        config = context.recipe.vegetation
        clearances = (
            (AssetCategory.ROAD, config.road_clearance_m),
            (AssetCategory.BUILDING, config.building_clearance_m),
            (AssetCategory.WATER, 1.0),
            (AssetCategory.FENCE, 0.5),
            (AssetCategory.INFRASTRUCTURE, 1.0),
        )
        for category, clearance in clearances:
            probe = Footprint.from_circle("probe", "probe", point, radius + clearance)
            if context.occupancy.collides(probe, layers={category.value}):
                return True
        return False

    def _try_place(
        self,
        context: GenerationContext,
        output: GeneratorOutput,
        *,
        entity_id: str,
        kinds: tuple[str, ...],
        point: Vec2,
        spacing: float,
        rng: DeterministicRng,
        rule: str,
        source: str,
        source_kind: str,
        tags: Sequence[str],
        explicit: bool = False,
        height: float | None = None,
    ) -> bool:
        extent = context.blueprint.extent
        if not (0.0 <= point[0] <= extent.width_m and 0.0 <= point[1] <= extent.depth_m):
            return False
        spacing_circle = Footprint.from_circle(entity_id, VEGETATION_LAYER, point, spacing / 2.0)
        if not explicit and context.occupancy.collides(spacing_circle, layers={VEGETATION_LAYER}):
            return False
        selection = context.assets.resolve(
            AssetRequest(AssetCategory.VEGETATION, kinds, entity_id=entity_id, height=height)
        )
        nominal = selection.archetype.dimensions
        jitter = context.recipe.vegetation.scale_jitter
        size = 1.0 + rng.uniform(-jitter, jitter)
        if height is not None and nominal.height_m > 0:
            size = height / nominal.height_m
        yaw = rng.uniform(0.0, 360.0)
        trunk = max(0.1, VEGETATION_SOLID_FRACTION * min(nominal.width_m, nominal.depth_m) * size)
        if not explicit and self._blocked(context, point, trunk):
            return False
        entity = make_entity(
            self,
            entity_id=entity_id,
            category=AssetCategory.VEGETATION,
            kind=selection.matched_kind,
            selection=selection,
            position=(point[0], point[1], context.terrain.height_at(*point)),
            yaw_deg=yaw,
            scale=(size, size, size),
            rule=rule,
            source_feature=source,
            parameters={"source_kind": source_kind},
            tags=tags,
        )
        output.entities.append(entity)
        context.occupancy.insert(spacing_circle)
        return True

    # ------------------------------------------------------------------ feature types

    def _scatter(
        self, context: GenerationContext, feature: VegetationArea, output: GeneratorOutput
    ) -> None:
        config = context.recipe.vegetation
        outline = area_outline(feature.geometry)
        rule = AREA_RULES[feature.kind]
        target = self._area_target(rule, polygon_area(outline), feature.density, context.recipe)
        if target <= 0:
            return
        min_x, min_y, max_x, max_y = bounds_of(outline)
        accepted = 0
        for candidate in range(target * 8 + 16):
            if accepted >= target:
                break
            # Each candidate draws from its own stream, so accepting or rejecting one
            # candidate never shifts the position of another.
            rng = context.rng("scatter", feature.id, candidate)
            point = (rng.uniform(min_x, max_x), rng.uniform(min_y, max_y))
            if not point_in_polygon(point, outline):
                continue
            kinds = rule.kinds
            if rule.understory and rng.random() < config.understory_ratio:
                kinds = ("bush",)
            if self._try_place(
                context,
                output,
                entity_id=f"vegetation.{feature.id}.{candidate:05d}",
                kinds=kinds,
                point=point,
                spacing=config.min_spacing_m * SPACING_FACTOR[kinds[0]],
                rng=rng,
                rule="area_scatter",
                source=feature_ref("vegetation", feature.id),
                source_kind=feature.kind,
                tags=feature.tags,
            ):
                accepted += 1
        if accepted < target // 2:
            output.issues.append(
                ValidationIssue.info(
                    "VEGETATION_TARGET_NOT_REACHED",
                    f"Placed {accepted} of {target} instances; spacing or obstacles limit density.",
                    location=feature_ref("vegetation", feature.id),
                )
            )

    def _orchard(
        self, context: GenerationContext, feature: VegetationArea, output: GeneratorOutput
    ) -> None:
        outline = area_outline(feature.geometry)
        spacing = max(context.recipe.vegetation.min_spacing_m, ORCHARD_MIN_SPACING_M)
        center, width, depth, yaw = minimum_area_rectangle(outline)
        columns = max(1, int(width // spacing))
        rows = max(1, int(depth // spacing))
        for row in range(rows):
            for column in range(columns):
                entity_id = f"vegetation.{feature.id}.r{row:02d}c{column:02d}"
                if context.unit("orchard", entity_id) >= feature.density:
                    continue
                rng = context.rng("orchard", entity_id)
                local = (
                    (column + 0.5) * spacing - columns * spacing / 2.0 + rng.uniform(-0.3, 0.3),
                    (row + 0.5) * spacing - rows * spacing / 2.0 + rng.uniform(-0.3, 0.3),
                )
                point = add(center, rotate(local, yaw))
                if not point_in_polygon(point, outline):
                    continue
                self._try_place(
                    context,
                    output,
                    entity_id=entity_id,
                    kinds=ORCHARD_KINDS,
                    point=point,
                    spacing=spacing * 0.8,
                    rng=rng,
                    rule="orchard_grid",
                    source=feature_ref("vegetation", feature.id),
                    source_kind=feature.kind,
                    tags=feature.tags,
                )

    def _line(
        self, context: GenerationContext, feature: VegetationLine, output: GeneratorOutput
    ) -> None:
        default_spacing, kinds = LINE_RULES[feature.kind]
        spacing = feature.spacing_m or default_spacing
        for index, (_, point, tangent) in enumerate(
            sample_polyline(feature.geometry.points, spacing, spacing / 2.0)
        ):
            rng = context.rng("line", feature.id, index)
            offset = scale(left_normal(tangent), rng.uniform(-0.3, 0.3))
            self._try_place(
                context,
                output,
                entity_id=f"vegetation.{feature.id}.{index:04d}",
                kinds=kinds,
                point=add(point, offset),
                spacing=spacing * 0.9,
                rng=rng,
                rule="line_planting",
                source=feature_ref("vegetation", feature.id),
                source_kind=feature.kind,
                tags=feature.tags,
            )

    def _point(
        self, context: GenerationContext, feature: VegetationPoint, output: GeneratorOutput
    ) -> None:
        kinds = POINT_KINDS[feature.kind]
        self._try_place(
            context,
            output,
            entity_id=f"vegetation.{feature.id}",
            kinds=kinds,
            point=feature.geometry.position,
            spacing=context.recipe.vegetation.min_spacing_m * SPACING_FACTOR[kinds[0]],
            rng=context.rng("point", feature.id),
            rule="explicit_point",
            source=feature_ref("vegetation", feature.id),
            source_kind=feature.kind,
            tags=feature.tags,
            explicit=True,
            height=feature.height_m,
        )
