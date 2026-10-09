"""RNG, hashing, merge patch, spatial index, heightfield and noise."""

from __future__ import annotations

import json

import pytest

from environment_generator.core.hashing import (
    canonical_json,
    canonicalize,
    fingerprint,
    pretty_json,
)
from environment_generator.core.issues import (
    Severity,
    ValidationIssue,
    count_by_severity,
    sort_issues,
)
from environment_generator.core.patch import json_merge_patch
from environment_generator.core.rng import (
    MAX_SEED,
    DeterministicRng,
    derive_seed,
    hash_unit,
    splitmix64,
)
from environment_generator.core.spatial import Footprint, SpatialIndex
from environment_generator.core.terrain import FlatGround, Heightfield, fractal_noise, value_noise

# ----------------------------------------------------------------------------- rng


def test_rng_reference_values_are_stable() -> None:
    # SplitMix64(0) must match the published reference output 0xE220A8397B1DCDAF.
    assert splitmix64(0)[1] == 0xE220A8397B1DCDAF
    # Pinned outputs: changing them changes every generated manifest.
    rng = DeterministicRng(42)
    assert [rng.next_u64() for _ in range(3)] == [
        1546998764402558742,
        6990951692964543102,
        12544586762248559009,
    ]
    assert derive_seed(1337, "a") == 8228077153066095180


def test_rng_is_deterministic_and_seed_sensitive() -> None:
    a, b, c = DeterministicRng(7), DeterministicRng(7), DeterministicRng(8)
    seq_a = [a.random() for _ in range(50)]
    assert seq_a == [b.random() for _ in range(50)]
    assert seq_a != [c.random() for _ in range(50)]
    assert all(0.0 <= v < 1.0 for v in seq_a)


def test_rng_helpers_ranges() -> None:
    rng = DeterministicRng(3)
    ints = [rng.randint(-2, 2) for _ in range(500)]
    assert set(ints) == {-2, -1, 0, 1, 2}
    assert all(1.0 <= rng.uniform(1.0, 2.0) < 2.0 for _ in range(100))
    assert rng.choice(["x"]) == "x"
    items = list(range(10))
    rng.shuffle(items)
    assert sorted(items) == list(range(10))
    picks = [rng.weighted_index([0.0, 1.0, 0.0]) for _ in range(50)]
    assert set(picks) == {1}
    samples = [rng.gauss(10.0, 2.0) for _ in range(2000)]
    assert sum(samples) / len(samples) == pytest.approx(10.0, abs=0.2)


def test_rng_errors() -> None:
    rng = DeterministicRng(1)
    with pytest.raises(ValueError):
        DeterministicRng(-1)
    with pytest.raises(ValueError):
        rng.randint(3, 2)
    with pytest.raises(ValueError):
        rng.choice([])
    with pytest.raises(ValueError):
        rng.weighted_index([0.0, 0.0])


def test_fork_and_derive_are_independent_of_consumption() -> None:
    rng = DeterministicRng(99)
    first = rng.fork("child").random()
    rng.random()
    assert rng.fork("child").random() == first
    assert DeterministicRng.from_labels(99, "child").random() == first
    assert derive_seed(1, "a", "b") != derive_seed(1, "ab")
    assert 0 <= derive_seed(123, "x") <= MAX_SEED
    assert 0.0 <= hash_unit(5, "x") < 1.0


# ----------------------------------------------------------------------------- hashing


def test_canonicalize_rounds_and_normalises() -> None:
    assert canonicalize({"a": (1.234567, -0.00001)}) == {"a": [1.2346, 0.0]}
    with pytest.raises(ValueError):
        canonicalize(float("nan"))
    with pytest.raises(TypeError):
        canonicalize(object())


def test_canonical_json_is_key_order_independent() -> None:
    assert canonical_json({"b": 1, "a": [1.0, 2]}) == canonical_json({"a": [1.0, 2], "b": 1})
    assert fingerprint({"x": 1}).startswith("sha256:")
    assert fingerprint({"x": 1.00001}) == fingerprint({"x": 1.0})


