"""Unity integration adapter.

STATUS: the integrator is a STUB - importing a manifest into a Unity project
is the job of a Unity-side (C#) importer that does not exist yet. The
coordinate helpers below are real, pure-math functions with tests; a Unity
importer can port them line by line.

Manifest frame: right-handed, +X east, +Y north, +Z up, yaw counter-clockwise
from above, local +Y is an object's front.

Unity frame: left-handed, +X right, +Y up, +Z forward.

Mapping: ``unity = (x, z, y)`` for positions and scales; rotations are
converted by conjugating with the axis swap, which for a pure yaw ``θ`` gives a
Unity Y rotation of ``-θ``.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from environment_generator.core.errors import AdapterUnavailableError
from environment_generator.models.scene import SceneEntity

Vec3 = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]  # (x, y, z, w)
Matrix3 = tuple[Vec3, Vec3, Vec3]


def to_unity_position(position: Vec3) -> Vec3:
    x, y, z = position
    return (x, z, y)


def to_unity_scale(scale: Vec3) -> Vec3:
    sx, sy, sz = scale
    return (sx, sz, sy)


def to_unity_yaw(yaw_deg: float) -> float:
    """Unity ``eulerAngles.y`` for a manifest yaw, in ``[0, 360)``."""
    result = (-yaw_deg) % 360.0
    return 0.0 if result == 360.0 else result


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
    """Rotation matrix of an extrinsic X-Y-Z Euler rotation (``Rz @ Ry @ Rx``)."""
    rx, ry, rz = (math.radians(a) for a in rotation_deg)
    return _matmul(_rotation_z(rz), _matmul(_rotation_y(ry), _rotation_x(rx)))


def to_unity_rotation_matrix(rotation_deg: Vec3) -> Matrix3:
    """The same physical rotation expressed in Unity axes (``M R M`` with M swapping Y/Z)."""
    r = manifest_rotation_matrix(rotation_deg)
    swap = (0, 2, 1)
    return (
        (r[swap[0]][swap[0]], r[swap[0]][swap[1]], r[swap[0]][swap[2]]),
        (r[swap[1]][swap[0]], r[swap[1]][swap[1]], r[swap[1]][swap[2]]),
        (r[swap[2]][swap[0]], r[swap[2]][swap[1]], r[swap[2]][swap[2]]),
    )


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
    """Unity ``Quaternion`` components ``(x, y, z, w)`` for a manifest rotation."""
    return matrix_to_quaternion(to_unity_rotation_matrix(rotation_deg))


@dataclass(frozen=True)
class UnityTransform:
    position: Vec3
    rotation: Quaternion
    scale: Vec3


def entity_to_unity_transform(entity: SceneEntity) -> UnityTransform:
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
