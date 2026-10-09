"""JSON Schema export of the public contracts.

The Pydantic models are the single source of truth; ``schemas/*.schema.json``
are generated from them (``envgen schema export``) and committed so that
producers in other languages can validate documents without Python. CI runs
``envgen schema check`` to fail when the committed files drift.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from environment_generator.models.assets import AssetRegistryDocument
from environment_generator.models.base import CONTRACT_VERSION
from environment_generator.models.blueprint import LocationBlueprint
from environment_generator.models.overrides import LocationOverrides
from environment_generator.models.recipe import LocationRecipe
from environment_generator.models.scene import SceneManifest

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

PUBLIC_SCHEMAS: dict[str, type[BaseModel]] = {
    "location-blueprint.schema.json": LocationBlueprint,
    "location-recipe.schema.json": LocationRecipe,
    "location-overrides.schema.json": LocationOverrides,
    "asset-registry.schema.json": AssetRegistryDocument,
    "scene-manifest.schema.json": SceneManifest,
}


def build_schema(filename: str, model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema(mode="validation")
    name = filename.removesuffix(".schema.json")
    return {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": f"urn:environment-generator:schema:{name}:{CONTRACT_VERSION}",
        **schema,
    }


def render_schema(filename: str, model: type[BaseModel]) -> str:
    return json.dumps(build_schema(filename, model), indent=2, ensure_ascii=False) + "\n"


def export_schemas(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, model in PUBLIC_SCHEMAS.items():
        path = directory / filename
        path.write_text(render_schema(filename, model), encoding="utf-8")
        written.append(path)
    return written


def stale_schemas(directory: Path) -> list[str]:
    """Names of committed schema files that differ from the models (or are missing)."""
    stale = []
    for filename, model in PUBLIC_SCHEMAS.items():
        path = directory / filename
        if not path.exists() or path.read_text(encoding="utf-8") != render_schema(filename, model):
            stale.append(filename)
    return stale
