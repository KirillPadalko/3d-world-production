"""LocationBlueprint -> internal SiteDescription (the generator's view)."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from environment_generator.blueprint import load_blueprint
from environment_generator.blueprint.site_adapter import blueprint_to_site
from environment_generator.core.errors import ExternalDataError
from environment_generator.core.geometry import forward_vector
from environment_generator.models.geometry import RectangleGeometry
from environment_generator.models.site import (
    Condition,
    FenceKind,
    InfrastructureLine,
    RoadKind,
    VegetationArea,
    VegetationPoint,
)
from tests.blueprints import (
    building,
    fence,
    make_location,
    node,
    pole,
    segment,
    tree,
    vegetation_zone,
    wire,
)
from tests.conftest import DACHA_DIR


def test_building_yaw_and_condition_are_converted() -> None:
    site = blueprint_to_site(
        make_location(
            buildings=[
                building("east", 30, 20, yaw=90, width=10, depth=6, condition=0.9),
                building("ruin", 60, 60, condition=0.1, abandonment=0.8),
            ]
        )
    ).site
    east = site.buildings[0]
    assert isinstance(east.geometry, RectangleGeometry)
    assert east.geometry.center == (30, 20)
    assert east.geometry.size == (10, 6)
    # Facing east (clockwise 90) -> generator yaw 270 whose front is +X.
    assert east.geometry.rotation_deg == 270.0
    assert forward_vector(east.geometry.rotation_deg) == pytest.approx((1.0, 0.0))
    assert east.facing_known and east.condition is Condition.INTACT
    ruin = site.buildings[1]
    assert ruin.condition is Condition.RUINED
    assert ruin.attributes["conditionScore"] == 0.1 and ruin.attributes["abandonment"] == 0.8


def test_fence_missing_sections_become_gaps_in_metres() -> None:
    site = blueprint_to_site(
        make_location(
            fences=[
                fence(
                    "f",
                    [[0, 0], [10, 0], [10, 10], [0, 10]],
                    closed=True,
                    fenceType="wooden_picket",
                    missingSections=[{"start": 0.5, "end": 0.6}],
                )
            ]
        )
    ).site
    converted = site.fences[0]
    assert converted.kind is FenceKind.PICKET and converted.closed
    assert len(converted.gaps) == 1
    gap = converted.gaps[0]
    assert (gap.offset_m, gap.width_m) == pytest.approx((20.0, 4.0))  # perimeter 40 m


def test_road_graph_is_sampled_along_the_curve() -> None:
    site = blueprint_to_site(
        make_location(
            roads={
                "nodes": [node("a", 0, 40, "boundary"), node("b", 100, 40, "boundary")],
                "segments": [
                    segment(
                        "s",
                        "a",
                        "b",
                        curve="catmull_rom",
                        control=[[50, 60]],
                        importance="track",
                        surface="gravel",
                    )
                ],
            }
        )
    ).site
    road = site.roads[0]
    points = road.geometry.points
    assert points[0] == (0, 40) and points[-1] == (100, 40) and (50, 60) in points
    assert all(abs(a[0] - b[0]) <= 2.0 + 1e-9 for a, b in itertools.pairwise(points))
    assert road.kind is RoadKind.DIRT_TRACK and road.width_m == 6.0


def test_wires_attach_to_their_poles() -> None:
    site = blueprint_to_site(
        make_location(
            infrastructure=[
                pole("p-1", 10, 10, height=9),
                pole("p-2", 50, 10, height=8),
                wire("w", ["p-1", "p-2"]),
            ]
        )
    ).site
    line = next(i for i in site.infrastructure if isinstance(i, InfrastructureLine))
    assert line.geometry.points == [(10, 10), (50, 10)]
    assert not line.place_poles and line.support_ids == ["p-1", "p-2"]
    assert line.attach_height_m == pytest.approx(8 * 0.92)


def test_vegetation_species_and_unknowns() -> None:
    conversion = blueprint_to_site(
        make_location(
            vegetationZones=[
                vegetation_zone(
                    "vz",
                    [[0, 0], [30, 0], [30, 30]],
                    species=[
                        {"species": "birch", "weight": 3},
                        {"species": "unknown", "weight": 1},
                    ],
                ),
                vegetation_zone("beds", [[40, 0], [50, 0], [50, 10]], zone_type="garden_beds"),
            ],
            trees=[tree("t", 70, 70)],
        )
    )
    areas = [v for v in conversion.site.vegetation if isinstance(v, VegetationArea)]
    assert [a.id for a in areas] == ["vz"]
    assert [(s.species, s.weight) for s in areas[0].species] == [("birch", 3)]
    point = next(v for v in conversion.site.vegetation if isinstance(v, VegetationPoint))
    assert point.archetype is None  # unknown species -> generic tree
    codes = [n.code for n in conversion.notes]
    assert "NOT_INTERPRETED" in codes and "BIOME_UNKNOWN" in codes


def test_low_confidence_features_are_dropped_by_threshold() -> None:
    blueprint = make_location(
        trees=[
            tree("sure", 10, 10, provenance={"category": "observed", "confidence": 0.9}),
            tree("guess", 20, 20, provenance={"category": "inferred", "confidence": 0.2}),
            tree("authored", 30, 30),
        ]
    )
    conversion = blueprint_to_site(blueprint, min_confidence=0.5)
    assert conversion.dropped == ("trees/guess",)
    assert {v.id for v in conversion.site.vegetation} == {"sure", "authored"}


def test_heightmaps_need_the_package_root(tmp_path: Path) -> None:
    dacha = load_blueprint(DACHA_DIR / "location.blueprint.json")
    with pytest.raises(ExternalDataError, match="package root"):
        blueprint_to_site(dacha)
    site = blueprint_to_site(dacha, package_root=DACHA_DIR).site
    grid = site.terrain.height_grid
    assert grid is not None and (grid.columns, grid.rows) == (65, 65)
    assert site.terrain.base_elevation_m == pytest.approx(min(min(r) for r in grid.heights))
