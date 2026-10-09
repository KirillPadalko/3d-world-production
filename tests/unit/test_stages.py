"""Each pipeline stage run on its own."""

from __future__ import annotations

from pathlib import Path

import pytest

from environment_generator import __version__
from environment_generator.core.errors import (
    AssetResolutionError,
    ContractValidationError,
    GenerationError,
    InputLoadError,
    LayoutValidationError,
    OverrideError,
    PlanningError,
    SemanticValidationError,
)
from environment_generator.exporters import JsonManifestExporter
from environment_generator.generators import default_generators
from environment_generator.generators.base import GeneratorOutput, GeneratorSet
from environment_generator.generators.props import ClutterPropGenerator
from environment_generator.models.assets import AssetCategory
from environment_generator.models.pipeline import GenerationPlan
from environment_generator.models.report import StageReport, StageStatus
from environment_generator.pipeline.stages import (
    BuildReportStage,
    ExportInput,
    ExportManifestStage,
    GenerateSceneStage,
    InputBundle,
    LayoutInput,
    LoadInputsStage,
    PlanGenerationStage,
    PlanningInput,
    ReportInput,
    ResolveAssetsStage,
    ResolveInputsStage,
    ValidateLayoutStage,
)
from environment_generator.planning.planner import GenerationPlanner
from environment_generator.validation.layout import RuleBasedLayoutValidator
from tests.conftest import (
    MINIMAL_BLUEPRINT,
    RURAL_BLUEPRINT,
    RURAL_OVERRIDES,
    RURAL_RECIPE,
    blueprint_data,
    rect_building,
)

PLANNER = GenerationPlanner(default_generators())


def plan_for(bundle: InputBundle) -> GenerationPlan:
    loaded = LoadInputsStage().run(bundle).output
    resolved = ResolveInputsStage().run(loaded).output
    palette = ResolveAssetsStage(PLANNER).run(resolved).output
    return PlanGenerationStage(PLANNER).run(PlanningInput(resolved, palette)).output


# ----------------------------------------------------------------------------- 1 load


def test_load_defaults_and_fingerprints() -> None:
    outcome = LoadInputsStage().run(InputBundle(blueprint=MINIMAL_BLUEPRINT))
    loaded = outcome.output
    assert loaded.recipe.id == "default"
    assert loaded.registry.id == "builtin-stylized"
    assert loaded.overrides is None and loaded.fingerprints.overrides is None
    assert outcome.summary["blueprint_id"] == "minimal"
    again = LoadInputsStage().run(InputBundle(blueprint=MINIMAL_BLUEPRINT)).output
    assert again.fingerprints == loaded.fingerprints
    seeded = LoadInputsStage().run(InputBundle(blueprint=MINIMAL_BLUEPRINT, seed_override=3)).output
    assert seeded.fingerprints.combined != loaded.fingerprints.combined


def test_load_reports_all_contract_errors_at_once(tmp_path: Path) -> None:
    bad_recipe = {"schema_version": "1.0", "id": "r", "name": "R", "seed": -1}
    with pytest.raises(ContractValidationError) as excinfo:
        LoadInputsStage().run(InputBundle(blueprint=blueprint_data(extent={}), recipe=bad_recipe))
    locations = {issue.location for issue in excinfo.value.issues}
    assert any(loc and loc.startswith("blueprint:extent") for loc in locations)
    assert "recipe:seed" in locations


def test_load_file_errors(tmp_path: Path) -> None:
    with pytest.raises(InputLoadError, match="Cannot read"):
        LoadInputsStage().run(InputBundle(blueprint=tmp_path / "missing.json"))
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(InputLoadError, match="line 1"):
        LoadInputsStage().run(InputBundle(blueprint=broken))
    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(InputLoadError, match="JSON object"):
        LoadInputsStage().run(InputBundle(blueprint=array))


def test_load_semantic_errors() -> None:
    data = blueprint_data(buildings=[rect_building("b", [1000, 1000], [5, 5])])
    with pytest.raises(SemanticValidationError) as excinfo:
        LoadInputsStage().run(InputBundle(blueprint=data))
    assert excinfo.value.exit_code == 3
    assert "BLUEPRINT_FEATURE_OUTSIDE_EXTENT" in {i.code for i in excinfo.value.issues}


