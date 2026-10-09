"""Point infrastructure, pole-and-cable lines and recipe-driven street lights."""

from __future__ import annotations

import math

from environment_generator.assets.resolver import AssetRequest, AssetSelection
from environment_generator.core.geometry import (
    Vec2,
    add,
    bounds_of,
    cumulative_lengths,
    left_normal,
    point_along_polyline,
    rectangle_corners,
    sample_polyline,
    scale,
    yaw_facing,
)
from environment_generator.core.issues import ValidationIssue
from environment_generator.core.spatial import Footprint
from environment_generator.generators.base import (
    GenerationContext,
    GeneratorOutput,
    InfrastructureGenerator,
    WorkEstimate,
    feature_ref,
    make_entity,
    numeric_parameter,
)
from environment_generator.models.assets import AssetCategory, AssetNeed, Dimensions
from environment_generator.models.blueprint import (
    InfrastructureLine,
    InfrastructurePoint,
    LocationBlueprint,
)
from environment_generator.models.recipe import LocationRecipe
from environment_generator.models.scene import EntityPolyline, SceneEntity

#: Kinds requested for the poles and the conductor of each line type.
LINE_POLE_KINDS: dict[str, tuple[str, ...]] = {
    "power_line": ("power_pole", "utility_pole"),
    "telephone_line": ("telephone_pole", "utility_pole"),
}
LINE_CABLE_KINDS: dict[str, tuple[str, ...]] = {
    "power_line": ("power_cable",),
    "telephone_line": ("telephone_cable",),
}

#: Layers a pole or street light must not stand on.
SOLID_BLOCKERS = frozenset(
    {
        AssetCategory.ROAD.value,
        AssetCategory.BUILDING.value,
        AssetCategory.WATER.value,
        AssetCategory.FENCE.value,
        AssetCategory.INFRASTRUCTURE.value,
    }
)

#: Distances tried (along the line) when a pole position is blocked.
POLE_NUDGES_M = (0.0, 2.0, -2.0, 4.0, -4.0, 6.0, -6.0)
#: Cables attach this fraction of the pole height above ground.
CABLE_ATTACH_FRACTION = 0.92


