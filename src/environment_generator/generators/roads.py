"""Roads as terrain-following centre-line splines, plus junction markers."""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from environment_generator.assets.resolver import AssetRequest
from environment_generator.core.geometry import (
    Vec2,
    bounds_of,
    densify_polyline,
    distance,
    polyline_length,
    segment_intersection,
)
from environment_generator.generators.base import (
    GenerationContext,
    GeneratorOutput,
    RoadGenerator,
    WorkEstimate,
    feature_ref,
    make_entity,
)
from environment_generator.models.assets import AssetCategory, AssetNeed, Dimensions
from environment_generator.models.recipe import LocationRecipe
from environment_generator.models.scene import EntityPolyline, SceneEntity
from environment_generator.models.site import Road, RoadKind, RoadSurface, SiteDescription

DEFAULT_WIDTH_M: dict[RoadKind, float] = {
    RoadKind.HIGHWAY: 9.0,
    RoadKind.STREET: 6.5,
    RoadKind.RURAL_ROAD: 5.5,
    RoadKind.DIRT_TRACK: 3.5,
    RoadKind.FOOTPATH: 1.6,
}

DEFAULT_SURFACE: dict[RoadKind, RoadSurface] = {
    RoadKind.HIGHWAY: RoadSurface.ASPHALT,
    RoadKind.STREET: RoadSurface.ASPHALT,
    RoadKind.RURAL_ROAD: RoadSurface.ASPHALT,
    RoadKind.DIRT_TRACK: RoadSurface.DIRT,
    RoadKind.FOOTPATH: RoadSurface.GRAVEL,
}

#: Junction candidates closer than this (relative to road width) are merged.
JUNCTION_MERGE_FACTOR = 0.5


def road_width(road: Road, recipe: LocationRecipe) -> float:
    base = road.width_m if road.width_m is not None else DEFAULT_WIDTH_M[road.kind]
    return base * recipe.roads.width_scale


def road_surface(road: Road) -> RoadSurface:
    return road.surface if road.surface is not None else DEFAULT_SURFACE[road.kind]


@dataclass
class _Junction:
    point: Vec2
    roads: set[str]
    width: float
    surface: RoadSurface
    pair: tuple[str, str]
    index: int = 0


class PolylineRoadGenerator(RoadGenerator):
    """One entity per road (world-space polyline + width) and one per junction."""

    implementation = "polyline_roads"
    version = "1.1.0"

    def estimate(self, site: SiteDescription, recipe: LocationRecipe) -> WorkEstimate:
        needs = [
            AssetNeed(
                category=AssetCategory.ROAD, kinds=[r.kind.value], reason=feature_ref("roads", r.id)
            )
            for r in site.roads
        ]
        if recipe.roads.detect_junctions and len(site.roads) > 1:
            needs.append(AssetNeed(category=AssetCategory.ROAD, kinds=["junction"], reason="roads"))
        sources = tuple(feature_ref("roads", r.id) for r in site.roads)
        return WorkEstimate(sources, len(site.roads) * 2, tuple(needs))

    def generate(self, context: GenerationContext) -> GeneratorOutput:
        recipe = context.recipe
        output = GeneratorOutput()
        roads = sorted(context.site.roads, key=lambda r: r.id)
        for road in roads:
            entity_id = f"road.{road.id}"
            width = road_width(road, recipe)
            surface = road_surface(road)
            dense = densify_polyline(road.geometry.points, recipe.roads.sample_spacing_m)
            points3 = [(x, y, context.terrain.height_at(x, y)) for x, y in dense]
            min_x, min_y, max_x, max_y = bounds_of(dense)
            selection = context.assets.resolve(
                AssetRequest(
                    AssetCategory.ROAD,
                    (road.kind.value,),
                    entity_id=entity_id,
                    surface=surface.value,
                )
            )
            entity = make_entity(
                self,
                entity_id=entity_id,
                category=AssetCategory.ROAD,
                kind=road.kind.value,
                selection=selection,
                position=points3[0],
                rule="centerline",
                source_feature=feature_ref("roads", road.id),
                parameters={
                    "surface": surface.value,
                    "width_m": width,
                    "length_m": polyline_length(road.geometry.points),
                    "importance": road.effective_importance.value,
                },
                attributes=road.attributes,
                tags=road.tags,
                geometry=EntityPolyline(type="polyline", points=points3, width_m=width),
                dimensions=Dimensions(width_m=max_x - min_x, depth_m=max_y - min_y, height_m=0.0),
            )
            output.entities.append(entity)
            context.occupy(entity)

        if recipe.roads.detect_junctions:
            for junction in self._find_junctions(roads, recipe):
                output.entities.append(self._junction_entity(context, junction))
        return output

    def _find_junctions(self, roads: list[Road], recipe: LocationRecipe) -> list[_Junction]:
        junctions: list[_Junction] = []
        pair_counts: dict[tuple[str, str], int] = {}
        for i, road_a in enumerate(roads):
            for road_b in roads[i + 1 :]:
                width = max(road_width(road_a, recipe), road_width(road_b, recipe))
                wider = (
                    road_a if road_width(road_a, recipe) >= road_width(road_b, recipe) else road_b
                )
                points_a, points_b = road_a.geometry.points, road_b.geometry.points
                found: list[Vec2] = []
                for a1, a2 in itertools.pairwise(points_a):
                    for b1, b2 in itertools.pairwise(points_b):
                        hit = segment_intersection(a1, a2, b1, b2)
                        if hit is not None and all(distance(hit, p) > 0.5 for p in found):
                            found.append(hit)
                for point in sorted(found):
                    merged = next(
                        (
                            j
                            for j in junctions
                            if distance(j.point, point)
                            <= JUNCTION_MERGE_FACTOR * max(j.width, width)
                        ),
                        None,
                    )
                    if merged is not None:
                        merged.roads.update({road_a.id, road_b.id})
                        merged.width = max(merged.width, width)
                        continue
                    pair = (road_a.id, road_b.id)
                    index = pair_counts.get(pair, 0)
                    pair_counts[pair] = index + 1
                    junctions.append(
                        _Junction(
                            point, {road_a.id, road_b.id}, width, road_surface(wider), pair, index
                        )
                    )
        return junctions

    def _junction_entity(self, context: GenerationContext, junction: _Junction) -> SceneEntity:
        entity_id = f"road.junction.{junction.pair[0]}.{junction.pair[1]}.{junction.index}"
        x, y = junction.point
        selection = context.assets.resolve(
            AssetRequest(
                AssetCategory.ROAD,
                ("junction",),
                entity_id=entity_id,
                surface=junction.surface.value,
            )
        )
        return make_entity(
            self,
            entity_id=entity_id,
            category=AssetCategory.ROAD,
            kind="junction",
            selection=selection,
            position=(x, y, context.terrain.height_at(x, y)),
            rule="junction",
            parameters={
                "roads": sorted(junction.roads),
                "surface": junction.surface.value,
                "width_m": junction.width,
            },
            dimensions=Dimensions(width_m=junction.width, depth_m=junction.width, height_m=0.0),
        )
