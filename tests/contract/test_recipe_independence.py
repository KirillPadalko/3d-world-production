"""LocationBlueprint, LocationRecipe and LocationOverrides are separate contracts.

* a blueprint describes a place and contains no styling or generation rules;
* a recipe contains no observations or geometry and is reusable across places;
* overrides reference entities by ID and never modify the blueprint file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from environment_generator.models.blueprint import LocationBlueprint
from environment_generator.models.recipe import LocationRecipe
from environment_generator.models.schemas import build_schema
from environment_generator.pipeline import InputBundle, LoadInputsStage, Pipeline
from tests.conftest import (
    DACHA_BLUEPRINT,
    DACHA_OVERRIDES,
    DACHA_RECIPE,
    EXAMPLES,
    LOCATIONS,
    RURAL_BLUEPRINT,
    RURAL_RECIPE,
    WAR_TORN_RECIPE,
)


def property_names(schema: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                names.update(value)
            names |= property_names(value)
    elif isinstance(schema, list):
        for item in schema:
            names |= property_names(item)
    return names


def test_recipe_contains_no_geometry_or_observations() -> None:
    recipe_fields = property_names(build_schema("location-recipe.schema.json", LocationRecipe))
    geometry = {"polygon", "path", "position", "controlPoints", "transform", "footprint", "nodes"}
    observations = {"provenance", "source", "confidence", "frames", "observations"}
    assert not recipe_fields & (geometry | observations)


def test_blueprint_contains_no_styling_or_asset_rules() -> None:
    blueprint_fields = property_names(
        build_schema("location-blueprint.schema.json", LocationBlueprint)
    )
    rules = {"style", "weathering", "assets", "allowedArchetypes", "fallback", "densityScale"}
    engine = {"prefab", "prefabPath", "instanceId", "assetRef", "meshyTaskId", "unityGuid"}
    assert not blueprint_fields & (rules | engine)


@pytest.mark.parametrize("location", sorted(LOCATIONS.glob("*/location.blueprint.json")))
def test_a_generic_recipe_applies_to_every_location(location: Path) -> None:
    result = Pipeline().run(InputBundle(blueprint=location, recipe=RURAL_RECIPE))
    assert result.success, result.error


def test_recipes_can_target_location_families() -> None:
    LoadInputsStage().run(InputBundle(blueprint=DACHA_BLUEPRINT, recipe=DACHA_RECIPE))
    from environment_generator.core.errors import SemanticValidationError

    with pytest.raises(SemanticValidationError) as info:
        LoadInputsStage().run(InputBundle(blueprint=RURAL_BLUEPRINT, recipe=DACHA_RECIPE))
    assert [i.code for i in info.value.issues] == ["RECIPE_NOT_APPLICABLE"]


def test_switching_recipes_never_changes_the_blueprint() -> None:
    before = DACHA_BLUEPRINT.read_bytes()
    runs = [
        Pipeline().run(InputBundle(blueprint=DACHA_BLUEPRINT, recipe=recipe))
        for recipe in (None, DACHA_RECIPE, WAR_TORN_RECIPE)
    ]
    assert all(run.success for run in runs), [run.error for run in runs]
    blueprints = {run.loaded.blueprint.model_dump_json() for run in runs if run.loaded}
    prints = {run.loaded.fingerprints.blueprint for run in runs if run.loaded}
    assert len(blueprints) == 1 and len(prints) == 1
    hashes = {run.manifest.content_hash for run in runs if run.manifest}
    assert len(hashes) == 3  # the recipes do change the generated result
    assert DACHA_BLUEPRINT.read_bytes() == before


def test_overrides_never_modify_the_blueprint_file() -> None:
    before = DACHA_BLUEPRINT.read_bytes()
    result = Pipeline().run(
        InputBundle(blueprint=DACHA_BLUEPRINT, recipe=DACHA_RECIPE, overrides=DACHA_OVERRIDES)
    )
    assert result.success and result.loaded is not None and result.resolved is not None
    assert DACHA_BLUEPRINT.read_bytes() == before
    original = {b.id: b for b in result.loaded.blueprint.buildings}
    effective = {b.id: b for b in result.resolved.blueprint.buildings}
    assert original["b-house-02"].condition == 0.7
    assert effective["b-house-02"].condition == 0.4
    assert "pr-tires-06" in {p.id for p in result.loaded.blueprint.props}
    assert "pr-tires-06" not in {p.id for p in result.resolved.blueprint.props}


def test_example_recipes_and_overrides_are_standalone_documents() -> None:
    for path in sorted((EXAMPLES / "recipes").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "locationId" not in data and "buildings" not in data.get("metadata", {})
    for path in sorted((EXAMPLES / "overrides").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert set(data) <= {
            "schemaVersion",
            "id",
            "locationId",
            "recipeId",
            "description",
            "author",
            "conflictPolicy",
            "entityOperations",
            "placementOverrides",
            "metadata",
        }
