from __future__ import annotations

from environment_generator.core.issues import Severity
from environment_generator.models.assets import AssetRegistryDocument
from environment_generator.models.overrides import LocationOverrides
from environment_generator.validation.semantic import (
    validate_blueprint,
    validate_compatibility,
    validate_recipe,
    validate_registry,
)
from tests.conftest import make_blueprint, make_recipe, rect_building, road


def codes(issues: list) -> set[str]:  # type: ignore[type-arg]
    return {issue.code for issue in issues}


def test_valid_blueprint_has_no_errors() -> None:
    blueprint = make_blueprint(
        roads=[road("r-1", [[0, 40], [100, 40]])],
        buildings=[rect_building("b-1", [50, 60], [10, 8])],
    )
    assert not [i for i in validate_blueprint(blueprint) if i.severity is Severity.ERROR]


def test_duplicate_ids_are_errors() -> None:
    blueprint = make_blueprint(
        roads=[road("r-1", [[0, 40], [100, 40]]), road("r-1", [[0, 10], [100, 10]])]
    )
    assert "BLUEPRINT_DUPLICATE_ID" in codes(validate_blueprint(blueprint))


def test_self_intersecting_polygon_is_error() -> None:
    blueprint = make_blueprint(
        zones=[
            {
                "id": "z",
                "kind": "park",
                "geometry": {"type": "polygon", "points": [[0, 0], [10, 10], [10, 0], [0, 10]]},
            }
        ]
    )
    assert "BLUEPRINT_INVALID_POLYGON" in codes(validate_blueprint(blueprint))


def test_extent_checks() -> None:
    outside = make_blueprint(buildings=[rect_building("b-1", [500, 500], [10, 8])])
    assert "BLUEPRINT_FEATURE_OUTSIDE_EXTENT" in codes(validate_blueprint(outside))
    partial = make_blueprint(roads=[road("r-1", [[-20, 40], [50, 40]])])
    issues = validate_blueprint(partial)
    assert "BLUEPRINT_FEATURE_PARTIALLY_OUTSIDE" in codes(issues)
    assert all(i.severity is not Severity.ERROR for i in issues)


def test_fence_gap_beyond_length() -> None:
    blueprint = make_blueprint(
        fences=[
            {
                "id": "f",
                "kind": "wooden",
                "geometry": {"type": "polyline", "points": [[0, 0], [10, 0]]},
                "gaps": [{"offset_m": 9, "width_m": 3}],
            }
        ]
    )
    assert "BLUEPRINT_FENCE_GAP_OUT_OF_RANGE" in codes(validate_blueprint(blueprint))


def test_overlapping_buildings_and_low_confidence_are_reported() -> None:
    blueprint = make_blueprint(
        buildings=[
            rect_building("b-1", [50, 50], [10, 8]),
            rect_building("b-2", [54, 50], [10, 8], confidence=0.2),
        ]
    )
    found = codes(validate_blueprint(blueprint))
    assert {"BLUEPRINT_BUILDING_OVERLAP", "BLUEPRINT_LOW_CONFIDENCE"} <= found


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
    empty_fill = make_recipe(buildings={"zone_fill": {"enabled": True, "zone_kinds": []}})
    assert "RECIPE_EMPTY_ZONE_FILL" in codes(validate_recipe(empty_fill))


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
    blueprint = make_blueprint()
    recipe = make_recipe(applies_to=["rural-*"])
    assert "RECIPE_NOT_APPLICABLE" in codes(validate_compatibility(blueprint, recipe, None))
    assert validate_compatibility(blueprint, make_recipe(applies_to=["test-*"]), None) == []
    overrides = LocationOverrides.model_validate(
        {"schema_version": "1.0", "id": "o", "blueprint_id": "other", "recipe_id": "nope"}
    )
    found = codes(validate_compatibility(blueprint, make_recipe(), overrides))
    assert found == {"OVERRIDES_BLUEPRINT_MISMATCH", "OVERRIDES_RECIPE_MISMATCH"}
