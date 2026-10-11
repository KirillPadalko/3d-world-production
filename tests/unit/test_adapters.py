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
from environment_generator.adapters.unity import manifest_rotation_matrix, matrix_to_quaternion
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


def test_manifest_frame_is_unity_frame() -> None:
    """The manifest already uses Unity's axes: no component is swapped."""
    assert to_unity_position((1.0, 2.0, 3.0)) == (1.0, 2.0, 3.0)
    assert to_unity_scale((1.0, 2.0, 3.0)) == (1.0, 2.0, 3.0)
    assert to_unity_yaw(-90.0) == 270.0


@pytest.mark.parametrize("yaw", [0.0, 30.0, 90.0, 180.0, 271.5])
def test_yaw_turns_the_front_clockwise_from_north(yaw: float) -> None:
    # Location frame: +X east, +Z north; a clockwise heading points (sin, cos) in (x, z).
    q = to_unity_rotation((0.0, yaw, 0.0))
    front = _rotate_by_quaternion(q, (0.0, 0.0, 1.0))
    expected = (math.sin(math.radians(yaw)), 0.0, math.cos(math.radians(yaw)))
    assert front == pytest.approx(expected, abs=1e-9)
    # Equal to Unity's Quaternion.Euler(0, yaw, 0) = (0, sin(yaw/2), 0, cos(yaw/2)).
    assert (q[0], q[2]) == pytest.approx((0.0, 0.0), abs=1e-12)
    assert 2 * math.degrees(math.atan2(q[1], q[3])) % 360 == pytest.approx(to_unity_yaw(yaw))


@pytest.mark.parametrize("rotation", [(10.0, 0.0, 0.0), (0.0, -25.0, 40.0), (15.0, 30.0, 200.0)])
def test_rotation_order_is_z_then_x_then_y(rotation: Vec3) -> None:
    """Quaternion.Euler semantics: rotate about Z, then X, then Y (world axes)."""
    from environment_generator.adapters.unity import _rotation_x, _rotation_y, _rotation_z

    rx, ry, rz = (math.radians(a) for a in rotation)
    vector = (0.3, -1.2, 2.5)
    step = _apply(_rotation_z(rz), vector)
    step = _apply(_rotation_x(rx), step)
    step = _apply(_rotation_y(ry), step)
    assert _apply(manifest_rotation_matrix(rotation), vector) == pytest.approx(step)
    q = to_unity_rotation(rotation)
    assert _rotate_by_quaternion(q, vector) == pytest.approx(step)
    assert math.isclose(sum(c * c for c in q), 1.0)


def test_matrix_to_quaternion_branches() -> None:
    for rotation in [(180.0, 0.0, 0.0), (0.0, 180.0, 0.0), (0.0, 0.0, 180.0), (0.0, 0.0, 0.0)]:
        q = matrix_to_quaternion(manifest_rotation_matrix(rotation))
        assert math.isclose(sum(c * c for c in q), 1.0)
        assert q[3] >= 0.0
