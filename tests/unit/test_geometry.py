from __future__ import annotations

import itertools
import math

import pytest

from environment_generator.core import geometry as g


def test_polygon_area_and_orientation() -> None:
    square = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    assert g.signed_area(square) == 16.0
    assert g.signed_area(list(reversed(square))) == -16.0
    assert g.polygon_area(list(reversed(square))) == 16.0
    assert g.ensure_ccw(list(reversed(square))) == square
    assert g.polygon_centroid(square) == pytest.approx((2.0, 2.0))


def test_point_in_concave_polygon() -> None:
    l_shape = [(0.0, 0.0), (4.0, 0.0), (4.0, 1.0), (1.0, 1.0), (1.0, 4.0), (0.0, 4.0)]
    assert g.point_in_polygon((0.5, 3.0), l_shape)
    assert g.point_in_polygon((3.0, 0.5), l_shape)
    assert not g.point_in_polygon((3.0, 3.0), l_shape)
    assert not g.point_in_polygon((-1.0, 0.5), l_shape)


@pytest.mark.parametrize(
    ("a1", "a2", "b1", "b2", "expected"),
    [
        ((0, 0), (2, 2), (0, 2), (2, 0), True),  # proper crossing
        ((0, 0), (1, 0), (1, 0), (1, 1), True),  # touching end points
        ((0, 0), (2, 0), (1, 0), (3, 0), True),  # collinear overlap
        ((0, 0), (1, 0), (2, 0), (3, 0), False),  # collinear disjoint
        ((0, 0), (1, 1), (0, 1), (0.4, 0.6), False),
    ],
)
def test_segments_intersect(a1: g.Vec2, a2: g.Vec2, b1: g.Vec2, b2: g.Vec2, expected: bool) -> None:
    assert g.segments_intersect(a1, a2, b1, b2) is expected


def test_segment_intersection_point() -> None:
    assert g.segment_intersection((0, 0), (2, 2), (0, 2), (2, 0)) == pytest.approx((1.0, 1.0))
    assert g.segment_intersection((0, 0), (1, 0), (0, 1), (1, 1)) is None  # parallel
    assert g.segment_intersection((0, 0), (1, 0), (2, -1), (2, 1)) is None  # out of range


def test_polygon_is_simple_detects_bow_tie() -> None:
    assert g.polygon_is_simple([(0, 0), (2, 0), (2, 2), (0, 2)])
    assert not g.polygon_is_simple([(0, 0), (2, 2), (2, 0), (0, 2)])
    assert not g.polygon_is_simple([(0, 0), (0, 0), (1, 1)])


def test_polygon_and_circle_overlap() -> None:
    a = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    inside = [(0.5, 0.5), (1.0, 0.5), (1.0, 1.0)]
    far = [(5.0, 5.0), (6.0, 5.0), (6.0, 6.0)]
    assert g.polygons_overlap(a, inside)  # containment without edge crossings
    assert not g.polygons_overlap(a, far)
    assert g.circle_polygon_overlap((3.0, 1.0), 1.5, a)
    assert not g.circle_polygon_overlap((3.0, 1.0), 0.5, a)
    assert g.circles_overlap((0, 0), 1.0, (1.5, 0), 1.0)


def test_rectangle_corners_rotation() -> None:
    corners = g.rectangle_corners((0.0, 0.0), 4.0, 2.0, 90.0)
    xs = sorted(round(c[0], 9) for c in corners)
    ys = sorted(round(c[1], 9) for c in corners)
    assert xs == [-1.0, -1.0, 1.0, 1.0]
    assert ys == [-2.0, -2.0, 2.0, 2.0]
    assert g.signed_area(corners) > 0


def test_minimum_area_rectangle_recovers_rotated_rectangle() -> None:
    corners = g.rectangle_corners((10.0, 5.0), 8.0, 3.0, 30.0)
    center, width, depth, yaw = g.minimum_area_rectangle(corners)
    assert center == pytest.approx((10.0, 5.0))
    assert sorted([width, depth]) == pytest.approx([3.0, 8.0])
    assert width * depth == pytest.approx(24.0)
    assert yaw % 90 == pytest.approx(30.0 % 90, abs=1e-6)


def test_minimum_area_rectangle_rejects_degenerate_points() -> None:
    with pytest.raises(ValueError, match="fewer than three"):
        g.minimum_area_rectangle([(0, 0), (1, 1), (2, 2)])


def test_inflate_convex_polygon_square() -> None:
    square = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    grown = g.inflate_convex_polygon(square, 1.0)
    assert g.bounds_of(grown) == pytest.approx((-1.0, -1.0, 3.0, 3.0))
    assert g.inflate_convex_polygon(square, 0.0) == square


def test_convex_hull_and_convexity() -> None:
    points = [(0, 0), (2, 0), (1, 1), (2, 2), (0, 2)]
    hull = g.convex_hull(points)
    assert set(hull) == {(0, 0), (2, 0), (2, 2), (0, 2)}
    assert g.is_convex(hull)
    assert not g.is_convex([(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)])


def test_polyline_sampling() -> None:
    line = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    assert g.polyline_length(line) == 20.0
    assert g.cumulative_lengths(line) == [0.0, 10.0, 20.0]
    point, tangent = g.point_along_polyline(line, g.cumulative_lengths(line), 15.0)
    assert point == pytest.approx((10.0, 5.0))
    assert tangent == pytest.approx((0.0, 1.0))
    samples = g.sample_polyline(line, 5.0, start_offset=2.5)
    assert [s[0] for s in samples] == [2.5, 7.5, 12.5, 17.5]
    with pytest.raises(ValueError):
        g.sample_polyline(line, 0.0)


def test_densify_keeps_vertices_and_limits_segments() -> None:
    line = [(0.0, 0.0), (10.0, 0.0), (10.0, 3.0)]
    dense = g.densify_polyline(line, 4.0)
    assert dense[0] == (0.0, 0.0) and dense[-1] == (10.0, 3.0)
    assert (10.0, 0.0) in dense
    assert all(g.distance(a, b) <= 4.0 + 1e-9 for a, b in itertools.pairwise(dense))


def test_angles_and_facing() -> None:
    assert g.normalize_angle_deg(-90.0) == 270.0
    assert g.normalize_angle_deg(720.0) == 0.0
    assert g.normalize_angle_deg(-1e-18) == 0.0
    assert g.heading_deg((0.0, 1.0)) == pytest.approx(90.0)
    for direction in [(1.0, 0.0), (0.0, -1.0), (-3.0, 4.0)]:
        yaw = g.yaw_facing(direction)
        assert g.forward_vector(yaw) == pytest.approx(g.normalize(direction))
    assert g.forward_vector(0.0) == pytest.approx((0.0, 1.0))
    assert math.isclose(g.length(g.rotate((1.0, 0.0), 90.0)), 1.0)


def test_closest_point_on_polyline() -> None:
    point, dist = g.closest_point_on_polyline((5.0, 3.0), [(0.0, 0.0), (10.0, 0.0)])
    assert point == pytest.approx((5.0, 0.0))
    assert dist == pytest.approx(3.0)
