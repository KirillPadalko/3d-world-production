"""Loading, saving and migrating LocationBlueprint documents.

Serialisation is deterministic: field order follows the model, floats are
written exactly (shortest round-trip form), text is UTF-8, short numeric arrays
stay on one line. ``compact`` output omits values equal to their defaults;
``full`` output writes every field. Either form loads back to an equal model.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from environment_generator.blueprint.diagnostics import Category
from environment_generator.blueprint.validation import BlueprintValidation, validate_document
from environment_generator.blueprint.versioning import (
    DEFAULT_MIGRATIONS,
    MigrationRegistry,
    MigrationResult,
    VersionStatus,
    migrate_document,
)
from environment_generator.core.errors import (
    ContractValidationError,
    ExportError,
    MigrationError,
    SemanticValidationError,
    UnsupportedVersionError,
)
from environment_generator.core.hashing import pretty_json
from environment_generator.core.issues import Severity, has_errors
from environment_generator.models.blueprint import LocationBlueprint
from environment_generator.validation.contract import InputSource, read_json_document

#: Conventional file name inside a location package.
DEFAULT_FILENAME = "location.blueprint.json"


def package_root_of(source: InputSource) -> Path | None:
    """The folder external files are resolved against (``None`` for in-memory data)."""
    if isinstance(source, Mapping):
        return None
    return Path(source).resolve().parent


def raise_for(result: BlueprintValidation, label: str = "blueprint") -> LocationBlueprint:
    """Return the blueprint or raise the error class matching the failed phase."""
    if result.blueprint is None:
        if result.status is VersionStatus.MIGRATABLE:
            raise MigrationError(f"{label} needs migration before use", issues=result.issues)
        if result.status in {
            VersionStatus.TOO_NEW,
            VersionStatus.UNSUPPORTED,
            VersionStatus.INVALID,
            VersionStatus.MISSING,
        } and any(i.category == Category.VERSION.value for i in result.issues):
            raise UnsupportedVersionError(
                f"{label} has an unsupported schema version", issues=result.issues
            )
        raise ContractValidationError(
            f"{label} does not satisfy the LocationBlueprint schema "
            f"({len(result.issues)} problem(s))",
            issues=result.issues,
        )
    if has_errors(result.issues):
        errors = [i for i in result.issues if i.severity is Severity.ERROR]
        raise SemanticValidationError(
            f"{label} is invalid ({len(errors)} error(s))", issues=result.issues
        )
    return result.blueprint


def parse_blueprint(
    document: Mapping[str, Any],
    *,
    package_root: Path | None = None,
    check_external: bool = True,
    registry: MigrationRegistry = DEFAULT_MIGRATIONS,
) -> LocationBlueprint:
    """Validate a raw document fully and return the model (raises on errors)."""
    result = validate_document(
        document, package_root=package_root, check_external=check_external, registry=registry
    )
    return raise_for(result)


def validate_source(
    source: InputSource,
    *,
    package_root: Path | None = None,
    check_external: bool = True,
    registry: MigrationRegistry = DEFAULT_MIGRATIONS,
) -> BlueprintValidation:
    """Validate a blueprint file or mapping without raising for invalid content."""
    document = read_json_document(source, "blueprint")
    root = package_root if package_root is not None else package_root_of(source)
    return validate_document(
        document, package_root=root, check_external=check_external, registry=registry
    )


def load_blueprint(
    source: InputSource,
    *,
    package_root: Path | None = None,
    check_external: bool = True,
) -> LocationBlueprint:
    """Read and fully validate a blueprint; raises with diagnostics on errors."""
    return raise_for(
        validate_source(source, package_root=package_root, check_external=check_external)
    )


def blueprint_to_data(blueprint: LocationBlueprint, *, compact: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = blueprint.model_dump(
        mode="json", by_alias=True, exclude_defaults=compact
    )
    return data


def dumps_blueprint(blueprint: LocationBlueprint, *, compact: bool = True) -> str:
    """Deterministic JSON text (floats exact, UTF-8, trailing newline)."""
    return pretty_json(blueprint_to_data(blueprint, compact=compact), decimals=None)


def save_blueprint(
    blueprint: LocationBlueprint,
    path: Path,
    *,
    overwrite: bool = False,
    compact: bool = True,
) -> Path:
    """Write a blueprint. Existing files are only replaced with ``overwrite=True``."""
    if path.exists() and not overwrite:
        raise ExportError(f"'{path}' exists; pass overwrite=True to replace it")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps_blueprint(blueprint, compact=compact), encoding="utf-8")
    except OSError as exc:
        raise ExportError(f"Cannot write '{path}': {exc}") from exc
    return path


def _backup_path(path: Path, version: str) -> Path:
    candidate = path.with_name(f"{path.name}.v{version}.bak")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.v{version}.{counter}.bak")
        counter += 1
    return candidate


def migrate_file(
    source: Path,
    *,
    output: Path | None = None,
    in_place: bool = False,
    overwrite: bool = False,
    registry: MigrationRegistry = DEFAULT_MIGRATIONS,
) -> tuple[MigrationResult, Path | None]:
    """Migrate a blueprint file to the current version.

    The original file is only replaced with ``in_place=True``, and then a
    backup (``<name>.v<old>.bak``) is written first. With ``output`` the
    original is left untouched. Without either, nothing is written.
    """
    if in_place and output is not None:
        raise ValueError("choose either output or in_place")
    document = read_json_document(source, "blueprint")
    result = migrate_document(document, registry=registry)
    migrated = parse_blueprint(
        result.document, package_root=source.resolve().parent, registry=registry
    )
    text = dumps_blueprint(migrated)
    if in_place:
        if not result.changed:
            return result, None
        backup = _backup_path(source, str(result.source_version))
        backup.write_bytes(source.read_bytes())
        source.write_text(text, encoding="utf-8")
        return result, source
    if output is None:
        return result, None
    if output.resolve() == source.resolve():
        raise ExportError(
            "Refusing to overwrite the original file; use in_place=True for an explicit "
            "in-place migration."
        )
    if output.exists() and not overwrite:
        raise ExportError(f"'{output}' exists; pass overwrite=True to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return result, output


def describe_diagnostics(result: BlueprintValidation) -> str:
    """One line per diagnostic, for logs and the CLI."""
    if not result.issues:
        return "no diagnostics"
    return "\n".join(issue.format() for issue in result.issues)


__all__ = [
    "DEFAULT_FILENAME",
    "blueprint_to_data",
    "describe_diagnostics",
    "dumps_blueprint",
    "load_blueprint",
    "migrate_file",
    "package_root_of",
    "parse_blueprint",
    "raise_for",
    "save_blueprint",
    "validate_source",
]
