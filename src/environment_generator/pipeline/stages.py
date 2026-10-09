"""The eight pipeline stages.

Every stage is a small class with a typed input, a typed output wrapped in a
:class:`StageOutcome` (output + non-fatal issues + summary), and raises a
subclass of :class:`EnvironmentGeneratorError` on failure. Stages can be run
on their own; :class:`~environment_generator.pipeline.runner.Pipeline` wires
them together.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from environment_generator import GENERATOR_NAME, __version__
from environment_generator.assets.registry import build_palette, load_builtin_registry
from environment_generator.assets.resolver import PaletteAssetResolver
from environment_generator.core.errors import (
    AssetResolutionError,
    ContractValidationError,
    EnvironmentGeneratorError,
    GenerationError,
    LayoutValidationError,
    PlanningError,
    SemanticValidationError,
)
from environment_generator.core.hashing import fingerprint
from environment_generator.core.issues import (
    Severity,
    ValidationIssue,
    count_by_severity,
    has_errors,
    sort_issues,
)
from environment_generator.core.rng import derive_seed
from environment_generator.core.spatial import SpatialIndex
from environment_generator.core.terrain import FlatGround, HeightSampler
from environment_generator.exporters.base import ExportResult, SceneExporter
from environment_generator.generators.base import GenerationContext, GeneratorSet
from environment_generator.models.assets import AssetPalette, AssetRegistryDocument
from environment_generator.models.blueprint import LocationBlueprint
from environment_generator.models.overrides import LocationOverrides
from environment_generator.models.pipeline import (
    GenerationPlan,
    InputFingerprints,
    LoadedInputs,
    ResolvedInputs,
)
from environment_generator.models.recipe import FallbackPolicy, GeneratorName, LocationRecipe
from environment_generator.models.report import (
    GenerationReport,
    LayoutValidationResult,
    ReportError,
    StageReport,
    SummaryValue,
)
from environment_generator.models.scene import (
    AtmosphereSettings,
    GeneratorInfo,
    Scene,
    SceneEntity,
    SceneManifest,
    TerrainData,
)
from environment_generator.pipeline.overrides import (
    apply_entity_operations,
    apply_feature_operations,
    apply_recipe_patch,
    drop_low_confidence,
)
from environment_generator.planning.planner import GenerationPlanner
from environment_generator.validation.contract import InputSource, load_document
from environment_generator.validation.layout import EnvironmentValidator
from environment_generator.validation.semantic import (
    validate_blueprint,
    validate_compatibility,
    validate_recipe,
    validate_registry,
)

InT = TypeVar("InT")
OutT = TypeVar("OutT")


@dataclass(frozen=True)
class StageOutcome(Generic[OutT]):
    output: OutT
    issues: tuple[ValidationIssue, ...] = ()
    summary: Mapping[str, SummaryValue] = field(default_factory=dict)


class Stage(ABC, Generic[InT, OutT]):
    name: ClassVar[str]

    @abstractmethod
    def run(self, data: InT) -> StageOutcome[OutT]: ...


# --------------------------------------------------------------------------- 1. load

ModelT = TypeVar("ModelT", bound=BaseModel)


def _try_load(
    model: type[ModelT], source: InputSource, label: str, issues: list[ValidationIssue]
) -> ModelT | None:
    try:
        return load_document(model, source, label)
    except ContractValidationError as exc:
        issues.extend(exc.issues)
        return None


def _fingerprints(
    blueprint: LocationBlueprint,
    recipe: LocationRecipe,
    overrides: LocationOverrides | None,
    registry: AssetRegistryDocument,
    seed_override: int | None,
) -> InputFingerprints:
    blueprint_print = fingerprint(blueprint.model_dump(mode="json"))
    recipe_print = fingerprint(recipe.model_dump(mode="json"))
    overrides_print = fingerprint(overrides.model_dump(mode="json")) if overrides else None
    registry_print = fingerprint(registry.model_dump(mode="json"))
    combined = fingerprint(
        {
            "blueprint": blueprint_print,
            "recipe": recipe_print,
            "overrides": overrides_print,
            "registry": registry_print,
            "generator_version": __version__,
            "seed_override": seed_override,
        }
    )
    return InputFingerprints(
        blueprint=blueprint_print,
        recipe=recipe_print,
        overrides=overrides_print,
        registry=registry_print,
        combined=combined,
    )


@dataclass(frozen=True)
class InputBundle:
    """Where the inputs come from. ``None`` recipe/registry use built-in defaults."""

    blueprint: InputSource
    recipe: InputSource | None = None
    overrides: InputSource | None = None
    registry: InputSource | None = None
    seed_override: int | None = None


class LoadInputsStage(Stage[InputBundle, LoadedInputs]):
    """Read every document, validate contracts, then semantic consistency."""

    name = "load_inputs"

    def run(self, data: InputBundle) -> StageOutcome[LoadedInputs]:
        # Load every document before failing so all contract problems are reported at once.
        contract_issues: list[ValidationIssue] = []
        blueprint = _try_load(LocationBlueprint, data.blueprint, "blueprint", contract_issues)
        recipe = (
            _try_load(LocationRecipe, data.recipe, "recipe", contract_issues)
            if data.recipe is not None
            else LocationRecipe.default()
        )
        overrides = (
            _try_load(LocationOverrides, data.overrides, "overrides", contract_issues)
            if data.overrides is not None
            else None
        )
        registry = (
            _try_load(AssetRegistryDocument, data.registry, "registry", contract_issues)
            if data.registry is not None
            else load_builtin_registry()
        )
        if contract_issues:
            raise ContractValidationError(
                f"{len(contract_issues)} contract violation(s) in the inputs",
                issues=contract_issues,
            )
        assert blueprint is not None and recipe is not None and registry is not None

        issues = [
            *validate_blueprint(blueprint),
            *validate_recipe(recipe),
            *validate_registry(registry),
            *validate_compatibility(blueprint, recipe, overrides),
        ]
        issues = sort_issues(issues)
        if has_errors(issues):
            raise SemanticValidationError("Inputs are semantically invalid", issues=issues)

        fingerprints = _fingerprints(blueprint, recipe, overrides, registry, data.seed_override)
        loaded = LoadedInputs(
            blueprint=blueprint,
            recipe=recipe,
            overrides=overrides,
            registry=registry,
            seed_override=data.seed_override,
            fingerprints=fingerprints,
            issues=issues,
        )
        summary: dict[str, SummaryValue] = {
            "blueprint_id": blueprint.id,
            "recipe_id": recipe.id,
            "features": blueprint.feature_count(),
            "archetypes": len(registry.archetypes),
        }
        if overrides is not None:
            summary["overrides_id"] = overrides.id
        return StageOutcome(loaded, tuple(issues), summary)


# --------------------------------------------------------------------------- 2. resolve


class ResolveInputsStage(Stage[LoadedInputs, ResolvedInputs]):
    """Apply overrides, settle the seed and drop low-confidence features."""

    name = "resolve_inputs"

    def run(self, data: LoadedInputs) -> StageOutcome[ResolvedInputs]:
        recipe = data.recipe
        blueprint = data.blueprint
        overrides = data.overrides
        applied: list[str] = []
        issues: list[ValidationIssue] = []
        if overrides is not None:
            recipe = apply_recipe_patch(recipe, overrides.recipe_patch)
            if overrides.recipe_patch:
                applied.append("recipe_patch")
            blueprint, feature_log = apply_feature_operations(
                blueprint, overrides.feature_operations, overrides.id
            )
            applied.extend(feature_log)
            if overrides.feature_operations:
                post = sort_issues(validate_blueprint(blueprint))
                if has_errors(post):
                    raise SemanticValidationError(
                        "Blueprint is invalid after applying overrides", issues=post
                    )
        # Precedence: explicit seed override > overrides.seed > recipe.seed.
        if data.seed_override is not None:
            seed = data.seed_override
        elif overrides is not None and overrides.seed is not None:
            seed = overrides.seed
        else:
            seed = recipe.seed
        if seed != recipe.seed:
            recipe = recipe.model_copy(update={"seed": seed})

        blueprint, dropped = drop_low_confidence(blueprint, recipe.filters.min_confidence)
        if dropped:
            issues.append(
                ValidationIssue.info(
                    "FEATURES_BELOW_CONFIDENCE",
                    f"Ignored {len(dropped)} feature(s) below confidence "
                    f"{recipe.filters.min_confidence}: {', '.join(dropped[:10])}",
                    "recipe.filters.min_confidence",
                )
            )
        resolved = ResolvedInputs(
            blueprint=blueprint,
            recipe=recipe,
            registry=data.registry,
            seed=seed,
            overrides_id=overrides.id if overrides else None,
            strict_overrides=overrides.strict if overrides else True,
            entity_operations=list(overrides.entity_operations) if overrides else [],
            applied_operations=applied,
            dropped_features=dropped,
            fingerprints=data.fingerprints,
        )
        summary: dict[str, SummaryValue] = {
            "seed": seed,
            "applied_operations": len(applied),
            "pending_entity_operations": len(resolved.entity_operations),
            "dropped_features": len(dropped),
        }
        return StageOutcome(resolved, tuple(issues), summary)


# --------------------------------------------------------------------------- 3. assets


class ResolveAssetsStage(Stage[ResolvedInputs, AssetPalette]):
    """Filter the registry by recipe and biome; check generators' asset needs."""

    name = "resolve_assets"

    def __init__(self, planner: GenerationPlanner) -> None:
        self._planner = planner

    def run(self, data: ResolvedInputs) -> StageOutcome[AssetPalette]:
        needs = self._planner.asset_needs(data.blueprint, data.recipe)
        palette, issues = build_palette(data.registry, data.recipe, data.blueprint.biome, needs)
        if issues and data.recipe.assets.fallback is FallbackPolicy.ERROR:
            raise AssetResolutionError(
                "Required archetypes are missing and placeholders are disabled",
                issues=[i.model_copy(update={"severity": Severity.ERROR}) for i in issues],
            )
        summary: dict[str, SummaryValue] = {
            "registry_id": palette.registry_id,
            "archetypes": len(palette.archetypes),
            "excluded_archetypes": palette.excluded_archetypes,
            "unmet_needs": len(palette.unmet_needs),
        }
        return StageOutcome(palette, tuple(issues), summary)


