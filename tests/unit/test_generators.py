"""Behaviour of the built-in generator implementations."""

from __future__ import annotations

import math
from typing import Any

import pytest

from environment_generator.core.geometry import forward_vector, point_in_polygon
from environment_generator.core.spatial import Footprint
from environment_generator.generators import (
    ClutterPropGenerator,
    FootprintBuildingGenerator,
    GeneratorSet,
    HeightfieldTerrainGenerator,
    PanelFenceGenerator,
    PolylineRoadGenerator,
    PresetAtmosphereProcessor,
    ScatterVegetationGenerator,
    StandardInfrastructureGenerator,
    default_generators,
)
from environment_generator.generators.base import GenerationContext, SceneGenerator
from environment_generator.generators.buildings import footprint_rectangle
from environment_generator.models.assets import AssetCategory
from environment_generator.models.geometry import PolygonGeometry, area_outline
from environment_generator.models.recipe import LocationRecipe
from environment_generator.models.scene import EntityPolygon, EntityPolyline, SceneEntity
from environment_generator.models.site import SiteDescription
from tests.conftest import make_context, make_recipe, make_site, rect_building, road


def run(context: GenerationContext, *generators: SceneGenerator) -> list[SceneEntity]:
    """Run generators in order, feeding results forward like the pipeline does."""
    produced: list[SceneEntity] = []
    entities = context.entities
    assert isinstance(entities, dict)
    for generator in generators:
        output = generator.generate(context)
        for entity in output.entities:
            entities[entity.id] = entity
        if output.terrain is not None:
            context.terrain = output.terrain.to_heightfield()
        produced.extend(output.entities)
    return produced


def by_category(entities: list[SceneEntity], category: AssetCategory) -> list[SceneEntity]:
    return [e for e in entities if e.category is category]


# ----------------------------------------------------------------------------- set


def test_generator_set_enforces_slots() -> None:
    generators = default_generators()
    assert [g.slot.value for g in generators] == [
        "terrain",
        "roads",
        "buildings",
        "fences",
        "infrastructure",
        "vegetation",
        "props",
        "atmosphere",
    ]
    with pytest.raises(TypeError, match="cannot fill"):
        GeneratorSet(
            terrain=HeightfieldTerrainGenerator(),
            roads=PolylineRoadGenerator(),
            buildings=FootprintBuildingGenerator(),
            fences=PanelFenceGenerator(),
            infrastructure=StandardInfrastructureGenerator(),
            vegetation=ScatterVegetationGenerator(),
            props=ScatterVegetationGenerator(),  # type: ignore[arg-type]
            atmosphere=PresetAtmosphereProcessor(),
        )


# ----------------------------------------------------------------------------- terrain


def test_terrain_honours_spot_heights_and_carves_water() -> None:
    blueprint = make_site(
        terrain={
            "relief": "hilly",
            "base_elevation_m": 10,
            "elevation_points": [{"position": [0, 0], "elevation_m": 5.0}],
        },
        water=[
            {
                "id": "pond",
                "kind": "pond",
                "geometry": {"type": "rectangle", "center": [60, 40], "size": [20, 16]},
            }
        ],
    )
    context = make_context(blueprint)
    output = HeightfieldTerrainGenerator().generate(context)
    terrain = output.terrain
    assert terrain is not None
    assert terrain.heights[0][0] == pytest.approx(5.0)  # spot height reproduced exactly
    assert terrain.columns == math.ceil(100 / 4.0) + 1
    water = by_category(output.entities, AssetCategory.WATER)[0]
    assert isinstance(water.geometry, EntityPolygon)
    level = water.parameters["surfaceElevationM"]
    assert isinstance(level, float)
    assert terrain.to_heightfield().height_at(60, 40) == pytest.approx(level - 1.5)
    assert any(f.layer == "water" for f in context.occupancy)


def test_flat_relief_without_spot_heights_is_flat() -> None:
    blueprint = make_site(terrain={"relief": "flat", "base_elevation_m": 3.0})
    terrain = HeightfieldTerrainGenerator().generate(make_context(blueprint)).terrain
    assert terrain is not None
    assert terrain.min_elevation_m == terrain.max_elevation_m == 3.0


