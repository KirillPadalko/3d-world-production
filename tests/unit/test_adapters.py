"""Adapter stubs and the Unity coordinate conversion."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from environment_generator.adapters import (
    AdapterStatus,
    FootageReference,
    UnconfiguredBlenderProcessor,
    UnconfiguredLocationAnalyzer,
    UnconfiguredUnityIntegrator,
    available_adapters,
    to_unity_position,
    to_unity_rotation,
    to_unity_scale,
    to_unity_yaw,
)
from environment_generator.adapters.unity import (
    manifest_rotation_matrix,
    matrix_to_quaternion,
    to_unity_rotation_matrix,
)
from environment_generator.core.errors import AdapterUnavailableError
from environment_generator.pipeline import InputBundle, Pipeline
from tests.conftest import MINIMAL_BLUEPRINT

Vec3 = tuple[float, float, float]


def _apply(matrix: tuple[Vec3, Vec3, Vec3], v: Vec3) -> Vec3:
    return (
        sum(matrix[0][k] * v[k] for k in range(3)),
        sum(matrix[1][k] * v[k] for k in range(3)),
        sum(matrix[2][k] * v[k] for k in range(3)),
    )


def _rotate_by_quaternion(q: tuple[float, float, float, float], v: Vec3) -> Vec3:
    x, y, z, w = q
    # v' = v + 2w(q x v) + 2 q x (q x v)
    cx = y * v[2] - z * v[1]
    cy = z * v[0] - x * v[2]
    cz = x * v[1] - y * v[0]
    ccx = y * cz - z * cy
    ccy = z * cx - x * cz
    ccz = x * cy - y * cx
    return (v[0] + 2 * (w * cx + ccx), v[1] + 2 * (w * cy + ccy), v[2] + 2 * (w * cz + ccz))


def test_stubs_fail_loudly() -> None:
    with pytest.raises(AdapterUnavailableError, match="not implemented"):
        UnconfiguredLocationAnalyzer().analyze([FootageReference(uri="file:///clip.mp4")])
    result = Pipeline().run(InputBundle(blueprint=MINIMAL_BLUEPRINT))
    assert result.manifest is not None
    with pytest.raises(AdapterUnavailableError):
        UnconfiguredBlenderProcessor().process(result.manifest, Path("out"))
    with pytest.raises(AdapterUnavailableError) as excinfo:
        UnconfiguredUnityIntegrator().integrate(Path("scene-manifest.json"), Path("UnityProject"))
    assert excinfo.value.exit_code == 7


def test_adapter_listing_is_honest() -> None:
    adapters = {a.name: a for a in available_adapters()}
    assert adapters["unity"].status is AdapterStatus.STUB
    assert adapters["blender"].status is AdapterStatus.STUB
    assert adapters["location-analysis"].status is AdapterStatus.STUB
    assert adapters["scene-manifest-json"].status is AdapterStatus.LOCAL


def test_position_and_scale_swap_y_and_z() -> None:
    assert to_unity_position((1.0, 2.0, 3.0)) == (1.0, 3.0, 2.0)
    assert to_unity_scale((1.0, 2.0, 3.0)) == (1.0, 3.0, 2.0)


@pytest.mark.parametrize("yaw", [0.0, 30.0, 90.0, 180.0, 271.5])
def test_yaw_keeps_the_front_facing_the_same_world_direction(yaw: float) -> None:
    # Manifest front (local +Y) in world ENU coordinates.
    front_enu = (-math.sin(math.radians(yaw)), math.cos(math.radians(yaw)), 0.0)
    # Unity forward (+Z) rotated by the converted rotation, mapped back to ENU.
    q = to_unity_rotation((0.0, 0.0, yaw))
    forward_unity = _rotate_by_quaternion(q, (0.0, 0.0, 1.0))
    front_back_to_enu = (forward_unity[0], forward_unity[2], forward_unity[1])
    assert front_back_to_enu == pytest.approx(front_enu, abs=1e-9)
    # For pure yaw the quaternion is a rotation about Unity's Y axis by -yaw.
    expected_y = to_unity_yaw(yaw)
    assert (q[0], q[2]) == pytest.approx((0.0, 0.0), abs=1e-12)
    assert 2 * math.degrees(math.atan2(q[1], q[3])) % 360 == pytest.approx(expected_y % 360)


@pytest.mark.parametrize("rotation", [(10.0, 0.0, 0.0), (0.0, -25.0, 40.0), (15.0, 30.0, 200.0)])
def test_general_rotations_commute_with_the_axis_swap(rotation: Vec3) -> None:
    swap = to_unity_position
    vector = (0.3, -1.2, 2.5)
    rotated_enu = _apply(manifest_rotation_matrix(rotation), vector)
    rotated_unity = _apply(to_unity_rotation_matrix(rotation), swap(vector))
    assert rotated_unity == pytest.approx(swap(rotated_enu))
    q = to_unity_rotation(rotation)
    assert _rotate_by_quaternion(q, swap(vector)) == pytest.approx(swap(rotated_enu))
    assert math.isclose(sum(c * c for c in q), 1.0)


def test_matrix_to_quaternion_branches() -> None:
    for rotation in [(180.0, 0.0, 0.0), (0.0, 180.0, 0.0), (0.0, 0.0, 180.0), (0.0, 0.0, 0.0)]:
        q = matrix_to_quaternion(manifest_rotation_matrix(rotation))
        assert math.isclose(sum(c * c for c in q), 1.0)
        assert q[3] >= 0.0


@pytest.mark.parametrize("rotation", [(10.0, 0.0, 0.0), (0.0, -25.0, 40.0), (15.0, 30.0, 200.0)])
def test_documented_csharp_formula_matches(rotation: Vec3) -> None:
    """docs/ADAPTERS.md: AngleAxis(-rz, up) * AngleAxis(-ry, forward) * AngleAxis(-rx, right)."""
    from environment_generator.adapters.unity import _matmul, _rotation_x, _rotation_y, _rotation_z

    rx, ry, rz = (math.radians(a) for a in rotation)
    # In Unity axes: up = Y, forward = Z, right = X; AngleAxis builds the standard matrix.
    documented = _matmul(_rotation_y(-rz), _matmul(_rotation_z(-ry), _rotation_x(-rx)))
    converted = to_unity_rotation_matrix(rotation)
    for row_a, row_b in zip(documented, converted, strict=True):
        assert row_a == pytest.approx(row_b)
