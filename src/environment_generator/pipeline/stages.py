"""The eight pipeline stages.

Every stage is a small class with a typed input, a typed output wrapped in a
:class:`StageOutcome` (output + non-fatal issues + summary), and raises a
subclass of :class:`EnvironmentGeneratorError` on failure. Stages can be run
on their own; :class:`~environment_generator.pipeline.runner.Pipeline` wires
them together.
"""

from __future__ import annotations

import hashlib
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
from environment_generator.blueprint.diagnostics import Category, diagnostic
from environment_generator.blueprint.files import iter_file_references, resolve_package_path
from environment_generator.blueprint.io import package_root_of, validate_source
from environment_generator.blueprint.overrides import apply_entity_operations
from environment_generator.blueprint.site_adapter import blueprint_to_site
from environment_generator.blueprint.versioning import VersionStatus
from environment_generator.core.errors import (
    AssetResolutionError,
    ContractValidationError,
    EnvironmentGeneratorError,
    ExternalDataError,
    GenerationError,
    LayoutValidationError,
    MigrationError,
    PlanningError,
    SemanticValidationError,
    UnsupportedVersionError,
)
from environment_generator.core.hashing import fingerprint
from environment_generator.core.issues import (
    Severity,
    ValidationIssue,
    count_by_severity,
    has_errors,
    sort_issues,
)
from environment_generator.core.spatial import SpatialIndex
from environment_generator.core.terrain import FlatGround, HeightSampler
from environment_generator.exporters.base import ExportResult, SceneExporter
from environment_generator.generators.base import GenerationContext, GeneratorSet
from environment_generator.models.assets import AssetPalette, AssetRegistryDocument
from environment_generator.models.blueprint import LocationBlueprint
from environment_generator.models.overrides import ConflictPolicy, LocationOverrides
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
    Annotations,
    AtmosphereSettings,
    GenerationControls,
    GeneratorInfo,
    Scene,
    SceneEntity,
    SceneManifest,
    TerrainData,
)
from environment_generator.pipeline.overrides import apply_placement_overrides
from environment_generator.planning.planner import GenerationPlanner
from environment_generator.validation.contract import InputSource, load_document
from environment_generator.validation.layout import EnvironmentValidator
from environment_generator.validation.semantic import (
    validate_compatibility,
    validate_recipe,
    validate_registry,
)

InT = TypeVar("InT")
OutT = TypeVar("OutT")

#: Generation controls that the built-in generators record but do not vary.
DEFAULT_STRUCTURAL_SIMILARITY = 1.0
DEFAULT_VISUAL_VARIATION = 0.5


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


def _external_fingerprint(blueprint: LocationBlueprint, root: Path | None) -> str | None:
    """Hash over the generation-relevant external files (heightmap, masks)."""
    if root is None:
        return None
    digest = hashlib.sha256()
    found = False
    for use in iter_file_references(blueprint):
        if not use.required:
            continue
        try:
            path = resolve_package_path(root, use.reference.path)
            data = path.read_bytes()
        except (OSError, ExternalDataError):
            continue
        found = True
        digest.update(use.reference.path.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(data).digest())
    return "sha256:" + digest.hexdigest() if found else None


def _fingerprints(
    blueprint: LocationBlueprint,
    root: Path | None,
    recipe: LocationRecipe,
    overrides: LocationOverrides | None,
    registry: AssetRegistryDocument,
    seed_override: int | None,
) -> InputFingerprints:
    blueprint_print = fingerprint(blueprint.model_dump(mode="json"))
    recipe_print = fingerprint(recipe.model_dump(mode="json"))
    overrides_print = fingerprint(overrides.model_dump(mode="json")) if overrides else None
    registry_print = fingerprint(registry.model_dump(mode="json"))
    external_print = _external_fingerprint(blueprint, root)
    combined = fingerprint(
        {
            "blueprint": blueprint_print,
            "recipe": recipe_print,
            "overrides": overrides_print,
            "registry": registry_print,
            "externalFiles": external_print,
            "generatorVersion": __version__,
            "seedOverride": seed_override,
        }
    )
    return InputFingerprints(
        blueprint=blueprint_print,
        recipe=recipe_print,
        overrides=overrides_print,
        registry=registry_print,
        external_files=external_print,
        combined=combined,
    )


