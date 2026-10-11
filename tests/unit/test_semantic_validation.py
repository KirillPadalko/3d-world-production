from __future__ import annotations

from environment_generator.models.assets import AssetRegistryDocument
from environment_generator.models.overrides import LocationOverrides
from environment_generator.validation.semantic import (
    validate_compatibility,
    validate_recipe,
    validate_registry,
)
from tests.blueprints import make_location
from tests.conftest import make_recipe


def codes(issues: list) -> set[str]:  # type: ignore[type-arg]
    return {issue.code for issue in issues}


def test_recipe_checks() -> None:
    disabled = make_recipe(
        **{
            name: {"enabled": False}
            for name in (
                "terrain",
                "roads",
                "buildings",
                "fences",
                "infrastructure",
                "vegetation",
                "props",
                "atmosphere",
            )
        }
    )
    assert "RECIPE_NOTHING_ENABLED" in codes(validate_recipe(disabled))
    assert validate_recipe(make_recipe()) == []


def test_registry_checks(builtin_registry: AssetRegistryDocument) -> None:
    assert validate_registry(builtin_registry) == []
    first = builtin_registry.archetypes[0]
    broken = builtin_registry.model_copy(
        update={
            "archetypes": [
                first,
                first,
                first.model_copy(update={"id": "placeholder.prop.x"}),
                first.model_copy(
                    update={
                        "id": "building.bad",
                        "constraints": first.constraints.model_copy(
                            update={"min_floors": 3, "max_floors": 1}
                        ),
                    }
                ),
            ]
        }
    )
    assert codes(validate_registry(broken)) == {
        "REGISTRY_DUPLICATE_ARCHETYPE",
        "REGISTRY_RESERVED_ID",
        "REGISTRY_INVALID_CONSTRAINTS",
    }


def test_compatibility_checks() -> None:
    blueprint = make_location()
    recipe = make_recipe(appliesTo=["rural-*"])
    assert "RECIPE_NOT_APPLICABLE" in codes(validate_compatibility(blueprint, recipe, None))
    assert validate_compatibility(blueprint, make_recipe(appliesTo=["test-*"]), None) == []
    overrides = LocationOverrides.model_validate(
        {"schemaVersion": "1.0", "id": "o", "locationId": "other", "recipeId": "nope"}
    )
    found = codes(validate_compatibility(blueprint, make_recipe(), overrides))
    assert found == {"OVERRIDES_LOCATION_MISMATCH", "OVERRIDES_RECIPE_MISMATCH"}