def test_terrain_noise_depends_on_seed() -> None:
    blueprint = make_site(terrain={"relief": "rugged"})
    a = HeightfieldTerrainGenerator().generate(make_context(blueprint, seed=1)).terrain
    b = HeightfieldTerrainGenerator().generate(make_context(blueprint, seed=2)).terrain
    assert a is not None and b is not None and a.heights != b.heights


# ----------------------------------------------------------------------------- roads


def test_roads_follow_terrain_and_find_junctions() -> None:
    blueprint = make_site(
        roads=[
            road("r-a", [[0, 40], [100, 40]], kind="rural_road"),
            road("r-b", [[50, 0], [50, 80]], kind="dirt_track"),
            road("r-c", [[50, 40], [90, 75]], kind="footpath"),
        ]
    )
    entities = run(make_context(blueprint), PolylineRoadGenerator())
    roads = {e.id: e for e in entities if e.kind != "junction"}
    assert set(roads) == {"road.r-a", "road.r-b", "road.r-c"}
    geometry = roads["road.r-a"].geometry
    assert isinstance(geometry, EntityPolyline) and geometry.width_m == 5.5
    assert len(geometry.points) > 2  # densified
    assert roads["road.r-b"].parameters["surface"] == "dirt"
    junctions = [e for e in entities if e.kind == "junction"]
    assert len(junctions) == 1  # three roads meeting at one point merge into one junction
    assert junctions[0].parameters["roads"] == ["r-a", "r-b", "r-c"]
    assert junctions[0].transform.position[:2] == pytest.approx((50.0, 40.0))


def test_road_width_scale() -> None:
    blueprint = make_site(roads=[road("r", [[0, 10], [100, 10]], kind="street")])
    recipe = make_recipe(roads={"width_scale": 2.0, "detect_junctions": False})
    (entity,) = run(make_context(blueprint, recipe), PolylineRoadGenerator())
    assert entity.parameters["widthM"] == pytest.approx(13.0)


# ----------------------------------------------------------------------------- buildings


def test_polygon_footprints_become_rectangles() -> None:
    geometry = PolygonGeometry(type="polygon", points=[(0, 0), (4, 0), (4, 10), (0, 10)])
    center, width, depth, _ = footprint_rectangle(geometry)
    assert center == pytest.approx((2.0, 5.0))
    assert (width, depth) == pytest.approx((10.0, 4.0))  # width is the long side


def test_buildings_face_the_nearest_road() -> None:
    blueprint = make_site(
        roads=[road("r", [[0, 40], [100, 40]])],
        buildings=[
            rect_building("north", [30, 55], [10, 8]),
            rect_building("south", [70, 25], [10, 8], rotation=180),
        ],
    )
    entities = run(make_context(blueprint), PolylineRoadGenerator(), FootprintBuildingGenerator())
    buildings = {e.id: e for e in by_category(entities, AssetCategory.BUILDING)}
    north_front = forward_vector(buildings["building.north"].transform.yaw_deg)
    south_front = forward_vector(buildings["building.south"].transform.yaw_deg)
    assert north_front[1] == pytest.approx(-1.0)
    assert south_front[1] == pytest.approx(1.0)
    dims = buildings["building.north"].dimensions
    assert (dims.width_m, dims.depth_m) == pytest.approx((10.0, 8.0))  # footprint matched