@dataclass(frozen=True)
class InputBundle:
    """Where the inputs come from. ``None`` recipe/registry use built-in defaults.

    ``package_root`` is the folder blueprint file references are resolved
    against; it defaults to the folder containing the blueprint file.
    """

    blueprint: InputSource
    recipe: InputSource | None = None
    overrides: InputSource | None = None
    registry: InputSource | None = None
    seed_override: int | None = None
    package_root: Path | None = None


class LoadInputsStage(Stage[InputBundle, LoadedInputs]):
    """Read every document, validate contracts, then semantic consistency."""

    name = "load_inputs"

    def run(self, data: InputBundle) -> StageOutcome[LoadedInputs]:
        root = data.package_root or package_root_of(data.blueprint)
        checked = validate_source(data.blueprint, package_root=root)
        if checked.status is VersionStatus.MIGRATABLE:
            raise MigrationError("The blueprint needs migration before use", issues=checked.issues)
        version_issues = [i for i in checked.issues if i.category == Category.VERSION.value]
        if checked.blueprint is None and version_issues:
            raise UnsupportedVersionError(
                "The blueprint has an unsupported schema version", issues=version_issues
            )

        # Load every document before failing so all contract problems are reported at once.
        contract_issues: list[ValidationIssue] = []
        if checked.blueprint is None:
            contract_issues.extend(checked.issues)
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
        blueprint = checked.blueprint
        assert blueprint is not None and recipe is not None and registry is not None

        issues = sort_issues(
            [
                *checked.issues,
                *validate_recipe(recipe),
                *validate_registry(registry),
                *validate_compatibility(blueprint, recipe, overrides),
            ]
        )
        if has_errors(issues):
            raise SemanticValidationError("Inputs are semantically invalid", issues=issues)

        loaded = LoadedInputs(
            blueprint=blueprint,
            package_root=str(root) if root is not None else None,
            recipe=recipe,
            overrides=overrides,
            registry=registry,
            seed_override=data.seed_override,
            fingerprints=_fingerprints(
                blueprint, root, recipe, overrides, registry, data.seed_override
            ),
            issues=issues,
        )
        summary: dict[str, SummaryValue] = {
            "location_id": blueprint.location_id,
            "schema_version": blueprint.schema_version,
            "recipe_id": recipe.id,
            "archetypes": len(registry.archetypes),
        }
        if overrides is not None:
            summary["overrides_id"] = overrides.id
        return StageOutcome(loaded, tuple(issues), summary)


# --------------------------------------------------------------------------- 2. resolve


def resolve_controls(blueprint: LocationBlueprint, recipe: LocationRecipe) -> GenerationControls:
    """Recipe values win; ``null`` recipe values fall back to the blueprint."""
    generation = blueprint.generation
    return GenerationControls(
        structural_similarity=(
            recipe.structural_similarity
            if recipe.structural_similarity is not None
            else generation.structural_similarity
        ),
        visual_variation=(
            recipe.visual_variation
            if recipe.visual_variation is not None
            else generation.visual_variation
        ),
        detail_density=recipe.detail_density,
        abandonment=(
            recipe.abandonment
            if recipe.abandonment is not None
            else blueprint.atmosphere.abandonment
        ),
    )


