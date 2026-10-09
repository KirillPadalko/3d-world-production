"""The committed JSON Schemas are the public contract.

* they must match the models (no drift),
* they must be valid JSON Schema 2020-12 documents,
* every example must validate against them with an independent validator,
* invalid fixtures must be rejected by both the schema and the models.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError

from environment_generator.models.schemas import JSON_SCHEMA_DIALECT, PUBLIC_SCHEMAS, stale_schemas
from tests.conftest import EXAMPLES, FIXTURES, REPO_ROOT, SCHEMAS

BUILTIN_REGISTRY = (
    REPO_ROOT / "src" / "environment_generator" / "assets" / "data" / "builtin-registry.json"
)


def schema(name: str) -> dict[str, Any]:
    data = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(schema(name))


def documents(pattern: str) -> list[Path]:
    found = sorted(EXAMPLES.glob(pattern))
    assert found, pattern
    return found


def test_committed_schemas_match_models() -> None:
    assert stale_schemas(SCHEMAS) == [], "run `uv run envgen schema export`"


@pytest.mark.parametrize("name", sorted(PUBLIC_SCHEMAS))
def test_schemas_are_valid_2020_12(name: str) -> None:
    document = schema(name)
    assert document["$schema"] == JSON_SCHEMA_DIALECT
    assert document["$id"].startswith("urn:environment-generator:schema:")
    Draft202012Validator.check_schema(document)


@pytest.mark.parametrize(
    ("schema_name", "path"),
    [
        *[("location-blueprint.schema.json", p) for p in documents("blueprints/*.json")],
        *[("location-recipe.schema.json", p) for p in documents("recipes/*.json")],
        *[("location-overrides.schema.json", p) for p in documents("overrides/*.json")],
        *[
            ("scene-manifest.schema.json", p)
            for p in documents("expected-output/*/scene-manifest.json")
        ],
        ("asset-registry.schema.json", BUILTIN_REGISTRY),
    ],
    ids=lambda value: value.name if isinstance(value, Path) else value,
)
def test_documents_validate_against_schema(schema_name: str, path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    errors = sorted(validator(schema_name).iter_errors(document), key=str)
    assert not errors, [f"{list(e.absolute_path)}: {e.message}" for e in errors[:5]]
    PUBLIC_SCHEMAS[schema_name].model_validate(document)


INVALID = {
    "blueprint-missing-extent.json": "location-blueprint.schema.json",
    "blueprint-forest-as-point.json": "location-blueprint.schema.json",
    "blueprint-unknown-field.json": "location-blueprint.schema.json",
    "blueprint-bad-identifier.json": "location-blueprint.schema.json",
    "recipe-out-of-range.json": "location-recipe.schema.json",
    "overrides-unknown-op.json": "location-overrides.schema.json",
    "registry-bad-archetype-id.json": "asset-registry.schema.json",
}


@pytest.mark.parametrize(("fixture", "schema_name"), sorted(INVALID.items()))
def test_invalid_documents_are_rejected_by_schema_and_models(
    fixture: str, schema_name: str
) -> None:
    document = json.loads((FIXTURES / "invalid" / fixture).read_text(encoding="utf-8"))
    assert list(validator(schema_name).iter_errors(document)), "schema accepted an invalid document"
    model: type[BaseModel] = PUBLIC_SCHEMAS[schema_name]
    with pytest.raises(ValidationError):
        model.model_validate(document)


def test_manifest_produced_now_validates(tmp_path: Path) -> None:
    from environment_generator.pipeline import InputBundle, Pipeline, PipelineOptions

    Pipeline().run(
        InputBundle(blueprint=EXAMPLES / "blueprints" / "minimal.blueprint.json"),
        PipelineOptions(output_dir=tmp_path),
    )
    manifest = json.loads((tmp_path / "scene-manifest.json").read_text(encoding="utf-8"))
    assert not list(validator("scene-manifest.schema.json").iter_errors(manifest))
