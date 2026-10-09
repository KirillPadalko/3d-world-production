"""Validation issues shared by every layer of the generator."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Severity(StrEnum):
    """How serious a :class:`ValidationIssue` is."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


class ValidationIssue(BaseModel):
    """A single finding produced by validation, resolution or generation.

    ``code`` is a stable, machine-readable identifier (``UPPER_SNAKE_CASE``);
    ``location`` points at the offending input (``buildings/b-1``,
    ``recipe.terrain.cell_size_m``) or entity.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: Severity
    code: str
    message: str
    location: str | None = None
    entity_ids: tuple[str, ...] = ()

    @classmethod
    def error(
        cls, code: str, message: str, location: str | None = None, entity_ids: Sequence[str] = ()
    ) -> ValidationIssue:
        return cls(
            severity=Severity.ERROR,
            code=code,
            message=message,
            location=location,
            entity_ids=tuple(entity_ids),
        )

    @classmethod
    def warning(
        cls, code: str, message: str, location: str | None = None, entity_ids: Sequence[str] = ()
    ) -> ValidationIssue:
        return cls(
            severity=Severity.WARNING,
            code=code,
            message=message,
            location=location,
            entity_ids=tuple(entity_ids),
        )

    @classmethod
    def info(
        cls, code: str, message: str, location: str | None = None, entity_ids: Sequence[str] = ()
    ) -> ValidationIssue:
        return cls(
            severity=Severity.INFO,
            code=code,
            message=message,
            location=location,
            entity_ids=tuple(entity_ids),
        )

    def format(self) -> str:
        where = f" [{self.location}]" if self.location else ""
        return f"{self.severity.value.upper()} {self.code}{where}: {self.message}"


def has_errors(issues: Iterable[ValidationIssue]) -> bool:
    return any(issue.severity is Severity.ERROR for issue in issues)


def errors_only(issues: Iterable[ValidationIssue]) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.severity is Severity.ERROR]


def sort_issues(issues: Iterable[ValidationIssue]) -> list[ValidationIssue]:
    """Order issues deterministically: severity, then code, then location."""
    return sorted(
        issues,
        key=lambda i: (_SEVERITY_ORDER[i.severity], i.code, i.location or "", i.message),
    )


def count_by_severity(issues: Iterable[ValidationIssue]) -> dict[str, int]:
    counts = {severity.value: 0 for severity in Severity}
    for issue in issues:
        counts[issue.severity.value] += 1
    return counts