class ResolveInputsStage(Stage[LoadedInputs, ResolvedInputs]):
    """Apply overrides, settle seeds and controls, and build the site view."""

    name = "resolve_inputs"

    def run(self, data: LoadedInputs) -> StageOutcome[ResolvedInputs]:
        root = Path(data.package_root) if data.package_root else None
        blueprint = data.blueprint
        recipe = data.recipe
        overrides = data.overrides
        issues: list[ValidationIssue] = []
        applied: list[str] = []
        trace: dict[str, list[str]] = {}
        if overrides is not None:
            outcome = apply_entity_operations(blueprint, overrides, package_root=root)
            blueprint = outcome.blueprint
            applied = list(outcome.applied)
            trace = {k: list(v) for k, v in outcome.trace.items()}
            issues.extend(outcome.issues)

        # Master seed: explicit override > recipe.seed > blueprint generation.masterSeed.
        if data.seed_override is not None:
            seed = data.seed_override
        elif recipe.seed is not None:
            seed = recipe.seed
        else:
            seed = blueprint.generation.master_seed
        subsystem_seeds = {
            **{k.value: v for k, v in blueprint.generation.subsystem_seeds.items()},
            **{k.value: v for k, v in recipe.subsystem_seeds.items()},
        }
        controls = resolve_controls(blueprint, recipe)
        if (
            controls.structural_similarity != DEFAULT_STRUCTURAL_SIMILARITY
            or controls.visual_variation != DEFAULT_VISUAL_VARIATION
        ):
            issues.append(
                diagnostic(
                    "info",
                    "GENERATION_CONTROL_RECORDED",
                    "structuralSimilarity and visualVariation are recorded in the plan and "
                    "manifest; the built-in generators do not vary their output with them yet.",
                    category=Category.INTERPRETATION,
                    path="generation",
                )
            )

        conversion = blueprint_to_site(
            blueprint, package_root=root, min_confidence=recipe.filters.min_confidence
        )
        issues.extend(conversion.notes)
        if conversion.dropped:
            issues.append(
                ValidationIssue.info(
                    "FEATURES_BELOW_CONFIDENCE",
                    f"Ignored {len(conversion.dropped)} feature(s) below confidence "
                    f"{recipe.filters.min_confidence}: {', '.join(conversion.dropped[:10])}",
                    "recipe.filters.minConfidence",
                )
            )
        resolved = ResolvedInputs(
            blueprint=blueprint,
            site=conversion.site,
            recipe=recipe,
            registry=data.registry,
            seed=seed,
            subsystem_seeds=subsystem_seeds,
            controls=controls,
            overrides_id=overrides.id if overrides else None,
            conflict_policy=overrides.conflict_policy if overrides else ConflictPolicy.FAIL,
            placement_overrides=list(overrides.placement_overrides) if overrides else [],
            applied_operations=applied,
            override_trace=trace,
            dropped_features=list(conversion.dropped),
            annotations=Annotations(landmarks=blueprint.landmarks, gameplay=blueprint.gameplay),
            fingerprints=data.fingerprints,
        )
        summary: dict[str, SummaryValue] = {
            "seed": seed,
            "applied_operations": len(applied),
            "placement_overrides": len(resolved.placement_overrides),
            "dropped_features": len(conversion.dropped),
            "site_features": conversion.site.feature_count(),
        }
        return StageOutcome(resolved, tuple(sort_issues(issues)), summary)


# --------------------------------------------------------------------------- 3. assets


class ResolveAssetsStage(Stage[ResolvedInputs, AssetPalette]):
    """Filter the registry by recipe and biome; check generators' asset needs."""

    name = "resolve_assets"

    def __init__(self, planner: GenerationPlanner) -> None:
        self._planner = planner

    def run(self, data: ResolvedInputs) -> StageOutcome[AssetPalette]:
        needs = self._planner.asset_needs(data.site, data.recipe)
        palette, issues = build_palette(data.registry, data.recipe, data.site.biome, needs)
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


def _trace_entity_operations(
    entities: dict[str, SceneEntity], trace: Mapping[str, list[str]]
) -> None:
    """Record on generated entities which entity operations shaped their source."""
    if not trace:
        return
    for entity_id, entity in list(entities.items()):
        source = entity.provenance.source_feature
        if source is None:
            continue
        refs = trace.get(source.rsplit("/", 1)[-1])
        if refs:
            provenance = entity.provenance.model_copy(
                update={"overrides": [*entity.provenance.overrides, *refs]}
            )
            entities[entity_id] = entity.model_copy(update={"provenance": provenance})


class GenerateSceneStage(Stage[GenerationPlan, Scene]):
    """Run the planned generators and apply placement overrides."""

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
            seed=plan.asset_seed,
            preferred_tags=recipe.effective_preferred_tags(),
            fallback=recipe.assets.fallback,
        )
        entities: dict[str, SceneEntity] = {}
        occupancy = SpatialIndex()
        sampler: HeightSampler = FlatGround(plan.site.terrain.base_elevation_m)
        terrain: TerrainData | None = None
        atmosphere: AtmosphereSettings | None = None
        issues: list[ValidationIssue] = []
        counts: dict[str, SummaryValue] = {}
        for task in plan.tasks:
            generator = self._generators.get(task.generator)
            context = GenerationContext(
                site=plan.site,
                recipe=recipe,
                controls=plan.controls,
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

        _trace_entity_operations(entities, plan.override_trace)
        issues.extend(
            apply_placement_overrides(
                entities,
                plan.placement_overrides,
                overrides_id=plan.overrides_id,
                policy=plan.conflict_policy,
            )
        )
        scene = Scene(
            location_id=plan.location_id,
            extent=plan.site.extent,
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
            location_id=loaded.blueprint.location_id if loaded else None,
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
