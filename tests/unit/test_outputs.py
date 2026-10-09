"""Manifest exporter, SVG preview and text report."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from environment_generator.core.errors import ExportError
from environment_generator.exporters import (
    JsonManifestExporter,
    build_manifest,
    load_manifest,
    manifest_content_hash,
    verify_manifest,
)
from environment_generator.pipeline import InputBundle, Pipeline, PipelineOptions
from environment_generator.reporting import render_report, render_svg
from tests.conftest import MINIMAL_BLUEPRINT


@pytest.fixture(scope="module")
def minimal_result():  # type: ignore[no-untyped-def]
    result = Pipeline().run(InputBundle(blueprint=MINIMAL_BLUEPRINT))
    assert result.success
    return result


def test_manifest_hash_is_verifiable(minimal_result) -> None:  # type: ignore[no-untyped-def]
    manifest = minimal_result.manifest
    assert verify_manifest(manifest)
    tampered = manifest.model_copy(update={"entities": manifest.entities[1:]})
    assert not verify_manifest(tampered)
    data = manifest.model_dump(mode="json")
    assert manifest_content_hash(data) == manifest.content_hash
    data["content_hash"] = "sha256:other"
    assert manifest_content_hash(data) == manifest.content_hash  # field itself is excluded


def test_manifest_contents(minimal_result) -> None:  # type: ignore[no-untyped-def]
    manifest = minimal_result.manifest
    assert manifest.coordinate_system.up_axis == "+z"
    assert manifest.source.blueprint_id == "minimal"
    assert manifest.statistics.entity_count == len(manifest.entities)
    assert sum(manifest.statistics.by_category.values()) == len(manifest.entities)
    ids = [e.id for e in manifest.entities]
    assert ids == sorted(ids)
    for entity in manifest.entities:
        assert entity.provenance.implementation.count("@") == 1


def test_written_manifest_round_trips(minimal_result, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    exporter = JsonManifestExporter()
    result = exporter.export(minimal_result.scene, minimal_result.plan, tmp_path)
    assert result.path is not None
    text = result.path.read_text(encoding="utf-8")
    assert text.endswith("\n") and '"position": [' in text
    loaded = load_manifest(result.path)
    assert verify_manifest(loaded)
    assert loaded.content_hash == result.manifest.content_hash
    assert build_manifest(minimal_result.scene, minimal_result.plan) == result.manifest


def test_export_errors_are_structured(minimal_result, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(ExportError):
        JsonManifestExporter().export(minimal_result.scene, minimal_result.plan, blocker / "sub")


def test_svg_preview_is_well_formed(minimal_result) -> None:  # type: ignore[no-untyped-def]
    svg = render_svg(minimal_result.manifest)
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")
    titles = [el.text for el in root.iter() if el.tag.endswith("title")]
    assert "building.b-1 (building.house.small_gable)" in titles or any(
        t and t.startswith("building.b-1") for t in titles
    )
    assert "Minimal example" in svg


def test_text_report(minimal_result) -> None:  # type: ignore[no-untyped-def]
    text = render_report(minimal_result.report)
    assert text.startswith("GENERATION succeeded")
    assert "generate_scene" in text and "Manifest hash" in text


def test_report_json_lists_all_stages(tmp_path: Path) -> None:
    result = Pipeline().run(
        InputBundle(blueprint=MINIMAL_BLUEPRINT),
        PipelineOptions(output_dir=tmp_path, include_timings=False),
    )
    report = json.loads((tmp_path / "generation-report.json").read_text(encoding="utf-8"))
    assert [s["name"] for s in report["stages"]] == [
        "load_inputs",
        "resolve_inputs",
        "resolve_assets",
        "plan_generation",
        "generate_scene",
        "validate_layout",
        "export_manifest",
        "build_report",
    ]
    assert all(s["duration_ms"] is None for s in report["stages"])
    assert report["outputs"] == {
        "manifest": "scene-manifest.json",
        "report": "generation-report.json",
    }
    assert result.report.success