class StandardInfrastructureGenerator(InfrastructureGenerator):
    implementation = "standard_infrastructure"
    version = "1.0.0"

    def estimate(self, blueprint: LocationBlueprint, recipe: LocationRecipe) -> WorkEstimate:
        sources: list[str] = []
        needs: list[AssetNeed] = []
        count = 0
        spacing = recipe.infrastructure.pole_spacing_m
        for feature in blueprint.infrastructure:
            ref = feature_ref("infrastructure", feature.id)
            sources.append(ref)
            if isinstance(feature, InfrastructurePoint):
                count += 1
                needs.append(
                    AssetNeed(
                        category=AssetCategory.INFRASTRUCTURE, kinds=[feature.kind], reason=ref
                    )
                )
            else:
                length = sum(
                    math.dist(a, b)
                    for a, b in zip(
                        feature.geometry.points, feature.geometry.points[1:], strict=False
                    )
                )
                if feature.kind == "pipeline":
                    count += 1
                    needs.append(
                        AssetNeed(
                            category=AssetCategory.INFRASTRUCTURE, kinds=["pipeline"], reason=ref
                        )
                    )
                else:
                    count += 2 + int(length // (feature.pole_spacing_m or spacing))
                    needs.append(
                        AssetNeed(
                            category=AssetCategory.INFRASTRUCTURE,
                            kinds=list(LINE_POLE_KINDS[feature.kind]),
                            reason=ref,
                        )
                    )
                    needs.append(
                        AssetNeed(
                            category=AssetCategory.INFRASTRUCTURE,
                            kinds=list(LINE_CABLE_KINDS[feature.kind]),
                            reason=ref,
                        )
                    )
        lights = recipe.infrastructure.street_lights
        if lights.enabled:
            kinds = set(lights.road_kinds)
            lit = [r for r in blueprint.roads if r.kind in kinds]
            if lit:
                needs.append(
                    AssetNeed(
                        category=AssetCategory.INFRASTRUCTURE,
                        kinds=["street_light"],
                        reason="recipe.infrastructure.street_lights",
                    )
                )
            for road in lit:
                sources.append(feature_ref("roads", road.id))
                length = sum(
                    math.dist(a, b)
                    for a, b in zip(road.geometry.points, road.geometry.points[1:], strict=False)
                )
                count += int(length // lights.spacing_m) + 1
        return WorkEstimate(tuple(sources), count, tuple(needs))

    def generate(self, context: GenerationContext) -> GeneratorOutput:
        output = GeneratorOutput()
        features = sorted(context.blueprint.infrastructure, key=lambda f: f.id)
        for feature in features:
            if isinstance(feature, InfrastructurePoint):
                self._point(context, feature, output)
        for feature in features:
            if isinstance(feature, InfrastructureLine):
                if feature.kind == "pipeline":
                    self._pipeline(context, feature, output)
                else:
                    self._pole_line(context, feature, output)
        if context.recipe.infrastructure.street_lights.enabled:
            self._street_lights(context, output)
        return output

    # ------------------------------------------------------------------ points

    def _point(
        self, context: GenerationContext, feature: InfrastructurePoint, output: GeneratorOutput
    ) -> None:
        entity_id = f"infrastructure.{feature.id}"
        x, y = feature.geometry.position
        selection = context.assets.resolve(
            AssetRequest(AssetCategory.INFRASTRUCTURE, (feature.kind,), entity_id=entity_id)
        )
        entity = make_entity(
            self,
            entity_id=entity_id,
            category=AssetCategory.INFRASTRUCTURE,
            kind=feature.kind,
            selection=selection,
            position=(x, y, context.terrain.height_at(x, y)),
            yaw_deg=feature.geometry.rotation_deg,
            rule="explicit_point",
            source_feature=feature_ref("infrastructure", feature.id),
            tags=feature.tags,
        )
        output.entities.append(entity)
        context.occupy(entity)

    # ------------------------------------------------------------------ lines

    def _pipeline(
        self, context: GenerationContext, feature: InfrastructureLine, output: GeneratorOutput
    ) -> None:
        entity_id = f"infrastructure.{feature.id}"
        selection = context.assets.resolve(
            AssetRequest(AssetCategory.INFRASTRUCTURE, ("pipeline",), entity_id=entity_id)
        )
        diameter = selection.archetype.dimensions.depth_m
        points = [
            (x, y, context.terrain.height_at(x, y) + diameter / 2.0)
            for x, y in feature.geometry.points
        ]
        output.entities.append(
            self._line_entity(context, feature, entity_id, "pipeline", selection, points, diameter)
        )
        context.occupy(output.entities[-1])

    def _pole_line(
        self, context: GenerationContext, feature: InfrastructureLine, output: GeneratorOutput
    ) -> None:
        ref = feature_ref("infrastructure", feature.id)
        spacing = feature.pole_spacing_m or context.recipe.infrastructure.pole_spacing_m
        points = list(feature.geometry.points)
        cumulative = cumulative_lengths(points)
        # Poles at every vertex and evenly in between so no span exceeds `spacing`.
        offsets: list[float] = []
        for i in range(len(points) - 1):
            span = cumulative[i + 1] - cumulative[i]
            pieces = max(1, math.ceil(span / spacing))
            offsets.extend(cumulative[i] + span * k / pieces for k in range(pieces))
        offsets.append(cumulative[-1])

        poles: list[SceneEntity] = []
        dropped = 0
        for index, offset in enumerate(offsets):
            pole_id = f"infrastructure.{feature.id}.pole{index:03d}"
            selection = context.assets.resolve(
                AssetRequest(
                    AssetCategory.INFRASTRUCTURE, LINE_POLE_KINDS[feature.kind], entity_id=pole_id
                )
            )
            placed = self._place_pole(
                context, feature, pole_id, selection, points, cumulative, offset
            )
            if placed is None:
                dropped += 1
                continue
            poles.append(placed)
        if dropped:
            output.issues.append(
                ValidationIssue.warning(
                    "INFRASTRUCTURE_POLE_DROPPED",
                    f"{dropped} pole(s) could not be placed without collisions.",
                    location=ref,
                )
            )
        for i, pole in enumerate(poles):
            neighbours = [poles[j].id for j in (i - 1, i + 1) if 0 <= j < len(poles)]
            pole = pole.model_copy(
                update={
                    "parameters": {
                        **pole.parameters,
                        "connects_to": neighbours,
                        "line_id": feature.id,
                    }
                }
            )
            poles[i] = pole
            output.entities.append(pole)
            context.occupy(pole)
        if len(poles) >= 2:
            cable_points = [
                (
                    p.transform.position[0],
                    p.transform.position[1],
                    p.transform.position[2] + p.dimensions.height_m * CABLE_ATTACH_FRACTION,
                )
                for p in poles
            ]
            cable_id = f"infrastructure.{feature.id}.cable"
            selection = context.assets.resolve(
                AssetRequest(
                    AssetCategory.INFRASTRUCTURE, LINE_CABLE_KINDS[feature.kind], entity_id=cable_id
                )
            )
            output.entities.append(
                self._line_entity(
                    context, feature, cable_id, "cable", selection, cable_points, None
                )
            )

    def _place_pole(
        self,
        context: GenerationContext,
        feature: InfrastructureLine,
        pole_id: str,
        selection: AssetSelection,
        points: list[tuple[float, float]],
        cumulative: list[float],
        offset: float,
    ) -> SceneEntity | None:
        dims = selection.archetype.dimensions
        for nudge in POLE_NUDGES_M:
            point, tangent = point_along_polyline(points, cumulative, offset + nudge)
            corners = rectangle_corners(point, dims.width_m, dims.depth_m, 0.0)
            probe = Footprint.from_polygon(pole_id, "probe", corners).inflated(0.3)
            if context.occupancy.collides(probe, layers=SOLID_BLOCKERS):
                continue
            return make_entity(
                self,
                entity_id=pole_id,
                category=AssetCategory.INFRASTRUCTURE,
                kind=selection.matched_kind,
                selection=selection,
                position=(point[0], point[1], context.terrain.height_at(*point)),
                yaw_deg=yaw_facing(left_normal(tangent)),
                rule="line_pole",
                source_feature=feature_ref("infrastructure", feature.id),
                tags=feature.tags,
            )
        return None

    def _line_entity(
        self,
        context: GenerationContext,
        feature: InfrastructureLine,
        entity_id: str,
        kind: str,
        selection: AssetSelection,
        points: list[tuple[float, float, float]],
        width: float | None,
    ) -> SceneEntity:
        flat: list[Vec2] = [(p[0], p[1]) for p in points]
        min_x, min_y, max_x, max_y = bounds_of(flat)
        return make_entity(
            self,
            entity_id=entity_id,
            category=AssetCategory.INFRASTRUCTURE,
            kind=kind,
            selection=selection,
            position=points[0],
            rule="line_" + kind,
            source_feature=feature_ref("infrastructure", feature.id),
            parameters={"line_id": feature.id, "line_kind": feature.kind},
            tags=feature.tags,
            geometry=EntityPolyline(type="polyline", points=points, width_m=width),
            dimensions=Dimensions(
                width_m=max_x - min_x,
                depth_m=max_y - min_y,
                height_m=max(p[2] for p in points) - min(p[2] for p in points),
            ),
        )

    # ------------------------------------------------------------------ street lights

    def _street_lights(self, context: GenerationContext, output: GeneratorOutput) -> None:
        config = context.recipe.infrastructure.street_lights
        kinds = {k.value for k in config.road_kinds}
        road_entities = {
            e.provenance.source_feature: e
            for e in context.entities_of(AssetCategory.ROAD)
            if e.kind in kinds
        }
        extent = context.blueprint.extent
        for road in sorted(context.blueprint.roads, key=lambda r: r.id):
            road_entity = road_entities.get(feature_ref("roads", road.id))
            if road_entity is None:
                continue
            half_width = numeric_parameter(road_entity, "width_m") / 2.0
            samples = sample_polyline(
                road.geometry.points, config.spacing_m, config.spacing_m / 2.0
            )
            for index, (_, point, tangent) in enumerate(samples):
                if config.placement == "both":
                    sides = [("l", 1.0), ("r", -1.0)]
                elif config.placement == "left":
                    sides = [("l", 1.0)]
                elif config.placement == "right":
                    sides = [("r", -1.0)]
                else:
                    sides = [("l", 1.0)] if index % 2 == 0 else [("r", -1.0)]
                for side, sign in sides:
                    light_id = f"infrastructure.street_light.{road.id}.{side}{index:03d}"
                    selection = context.assets.resolve(
                        AssetRequest(
                            AssetCategory.INFRASTRUCTURE, ("street_light",), entity_id=light_id
                        )
                    )
                    dims = selection.archetype.dimensions
                    normal = scale(left_normal(tangent), sign)
                    position = add(
                        point, scale(normal, half_width + config.offset_m + dims.depth_m / 2.0)
                    )
                    if not (
                        0.0 <= position[0] <= extent.width_m
                        and 0.0 <= position[1] <= extent.depth_m
                    ):
                        continue
                    yaw = yaw_facing(scale(normal, -1.0))
                    probe = Footprint.from_polygon(
                        light_id,
                        "probe",
                        rectangle_corners(position, dims.width_m, dims.depth_m, yaw),
                    )
                    if context.occupancy.collides(probe, layers=SOLID_BLOCKERS):
                        continue
                    entity = make_entity(
                        self,
                        entity_id=light_id,
                        category=AssetCategory.INFRASTRUCTURE,
                        kind="street_light",
                        selection=selection,
                        position=(position[0], position[1], context.terrain.height_at(*position)),
                        yaw_deg=yaw,
                        rule="street_light_spacing",
                        source_feature=feature_ref("roads", road.id),
                    )
                    output.entities.append(entity)
                    context.occupy(entity)
