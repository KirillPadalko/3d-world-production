"""LocationBlueprint services: versioning, IO, validation, overrides, conversion.

The contract models live in :mod:`environment_generator.models.blueprint`;
this package works with them:

* :func:`load_blueprint` / :func:`parse_blueprint` - read and fully validate;
* :func:`validate_document` - all phases, returns structured diagnostics;
* :func:`dumps_blueprint` / :func:`save_blueprint` - deterministic JSON;
* :func:`migrate_document` / :func:`migrate_file` - schema upgrades;
* :func:`apply_entity_operations` - LocationOverrides on a blueprint;
* :func:`blueprint_to_site` - the generator's internal view.
"""

from environment_generator.blueprint.diagnostics import Category, ValidationReport, diagnostic
from environment_generator.blueprint.index import EntityIndex, IndexedObject
from environment_generator.blueprint.io import (
    DEFAULT_FILENAME,
    blueprint_to_data,
    dumps_blueprint,
    load_blueprint,
    migrate_file,
    package_root_of,
    parse_blueprint,
    raise_for,
    save_blueprint,
    validate_source,
)
from environment_generator.blueprint.overrides import OverrideOutcome, apply_entity_operations
from environment_generator.blueprint.site_adapter import SiteConversion, blueprint_to_site
from environment_generator.blueprint.validation import (
    BlueprintValidation,
    validate_document,
    validate_model,
)
from environment_generator.blueprint.versioning import (
    CURRENT_VERSION,
    DEFAULT_MIGRATIONS,
    Migration,
    MigrationRegistry,
    MigrationResult,
    SchemaVersion,
    VersionStatus,
    check_version,
    migrate_document,
)

__all__ = [
    "CURRENT_VERSION",
    "DEFAULT_FILENAME",
    "DEFAULT_MIGRATIONS",
    "BlueprintValidation",
    "Category",
    "EntityIndex",
    "IndexedObject",
    "Migration",
    "MigrationRegistry",
    "MigrationResult",
    "OverrideOutcome",
    "SchemaVersion",
    "SiteConversion",
    "ValidationReport",
    "VersionStatus",
    "apply_entity_operations",
    "blueprint_to_data",
    "blueprint_to_site",
    "check_version",
    "diagnostic",
    "dumps_blueprint",
    "load_blueprint",
    "migrate_document",
    "migrate_file",
    "package_root_of",
    "parse_blueprint",
    "raise_for",
    "save_blueprint",
    "validate_document",
    "validate_model",
    "validate_source",
]
