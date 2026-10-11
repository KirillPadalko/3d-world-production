"""Fences and walls split into panel entities along their polylines."""

from __future__ import annotations

import dataclasses
import math

from environment_generator.assets.resolver import AssetRequest
from environment_generator.core.geometry import (
    cumulative_lengths,
    heading_deg,
    lerp,
    polyline_length,
    segment_quad,
    sub,
)
from environment_generator.core.issues import ValidationIssue
from environment_generator.core.spatial import Footprint
from environment_generator.generators.base import (
    FenceGenerator,
    GenerationContext,
    GeneratorOutput,
    WorkEstimate,
    feature_ref,
    kinds_with_hint,
    make_entity,
)
from environment_generator.models.assets import AssetCategory, AssetNeed
from environment_generator.models.recipe import LocationRecipe
from environment_generator.models.site import Fence, FenceKind, SiteDescription

DEFAULT_HEIGHT_M: dict[FenceKind, float] = {
    FenceKind.WOODEN: 1.2,
    FenceKind.PICKET: 1.0,
    FenceKind.CHAIN_LINK: 2.0,
    FenceKind.WIRE: 1.2,
    FenceKind.METAL_SHEET: 1.8,
    FenceKind.STONE_WALL: 1.2,
    FenceKind.BRICK_WALL: 2.0,
    FenceKind.CONCRETE_WALL: 2.5,
    FenceKind.METAL_RAILING: 1.1,
}

#: Panels shorter than this are dropped (slivers next to gaps).
MIN_PANEL_LENGTH_M = 0.25
_NOMINAL_PANEL_M = 2.5


def fence_points(fence: Fence) -> list[tuple[float, float]]:
    points = [(float(x), float(y)) for x, y in fence.geometry.points]
    if fence.closed:
        points.append(points[0])
    return points


def _subtract(
    interval: tuple[float, float], holes: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    pieces = [interval]
    for h0, h1 in holes:
        next_pieces: list[tuple[float, float]] = []
        for a, b in pieces:
            if h1 <= a or h0 >= b:
                next_pieces.append((a, b))
                continue
            if h0 > a:
                next_pieces.append((a, h0))
            if h1 < b:
                next_pieces.append((h1, b))
        pieces = next_pieces
    return pieces


class PanelFenceGenerator(FenceGenerator):
    """One entity per panel so walls can act as destructible or partial cover.

    Panels are evenly sized per polyline edge, follow the terrain, skip
    declared gaps and (optionally) leave openings where a road crosses.
    """

    implementation = "panel_fences"
    version = "1.1.0"

    def estimate(self, site: SiteDescription, recipe: LocationRecipe) -> WorkEstimate:
        sources = tuple(feature_ref("fences", f.id) for f in site.fences)
        count = sum(
            math.ceil(polyline_length(fence_points(f)) / _NOMINAL_PANEL_M) for f in site.fences
        )
        needs = tuple(
            AssetNeed(
                category=AssetCategory.FENCE,
                kinds=list(kinds_with_hint(f.archetype, f.kind.value)),
                reason=feature_ref("fences", f.id),
            )
            for f in site.fences
        )
        return WorkEstimate(sources, count, needs)

    def generate(self, context: GenerationContext) -> GeneratorOutput:
        output = GeneratorOutput()
        for fence in sorted(context.site.fences, key=lambda f: f.id):
            self._fence(context, fence, output)
        return output

    def _fence(self, context: GenerationContext, fence: Fence, output: GeneratorOutput) -> None:
        config = context.recipe.fences
        ref = feature_ref("fences", fence.id)
        points = fence_points(fence)
        cumulative = cumulative_lengths(points)
        height = (fence.height_m or DEFAULT_HEIGHT_M[fence.kind]) * config.height_scale
        base = context.assets.resolve(
            AssetRequest(
                AssetCategory.FENCE,
                kinds_with_hint(fence.archetype, fence.kind.value),
                entity_id=f"fence.{fence.id}",
                height=height,
            )
        )
        nominal = base.archetype.dimensions
        panel_length = max(nominal.width_m, 0.5)
        gaps = sorted((g.offset_m, g.offset_m + g.width_m) for g in fence.gaps)
        road_gaps = 0
        for edge in range(len(points) - 1):
            start, end = points[edge], points[edge + 1]
            e0, e1 = cumulative[edge], cumulative[edge + 1]
            if e1 - e0 < 1e-6:
                continue
            direction = sub(end, start)
            yaw = heading_deg(direction)
            panel_index = 0
            for s0, s1 in _subtract((e0, e1), gaps):
                count = max(1, math.ceil((s1 - s0) / panel_length - 1e-9))
                for k in range(count):
                    a = s0 + (s1 - s0) * k / count
                    b = s0 + (s1 - s0) * (k + 1) / count
                    if b - a < MIN_PANEL_LENGTH_M:
                        continue
                    pa = lerp(start, end, (a - e0) / (e1 - e0))
                    pb = lerp(start, end, (b - e0) / (e1 - e0))
                    panel_id = f"fence.{fence.id}.e{edge:02d}p{panel_index:02d}"
                    panel_index += 1
                    if config.gap_at_roads:
                        probe = Footprint.from_polygon(
                            panel_id, "probe", segment_quad(pa, pb, max(nominal.depth_m / 2.0, 0.1))
                        )
                        if context.occupancy.collides(probe, layers={AssetCategory.ROAD.value}):
                            road_gaps += 1
                            continue
                    mid = lerp(pa, pb, 0.5)
                    length = b - a
                    factors = (
                        (length / nominal.width_m, 1.0, height / nominal.height_m)
                        if base.archetype.scalable and nominal.width_m > 0 and nominal.height_m > 0
                        else (1.0, 1.0, 1.0)
                    )
                    selection = dataclasses.replace(
                        base,
                        variant=context.entity_seed("variant", panel_id) % base.archetype.variants,
                    )
                    entity = make_entity(
                        self,
                        entity_id=panel_id,
                        category=AssetCategory.FENCE,
                        kind=fence.kind.value,
                        selection=selection,
                        position=(mid[0], mid[1], context.terrain.height_at(*mid)),
                        yaw_deg=yaw,
                        scale=factors,
                        rule="panel",
                        source_feature=ref,
                        parameters={"fence_id": fence.id, "height_m": height, "length_m": length},
                        attributes=fence.attributes,
                        tags=fence.tags,
                    )
                    output.entities.append(entity)
                    context.occupy(entity)
        if road_gaps:
            output.issues.append(
                ValidationIssue.info(
                    "FENCE_ROAD_GAP",
                    f"Left {road_gaps} panel opening(s) where the fence crosses a road.",
                    location=ref,
                )
            )