# --------------------------------------------------------------------------- 4. plan


@dataclass(frozen=True)
class PlanningInput:
    resolved: ResolvedInputs
    palette: AssetPalette


class PlanGenerationStage(Stage[PlanningInput, GenerationPlan]):
    name = "plan_generation"

    def __init__(self, planner: GenerationPlanner) -> None:
        self._planner = planner

    def run(self, data: PlanningInput) -> StageOutcome[GenerationPlan]:
        plan = self._planner.plan(data.resolved, data.palette)
        summary: dict[str, SummaryValue] = {
            "tasks": len(plan.tasks),
            "order": " > ".join(t.generator.value for t in plan.tasks),
            "estimated_entities": plan.estimated_entities,
        }
        return StageOutcome(plan, (), summary)


# --------------------------------------------------------------------------- 5. generate


class GenerateSceneStage(Stage[GenerationPlan, Scene]):
    """Run the planned generators and apply entity overrides."""

    name = "generate_scene"

    def __init__(self, generators: GeneratorSet) -> None:
        self._generators = generators

    def _check_plan(self, plan: GenerationPlan) -> None:
        if plan.generator_version != __version__:
            raise PlanningError(
                f"Plan was created by generator {plan.generator_version}, this is {__version__}"
            )
        for task in plan.tasks:
            expected = self._generators.get(task.generator).identifier
            if task.implementation != expected:
                raise PlanningError(
                    f"Plan expects '{task.implementation}' for {task.generator.value}, "
                    f"but '{expected}' is configured"
                )

    def run(self, data: GenerationPlan) -> StageOutcome[Scene]:
        plan = data
        self._check_plan(plan)
        recipe = plan.recipe
        resolver = PaletteAssetResolver(
            plan.palette,
            seed=derive_seed(plan.seed, "assets"),
            preferred_tags=recipe.effective_preferred_tags(),
            fallback=recipe.assets.fallback,
        )
        entities: dict[str, SceneEntity] = {}
        occupancy = SpatialIndex()
        sampler: HeightSampler = FlatGround(plan.blueprint.terrain.base_elevation_m)
        terrain: TerrainData | None = None
        atmosphere: AtmosphereSettings | None = None
        issues: list[ValidationIssue] = []
        counts: dict[str, SummaryValue] = {}
        for task in plan.tasks:
            generator = self._generators.get(task.generator)
            context = GenerationContext(
                blueprint=plan.blueprint,
                recipe=recipe,
                seed=task.seed,
                assets=resolver,
                terrain=sampler,
                occupancy=occupancy,
                entities=MappingProxyType(entities),
            )
            try:
                output = generator.generate(context)
            except EnvironmentGeneratorError:
                raise
            except (ValueError, ArithmeticError, ValidationError, KeyError) as exc:
                raise GenerationError(
                    f"Generator '{task.generator.value}' ({generator.identifier}) failed: {exc}",
                    generator=task.generator.value,
                ) from exc
            allowed = sorted(c.value for c in generator.produces)
            for entity in output.entities:
                if entity.category not in generator.produces:
                    raise GenerationError(
                        f"Generator '{task.generator.value}' emitted a {entity.category.value} "
                        f"entity ({entity.id}); allowed: {allowed}",
                        generator=task.generator.value,
                    )
                if entity.id in entities:
                    raise GenerationError(
                        f"Generator '{task.generator.value}' emitted duplicate id '{entity.id}'",
                        generator=task.generator.value,
                    )
                entities[entity.id] = entity
            if task.generator is GeneratorName.TERRAIN:
                if output.terrain is None:
                    raise GenerationError(
                        "The terrain generator returned no terrain", generator="terrain"
                    )
                terrain = output.terrain
                sampler = terrain.to_heightfield()
            if task.generator is GeneratorName.ATMOSPHERE:
                if output.atmosphere is None:
                    raise GenerationError(
                        "The atmosphere processor returned no settings", generator="atmosphere"
                    )
                atmosphere = output.atmosphere
            issues.extend(output.issues)
            counts[f"entities.{task.generator.value}"] = len(output.entities)

        issues.extend(
            apply_entity_operations(
                entities,
                plan.entity_operations,
                overrides_id=plan.overrides_id,
                strict=plan.strict_overrides,
                assets=resolver,
            )
        )
        scene = Scene(
            blueprint_id=plan.blueprint.id,
            extent=plan.blueprint.extent,
            terrain=terrain,
            atmosphere=atmosphere,
            entities=sorted(entities.values(), key=lambda e: e.id),
        )
        summary: dict[str, SummaryValue] = {"entities": len(scene.entities), **counts}
        return StageOutcome(scene, tuple(sort_issues(issues)), summary)


