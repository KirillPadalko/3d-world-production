"""Frame conversion (location <-> generator) and the reference road curves."""

from __future__ import annotations

import itertools
import math

import pytest

from environment_generator.core.curves import (
    catmull_rom_point,
    sample_catmull_rom,
    sample_curve,
)
from environment_generator.core.frames import (
    generator_scale_to_location,
    generator_to_location,
    generator_yaw_to_location,
    location_scale_to_generator,
    location_to_generator,
    location_yaw_to_generator,
)
from environment_generator.core.geometry import forward_vector


def test_positions_swap_up_and_north_and_round_trip() -> None:
    assert location_to_generator((1.0, 2.0, 3.0)) == (1.0, 3.0, 2.0)
    assert generator_to_location(location_to_generator((4.0, 5.0, 6.0))) == (4.0, 5.0, 6.0)
    assert generator_scale_to_location((1.0, 2.0, 3.0)) == (1.0, 3.0, 2.0)
    assert location_scale_to_generator(generator_scale_to_location((1, 2, 3))) == (1, 2, 3)


@pytest.mark.parametrize("heading", [0.0, 45.0, 90.0, 180.0, 270.0, 359.5])
def test_clockwise_heading_points_the_same_way_in_both_frames(heading: float) -> None:
    # Location frame: heading clockwise from north, front = (sin h, cos h) in (east, north).
    expected = (math.sin(math.radians(heading)), math.cos(math.radians(heading)))
    # Generator frame: counter-clockwise yaw, front = forward_vector(yaw) in (east, north).
    front = forward_vector(location_yaw_to_generator(heading))
    assert front == pytest.approx(expected, abs=1e-12)
    assert generator_yaw_to_location(location_yaw_to_generator(heading)) == pytest.approx(heading)


def test_yaws_are_normalised_without_negative_zero() -> None:
    assert location_yaw_to_generator(0.0) == 0.0
    assert math.copysign(1.0, location_yaw_to_generator(0.0)) == 1.0
    assert location_yaw_to_generator(90.0) == 270.0
    assert generator_yaw_to_location(-90.0) == 90.0


def test_catmull_rom_passes_through_every_point_exactly() -> None:
    points = [(0.0, 0.0), (10.0, 5.0), (20.0, 0.0), (35.0, 8.0)]
    sampled = sample_catmull_rom(points, 1.0)
    for point in points:
        assert point in sampled
    assert sampled[0] == points[0] and sampled[-1] == points[-1]
    assert all(math.dist(a, b) <= 1.5 for a, b in itertools.pairwise(sampled))


def test_catmull_rom_reference_values() -> None:
    """Pinned values so other implementations can check their formula."""
    point = catmull_rom_point((0.0, 0.0), (1.0, 1.0), (2.0, 0.0), (3.0, 1.0), 0.5)
    assert point == pytest.approx((1.5, 0.5))
    curved = catmull_rom_point((-10.0, 0.0), (0.0, 0.0), (10.0, 10.0), (20.0, 10.0), 0.5)
    assert curved == pytest.approx((5.0, 5.0))
    # Cross-checked against the equivalent non-uniform Hermite form (Yuksel et al.).
    asymmetric = catmull_rom_point((0.0, 0.0), (1.0, 0.0), (5.0, 3.0), (6.0, 3.0), 0.25)
    assert asymmetric == pytest.approx((1.885733089003862, 0.555661029667954), abs=1e-12)
    irregular = catmull_rom_point((0.0, 0.0), (2.0, 7.0), (3.0, -1.0), (9.0, 4.0), 0.7)
    assert irregular == pytest.approx((2.358153629470988, 0.927374623367740), abs=1e-12)


def test_two_point_curves_are_straight_and_sampling_is_deterministic() -> None:
    straight = sample_curve("catmull_rom", [(0, 0), (10, 0)], 2.5)
    assert straight == [(0.0, 0.0), (2.5, 0.0), (5.0, 0.0), (7.5, 0.0), (10.0, 0.0)]
    points = [(0, 0), (30, 12), (60, 0)]
    assert sample_curve("catmull_rom", points, 2.0) == sample_curve("catmull_rom", points, 2.0)
    assert sample_curve("polyline", points, 100.0) == [(0.0, 0.0), (30.0, 12.0), (60.0, 0.0)]


def test_invalid_curves_are_rejected() -> None:
    with pytest.raises(ValueError, match="distinct"):
        sample_catmull_rom([(0, 0), (0, 0), (5, 5)], 1.0)
    with pytest.raises(ValueError, match="positive"):
        sample_catmull_rom([(0, 0), (5, 5)], 0.0)
    with pytest.raises(ValueError, match="unknown"):
        sample_curve("bezier", [(0, 0), (5, 5)], 1.0)
