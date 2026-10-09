"""End-to-end pipeline runs on the shipped examples."""

from __future__ import annotations

from pathlib import Path

import pytest

from environment_generator.core.errors import LayoutValidationError, OverrideError
from environment_generator.core.issues import Severity
from environment_generator.exporters.base import ExportResult, SceneExporter
from environment_generator.generators import default_generators
from environment_generator.generators.base import GeneratorSet
from environment_generator.generators.vegetation import ScatterVegetationGenerator
from environment_generator.models.assets import AssetCategory
from environment_generator.models.pipeline import GenerationPlan
from environment_generator.models.report import StageStatus
from environment_generator.models.scene import Scene
from environment_generator.pipeline import InputBundle, Pipeline, PipelineOptions
from tests.conftest import (
    INDUSTRIAL_BLUEPRINT,
    MINIMAL_BLUEPRINT,
    RURAL_BLUEPRINT,
    RURAL_OVERRIDES,
    RURAL_RECIPE,
    WAR_TORN_RECIPE,
    blueprint_data,
    rect_building,
    road,
)

EXAMPLE_CASES = [
    (RURAL_BLUEPRINT, RURAL_RECIPE, None),
    (RURAL_BLUEPRINT, RURAL_RECIPE, RURAL_OVERRIDES),
    (RURAL_BLUEPRINT, WAR_TORN_RECIPE, None),
    (INDUSTRIAL_BLUEPRINT, RURAL_RECIPE, None),
    (INDUSTRIAL_BLUEPRINT, WAR_TORN_RECIPE, None),
    (MINIMAL_BLUEPRINT, None, None),
]


@pytest.mark.parametrize(("blueprint", "recipe", "overrides"), EXAMPLE_CASES)
def test_examples_generate_valid_layouts(
    blueprint: Path, recipe: Path | None, overrides: Path | None
) -> None:
    result = Pipeline().run(InputBundle(blueprint=blueprint, recipe=recipe, overrides=overrides))
    assert result.success, result.error
    assert result.manifest is not None and result.layout is not None
    assert not result.layout.has_errors
    assert all(s.status is StageStatus.SUCCEEDED for s in result.report.stages)
    assert result.manifest.statistics.placeholder_count == 0
    categories = set(result.manifest.statistics.by_category)
    assert {"terrain", "building", "road"} <= categories


def test_rural_example_covers_every_generator() -> None:
    result = Pipeline().run(InputBundle(blueprint=RURAL_BLUEPRINT, recipe=RURAL_RECIPE))
    assert result.manifest is not None
    assert set(result.manifest.statistics.by_generator) == {
        "terrain",
        "roads",
        "buildings",
        "fences",
        "infrastructure",
        "vegetation",
        "props",
    }
    assert result.manifest.atmosphere is not None
    rules = {e.provenance.rule for e in result.manifest.entities}
    assert {"zone_infill", "street_light_spacing", "building_clutter", "junction"} <= rules


def test_overrides_are_applied_and_traceable() -> None:
    base = Pipeline().run(InputBundle(blueprint=RURAL_BLUEPRINT, recipe=RURAL_RECIPE))
    edited = Pipeline().run(
        InputBundle(blueprint=RURAL_BLUEPRINT, recipe=RURAL_RECIPE, overrides=RURAL_OVERRIDES)
    )
    assert base.manifest is not None and edited.manifest is not None
    before = {e.id: e for e in base.manifest.entities}
    after = {e.id: e for e in edited.manifest.entities}
    assert "building.b-shed-1" in before and "building.b-shed-1" not in after
    assert "vegetation.t-oak-2" in before and "vegetation.t-oak-2" not in after
    assert after["building.b-barn"].parameters["condition"] == "ruined"
    assert "prop.p-checkpoint-1" in after
    shop = after["building.b-shop"]
    assert shop.archetype_id == "building.house.flat_modern"
    assert shop.provenance.overrides == ["designer-pass-01#entity_operations[0]"]
    car = after["prop.p-car-1"]
    assert car.transform.position == (120.5, 119.0, 2.0)
    assert edited.manifest.atmosphere is not None
    assert edited.manifest.atmosphere.time_of_day.value == "dusk"
    assert edited.manifest.source.overrides_id == "designer-pass-01"


def test_dry_run_stops_after_planning(tmp_path: Path) -> None:
    result = Pipeline().run(
        InputBundle(blueprint=RURAL_BLUEPRINT, recipe=RURAL_RECIPE),
        PipelineOptions(output_dir=tmp_path, dry_run=True),
    )
    assert result.success and result.plan is not None
    assert result.scene is None and result.manifest is None
    statuses = {s.name: s.status for s in result.report.stages}
    assert statuses["generate_scene"] is StageStatus.SKIPPED
    assert statuses["plan_generation"] is StageStatus.SUCCEEDED
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "generation-plan.json",
        "generation-report.json",
    ]
    assert result.report.dry_run