# --------------------------------------------------------------------------- 6. validate


@dataclass(frozen=True)
class LayoutInput:
    scene: Scene
    plan: GenerationPlan


class ValidateLayoutStage(Stage[LayoutInput, LayoutValidationResult]):
    name = "validate_layout"

    def __init__(self, validator: EnvironmentValidator) -> None:
        self._validator = validator

    def run(self, data: LayoutInput) -> StageOutcome[LayoutValidationResult]:
        settings = data.plan.recipe.validation
        result = self._validator.validate(
            data.scene,
            settings=settings,
            known_archetypes=[a.id for a in data.plan.palette.archetypes],
        )
        if result.has_errors and settings.fail_on_error:
            raise LayoutValidationError("Generated layout failed validation", issues=result.issues)
        counts = count_by_severity(result.issues)
        summary: dict[str, SummaryValue] = {
            "rules": len(result.rules),
            "checked_entities": result.checked_entities,
            "errors": counts["error"],
            "warnings": counts["warning"],
        }
        return StageOutcome(result, tuple(result.issues), summary)


# --------------------------------------------------------------------------- 7. export


@dataclass(frozen=True)
class ExportInput:
    scene: Scene
    plan: GenerationPlan
    destination: Path | None = None


class ExportManifestStage(Stage[ExportInput, ExportResult]):
    name = "export_manifest"

    def __init__(self, exporter: SceneExporter) -> None:
        self._exporter = exporter

    def run(self, data: ExportInput) -> StageOutcome[ExportResult]:
        result = self._exporter.export(data.scene, data.plan, data.destination)
        summary: dict[str, SummaryValue] = {
            "content_hash": result.manifest.content_hash,
            "entities": result.manifest.statistics.entity_count,
        }
        if result.path is not None:
            summary["path"] = result.path.name
        return StageOutcome(result, (), summary)


