"""Schema versioning policy and the migration framework.

Policy (see docs/LOCATION_BLUEPRINT.md, "Versioning"):

* ``schemaVersion`` is ``"MAJOR.MINOR"``.
* MINOR versions only add optional fields or enum values. A reader accepts
  documents with its own major and an equal or lower minor.
* A document with a *higher minor* than the reader supports may contain
  fields the reader would drop, so it is rejected with an actionable error
  instead of being read partially.
* MAJOR versions may break compatibility. Older majors are read only through
  a registered migration chain; newer majors are rejected.
* Migrations are pure functions on raw JSON documents. They never modify
  their input and never write files on their own.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import total_ordering
from typing import Any

from environment_generator.core.errors import MigrationError, UnsupportedVersionError
from environment_generator.core.issues import Severity, ValidationIssue
from environment_generator.models.blueprint import BLUEPRINT_SCHEMA_VERSION

_VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})$")
VERSION_FIELD = "schemaVersion"


@total_ordering
@dataclass(frozen=True)
class SchemaVersion:
    major: int
    minor: int

    @classmethod
    def parse(cls, text: str) -> SchemaVersion:
        match = _VERSION_PATTERN.match(text)
        if match is None:
            raise ValueError(f"'{text}' is not a MAJOR.MINOR version")
        return cls(int(match.group(1)), int(match.group(2)))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SchemaVersion):
            return NotImplemented
        return (self.major, self.minor) < (other.major, other.minor)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


#: The version this implementation reads and writes.
CURRENT_VERSION = SchemaVersion.parse(BLUEPRINT_SCHEMA_VERSION)


class VersionStatus(StrEnum):
    CURRENT = "current"
    READABLE = "readable"  # same major, older minor
    MIGRATABLE = "migratable"  # older major with a migration path
    TOO_NEW = "too_new"  # same major, newer minor
    UNSUPPORTED = "unsupported"  # newer major, or older major without a path
    INVALID = "invalid"
    MISSING = "missing"


@dataclass(frozen=True)
class Migration:
    """One upgrade step from ``source`` to ``target`` on a raw JSON document."""

    source: SchemaVersion
    target: SchemaVersion
    description: str
    upgrade: Callable[[dict[str, Any]], dict[str, Any]]


class MigrationRegistry:
    """Known migration steps; :meth:`path` chains them to the current version."""

    def __init__(self, migrations: Iterable[Migration] = ()) -> None:
        self._by_source: dict[SchemaVersion, Migration] = {}
        for migration in migrations:
            self.register(migration)

    def register(self, migration: Migration) -> None:
        if not migration.source < migration.target:
            raise ValueError("a migration must upgrade to a newer version")
        if migration.source in self._by_source:
            raise ValueError(f"a migration from {migration.source} is already registered")
        self._by_source[migration.source] = migration

    def path(self, source: SchemaVersion, target: SchemaVersion) -> list[Migration]:
        """Ordered steps from ``source`` to ``target``; empty when equal."""
        steps: list[Migration] = []
        current = source
        while current < target:
            step = self._by_source.get(current)
            if step is None or target < step.target:
                raise MigrationError(
                    f"No migration path from schema {source} to {target} (stuck at {current})."
                )
            steps.append(step)
            current = step.target
        return steps

    def can_migrate(self, source: SchemaVersion, target: SchemaVersion) -> bool:
        try:
            self.path(source, target)
        except MigrationError:
            return False
        return True


#: Built-in migrations. 1.0 is the first public version, so there are none yet;
#: future versions register their upgrade steps here.
DEFAULT_MIGRATIONS = MigrationRegistry()


def _issue(code: str, message: str, suggestion: str) -> ValidationIssue:
    return ValidationIssue(
        severity=Severity.ERROR,
        code=code,
        message=message,
        category="version",
        path=VERSION_FIELD,
        suggestion=suggestion,
    )


def check_version(
    document: Mapping[str, Any],
    *,
    registry: MigrationRegistry = DEFAULT_MIGRATIONS,
    current: SchemaVersion = CURRENT_VERSION,
) -> tuple[VersionStatus, SchemaVersion | None, list[ValidationIssue]]:
    """Classify the declared version; issues are empty for readable documents."""
    raw = document.get(VERSION_FIELD)
    if raw is None:
        if "schema_version" in document:
            return (
                VersionStatus.INVALID,
                None,
                [
                    _issue(
                        "BLUEPRINT_LEGACY_FORMAT",
                        "Found 'schema_version' (snake_case): this is the unreleased 0.1 draft "
                        "format, which is not supported.",
                        f"Re-author the document in the v{current} format (camelCase fields).",
                    )
                ],
            )
        return (
            VersionStatus.MISSING,
            None,
            [
                _issue(
                    "BLUEPRINT_VERSION_MISSING",
                    "The document does not declare schemaVersion.",
                    f'Add "schemaVersion": "{current}" after checking the document matches it.',
                )
            ],
        )
    if not isinstance(raw, str):
        return (
            VersionStatus.INVALID,
            None,
            [
                _issue(
                    "BLUEPRINT_VERSION_INVALID",
                    f'schemaVersion must be a string like "{current}", got {raw!r}.',
                    f'Write the version as a string: "{current}".',
                )
            ],
        )
    try:
        version = SchemaVersion.parse(raw)
    except ValueError:
        return (
            VersionStatus.INVALID,
            None,
            [
                _issue(
                    "BLUEPRINT_VERSION_INVALID",
                    f"schemaVersion '{raw}' is not MAJOR.MINOR.",
                    f'Use the form "{current}".',
                )
            ],
        )
    if version == current:
        return VersionStatus.CURRENT, version, []
    if version.major == current.major and version < current:
        return VersionStatus.READABLE, version, []
    if version.major == current.major:
        return (
            VersionStatus.TOO_NEW,
            version,
            [
                _issue(
                    "BLUEPRINT_VERSION_TOO_NEW",
                    f"Schema {version} is newer than the supported {current}; fields added in "
                    "newer minor versions would be lost.",
                    "Upgrade environment-generator to a release that supports this version.",
                )
            ],
        )
    if version.major > current.major:
        return (
            VersionStatus.UNSUPPORTED,
            version,
            [
                _issue(
                    "BLUEPRINT_VERSION_UNSUPPORTED",
                    f"Schema major version {version.major} is not supported (this release reads "
                    f"{current.major}.x).",
                    "Upgrade environment-generator, or export the document as "
                    f"{current.major}.x from the producing tool.",
                )
            ],
        )
    if registry.can_migrate(version, current):
        return (
            VersionStatus.MIGRATABLE,
            version,
            [
                _issue(
                    "BLUEPRINT_MIGRATION_REQUIRED",
                    f"Schema {version} must be migrated to {current} before use.",
                    "Run `envgen blueprint migrate <file> --output <new-file>`.",
                )
            ],
        )
    return (
        VersionStatus.UNSUPPORTED,
        version,
        [
            _issue(
                "BLUEPRINT_VERSION_UNSUPPORTED",
                f"Schema {version} is older than {current} and no migration path exists.",
                "Re-export the document from its producing tool in the current format.",
            )
        ],
    )


@dataclass(frozen=True)
class MigrationResult:
    document: dict[str, Any]
    source_version: SchemaVersion
    target_version: SchemaVersion
    steps: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.steps)


def migrate_document(
    document: Mapping[str, Any],
    *,
    registry: MigrationRegistry = DEFAULT_MIGRATIONS,
    target: SchemaVersion = CURRENT_VERSION,
) -> MigrationResult:
    """Upgrade a raw document to ``target``. The input is never modified."""
    status, version, issues = check_version(document, registry=registry, current=target)
    if version is None or status in {VersionStatus.TOO_NEW, VersionStatus.UNSUPPORTED}:
        error = UnsupportedVersionError if status is not VersionStatus.INVALID else MigrationError
        raise error("The document cannot be migrated.", issues=issues)
    data = copy.deepcopy(dict(document))
    if status in {VersionStatus.CURRENT, VersionStatus.READABLE} and version.major == target.major:
        steps = registry.path(version, target) if registry.can_migrate(version, target) else []
    else:
        steps = registry.path(version, target)
    applied: list[str] = []
    for step in steps:
        data = step.upgrade(copy.deepcopy(data))
        declared = data.get(VERSION_FIELD)
        if declared != str(step.target):
            raise MigrationError(
                f"Migration {step.source} -> {step.target} did not set schemaVersion "
                f"(found {declared!r})."
            )
        applied.append(f"{step.source} -> {step.target}: {step.description}")
    return MigrationResult(data, version, target, tuple(applied))
