"""Reproducibility guarantees (docs/GENERATION_PIPELINE.md, "Determinism")."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from environment_generator.models.scene import SceneManifest
from environment_generator.pipeline import InputBundle, Pipeline
from tests.conftest import RURAL_BLUEPRINT, RURAL_OVERRIDES, RURAL_RECIPE, load_json


def manifest(**bundle: object) -> SceneManifest:
    result = Pipeline().run(InputBundle(**bundle))  # type: ignore[arg-type]
    assert result.success, result.error
    assert result.manifest is not None
    return result.manifest


def test_identical_inputs_give_identical_manifests() -> None:
    bundle = {"blueprint": RURAL_BLUEPRINT, "recipe": RURAL_RECIPE, "overrides": RURAL_OVERRIDES}
    first, second = manifest(**bundle), manifest(**bundle)
    assert first == second
    assert first.content_hash == second.content_hash


def test_inputs_as_files_or_data_are_equivalent() -> None:
    from_files = manifest(blueprint=RURAL_BLUEPRINT, recipe=RURAL_RECIPE)
    from_data = manifest(blueprint=load_json(RURAL_BLUEPRINT), recipe=load_json(RURAL_RECIPE))
    assert from_files.content_hash == from_data.content_hash


def test_seed_changes_the_layout_but_not_the_structure() -> None:
    a = manifest(blueprint=RURAL_BLUEPRINT, recipe=RURAL_RECIPE)
    b = manifest(blueprint=RURAL_BLUEPRINT, recipe=RURAL_RECIPE, seed_override=99)
    assert a.content_hash != b.content_hash
    assert b.source.seed == 99
    # Surveyed features keep their ids whatever the seed.
    explicit = {e.id for e in a.entities if e.provenance.rule == "explicit_footprint"}
    assert explicit == {e.id for e in b.entities if e.provenance.rule == "explicit_footprint"}


def test_disabling_a_generator_does_not_reshuffle_the_others() -> None:
    recipe = load_json(RURAL_RECIPE)
    full = manifest(blueprint=RURAL_BLUEPRINT, recipe=recipe)
    recipe["props"] = {"enabled": False}
    no_props = manifest(blueprint=RURAL_BLUEPRINT, recipe=recipe)
    without = {e.id: e for e in full.entities if e.category.value != "prop"}
    assert {e.id: e for e in no_props.entities} == without


def test_local_edits_keep_unrelated_entities_stable() -> None:
    blueprint = load_json(RURAL_BLUEPRINT)
    base = {e.id: e for e in manifest(blueprint=blueprint, recipe=RURAL_RECIPE).entities}
    blueprint["props"].append(
        {"id": "p-extra", "kind": "barrel", "geometry": {"type": "point", "position": [240, 20]}}
    )
    edited = {e.id: e for e in manifest(blueprint=blueprint, recipe=RURAL_RECIPE).entities}
    changed = {i for i in base if i in edited and base[i] != edited[i]}
    assert changed == set()
    assert set(edited) - set(base) == {"prop.p-extra"}


def _cli_generate(output: Path, hash_seed: str) -> bytes:
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}
    subprocess.run(
        [
            sys.executable,
            "-m",
            "environment_generator",
            "generate",
            "-b",
            str(RURAL_BLUEPRINT),
            "-r",
            str(RURAL_RECIPE),
            "-o",
            str(RURAL_OVERRIDES),
            "-d",
            str(output),
            "--no-timings",
        ],
        check=True,
        env=env,
        capture_output=True,
    )
    return (output / "scene-manifest.json").read_bytes()


def test_output_is_byte_identical_across_processes_and_hash_seeds(tmp_path: Path) -> None:
    first = _cli_generate(tmp_path / "a", "1")
    second = _cli_generate(tmp_path / "b", "4242")
    assert first == second
    report_a = (tmp_path / "a" / "generation-report.json").read_bytes()
    report_b = (tmp_path / "b" / "generation-report.json").read_bytes()
    assert report_a == report_b