def test_damage_ratio_is_deterministic_per_building() -> None:
    blueprint = make_site(
        buildings=[
            rect_building(f"b-{i}", [10 + (i % 5) * 18, 10 + (i // 5) * 18], [8, 6])
            for i in range(20)
        ]
    )
    recipe = make_recipe(buildings={"damage_ratio": 0.5, "ruin_fraction": 0.5})
    first = run(make_context(blueprint, recipe), FootprintBuildingGenerator())
    second = run(make_context(blueprint, recipe), FootprintBuildingGenerator())
    conditions = [e.parameters["condition"] for e in first]
    assert conditions == [e.parameters["condition"] for e in second]
    assert {"intact", "damaged", "ruined"} <= set(conditions)
    ruined = [e for e in first if e.parameters["condition"] == "ruined"]
    assert all("ruin" in e.archetype_id for e in ruined)


def test_zone_infill_respects_zone_roads_and_reserved_points() -> None:
    zone = {
        "id": "z",
        "kind": "residential",
        "density": 1.0,
        "geometry": {"type": "rectangle", "center": [50, 40], "size": [100, 80]},
    }
    blueprint = make_site(
        zones=[zone],
        roads=[road("r", [[0, 40], [100, 40]])],
        vegetation=[
            {"id": "oak", "kind": "tree", "geometry": {"type": "point", "position": [30, 51]}}
        ],
    )
    recipe = make_recipe(buildings={"zone_fill": {"enabled": True, "lot_spacing_m": 15}})
    context = make_context(blueprint, recipe)
    entities = run(context, PolylineRoadGenerator(), FootprintBuildingGenerator())
    infill = by_category(entities, AssetCategory.BUILDING)
    assert len(infill) >= 4
    outline = area_outline(blueprint.zones[0].geometry)
    road_probe = [f for f in context.occupancy if f.layer == "road"]
    oak = Footprint.from_circle("oak", "x", (30.0, 51.0), 2.0)
    for building in infill:
        assert building.provenance.rule == "zone_infill"
        assert building.id.startswith("building.fill.z.r.")
        x, y, _ = building.transform.position
        assert point_in_polygon((x, y), outline)
        footprint = Footprint.from_polygon("b", "building", _corners(building))
        assert not any(footprint.intersects(r) for r in road_probe)
        assert not footprint.intersects(oak)


def _corners(entity: SceneEntity) -> list[tuple[float, float]]:
    from environment_generator.core.geometry import rectangle_corners

    x, y, _ = entity.transform.position
    return rectangle_corners(
        (x, y), entity.dimensions.width_m, entity.dimensions.depth_m, entity.transform.yaw_deg
    )


# ----------------------------------------------------------------------------- fences


def test_fence_panels_skip_gaps_and_roads() -> None:
    blueprint = make_site(
        roads=[road("r", [[50, 0], [50, 80]], kind="dirt_track")],
        fences=[
            {
                "id": "f",
                "kind": "wooden",
                "height_m": 1.5,
                "geometry": {"type": "polyline", "points": [[10, 20], [90, 20]]},
                "gaps": [{"offset_m": 10, "width_m": 5}],
            }
        ],
    )
    context = make_context(blueprint)
    run(context, PolylineRoadGenerator())
    output = PanelFenceGenerator().generate(context)
    panels = output.entities
    xs = sorted(p.transform.position[0] for p in panels)
    assert not any(20 < x < 25 for x in xs)  # declared gap 20..25
    assert not any(48 < x < 52 for x in xs)  # road opening
    assert [i.code for i in output.issues] == ["FENCE_ROAD_GAP"]
    assert all(p.dimensions.height_m == pytest.approx(1.5) for p in panels)
    assert all(p.parameters["cover"] == "partial" for p in panels)
    total = sum(p.dimensions.width_m for p in panels)
    assert 65 < total < 75


def test_closed_fence_loops() -> None:
    blueprint = make_site(
        fences=[
            {
                "id": "f",
                "kind": "stone_wall",
                "closed": True,
                "geometry": {
                    "type": "polyline",
                    "points": [[10, 10], [30, 10], [30, 30], [10, 30]],
                },
            }
        ]
    )
    panels = PanelFenceGenerator().generate(make_context(blueprint)).entities
    assert sum(p.dimensions.width_m for p in panels) == pytest.approx(80.0)
    assert {p.id.split(".")[-1][:3] for p in panels} == {"e00", "e01", "e02", "e03"}


# ----------------------------------------------------------------------------- infrastructure


def test_pole_lines_connect_poles_and_cable() -> None:
    blueprint = make_site(
        infrastructure=[
            {
                "id": "pl",
                "kind": "power_line",
                "pole_spacing_m": 20,
                "geometry": {"type": "polyline", "points": [[5, 70], [95, 70]]},
            },
            {
                "id": "tx",
                "kind": "transformer",
                "geometry": {"type": "point", "position": [50, 60]},
            },
        ]
    )
    recipe = make_recipe(infrastructure={"street_lights": {"enabled": False}})
    entities = StandardInfrastructureGenerator().generate(make_context(blueprint, recipe)).entities
    poles = [e for e in entities if ".pole" in e.id]
    assert len(poles) == 6  # 90 m with spacing 20 -> 5 spans
    assert poles[0].parameters["connects_to"] == [poles[1].id]
    assert poles[2].parameters["connects_to"] == [poles[1].id, poles[3].id]
    cable = next(e for e in entities if e.id == "infrastructure.pl.cable")
    assert isinstance(cable.geometry, EntityPolyline) and cable.geometry.width_m is None
    assert len(cable.geometry.points) == len(poles)
    assert any(e.id == "infrastructure.tx" for e in entities)


def test_street_lights_line_lit_roads_without_blocking_them() -> None:
    blueprint = make_site(roads=[road("s", [[0, 40], [100, 40]], kind="street")])
    context = make_context(blueprint)
    run(context, PolylineRoadGenerator())
    lights = StandardInfrastructureGenerator().generate(context).entities
    assert len(lights) >= 3
    sides = {light.id.split(".")[-1][0] for light in lights}
    assert sides == {"l", "r"}  # alternate placement
    for light in lights:
        y = light.transform.position[1]
        assert abs(y - 40) > 3.25  # beside, not on, the 6.5 m street
        front = forward_vector(light.transform.yaw_deg)
        assert front[1] * (40 - y) > 0  # faces the road


# ----------------------------------------------------------------------------- vegetation


def _forest(**extra: Any) -> SiteDescription:
    return make_site(
        roads=[road("r", [[0, 40], [100, 40]])],
        buildings=[rect_building("b", [20, 60], [10, 8])],
        vegetation=[
            {
                "id": "wood",
                "kind": "forest",
                "density": 1.0,
                "geometry": {"type": "rectangle", "center": [50, 40], "size": [100, 80]},
            },
            {"id": "lone", "kind": "tree", "geometry": {"type": "point", "position": [90, 41]}},
        ],
        **extra,
    )


def test_scatter_respects_spacing_and_obstacles() -> None:
    blueprint = _forest()
    recipe = make_recipe(vegetation={"min_spacing_m": 4.0, "understory_ratio": 0.0})
    context = make_context(blueprint, recipe)
    run(context, PolylineRoadGenerator(), FootprintBuildingGenerator())
    trees = ScatterVegetationGenerator().generate(context).entities
    scattered = [t for t in trees if t.provenance.rule == "area_scatter"]
    assert len(scattered) > 50
    positions = [(t.transform.position[0], t.transform.position[1]) for t in scattered]
    for i, a in enumerate(positions):
        for b in positions[i + 1 :]:
            assert math.dist(a, b) >= 4.0 - 1e-9
    road_band = [p for p in positions if abs(p[1] - 40) < 3.25]
    assert not road_band
    # Explicit trees are placed even on top of obstacles (they are surveyed reality).
    assert any(t.id == "vegetation.lone" for t in trees)


def test_scatter_ids_are_stable_when_obstacles_change() -> None:
    recipe = make_recipe(vegetation={"understory_ratio": 0.0})
    plain = make_site(
        vegetation=_forest().model_dump(mode="json")["vegetation"][:1],
    )
    blocked = make_site(
        vegetation=plain.model_dump(mode="json")["vegetation"],
        buildings=[rect_building("b", [50, 40], [20, 20])],
    )
    a = {
        e.id: e for e in ScatterVegetationGenerator().generate(make_context(plain, recipe)).entities
    }
    ctx = make_context(blocked, recipe)
    run(ctx, FootprintBuildingGenerator())
    b = {e.id: e for e in ScatterVegetationGenerator().generate(ctx).entities}
    shared = set(a) & set(b)
    assert len(shared) > 0.6 * len(b)
    for entity_id in shared:
        assert a[entity_id].transform == b[entity_id].transform


def test_orchards_lines_and_density_scale() -> None:
    blueprint = make_site(
        vegetation=[
            {
                "id": "orch",
                "kind": "orchard",
                "density": 1.0,
                "geometry": {"type": "rectangle", "center": [30, 30], "size": [36, 24]},
            },
            {
                "id": "hedge",
                "kind": "hedgerow",
                "geometry": {"type": "polyline", "points": [[60, 10], [95, 10]]},
            },
        ]
    )
    entities = ScatterVegetationGenerator().generate(make_context(blueprint)).entities
    orchard = [e for e in entities if e.provenance.rule == "orchard_grid"]
    assert len(orchard) == 24  # 6 x 4 grid at 6 m
    assert {e.kind for e in orchard} == {"fruit_tree"}
    hedge = [e for e in entities if e.provenance.rule == "line_planting"]
    assert len(hedge) >= 18 and {e.kind for e in hedge} <= {"hedge", "bush"}
    sparse = ScatterVegetationGenerator().generate(
        make_context(_forest(), make_recipe(vegetation={"density_scale": 0.1}))
    )
    dense = ScatterVegetationGenerator().generate(make_context(_forest()))
    assert len(sparse.entities) < len(dense.entities)


# ----------------------------------------------------------------------------- props


def test_clutter_surrounds_buildings_without_collisions() -> None:
    blueprint = make_site(
        roads=[road("r", [[0, 40], [100, 40]])],
        buildings=[rect_building("w", [50, 60], [24, 12], kind="warehouse")],
        props=[
            {
                "id": "car",
                "kind": "car",
                "geometry": {"type": "point", "position": [10, 20], "rotation_deg": 90},
            }
        ],
    )
    recipe = make_recipe(props={"clutter": {"per_building": 6, "max_distance_m": 4}})
    context = make_context(blueprint, recipe)
    run(context, PolylineRoadGenerator(), FootprintBuildingGenerator())
    props = ClutterPropGenerator().generate(context).entities
    clutter = [p for p in props if p.provenance.rule == "building_clutter"]
    assert 3 <= len(clutter) <= 6
    assert {p.kind for p in clutter} <= {"crate", "pallet", "barrel", "dumpster"}
    assert all(p.parameters["nearEntity"] == "building.w" for p in clutter)
    car = next(p for p in props if p.id == "prop.car")
    assert car.transform.yaw_deg == 90.0
    assert car.dimensions.depth_m == pytest.approx(4.1)  # vehicles are never stretched


def test_clutter_kind_weights_override_tables() -> None:
    blueprint = make_site(buildings=[rect_building("h", [50, 40], [9, 7])])
    recipe = make_recipe(props={"clutter": {"per_building": 5, "kind_weights": {"sandbags": 1}}})
    context = make_context(blueprint, recipe)
    run(context, FootprintBuildingGenerator())
    props = ClutterPropGenerator().generate(context).entities
    assert props and {p.kind for p in props} == {"sandbags"}


# ----------------------------------------------------------------------------- atmosphere


def test_atmosphere_precedence_and_hemisphere() -> None:
    blueprint = make_site(atmosphere={"time_of_day": "noon", "weather": "rain", "season": "winter"})
    settings = PresetAtmosphereProcessor().process(make_context(blueprint))
    assert settings.time_of_day.value == "noon"
    assert settings.precipitation == "snow"  # rain in winter
    assert settings.foliage == "bare"
    assert settings.key_light_azimuth_deg == pytest.approx(180.0)
    direction = settings.key_light_direction
    assert math.isclose(math.sqrt(sum(c * c for c in direction)), 1.0)
    assert direction[2] < 0 and direction[1] > 0  # southern sun shines north and down

    recipe = make_recipe(atmosphere={"time_of_day": "dusk", "fog_density_scale": 2.0})
    south = make_site(geo_reference={"latitude": -33.9, "longitude": 18.4, "heading_deg": 0})
    dusk = PresetAtmosphereProcessor().process(make_context(south, recipe))
    assert dusk.time_of_day.value == "dusk"
    assert dusk.key_light_azimuth_deg == pytest.approx((180.0 - 285.0) % 360.0)
    assert dusk.fog_density == pytest.approx(0.004)


def test_defaults_when_nothing_is_observed() -> None:
    settings = PresetAtmosphereProcessor().process(make_context(make_site()))
    assert (settings.time_of_day.value, settings.weather.value, settings.season.value) == (
        "afternoon",
        "clear",
        "summer",
    )


def test_estimates_cover_asset_needs() -> None:
    blueprint = _forest()
    recipe = LocationRecipe.default()
    for generator in default_generators():
        estimate = generator.estimate(blueprint, recipe)
        assert estimate.estimated_entities >= 0
        assert all(need.kinds for need in estimate.asset_needs)