# ----------------------------------------------------------------------------- 2 resolve


def test_resolve_applies_overrides_and_seed_precedence() -> None:
    bundle = InputBundle(blueprint=RURAL_BLUEPRINT, recipe=RURAL_RECIPE, overrides=RURAL_OVERRIDES)
    loaded = LoadInputsStage().run(bundle).output
    resolved = ResolveInputsStage().run(loaded).output
    assert resolved.overrides_id == "designer-pass-01"
    assert "b-shed-1" not in {b.id for b in resolved.blueprint.buildings}
    assert resolved.recipe.atmosphere.time_of_day is not None
    assert resolved.seed == 1337  # no override seed
    assert len(resolved.entity_operations) == 3
    assert resolved.applied_operations[0] == "recipe_patch"

    with_seed = loaded.model_copy(
        update={
            "overrides": loaded.overrides.model_copy(update={"seed": 5})
            if loaded.overrides
            else None
        }
    )
    assert ResolveInputsStage().run(with_seed).output.seed == 5
    cli_seed = with_seed.model_copy(update={"seed_override": 9})
    resolved_cli = ResolveInputsStage().run(cli_seed).output
    assert resolved_cli.seed == 9 and resolved_cli.recipe.seed == 9


def test_resolve_drops_low_confidence_and_rejects_bad_overrides() -> None:
    loaded = (
        LoadInputsStage().run(InputBundle(blueprint=RURAL_BLUEPRINT, recipe=RURAL_RECIPE)).output
    )
    stricter = loaded.model_copy(
        update={
            "recipe": loaded.recipe.model_copy(
                update={"filters": loaded.recipe.filters.model_copy(update={"min_confidence": 0.8})}
            )
        }
    )
    outcome = ResolveInputsStage().run(stricter)
    assert "roads/p-forest" in outcome.output.dropped_features
    assert [i.code for i in outcome.issues] == ["FEATURES_BELOW_CONFIDENCE"]

    bad = {
        "schema_version": "1.0",
        "id": "bad",
        "blueprint_id": "rural-crossroads",
        "feature_operations": [{"op": "remove", "collection": "roads", "id": "nope"}],
    }
    loaded_bad = LoadInputsStage().run(InputBundle(blueprint=RURAL_BLUEPRINT, overrides=bad)).output
    with pytest.raises(OverrideError):
        ResolveInputsStage().run(loaded_bad)


# ----------------------------------------------------------------------------- 3 assets


def test_asset_stage_fallback_policy() -> None:
    data = blueprint_data(buildings=[rect_building("b", [50, 40], [8, 6], kind="church")])
    registry = {
        "schema_version": "1.0",
        "id": "tiny",
        "name": "Tiny",
        "archetypes": [
            {
                "id": "building.house.box",
                "category": "building",
                "kinds": ["house"],
                "dimensions": {"width_m": 8, "depth_m": 6, "height_m": 5},
                "asset_ref": "x",
            }
        ],
    }
    lenient = LoadInputsStage().run(InputBundle(blueprint=data, registry=registry)).output
    resolved = ResolveInputsStage().run(lenient).output
    outcome = ResolveAssetsStage(PLANNER).run(resolved)
    assert outcome.output.unmet_needs
    assert all(i.code == "ASSET_KIND_UNAVAILABLE" for i in outcome.issues)

    strict_recipe = {
        "schema_version": "1.0",
        "id": "s",
        "name": "S",
        "assets": {"fallback": "error"},
    }
    strict = (
        LoadInputsStage()
        .run(InputBundle(blueprint=data, recipe=strict_recipe, registry=registry))
        .output
    )
    with pytest.raises(AssetResolutionError) as excinfo:
        ResolveAssetsStage(PLANNER).run(ResolveInputsStage().run(strict).output)
    assert excinfo.value.exit_code == 4


# ----------------------------------------------------------------------------- 5 generate


