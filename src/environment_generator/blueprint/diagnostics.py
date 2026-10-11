"""Structured diagnostics for blueprint validation."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import StrEnum

from pydantic import Field

from environment_generator.core.issues import (
    Severity,
    ValidationIssue,
    count_by_severity,
    sort_issues,
)
from environment_generator.models.base import ContractModel


class Category(StrEnum):
    """Validation phase that produced a diagnostic."""

    VERSION = "version"
    SCHEMA = "schema"
    SEMANTIC = "semantic"
    REFERENCE = "reference"
    EXTERNAL = "external"
    INTERPRETATION = "interpretation"
    OVERRIDE = "override"


def diagnostic(
    severity: Severity | str,
    code: str,
    message: str,
    *,
    category: Category,
    path: str | None = None,
    entity_ids: Sequence[str] = (),
    suggestion: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        severity=Severity(severity),
        code=code,
        message=message,
        category=category.value,
        path=path,
        entity_ids=tuple(entity_ids),
        suggestion=suggestion,
    )


class ValidationReport(ContractModel):
    """Machine-readable result of ``envgen blueprint validate``."""

    document: str | None = None
    schema_version: str | None = None
    valid: bool
    counts: dict[str, int] = Field(default_factory=dict)
    diagnostics: list[ValidationIssue] = Field(default_factory=list)

    @classmethod
    def build(
        cls,
        issues: Iterable[ValidationIssue],
        *,
        document: str | None = None,
        schema_version: str | None = None,
    ) -> ValidationReport:
        ordered = sort_issues(issues)
        counts = count_by_severity(ordered)
        return cls(
            document=document,
            schema_version=schema_version,
            valid=counts["error"] == 0,
            counts=counts,
            diagnostics=ordered,
        )

    def by_category(self) -> dict[str, list[ValidationIssue]]:
        grouped: dict[str, list[ValidationIssue]] = {}
        for issue in self.diagnostics:
            grouped.setdefault(issue.category or "other", []).append(issue)
        return grouped