def test_generation_from_saved_plan_matches_direct_run(tmp_path: Path) -> None:
    bundle = InputBundle(blueprint=RURAL_BLUEPRINT, recipe=RURAL_RECIPE, overrides=RURAL_OVERRIDES)
    direct = Pipeline().run(
        bundle, PipelineOptions(output_dir=tmp_path / "direct", write_plan=True)
    )
    plan = GenerationPlan.model_validate_json(
        (tmp_path / "direct" / "generation-plan.json").read_text(encoding="utf-8")
    )
    replay = Pipeline().run_plan(plan, PipelineOptions(output_dir=tmp_path / "replay"))
    assert replay.success
    assert direct.manifest is not None and replay.manifest is not None
    assert replay.manifest.content_hash == direct.manifest.content_hash
    skipped = [s.name for s in replay.report.stages if s.status is StageStatus.SKIPPED]
    assert skipped == ["load_inputs", "resolve_inputs", "resolve_assets", "plan_generation"]


def test_failures_produce_reports_and_skip_later_stages(tmp_path: Path) -> None:
    overrides = {
        "schema_version": "1.0",
        "id": "bad",
        "blueprint_id": "rural-crossroads",
        "entity_operations": [{"op": "remove", "entity_id": "building.does-not-exist"}],
    }
    result = Pipeline().run(
        InputBundle(blueprint=RURAL_BLUEPRINT, recipe=RURAL_RECIPE, overrides=overrides),
        PipelineOptions(output_dir=tmp_path),
    )
    assert not result.success
    assert isinstance(result.error, OverrideError)
    statuses = {s.name: s.status for s in result.report.stages}
    assert statuses["generate_scene"] is StageStatus.FAILED
    assert statuses["validate_layout"] is StageStatus.SKIPPED
    assert result.report.error is not None and result.report.error.stage == "generate_scene"
    assert (tmp_path / "generation-report.json").exists()
    assert not (tmp_path / "scene-manifest.json").exists()


def test_layout_errors_fail_unless_disabled() -> None:
    data = blueprint_data(
        roads=[road("r", [[0, 40], [100, 40]])],
        buildings=[rect_building("on-road", [50, 40], [10, 8])],
    )
    failed = Pipeline().run(InputBundle(blueprint=data))
    assert isinstance(failed.error, LayoutValidationError)
    assert any(i.code == "LAYOUT_ROAD_OBSTRUCTED" for i in failed.error.issues)
    lenient = {
        "schema_version": "1.0",
        "id": "l",
        "name": "L",
        "validation": {"fail_on_error": False},
    }
    passed = Pipeline().run(InputBundle(blueprint=data, recipe=lenient))
    assert passed.success and passed.layout is not None
    assert any(i.severity is Severity.ERROR for i in passed.layout.issues)


def test_components_are_replaceable() -> None:
    class SparseVegetation(ScatterVegetationGenerator):
        implementation = "sparse_vegetation"
        version = "0.1.0"

        def generate(self, context):  # type: ignore[no-untyped-def]
            output = super().generate(context)
            output.entities = output.entities[::4]
            return output

    class MemoryExporter(SceneExporter):
        def __init__(self) -> None:
            self.calls = 0

        def export(
            self, scene: Scene, plan: GenerationPlan, destination: Path | None
        ) -> ExportResult:
            from environment_generator.exporters import build_manifest

            self.calls += 1
            return ExportResult(build_manifest(scene, plan), None)

    defaults = default_generators()
    generators = GeneratorSet(
        **{**{g.slot.value: g for g in defaults}, "vegetation": SparseVegetation()}  # type: ignore[arg-type]
    )
    exporter = MemoryExporter()
    custom = Pipeline(generators=generators, exporter=exporter).run(
        InputBundle(blueprint=RURAL_BLUEPRINT, recipe=RURAL_RECIPE)
    )
    standard = Pipeline().run(InputBundle(blueprint=RURAL_BLUEPRINT, recipe=RURAL_RECIPE))
    assert custom.success and exporter.calls == 1
    assert custom.plan is not None
    vegetation_task = next(t for t in custom.plan.tasks if t.generator.value == "vegetation")
    assert vegetation_task.implementation == "sparse_vegetation@0.1.0"
    assert custom.manifest is not None and standard.manifest is not None
    count = custom.manifest.statistics.by_category["vegetation"]
    assert count < standard.manifest.statistics.by_category["vegetation"] / 2
    sample = next(e for e in custom.manifest.entities if e.category is AssetCategory.VEGETATION)
    assert sample.provenance.implementation == "sparse_vegetation@0.1.0"
