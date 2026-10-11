"""Stage input/output models for the first pipeline stages and the plan."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from environment_generator.core.issues import ValidationIssue
from environment_generator.models.assets import AssetPalette, AssetRegistryDocument
from environment_generator.models.base import ContractModel, Identifier, Seed
from environment_generator.models.blueprint import LocationBlueprint
from environment_generator.models.overrides import (
    ConflictPolicy,
    LocationOverrides,
    PlacementOverride,
)
from environment_generator.models.recipe import GeneratorName, LocationRecipe
from environment_generator.models.scene import Annotations, GenerationControls
from environment_generator.models.site import SiteDescription


class InputFingerprints(ContractModel):
    """Content hashes of the validated inputs (see :mod:`core.hashing`)."""

    blueprint: str
    recipe: str
    overrides: str | None
    registry: str
    external_files: str | None = Field(
        default=None, description="Hash over the referenced external files that were read."
    )
    combined: str = Field(
        description="Hash of all inputs, the generator version and the seed override."
    )


class LoadedInputs(ContractModel):
    """Output of stage 1: validated documents exactly as supplied."""

    blueprint: LocationBlueprint
    package_root: str | None = Field(
        default=None, description="Directory external blueprint files are resolved against."
    )
    recipe: LocationRecipe
    overrides: LocationOverrides | None
    registry: AssetRegistryDocument
    seed_override: Seed | None = None
    fingerprints: InputFingerprints
    issues: list[ValidationIssue] = Field(default_factory=list)


class ResolvedInputs(ContractModel):
    """Output of stage 2: effective blueprint, its site view and the recipe."""

    blueprint: LocationBlueprint = Field(description="Blueprint after entity operations.")
    site: SiteDescription
    recipe: LocationRecipe
    registry: AssetRegistryDocument
    seed: Seed
    subsystem_seeds: dict[str, Seed] = Field(
        default_factory=dict, description="Explicit seeds (blueprint, then recipe)."
    )
    controls: GenerationControls
    overrides_id: Identifier | None
    conflict_policy: ConflictPolicy = ConflictPolicy.FAIL
    placement_overrides: list[PlacementOverride] = Field(default_factory=list)
    applied_operations: list[str]
    override_trace: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Blueprint entity ID -> entity operations that changed or added it.",
    )
    dropped_features: list[str]
    annotations: Annotations = Field(default_factory=Annotations)
    fingerprints: InputFingerprints


class GenerationTask(ContractModel):
    """One generator invocation in a plan."""

    generator: GeneratorName
    implementation: str = Field(description="'<implementation>@<version>' of the generator.")
    seed: Seed
    seed_source: Literal["derived", "blueprint", "recipe"] = "derived"
    depends_on: list[GeneratorName]
    source_features: list[str]
    estimated_entities: int = Field(ge=0)


class GenerationPlan(ContractModel):
    """Output of stage 4. Self-contained: generation can run from a saved plan."""

    plan_version: Literal["1.0"] = "1.0"
    generator_version: str
    input_fingerprint: str
    seed: Seed
    asset_seed: Seed
    location_id: Identifier
    location_name: str
    site: SiteDescription
    recipe: LocationRecipe
    controls: GenerationControls
    palette: AssetPalette
    overrides_id: Identifier | None
    conflict_policy: ConflictPolicy = ConflictPolicy.FAIL
    placement_overrides: list[PlacementOverride]
    override_trace: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Blueprint entity ID -> entity operations, copied to generated entities.",
    )
    annotations: Annotations = Field(default_factory=Annotations)
    tasks: list[GenerationTask]
    disabled_generators: list[GeneratorName]
    estimated_entities: int = Field(ge=0)
