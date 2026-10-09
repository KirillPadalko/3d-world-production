"""Typed data models: public contracts and stage inputs/outputs.

Public input contracts (exported as JSON Schema under ``schemas/``):
:class:`LocationBlueprint`, :class:`LocationRecipe`, :class:`LocationOverrides`
and :class:`AssetRegistryDocument`. Public output contract:
:class:`SceneManifest`.
"""

from environment_generator.models.assets import (
    Archetype,
    AssetCategory,
    AssetNeed,
    AssetPalette,
    AssetRegistryDocument,
    Dimensions,
)
from environment_generator.models.base import CONTRACT_VERSION, ContractModel
from environment_generator.models.blueprint import FeatureCollection, LocationBlueprint
from environment_generator.models.overrides import LocationOverrides
from environment_generator.models.pipeline import (
    GenerationPlan,
    GenerationTask,
    InputFingerprints,
    LoadedInputs,
    ResolvedInputs,
)
from environment_generator.models.recipe import GeneratorName, LocationRecipe
from environment_generator.models.report import (
    GenerationReport,
    LayoutValidationResult,
    StageReport,
    StageStatus,
)
from environment_generator.models.scene import (
    AtmosphereSettings,
    Provenance,
    Scene,
    SceneEntity,
    SceneManifest,
    TerrainData,
    Transform,
)

__all__ = [
    "CONTRACT_VERSION",
    "Archetype",
    "AssetCategory",
    "AssetNeed",
    "AssetPalette",
    "AssetRegistryDocument",
    "AtmosphereSettings",
    "ContractModel",
    "Dimensions",
    "FeatureCollection",
    "GenerationPlan",
    "GenerationReport",
    "GenerationTask",
    "GeneratorName",
    "InputFingerprints",
    "LayoutValidationResult",
    "LoadedInputs",
    "LocationBlueprint",
    "LocationOverrides",
    "LocationRecipe",
    "Provenance",
    "ResolvedInputs",
    "Scene",
    "SceneEntity",
    "SceneManifest",
    "StageReport",
    "StageStatus",
    "TerrainData",
    "Transform",
]
