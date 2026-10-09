"""Portable deterministic random numbers.

Python's :mod:`random` only guarantees a stable ``random()`` sequence across
versions; derived helpers (``randrange``, ``choice``, ``gauss`` ...) may change.
The generator therefore ships its own fully specified PRNG (xoshiro256**
seeded through SplitMix64) and derives every seed from labelled SHA-256
hashes. The same algorithms can be re-implemented bit-for-bit in C# or C++ if
an engine-side consumer ever needs to reproduce a placement.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import MutableSequence, Sequence
from typing import TypeVar

T = TypeVar("T")

MASK64 = (1 << 64) - 1
MAX_SEED = (1 << 63) - 1
_DOUBLE_UNIT = 1.0 / (1 << 53)


def splitmix64(state: int) -> tuple[int, int]:
    """Advance a SplitMix64 state; returns ``(new_state, output)``."""
    state = (state + 0x9E3779B97F4A7C15) & MASK64
    z = state
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return state, z ^ (z >> 31)


def derive_seed(base_seed: int, *labels: str | int) -> int:
    """Derive a 63-bit child seed from a base seed and a path of labels.

    Seeds derived from different label paths are statistically independent,
    so generators can be reordered, added or removed without shifting the
    random streams of unrelated features.
    """
    payload = "\x1f".join([str(base_seed), *(str(label) for label in labels)])
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & MAX_SEED


def hash_unit(base_seed: int, *labels: str | int) -> float:
    """A uniform float in ``[0, 1)`` that depends only on the seed and labels."""
    return (derive_seed(base_seed, *labels) >> 10) * _DOUBLE_UNIT


def _rotl(value: int, shift: int) -> int:
    return ((value << shift) | (value >> (64 - shift))) & MASK64


class DeterministicRng:
    """xoshiro256** generator with convenience sampling methods."""

    __slots__ = ("_state", "seed")

    def __init__(self, seed: int) -> None:
        if seed < 0:
            raise ValueError("seed must be non-negative")
        self.seed = seed
        state = seed & MASK64
        words: list[int] = []
        for _ in range(4):
            state, value = splitmix64(state)
            words.append(value)
        self._state = words

    @classmethod
    def from_labels(cls, base_seed: int, *labels: str | int) -> DeterministicRng:
        return cls(derive_seed(base_seed, *labels))

    def fork(self, *labels: str | int) -> DeterministicRng:
        """Independent child generator; does not consume from this stream."""
        return DeterministicRng(derive_seed(self.seed, *labels))

    def next_u64(self) -> int:
        s0, s1, s2, s3 = self._state
        result = (_rotl((s1 * 5) & MASK64, 7) * 9) & MASK64
        t = (s1 << 17) & MASK64
        s2 ^= s0
        s3 ^= s1
        s1 ^= s2
        s0 ^= s3
        s2 ^= t
        s3 = _rotl(s3, 45)
        self._state = [s0, s1, s2, s3]
        return result

    def random(self) -> float:
        """Uniform float in ``[0, 1)`` with 53 bits of precision."""
        return (self.next_u64() >> 11) * _DOUBLE_UNIT

    def uniform(self, low: float, high: float) -> float:
        return low + (high - low) * self.random()

    def randint(self, low: int, high: int) -> int:
        """Uniform integer in ``[low, high]`` (inclusive, unbiased)."""
        if high < low:
            raise ValueError("high must be >= low")
        span = high - low + 1
        limit = (1 << 64) - ((1 << 64) % span)
        while True:
            value = self.next_u64()
            if value < limit:
                return low + value % span

    def chance(self, probability: float) -> bool:
        return self.random() < probability

    def choice(self, items: Sequence[T]) -> T:
        if not items:
            raise ValueError("cannot choose from an empty sequence")
        return items[self.randint(0, len(items) - 1)]

    def weighted_index(self, weights: Sequence[float]) -> int:
        total = math.fsum(weights)
        if total <= 0 or any(w < 0 for w in weights):
            raise ValueError("weights must be non-negative with a positive sum")
        target = self.random() * total
        cumulative = 0.0
        for index, weight in enumerate(weights):
            cumulative += weight
            if target < cumulative:
                return index
        # Floating point slack: return the last positive weight.
        return max(i for i, w in enumerate(weights) if w > 0)

    def shuffle(self, items: MutableSequence[T]) -> None:
        for i in range(len(items) - 1, 0, -1):
            j = self.randint(0, i)
            items[i], items[j] = items[j], items[i]

    def gauss(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        """Normal variate (Box-Muller, one value per call)."""
        u1 = 1.0 - self.random()  # (0, 1]
        u2 = self.random()
        return mu + sigma * math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
