"""Heightfield terrain with surveyed spot heights, fractal noise and water."""

from __future__ import annotations

import math
from collections.abc import Sequence

from environment_generator.assets.resolver import AssetRequest
from environment_generator.core.geometry import (
    Vec2,
    bounds_of,
    distance,
    point_in_polygon,
    polygon_area,
    polygon_centroid,
)
from environment_generator.core.terrain import Heightfield, fractal_noise
from environment_generator.generators.base import (
    GenerationContext,
    GeneratorOutput,
    TerrainGenerator,
    WorkEstimate,
    feature_ref,
    make_entity,
)
from environment_generator.models.assets import AssetCategory, AssetNeed, Dimensions
from environment_generator.models.blueprint import LocationBlueprint, Relief
from environment_generator.models.geometry import area_outline
from environment_generator.models.recipe import LocationRecipe
from environment_generator.models.scene import EntityPolygon, TerrainData

#: Default noise amplitude per relief class when the recipe does not set one.
RELIEF_AMPLITUDE_M: dict[Relief, float] = {
    Relief.FLAT: 0.0,
    Relief.GENTLE: 1.5,
    Relief.HILLY: 6.0,
    Relief.RUGGED: 14.0,
}


def _interpolate(
    control: Sequence[tuple[Vec2, float]], fallback: float, point: Vec2
) -> tuple[float, float]:
    """Inverse-distance-weighted elevation and distance to the nearest spot height."""
    if not control:
        return fallback, math.inf
    weighted = 0.0
    total = 0.0
    nearest = math.inf
    for position, elevation in control:
        d = distance(point, position)
        nearest = min(nearest, d)
        if d < 1e-6:
            return elevation, 0.0
        weight = 1.0 / (d * d)
        weighted += weight * elevation
        total += weight
    return weighted / total, nearest


class HeightfieldTerrainGenerator(TerrainGenerator):
    """Regular-grid terrain.

    * With spot heights the base surface interpolates them (inverse distance
      weighting); otherwise it is ``terrain.base_elevation_m``.
    * Fractal value noise adds relief; it fades out near spot heights so
      surveyed elevations are honoured exactly.
    * Water bodies get a flat surface at the lowest shoreline height and the
      terrain under them is carved down by ``water_depth_m``.
    """

    implementation = "heightfield"
    version = "1.0.0"

    def estimate(self, blueprint: LocationBlueprint, recipe: LocationRecipe) -> WorkEstimate:
        needs = [
            AssetNeed(
                category=AssetCategory.TERRAIN,
                kinds=[blueprint.terrain.ground_cover.value],
                reason="terrain",
            )
        ]
        sources = ["terrain"]
        for body in blueprint.water:
            ref = feature_ref("water", body.id)
            sources.append(ref)
            needs.append(
                AssetNeed(category=AssetCategory.WATER, kinds=[body.kind.value], reason=ref)
            )
        return WorkEstimate(tuple(sources), 1 + len(blueprint.water), tuple(needs))

    def generate(self, context: GenerationContext) -> GeneratorOutput:
        blueprint = context.blueprint
        config = context.recipe.terrain
        extent = blueprint.extent
        cell = config.cell_size_m
        columns = math.ceil(extent.width_m / cell) + 1
        rows = math.ceil(extent.depth_m / cell) + 1
        relief = blueprint.terrain.relief
        amplitude = (
            config.noise_amplitude_m
            if config.noise_amplitude_m is not None
            else RELIEF_AMPLITUDE_M[relief]
        )
        control = [(p.position, p.elevation_m) for p in blueprint.terrain.elevation_points]
        fade_radius = max(config.noise_scale_m * 0.5, cell)
        noise_seed = context.entity_seed("noise")

        heights: list[list[float]] = []
        for j in range(rows):
            row: list[float] = []
            for i in range(columns):
                x, y = i * cell, j * cell
                base, nearest = _interpolate(control, blueprint.terrain.base_elevation_m, (x, y))
                noise = fractal_noise(
                    noise_seed, x / config.noise_scale_m, y / config.noise_scale_m, config.octaves
                )
                fade = 1.0 if not control else min(1.0, nearest / fade_radius)
                row.append(base + amplitude * noise * fade)
            heights.append(row)

        output = GeneratorOutput()
        pre_carve = Heightfield(cell, columns, rows, tuple(tuple(r) for r in heights))
        water_levels: list[tuple[str, list[Vec2], float]] = []
        for body in sorted(blueprint.water, key=lambda b: b.id):
            outline = area_outline(body.geometry)
            level = min(pre_carve.height_at(x, y) for x, y in outline)
            water_levels.append((body.id, outline, level))

        if config.carve_water and water_levels:
            for _, outline, level in water_levels:
                min_x, min_y, max_x, max_y = bounds_of(outline)
                for j in range(
                    max(0, math.floor(min_y / cell)), min(rows, math.ceil(max_y / cell) + 1)
                ):
                    for i in range(
                        max(0, math.floor(min_x / cell)), min(columns, math.ceil(max_x / cell) + 1)
                    ):
                        if point_in_polygon((i * cell, j * cell), outline):
                            heights[j][i] = min(heights[j][i], level - config.water_depth_m)

        flat = [h for row in heights for h in row]
        terrain = TerrainData(
            cell_size_m=cell,
            columns=columns,
            rows=rows,
            heights=heights,
            min_elevation_m=min(flat),
            max_elevation_m=max(flat),
            ground_cover=blueprint.terrain.ground_cover,
        )
        output.terrain = terrain

        ground_kind = blueprint.terrain.ground_cover.value
        ground = context.assets.resolve(
            AssetRequest(AssetCategory.TERRAIN, (ground_kind,), entity_id="terrain")
        )
        output.entities.append(
            make_entity(
                self,
                entity_id="terrain",
                category=AssetCategory.TERRAIN,
                kind=ground_kind,
                selection=ground,
                position=(0.0, 0.0, blueprint.terrain.base_elevation_m),
                rule="heightfield",
                source_feature="terrain",
                parameters={
                    "relief": relief.value,
                    "cell_size_m": cell,
                    "columns": columns,
                    "rows": rows,
                    "noise_amplitude_m": amplitude,
                },
                dimensions=Dimensions(
                    width_m=extent.width_m,
                    depth_m=extent.depth_m,
                    height_m=terrain.max_elevation_m - terrain.min_elevation_m,
                ),
            )
        )

        bodies = {b.id: b for b in blueprint.water}
        for body_id, outline, level in water_levels:
            body = bodies[body_id]
            entity_id = f"water.{body_id}"
            selection = context.assets.resolve(
                AssetRequest(AssetCategory.WATER, (body.kind.value,), entity_id=entity_id)
            )
            cx, cy = polygon_centroid(outline)
            min_x, min_y, max_x, max_y = bounds_of(outline)
            entity = make_entity(
                self,
                entity_id=entity_id,
                category=AssetCategory.WATER,
                kind=body.kind.value,
                selection=selection,
                position=(cx, cy, level),
                rule="water_surface",
                source_feature=feature_ref("water", body_id),
                parameters={
                    "surface_elevation_m": level,
                    "depth_m": config.water_depth_m if config.carve_water else 0.0,
                    "area_m2": polygon_area(outline),
                },
                tags=body.tags,
                geometry=EntityPolygon(type="polygon", points=[(x, y, level) for x, y in outline]),
                dimensions=Dimensions(width_m=max_x - min_x, depth_m=max_y - min_y, height_m=0.0),
            )
            output.entities.append(entity)
            context.occupy(entity)
        return output
