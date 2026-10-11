"""Height sampling primitives and deterministic value noise."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from environment_generator.core.rng import MASK64, splitmix64

_DOUBLE_UNIT = 1.0 / (1 << 53)


class HeightSampler(Protocol):
    """Anything that can answer "how high is the ground here?"."""

    def height_at(self, x: float, y: float) -> float: ...


@dataclass(frozen=True, slots=True)
class FlatGround:
    """Constant elevation, used when terrain generation is disabled."""

    elevation: float

    def height_at(self, x: float, y: float) -> float:
        return self.elevation


@dataclass(frozen=True, slots=True)
class Heightfield:
    """Regular grid of heights; ``heights[row][column]``, row 0 at the origin's Y."""

    cell_size: float
    columns: int
    rows: int
    heights: tuple[tuple[float, ...], ...]
    origin: tuple[float, float] = (0.0, 0.0)

    def __post_init__(self) -> None:
        if self.columns < 2 or self.rows < 2:
            raise ValueError("a heightfield needs at least 2x2 samples")
        if len(self.heights) != self.rows or any(len(r) != self.columns for r in self.heights):
            raise ValueError("heights do not match the declared grid shape")

    def height_at(self, x: float, y: float) -> float:
        """Bilinear interpolation, clamped to the grid."""
        gx = min(max((x - self.origin[0]) / self.cell_size, 0.0), self.columns - 1.0)
        gy = min(max((y - self.origin[1]) / self.cell_size, 0.0), self.rows - 1.0)
        i0 = min(math.floor(gx), self.columns - 2)
        j0 = min(math.floor(gy), self.rows - 2)
        tx, ty = gx - i0, gy - j0
        row0, row1 = self.heights[j0], self.heights[j0 + 1]
        bottom = row0[i0] + (row0[i0 + 1] - row0[i0]) * tx
        top = row1[i0] + (row1[i0 + 1] - row1[i0]) * tx
        return bottom + (top - bottom) * ty


def sample_grid(
    heights: list[list[float]] | tuple[tuple[float, ...], ...],
    width: float,
    depth: float,
    x: float,
    y: float,
) -> float:
    """Bilinear sample of a corner-aligned grid covering ``[0, width] x [0, depth]``.

    ``heights[row][column]``; row 0 lies on ``y = 0``, column 0 on ``x = 0``.
    """
    rows, columns = len(heights), len(heights[0])
    gx = min(max(x / width * (columns - 1), 0.0), columns - 1.0)
    gy = min(max(y / depth * (rows - 1), 0.0), rows - 1.0)
    i0 = min(math.floor(gx), columns - 2)
    j0 = min(math.floor(gy), rows - 2)
    tx, ty = gx - i0, gy - j0
    row0, row1 = heights[j0], heights[j0 + 1]
    bottom = row0[i0] + (row0[i0 + 1] - row0[i0]) * tx
    top = row1[i0] + (row1[i0 + 1] - row1[i0]) * tx
    return bottom + (top - bottom) * ty


def _lattice_value(seed: int, ix: int, iy: int) -> float:
    mixed = (seed * 0x9E3779B97F4A7C15 + ix * 0xC2B2AE3D27D4EB4F + iy * 0x165667B19E3779F9) & MASK64
    _, value = splitmix64(mixed)
    return (value >> 11) * _DOUBLE_UNIT * 2.0 - 1.0


def _smooth(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def value_noise(seed: int, x: float, y: float) -> float:
    """Smooth lattice noise in ``[-1, 1]``."""
    x0, y0 = math.floor(x), math.floor(y)
    tx, ty = _smooth(x - x0), _smooth(y - y0)
    ix, iy = int(x0), int(y0)
    v00 = _lattice_value(seed, ix, iy)
    v10 = _lattice_value(seed, ix + 1, iy)
    v01 = _lattice_value(seed, ix, iy + 1)
    v11 = _lattice_value(seed, ix + 1, iy + 1)
    bottom = v00 + (v10 - v00) * tx
    top = v01 + (v11 - v01) * tx
    return bottom + (top - bottom) * ty


def fractal_noise(
    seed: int, x: float, y: float, octaves: int, lacunarity: float = 2.0, gain: float = 0.5
) -> float:
    """Fractal Brownian motion of :func:`value_noise`, normalised to ``[-1, 1]``."""
    total = 0.0
    amplitude = 1.0
    frequency = 1.0
    norm = 0.0
    for octave in range(octaves):
        octave_seed = (seed + octave * 0x632BE59BD9B4E019) & MASK64
        total += amplitude * value_noise(octave_seed, x * frequency, y * frequency)
        norm += amplitude
        amplitude *= gain
        frequency *= lacunarity
    return total / norm if norm else 0.0
