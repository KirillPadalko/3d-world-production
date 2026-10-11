"""Generation and validation reports."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from environment_generator.core.issues import Severity, ValidationIssue
from environment_generator.models.base import ContractModel
from environment_generator.models.scene import GeneratorInfo

SummaryValue = str | int | float | bool


class StageStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class StageReport(ContractModel):
    name: str
    status: StageStatus
    duration_ms: float | None = None
    summary: dict[str, SummaryValue] = Field(default_factory=dict)
    issues: list[ValidationIssue] = Field(default_factory=list)


class LayoutValidationResult(ContractModel):
    """Output of the layout validation stage."""

    issues: list[ValidationIssue]
    rules: list[str]
    checked_entities: int

    @property
    def has_errors(self) -> bool:
        return any(issue.severity is Severity.ERROR for issue in self.issues)


class ReportError(ContractModel):
    code: str
    message: str
    stage: str | None = None


class GenerationReport(ContractModel):
    """Summary of a pipeline run, written next to the manifest."""

    report_version: Literal["1.0"] = "1.0"
    generator: GeneratorInfo
    success: bool
    dry_run: bool
    error: ReportError | None = None
    location_id: str | None = None
    recipe_id: str | None = None
    overrides_id: str | None = None
    seed: int | None = None
    input_fingerprint: str | None = None
    manifest_content_hash: str | None = None
    stages: list[StageReport]
    statistics: dict[str, int] = Field(default_factory=dict)
    issue_counts: dict[str, int] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)
