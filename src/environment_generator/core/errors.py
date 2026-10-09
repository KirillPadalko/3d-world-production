"""Structured exception hierarchy.

Every error raised deliberately by the generator derives from
:class:`EnvironmentGeneratorError`. Each class carries a stable ``code`` and the
process ``exit_code`` the CLI uses, so callers can react without parsing
messages.
"""

from __future__ import annotations

from collections.abc import Sequence

from environment_generator.core.issues import ValidationIssue

_MAX_ISSUES_IN_MESSAGE = 15


class EnvironmentGeneratorError(Exception):
    """Base class for all expected generator failures."""

    code = "ENVGEN_ERROR"
    exit_code = 1

    def __init__(self, message: str, *, issues: Sequence[ValidationIssue] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.issues: tuple[ValidationIssue, ...] = tuple(issues)

    def __str__(self) -> str:
        if not self.issues:
            return self.message
        lines = [self.message]
        lines.extend(f"  - {issue.format()}" for issue in self.issues[:_MAX_ISSUES_IN_MESSAGE])
        hidden = len(self.issues) - _MAX_ISSUES_IN_MESSAGE
        if hidden > 0:
            lines.append(f"  ... and {hidden} more")
        return "\n".join(lines)


class InputError(EnvironmentGeneratorError):
    """Inputs could not be loaded or are invalid."""

    code = "INPUT_ERROR"
    exit_code = 3


class InputLoadError(InputError):
    """A document could not be read or parsed as JSON."""

    code = "INPUT_LOAD_ERROR"


class ContractValidationError(InputError):
    """A document violates its public contract (JSON Schema / model constraints)."""

    code = "CONTRACT_VALIDATION_ERROR"


class SemanticValidationError(InputError):
    """A structurally valid document is semantically inconsistent."""

    code = "SEMANTIC_VALIDATION_ERROR"


class OverrideError(InputError):
    """Overrides could not be applied."""

    code = "OVERRIDE_ERROR"


class AssetResolutionError(EnvironmentGeneratorError):
    """No suitable asset archetype exists and the recipe forbids placeholders."""

    code = "ASSET_RESOLUTION_ERROR"
    exit_code = 4


class PlanningError(EnvironmentGeneratorError):
    """A generation plan could not be produced or does not match the generators."""

    code = "PLANNING_ERROR"
    exit_code = 4


class GenerationError(EnvironmentGeneratorError):
    """A generator failed or violated its output contract."""

    code = "GENERATION_ERROR"
    exit_code = 4

    def __init__(
        self,
        message: str,
        *,
        generator: str | None = None,
        issues: Sequence[ValidationIssue] = (),
    ) -> None:
        super().__init__(message, issues=issues)
        self.generator = generator


class LayoutValidationError(EnvironmentGeneratorError):
    """The generated layout failed validation."""

    code = "LAYOUT_VALIDATION_ERROR"
    exit_code = 5


class ExportError(EnvironmentGeneratorError):
    """The scene manifest could not be exported."""

    code = "EXPORT_ERROR"
    exit_code = 6


class AdapterUnavailableError(EnvironmentGeneratorError):
    """An external integration was requested but only a stub exists."""

    code = "ADAPTER_UNAVAILABLE"
    exit_code = 7