# --------------------------------------------------------------------------- 8. report


@dataclass(frozen=True)
class ReportInput:
    stages: tuple[StageReport, ...]
    dry_run: bool
    error: ReportError | None = None
    loaded: LoadedInputs | None = None
    resolved: ResolvedInputs | None = None
    manifest: SceneManifest | None = None
    outputs: Mapping[str, str] = field(default_factory=dict)


class BuildReportStage(Stage[ReportInput, GenerationReport]):
    name = "build_report"

    def run(self, data: ReportInput) -> StageOutcome[GenerationReport]:
        all_issues = [issue for stage in data.stages for issue in stage.issues]
        statistics: dict[str, int] = {}
        if data.manifest is not None:
            stats = data.manifest.statistics
            statistics["entities"] = stats.entity_count
            statistics["placeholders"] = stats.placeholder_count
            statistics.update({f"category.{k}": v for k, v in stats.by_category.items()})
        loaded = data.loaded
        resolved = data.resolved
        report = GenerationReport(
            generator=GeneratorInfo(name=GENERATOR_NAME, version=__version__),
            success=data.error is None,
            dry_run=data.dry_run,
            error=data.error,
            blueprint_id=loaded.blueprint.id if loaded else None,
            recipe_id=loaded.recipe.id if loaded else None,
            overrides_id=loaded.overrides.id if loaded and loaded.overrides else None,
            seed=resolved.seed if resolved else None,
            input_fingerprint=loaded.fingerprints.combined if loaded else None,
            manifest_content_hash=data.manifest.content_hash if data.manifest else None,
            stages=list(data.stages),
            statistics=statistics,
            issue_counts=count_by_severity(all_issues),
            outputs=dict(sorted(data.outputs.items())),
        )
        return StageOutcome(report, (), {})