def test_generate_stage_runs_plan_and_checks_compatibility() -> None:
    plan = plan_for(InputBundle(blueprint=MINIMAL_BLUEPRINT))
    outcome = GenerateSceneStage(default_generators()).run(plan)
    scene = outcome.output
    assert [e.id for e in scene.entities] == sorted(e.id for e in scene.entities)
    assert scene.terrain is not None and scene.atmosphere is not None
    assert outcome.summary["entities"] == len(scene.entities)

    old = plan.model_copy(update={"generator_version": "0.0.1"})
    with pytest.raises(PlanningError, match=r"0\.0\.1"):
        GenerateSceneStage(default_generators()).run(old)
    tampered = plan.model_copy(
        update={
            "tasks": [
                plan.tasks[0].model_copy(update={"implementation": "other@9"}),
                *plan.tasks[1:],
            ]
        }
    )
    with pytest.raises(PlanningError, match="other@9"):
        GenerateSceneStage(default_generators()).run(tampered)
    assert plan.generator_version == __version__


class _RogueProps(ClutterPropGenerator):
    """Violates the slot contract by emitting a building."""

    def generate(self, context):  # type: ignore[no-untyped-def]
        building = next(iter(context.entities_of(AssetCategory.BUILDING)))
        return GeneratorOutput(entities=[building.model_copy(update={"id": "building.rogue"})])


class _BrokenProps(ClutterPropGenerator):
    def generate(self, context):  # type: ignore[no-untyped-def]
        raise ValueError("boom")


@pytest.mark.parametrize(
    ("generator", "message"), [(_RogueProps(), "emitted a building"), (_BrokenProps(), "boom")]
)
def test_generate_stage_enforces_slot_contracts(
    generator: ClutterPropGenerator, message: str
) -> None:
    defaults = default_generators()
    generators = GeneratorSet(**{**{g.slot.value: g for g in defaults}, "props": generator})  # type: ignore[arg-type]
    plan = plan_for(InputBundle(blueprint=MINIMAL_BLUEPRINT))
    with pytest.raises(GenerationError, match=message) as excinfo:
        GenerateSceneStage(generators).run(plan)
    assert excinfo.value.generator == "props"


# ----------------------------------------------------------------------------- 6-8


def test_validate_export_and_report_stages(tmp_path: Path) -> None:
    plan = plan_for(InputBundle(blueprint=MINIMAL_BLUEPRINT))
    scene = GenerateSceneStage(default_generators()).run(plan).output
    layout = ValidateLayoutStage(RuleBasedLayoutValidator()).run(LayoutInput(scene, plan))
    assert layout.summary["errors"] == 0

    broken = scene.model_copy(update={"entities": [*scene.entities, scene.entities[0]]})
    with pytest.raises(LayoutValidationError) as excinfo:
        ValidateLayoutStage(RuleBasedLayoutValidator()).run(LayoutInput(broken, plan))
    assert excinfo.value.exit_code == 5
    lenient_plan = plan.model_copy(
        update={
            "recipe": plan.recipe.model_copy(
                update={
                    "validation": plan.recipe.validation.model_copy(update={"fail_on_error": False})
                }
            )
        }
    )
    assert (
        ValidateLayoutStage(RuleBasedLayoutValidator())
        .run(LayoutInput(broken, lenient_plan))
        .output.has_errors
    )

    exported = ExportManifestStage(JsonManifestExporter()).run(ExportInput(scene, plan, tmp_path))
    assert exported.output.path == tmp_path / "scene-manifest.json"
    assert exported.output.manifest.content_hash.startswith("sha256:")

    report = (
        BuildReportStage()
        .run(
            ReportInput(
                stages=(StageReport(name="load_inputs", status=StageStatus.SUCCEEDED),),
                dry_run=False,
                manifest=exported.output.manifest,
                outputs={"manifest": "scene-manifest.json"},
            )
        )
        .output
    )
    assert report.success and report.statistics["entities"] == len(scene.entities)
    assert report.manifest_content_hash == exported.output.manifest.content_hash
