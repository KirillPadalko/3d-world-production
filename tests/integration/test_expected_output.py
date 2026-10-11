"""Golden tests against ``examples/expected-output``.

If generation behaviour changes on purpose, regenerate the files with
``uv run python scripts/regenerate_expected_output.py`` and commit them.

Floats are compared with a small tolerance so that last-digit differences in
platform math libraries do not fail the test; structure, ids, archetypes and
parameters must match exactly.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import pytest

from environment_generator.pipeline import Pipeline, PipelineOptions
from tests.conftest import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "regenerate_expected_output", REPO_ROOT / "scripts" / "regenerate_expected_output.py"
)
assert _spec is not None and _spec.loader is not None
regenerate = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = regenerate  # dataclasses resolve annotations via sys.modules
_spec.loader.exec_module(regenerate)

TOLERANCE = 1e-3


def assert_close(expected: Any, actual: Any, path: str = "$") -> None:
    if isinstance(expected, float) or isinstance(actual, float):
        assert isinstance(actual, (int, float)) and not isinstance(actual, bool), path
        assert math.isclose(expected, actual, abs_tol=TOLERANCE), f"{path}: {expected} != {actual}"
    elif isinstance(expected, dict):
        assert isinstance(actual, dict) and set(expected) == set(actual), path
        for key in expected:
            if key in {"contentHash", "content_hash", "manifestContentHash", "inputFingerprint"}:
                continue
            assert_close(expected[key], actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(expected) == len(actual), f"{path}: length differs"
        for index, (e, a) in enumerate(zip(expected, actual, strict=True)):
            assert_close(e, a, f"{path}[{index}]")
    else:
        assert expected == actual, f"{path}: {expected!r} != {actual!r}"


@pytest.mark.parametrize("case", regenerate.CASES, ids=lambda c: c.name)
def test_matches_expected_output(case: Any, tmp_path: Path) -> None:
    expected_dir = REPO_ROOT / "examples" / "expected-output" / case.name
    result = Pipeline().run(
        case.bundle(),
        PipelineOptions(output_dir=tmp_path, write_preview=True, include_timings=False),
    )
    assert result.success, result.error
    for filename in ("scene-manifest.json", "generation-report.json"):
        expected = json.loads((expected_dir / filename).read_text(encoding="utf-8"))
        actual = json.loads((tmp_path / filename).read_text(encoding="utf-8"))
        assert_close(expected, actual, filename)
    assert (expected_dir / "preview.svg").exists()
