"""Pipeline orchestration: runs the stages, records reports, writes outputs."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from environment_generator import GENERATOR_NAME, __version__
from environment_generator.core.errors import EnvironmentGeneratorError, ExportError
from environment_generator.core.hashing import pretty_json
from environment_generator.core.issues import ValidationIssue
from environment_generator.exporters.base import SceneExporter
from environment_generator.exporters.json_manifest import JsonManifestExporter
from environment_generator.generators import default_generators
from environment_generator.generators.base import GeneratorSet
from environment_generator.models.assets import AssetPalette
from environment_generator.models.pipeline import GenerationPlan, LoadedInputs, ResolvedInputs
from environment_generator.models.report import (
    GenerationReport,
    LayoutValidationResult,
    ReportError,
    StageReport,
    StageStatus,
)
from environment_generator.models.scene import GeneratorInfo, Scene, SceneManifest
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
    StageOutcome,
    ValidateLayoutStage,
)
from environment_generator.planning.planner import GenerationPlanner
from environment_generator.reporting.svg_preview import render_svg
from environment_generator.validation.layout import EnvironmentValidator, RuleBasedLayoutValidator

logger = logging.getLogger(__name__)

T = TypeVar("T")

STAGE_ORDER = (
    LoadInputsStage.name,
    ResolveInputsStage.name,
    ResolveAssetsStage.name,
    PlanGenerationStage.name,
    GenerateSceneStage.name,
    ValidateLayoutStage.name,
    ExportManifestStage.name,
    BuildReportStage.name,
)

PLAN_FILENAME = "generation-plan.json"
REPORT_FILENAME = "generation-report.json"
PREVIEW_FILENAME = "preview.svg"


@dataclass(frozen=True)
class PipelineOptions:
    output_dir: Path | None = None
    dry_run: bool = False
    write_plan: bool = False
    write_preview: bool = False
    include_timings: bool = True


@dataclass
class PipelineResult:
    """Everything a run produced. ``error`` is set when a stage failed."""

    report: GenerationReport
    loaded: LoadedInputs | None = None
    resolved: ResolvedInputs | None = None
    palette: AssetPalette | None = None
    plan: GenerationPlan | None = None
    scene: Scene | None = None
    layout: LayoutValidationResult | None = None
    manifest: SceneManifest | None = None
    error: EnvironmentGeneratorError | None = None
    written: dict[str, Path] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.error is None


class _StageRecorder:
    def __init__(self, clock: Callable[[], float], include_timings: bool) -> None:
        self._clock = clock
        self._include_timings = include_timings
        self.reports: list[StageReport] = []
        self.failed_stage: str | None = None

    def run(self, name: str, step: Callable[[], StageOutcome[T]]) -> T:
        start = self._clock()
        logger.info("stage %s: started", name)
        try:
            outcome = step()
        except EnvironmentGeneratorError as exc:
            self.failed_stage = name
            issues = [*exc.issues, ValidationIssue.error(exc.code, exc.message, name)]
            self.reports.append(
                StageReport(
                    name=name,
                    status=StageStatus.FAILED,
                    duration_ms=self._elapsed(start),
                    issues=issues,
                )
            )
            logger.error("stage %s: failed: %s", name, exc.message)
            raise
        self.reports.append(
            StageReport(
                name=name,
                status=StageStatus.SUCCEEDED,
                duration_ms=self._elapsed(start),
                summary=dict(outcome.summary),
                issues=list(outcome.issues),
            )
        )
        logger.info("stage %s: done (%d issue(s))", name, len(outcome.issues))
        return outcome.output

    def skip(self, name: str, reason: str) -> None:
        self.reports.append(
            StageReport(name=name, status=StageStatus.SKIPPED, summary={"reason": reason})
        )

    def _elapsed(self, start: float) -> float | None:
        if not self._include_timings:
            return None
        return round((self._clock() - start) * 1000.0, 3)


class Pipeline:
    """Runs the generation stages in order.

    Components are injectable: pass a custom :class:`GeneratorSet`,
    :class:`EnvironmentValidator` or :class:`SceneExporter` to replace parts of
    the pipeline without touching the others.
    """

    def __init__(
        self,
        generators: GeneratorSet | None = None,
        validator: EnvironmentValidator | None = None,
        exporter: SceneExporter | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.generators = generators or default_generators()
        planner = GenerationPlanner(self.generators)
        self.load_stage = LoadInputsStage()
        self.resolve_stage = ResolveInputsStage()
        self.assets_stage = ResolveAssetsStage(planner)
        self.plan_stage = PlanGenerationStage(planner)
        self.generate_stage = GenerateSceneStage(self.generators)
        self.validate_stage = ValidateLayoutStage(validator or RuleBasedLayoutValidator())
        self.export_stage = ExportManifestStage(exporter or JsonManifestExporter())
        self.report_stage = BuildReportStage()
        self._clock = clock

    # ------------------------------------------------------------------ public API

    def run(self, inputs: InputBundle, options: PipelineOptions | None = None) -> PipelineResult:
        """Run all stages (or stages 1-4 when ``options.dry_run``)."""
        options = options or PipelineOptions()
        recorder = _StageRecorder(self._clock, options.include_timings)
        result = PipelineResult(report=_empty_report(options.dry_run))
        try:
            result.loaded = recorder.run(LoadInputsStage.name, lambda: self.load_stage.run(inputs))
            loaded = result.loaded
            result.resolved = recorder.run(
                ResolveInputsStage.name, lambda: self.resolve_stage.run(loaded)
            )
            resolved = result.resolved
            result.palette = recorder.run(
                ResolveAssetsStage.name, lambda: self.assets_stage.run(resolved)
            )
            palette = result.palette
            result.plan = recorder.run(
                PlanGenerationStage.name,
                lambda: self.plan_stage.run(PlanningInput(resolved, palette)),
            )
            if options.dry_run:
                for name in STAGE_ORDER[4:7]:
                    recorder.skip(name, "dry run")
                if options.output_dir is not None:
                    result.written["plan"] = self._write(
                        options.output_dir / PLAN_FILENAME,
                        pretty_json(result.plan.model_dump(mode="json"), decimals=None),
                    )
            else:
                self._generate(result, recorder, options)
        except EnvironmentGeneratorError as exc:
            result.error = exc
            self._skip_remaining(recorder)
        return self._finish(result, recorder, options)

    def run_plan(
        self, plan: GenerationPlan, options: PipelineOptions | None = None
    ) -> PipelineResult:
        """Run stages 5-8 from a saved plan (stages 1-4 are reported as skipped)."""
        options = options or PipelineOptions()
        recorder = _StageRecorder(self._clock, options.include_timings)
        result = PipelineResult(report=_empty_report(False), plan=plan)
        for name in STAGE_ORDER[:4]:
            recorder.skip(name, "loaded from plan")
        try:
            self._generate(result, recorder, options)
        except EnvironmentGeneratorError as exc:
            result.error = exc
            self._skip_remaining(recorder)
        return self._finish(result, recorder, options)

    # ------------------------------------------------------------------ internals

    def _generate(
        self, result: PipelineResult, recorder: _StageRecorder, options: PipelineOptions
    ) -> None:
        plan = result.plan
        assert plan is not None
        result.scene = recorder.run(GenerateSceneStage.name, lambda: self.generate_stage.run(plan))
        scene = result.scene
        result.layout = recorder.run(
            ValidateLayoutStage.name, lambda: self.validate_stage.run(LayoutInput(scene, plan))
        )
        export = recorder.run(
            ExportManifestStage.name,
            lambda: self.export_stage.run(ExportInput(scene, plan, options.output_dir)),
        )
        result.manifest = export.manifest
        if export.path is not None:
            result.written["manifest"] = export.path
        if options.output_dir is not None:
            if options.write_plan:
                result.written["plan"] = self._write(
                    options.output_dir / PLAN_FILENAME,
                    pretty_json(plan.model_dump(mode="json"), decimals=None),
                )
            if options.write_preview:
                result.written["preview"] = self._write(
                    options.output_dir / PREVIEW_FILENAME, render_svg(export.manifest)
                )

    def _skip_remaining(self, recorder: _StageRecorder) -> None:
        done = {report.name for report in recorder.reports}
        for name in STAGE_ORDER[:-1]:
            if name not in done:
                recorder.skip(name, f"previous stage '{recorder.failed_stage}' failed")

    def _finish(
        self, result: PipelineResult, recorder: _StageRecorder, options: PipelineOptions
    ) -> PipelineResult:
        outputs = {key: path.name for key, path in result.written.items()}
        if options.output_dir is not None:
            outputs["report"] = REPORT_FILENAME
        error = None
        if result.error is not None:
            error = ReportError(
                code=result.error.code, message=result.error.message, stage=recorder.failed_stage
            )
        order = {name: i for i, name in enumerate(STAGE_ORDER)}
        stages = tuple(sorted(recorder.reports, key=lambda r: order[r.name]))
        report_input = ReportInput(
            stages=stages,
            dry_run=options.dry_run,
            error=error,
            loaded=result.loaded,
            resolved=result.resolved,
            manifest=result.manifest,
            outputs=outputs,
        )
        report = self.report_stage.run(report_input).output
        report = report.model_copy(
            update={
                "stages": [
                    *report.stages,
                    StageReport(name=BuildReportStage.name, status=StageStatus.SUCCEEDED),
                ]
            }
        )
        result.report = report
        if options.output_dir is not None:
            try:
                result.written["report"] = self._write(
                    options.output_dir / REPORT_FILENAME,
                    pretty_json(report.model_dump(mode="json")),
                )
            except ExportError as exc:
                if result.error is None:
                    result.error = exc
        return result

    @staticmethod
    def _write(path: Path, text: str) -> Path:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            raise ExportError(f"Cannot write '{path}': {exc}") from exc
        return path


def _empty_report(dry_run: bool) -> GenerationReport:
    return GenerationReport(
        generator=GeneratorInfo(name=GENERATOR_NAME, version=__version__),
        success=False,
        dry_run=dry_run,
        stages=[],
    )
