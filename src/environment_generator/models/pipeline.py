"""Stage input/output models for the first pipeline stages and the plan."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from environment_generator.core.issues import ValidationIssue
from environment_generator.models.assets import AssetPalette, AssetRegistryDocument
from environment_generator.models.base import ContractModel, Identifier, Seed
from environment_generator.models.blueprint import LocationBlueprint
from environment_generator.models.overrides import EntityOperation, LocationOverrides
from environment_generator.models.recipe import GeneratorName, LocationRecipe


class InputFingerprints(ContractModel):
    """Content hashes of the validated inputs (see :mod:`core.hashing`)."""

    blueprint: str
    recipe: str
    overrides: str | None
    registry: str
    combined: str = Field(
        description="Hash of all inputs, the generator version and the seed override."
    )


class LoadedInputs(ContractModel):
    """Output of stage 1: validated documents exactly as supplied."""

    blueprint: LocationBlueprint
    recipe: LocationRecipe
    overrides: LocationOverrides | None
    registry: AssetRegistryDocument
    seed_override: Seed | None = None
    fingerprints: InputFingerprints
    issues: list[ValidationIssue] = Field(default_factory=list)


class ResolvedInputs(ContractModel):
    """Output of stage 2: effective blueprint and recipe after overrides."""

    blueprint: LocationBlueprint
    recipe: LocationRecipe
    registry: AssetRegistryDocument
    seed: Seed
    overrides_id: Identifier | None
    strict_overrides: bool
    entity_operations: list[EntityOperation]
    applied_operations: list[str]
    dropped_features: list[str]
    fingerprints: InputFingerprints


class GenerationTask(ContractModel):
    """One generator invocation in a plan."""

    generator: GeneratorName
    implementation: str = Field(description="'<implementation>@<version>' of the generator.")
    seed: Seed
    depends_on: list[GeneratorName]
    source_features: list[str]
    estimated_entities: int = Field(ge=0)


class GenerationPlan(ContractModel):
    """Output of stage 4. Self-contained: generation can run from a saved plan."""

    plan_version: Literal["1.0"] = "1.0"
    generator_version: str
    input_fingerprint: str
    seed: Seed
    blueprint: LocationBlueprint
    recipe: LocationRecipe
    palette: AssetPalette
    overrides_id: Identifier | None
    strict_overrides: bool
    entity_operations: list[EntityOperation]
    tasks: list[GenerationTask]
    disabled_generators: list[GeneratorName]
    estimated_entities: int = Field(ge=0)
