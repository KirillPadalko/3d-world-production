"""Engine-agnostic primitives: errors, issues, geometry, randomness, hashing.

This package has no dependency on the rest of ``environment_generator``.
"""

from environment_generator.core.errors import (
    AdapterUnavailableError,
    AssetResolutionError,
    ContractValidationError,
    EnvironmentGeneratorError,
    ExportError,
    ExternalDataError,
    GenerationError,
    InputError,
    InputLoadError,
    LayoutValidationError,
    MigrationError,
    OverrideError,
    PlanningError,
    SemanticValidationError,
    UnsupportedVersionError,
)
from environment_generator.core.issues import Severity, ValidationIssue
from environment_generator.core.rng import DeterministicRng, derive_seed, hash_unit

__all__ = [
    "AdapterUnavailableError",
    "AssetResolutionError",
    "ContractValidationError",
    "DeterministicRng",
    "EnvironmentGeneratorError",
    "ExportError",
    "ExternalDataError",
    "GenerationError",
    "InputError",
    "InputLoadError",
    "LayoutValidationError",
    "MigrationError",
    "OverrideError",
    "PlanningError",
    "SemanticValidationError",
    "Severity",
    "UnsupportedVersionError",
    "ValidationIssue",
    "derive_seed",
    "hash_unit",
]