def test_pretty_json_inlines_scalar_arrays_and_round_trips() -> None:
    data = {"points": [[1.0, 2.0], [3.0, 4.0]], "name": "x", "empty": [], "nested": {}}
    text = pretty_json(data)
    assert "[1.0, 2.0]" in text
    assert text.endswith("\n")
    assert json.loads(text) == data


# ----------------------------------------------------------------------------- issues


def test_issue_helpers() -> None:
    issues = [
        ValidationIssue.info("B", "info"),
        ValidationIssue.error("A", "boom", "x"),
        ValidationIssue.warning("C", "careful"),
    ]
    assert [i.severity for i in sort_issues(issues)] == [
        Severity.ERROR,
        Severity.WARNING,
        Severity.INFO,
    ]
    assert count_by_severity(issues) == {"error": 1, "warning": 1, "info": 1}
    assert issues[1].format() == "ERROR A [x]: boom"


# ----------------------------------------------------------------------------- patch


def test_json_merge_patch_rfc7396_semantics() -> None:
    target = {"a": {"b": 1, "c": 2}, "d": [1, 2], "e": 1}
    patched = json_merge_patch(target, {"a": {"b": 5, "c": None}, "d": [3], "f": {"g": 1}})
    assert patched == {"a": {"b": 5}, "d": [3], "e": 1, "f": {"g": 1}}
    assert target["a"] == {"b": 1, "c": 2}  # input untouched
    assert json_merge_patch({"a": 1}, [1, 2]) == [1, 2]


# ----------------------------------------------------------------------------- spatial


def test_spatial_index_queries_by_layer_and_owner() -> None:
    index = SpatialIndex(cell_size=4.0)
    square = Footprint.from_polygon("road-1", "road", [(0, 0), (10, 0), (10, 2), (0, 2)])
    tree = Footprint.from_circle("tree-1", "vegetation", (20.0, 20.0), 1.0)
    index.extend([square, tree])
    probe = Footprint.from_circle("p", "probe", (5.0, 3.0), 1.5)
    assert index.query(probe) == [square]
    assert index.query(probe, layers={"vegetation"}) == []
    assert not index.collides(probe, exclude_owner="road-1")
    assert index.collides(Footprint.from_circle("p", "probe", (21.0, 20.0), 0.5))
    assert len(index) == 2 and list(index) == [square, tree]


def test_footprint_inflation() -> None:
    circle = Footprint.from_circle("c", "x", (0.0, 0.0), 1.0).inflated(0.5)
    assert circle.radius == 1.5
    concave = Footprint.from_polygon(
        "l", "x", [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)]
    ).inflated(1.0)
    assert concave.polygon is not None
    assert concave.bounds == pytest.approx((-1.0, -1.0, 5.0, 5.0))
    with pytest.raises(ValueError):
        Footprint.from_circle("c", "x", (0.0, 0.0), 0.0)
    with pytest.raises(ValueError):
        Footprint.from_polygon("p", "x", [(0, 0), (1, 1)])


# ----------------------------------------------------------------------------- terrain


def test_heightfield_bilinear_and_clamping() -> None:
    field = Heightfield(2.0, 2, 2, ((0.0, 2.0), (4.0, 6.0)))
    assert field.height_at(0.0, 0.0) == 0.0
    assert field.height_at(1.0, 1.0) == pytest.approx(3.0)
    assert field.height_at(-5.0, 100.0) == 4.0
    assert FlatGround(3.5).height_at(1, 2) == 3.5
    with pytest.raises(ValueError):
        Heightfield(1.0, 2, 2, ((0.0,), (0.0, 1.0)))


def test_noise_is_deterministic_and_bounded() -> None:
    values = [fractal_noise(11, x * 0.37, x * 0.21, 4) for x in range(200)]
    assert values == [fractal_noise(11, x * 0.37, x * 0.21, 4) for x in range(200)]
    assert all(-1.0 <= v <= 1.0 for v in values)
    assert value_noise(1, 3.0, 4.0) != value_noise(2, 3.0, 4.0)
    assert value_noise(5, -3.5, -7.25) == value_noise(5, -3.5, -7.25)
