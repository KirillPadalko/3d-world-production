"""Unity integration adapter.

STATUS: the integrator is a STUB - importing a manifest into a Unity project
is the job of a Unity-side (C#) importer that does not exist yet. The
coordinate helpers below are real, pure-math functions with tests; a Unity
importer can port them line by line.

The manifest uses the location frame of LocationBlueprint v1.0: metres,
+X east, +Y up, +Z north, left-handed, an object's front is local +Z, and
``rotationDeg`` are Euler angles applied Z, then X, then Y (extrinsic). That is
Unity's own convention, so positions, scales and ``Quaternion.Euler(rotationDeg)``
are used unchanged; map east/north to Unity's world axes by placing the
imported root object, never by swapping components.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from environment_generator.core.errors import AdapterUnavailableError
from environment_generator.core.geometry import normalize_angle_deg
from environment_generator.models.scene import ManifestEntity

Vec3 = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]  # (x, y, z, w)
Matrix3 = tuple[Vec3, Vec3, Vec3]


def to_unity_position(position: Vec3) -> Vec3:
    """Unity ``transform.localPosition``: identical to the manifest position."""
    return position


def to_unity_scale(scale: Vec3) -> Vec3:
    """Unity ``transform.localScale``: identical to the manifest scale."""
    return scale


def to_unity_yaw(yaw_deg: float) -> float:
    """Unity ``eulerAngles.y`` for a manifest yaw (both clockwise from +Z), in ``[0, 360)``."""
    return normalize_angle_deg(yaw_deg)


def _rotation_x(angle: float) -> Matrix3:
    c, s = math.cos(angle), math.sin(angle)
    return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))


def _rotation_y(angle: float) -> Matrix3:
    c, s = math.cos(angle), math.sin(angle)
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))


def _rotation_z(angle: float) -> Matrix3:
    c, s = math.cos(angle), math.sin(angle)
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def _matmul(a: Matrix3, b: Matrix3) -> Matrix3:
    def cell(i: int, j: int) -> float:
        return a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j]

    return (
        (cell(0, 0), cell(0, 1), cell(0, 2)),
        (cell(1, 0), cell(1, 1), cell(1, 2)),
        (cell(2, 0), cell(2, 1), cell(2, 2)),
    )


def manifest_rotation_matrix(rotation_deg: Vec3) -> Matrix3:
    """Matrix of a manifest rotation: extrinsic Z, then X, then Y (``Ry @ Rx @ Rz``).

    Same as Unity's ``Quaternion.Euler``; a positive Y angle turns +Z towards +X
    (clockwise seen from above).
    """
    rx, ry, rz = (math.radians(a) for a in rotation_deg)
    return _matmul(_rotation_y(ry), _matmul(_rotation_x(rx), _rotation_z(rz)))


def matrix_to_quaternion(m: Matrix3) -> Quaternion:
    """Standard rotation-matrix to quaternion conversion, returned as ``(x, y, z, w)``."""
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (m[2][1] - m[1][2]) / s
        y = (m[0][2] - m[2][0]) / s
        z = (m[1][0] - m[0][1]) / s
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        w = (m[2][1] - m[1][2]) / s
        x = 0.25 * s
        y = (m[0][1] + m[1][0]) / s
        z = (m[0][2] + m[2][0]) / s
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        w = (m[0][2] - m[2][0]) / s
        x = (m[0][1] + m[1][0]) / s
        y = 0.25 * s
        z = (m[1][2] + m[2][1]) / s
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
        w = (m[1][0] - m[0][1]) / s
        x = (m[0][2] + m[2][0]) / s
        y = (m[1][2] + m[2][1]) / s
        z = 0.25 * s
    if w < 0:  # canonical hemisphere for stable output
        x, y, z, w = -x, -y, -z, -w
    return (x, y, z, w)


def to_unity_rotation(rotation_deg: Vec3) -> Quaternion:
    """Unity ``Quaternion`` ``(x, y, z, w)``; equal to ``Quaternion.Euler(rotation_deg)``."""
    return matrix_to_quaternion(manifest_rotation_matrix(rotation_deg))


@dataclass(frozen=True)
class UnityTransform:
    position: Vec3
    rotation: Quaternion
    scale: Vec3


def entity_to_unity_transform(entity: ManifestEntity) -> UnityTransform:
    transform = entity.transform
    return UnityTransform(
        position=to_unity_position(transform.position),
        rotation=to_unity_rotation(transform.rotation_deg),
        scale=to_unity_scale(transform.scale),
    )


@dataclass(frozen=True)
class UnityIntegrationResult:
    scene_path: Path
    instantiated: int
    log: str


class UnitySceneIntegrator(ABC):
    """Interface: import a manifest into a Unity project."""

    @abstractmethod
    def integrate(self, manifest_path: Path, project_path: Path) -> UnityIntegrationResult:
        """Instantiate the manifest's entities in a Unity scene."""


class UnconfiguredUnityIntegrator(UnitySceneIntegrator):
    """Stub that always fails loudly."""

    def integrate(self, manifest_path: Path, project_path: Path) -> UnityIntegrationResult:
        raise AdapterUnavailableError(
            "Unity integration is not implemented in this phase. Consume scene-manifest.json with "
            "a Unity-side importer; docs/ADAPTERS.md describes the contract and coordinate mapping."
        )
