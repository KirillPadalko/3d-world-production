"""Validation issues shared by every layer of the generator."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Severity(StrEnum):
    """How serious a :class:`ValidationIssue` is."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


class ValidationIssue(BaseModel):
    """A single diagnostic produced by validation, resolution or generation.

    * ``code`` - stable, machine-readable identifier (``UPPER_SNAKE_CASE``);
    * ``category`` - validation phase that produced it (``version``,
      ``schema``, ``semantic``, ``reference``, ``external``, ...);
    * ``location`` - human-readable pointer (``buildings/b-1``, a document
      name, a pipeline stage);
    * ``path`` - field path inside the document (``buildings[2].transform.yawDeg``);
    * ``entity_ids`` - affected entity IDs, most relevant first;
    * ``suggestion`` - how to fix it, when known.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        alias_generator=to_camel,
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )

    severity: Severity
    code: str
    message: str
    category: str | None = None
    location: str | None = None
    path: str | None = None
    entity_ids: tuple[str, ...] = ()
    suggestion: str | None = None

    @property
    def entity_id(self) -> str | None:
        return self.entity_ids[0] if self.entity_ids else None

    @classmethod
    def error(
        cls,
        code: str,
        message: str,
        location: str | None = None,
        entity_ids: Sequence[str] = (),
        suggestion: str | None = None,
    ) -> ValidationIssue:
        return cls(
            severity=Severity.ERROR,
            code=code,
            message=message,
            location=location,
            entity_ids=tuple(entity_ids),
            suggestion=suggestion,
        )

    @classmethod
    def warning(
        cls,
        code: str,
        message: str,
        location: str | None = None,
        entity_ids: Sequence[str] = (),
        suggestion: str | None = None,
    ) -> ValidationIssue:
        return cls(
            severity=Severity.WARNING,
            code=code,
            message=message,
            location=location,
            entity_ids=tuple(entity_ids),
            suggestion=suggestion,
        )

    @classmethod
    def info(
        cls,
        code: str,
        message: str,
        location: str | None = None,
        entity_ids: Sequence[str] = (),
        suggestion: str | None = None,
    ) -> ValidationIssue:
        return cls(
            severity=Severity.INFO,
            code=code,
            message=message,
            location=location,
            entity_ids=tuple(entity_ids),
            suggestion=suggestion,
        )

    def format(self) -> str:
        where = self.path or self.location
        where_text = f" [{where}]" if where else ""
        hint = f" (hint: {self.suggestion})" if self.suggestion else ""
        return f"{self.severity.value.upper()} {self.code}{where_text}: {self.message}{hint}"


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
