"""LocationOverrides: blueprint entity operations and placement overrides."""

from __future__ import annotations

from typing import Any

import pytest

from environment_generator.blueprint.overrides import apply_entity_operations
from environment_generator.core.errors import OverrideError
from environment_generator.core.issues import Severity
from environment_generator.models.assets import AssetCategory, Dimensions
from environment_generator.models.blueprint import LocationBlueprint
from environment_generator.models.overrides import ConflictPolicy, LocationOverrides
from environment_generator.models.recipe import GeneratorName
from environment_generator.models.scene import Provenance, SceneEntity, Transform
from environment_generator.pipeline.overrides import apply_placement_overrides
from tests.blueprints import building, make_location, prop, straight_road, tree


def overrides(*operations: dict[str, Any], **data: Any) -> LocationOverrides:
    return LocationOverrides.model_validate(
        {
            "schemaVersion": "1.0",
            "id": "ov",
            "locationId": "test-location",
            "entityOperations": list(operations),
            **data,
        },
        by_alias=True,
        by_name=False,
    )


def sample() -> LocationBlueprint:
    return make_location(
        roads=straight_road(),
        buildings=[
            building("b-1", 20, 60, previousIds=["b-old"]),
            building("b-2", 60, 60, archetype="wooden_house_small"),
        ],
        trees=[tree("t-1", 80, 20)],
        props=[prop("p-1", 30, 20)],
        landmarks=[
            {
                "id": "lm-1",
                "landmarkType": "building",
                "position": [60, 0, 60],
                "linkedEntityId": "b-2",
            }
        ],
    )


def codes(issues: Any) -> list[str]:
    return [issue.code for issue in issues]


def test_operations_apply_in_order_without_mutating_the_source() -> None:
    blueprint = sample()
    before = blueprint.model_dump(mode="json")
    outcome = apply_entity_operations(
        blueprint,
        overrides(
            {
                "op": "update",
                "id": "b-2",
                "patch": {"condition": 0.2, "openings": {"doors": "open"}},
            },
            {"op": "replaceArchetype", "id": "b-2", "archetype": "wooden_house_medium"},
            {"op": "delete", "id": "t-1", "expectedType": "trees"},
            {"op": "add", "collection": "props", "entity": prop("p-2", 40, 25, "crate")},
        ),
    )
    result = outcome.blueprint
    assert outcome.applied == (
        "update buildings/b-2",
        "replaceArchetype buildings/b-2 -> wooden_house_medium",
        "delete trees/t-1",
        "add props/p-2",
    )
    b2 = next(b for b in result.buildings if b.id == "b-2")
    assert (b2.condition, b2.openings.doors.value, b2.archetype) == (
        0.2,
        "open",
        "wooden_house_medium",
    )
    assert b2.openings.windows.value == "unknown"  # merge patch keeps untouched fields
    assert result.trees == []
    assert [p.id for p in result.props] == ["p-1", "p-2"]
    assert blueprint.model_dump(mode="json") == before  # source untouched


def test_merge_patch_null_removes_optional_fields() -> None:
    blueprint = make_location(buildings=[building("b-1", 20, 60, floors=2, height=7)])
    outcome = apply_entity_operations(
        blueprint, overrides({"op": "update", "id": "b-1", "patch": {"floors": None}})
    )
    assert outcome.blueprint.buildings[0].floors is None


@pytest.mark.parametrize(
    ("operation", "code"),
    [
        ({"op": "delete", "id": "nope"}, "OVERRIDE_TARGET_MISSING"),
        ({"op": "delete", "id": "b-1", "expectedType": "props"}, "OVERRIDE_TYPE_MISMATCH"),
        ({"op": "add", "collection": "trees", "entity": tree("p-1", 1, 1)}, "OVERRIDE_ID_CONFLICT"),
        (
            {"op": "add", "collection": "trees", "entity": tree("b-old", 1, 1)},
            "OVERRIDE_ID_CONFLICT",
        ),
        (
            {"op": "add", "collection": "trees", "entity": {"transform": {}}},
            "OVERRIDE_ADD_WITHOUT_ID",
        ),
        ({"op": "update", "id": "b-1", "patch": {"id": "b-9"}}, "OVERRIDE_ID_CHANGE"),
        ({"op": "replaceArchetype", "id": "s-1", "archetype": "x"}, "OVERRIDE_NO_ARCHETYPE"),
    ],
)
def test_conflicts_fail_by_default(operation: dict[str, Any], code: str) -> None:
    with pytest.raises(OverrideError) as info:
        apply_entity_operations(sample(), overrides(operation))
    assert code in codes(info.value.issues)
    issue = next(i for i in info.value.issues if i.code == code)
    assert issue.severity is Severity.ERROR
    assert issue.path == "ov#entityOperations[0]"
    assert issue.suggestion


def test_report_policy_skips_and_reports_conflicts() -> None:
    outcome = apply_entity_operations(
        sample(),
        overrides(
            {"op": "delete", "id": "nope"},
            {"op": "delete", "id": "t-1"},
            conflictPolicy="report",
        ),
    )
    assert outcome.applied == ("delete trees/t-1",)
    assert outcome.unresolved == (
        "ov#entityOperations[0]: Entity 'nope' does not exist in the blueprint.",
    )
    assert [(i.code, i.severity) for i in outcome.issues] == [
        ("OVERRIDE_TARGET_MISSING", Severity.WARNING)
    ]


def test_former_ids_resolve_with_a_note() -> None:
    outcome = apply_entity_operations(
        sample(), overrides({"op": "update", "id": "b-old", "patch": {"condition": 0.5}})
    )
    assert outcome.applied == ("update buildings/b-1",)
    assert codes(outcome.issues) == ["OVERRIDE_TARGET_RENAMED"]
    assert outcome.blueprint.buildings[0].condition == 0.5


@pytest.mark.parametrize("policy", ["fail", "report"])
def test_invalid_result_always_fails(policy: str) -> None:
    # Deleting b-2 leaves landmark lm-1 pointing at nothing.
    with pytest.raises(OverrideError, match="invalid blueprint") as info:
        apply_entity_operations(
            sample(), overrides({"op": "delete", "id": "b-2"}, conflictPolicy=policy)
        )
    assert "REFERENCE_NOT_FOUND" in codes(info.value.issues)
    with pytest.raises(OverrideError, match="invalid blueprint"):
        apply_entity_operations(
            sample(), overrides({"op": "update", "id": "b-1", "patch": {"condition": 2}})
        )


def test_overrides_for_another_location_are_rejected() -> None:
    with pytest.raises(OverrideError) as info:
        apply_entity_operations(sample(), overrides(locationId="elsewhere"))
    assert codes(info.value.issues) == ["OVERRIDE_LOCATION_MISMATCH"]


def test_no_operations_returns_the_same_blueprint() -> None:
    blueprint = sample()
    assert apply_entity_operations(blueprint, overrides()).blueprint is blueprint


# --------------------------------------------------------------------------- placement


def _entity(entity_id: str = "prop.p") -> SceneEntity:
    return SceneEntity(
        id=entity_id,
        category=AssetCategory.PROP,
        kind="crate",
        archetype_id="prop.crate.wooden",
        asset_ref="envgen://prop/crate/wooden",
        transform=Transform(position=(1, 2, 0), scale=(2.0, 2.0, 2.0)),
        dimensions=Dimensions(width_m=2, depth_m=4, height_m=6),
        provenance=Provenance(generator=GeneratorName.PROPS, implementation="t@1", rule="t"),
    )


def test_placement_overrides_convert_from_the_location_frame() -> None:
    entities = {"prop.p": _entity()}
    placement = overrides(
        placementOverrides=[
            {"entityId": "prop.p", "position": [10, 3, 20], "yawDeg": 90, "scale": [1, 2, 4]}
        ]
    ).placement_overrides
    issues = apply_placement_overrides(
        entities, placement, overrides_id="ov", policy=ConflictPolicy.FAIL
    )
    assert issues == []
    moved = entities["prop.p"]
    # Location [x, up, north] -> generator (x, north, up); clockwise 90 -> counter-clockwise 270.
    assert moved.transform.position == (10, 20, 3)
    assert moved.transform.rotation_deg[2] == 270.0
    # Location scale (width, height, depth) -> generator (width, depth, height).
    assert moved.transform.scale == (1, 4, 2)
    assert (moved.dimensions.width_m, moved.dimensions.depth_m, moved.dimensions.height_m) == (
        1.0,
        8.0,
        6.0,
    )
    assert moved.provenance.overrides == ["ov#placementOverrides[0]"]


def test_placement_override_for_unknown_entity_follows_policy() -> None:
    placement = overrides(
        placementOverrides=[{"entityId": "prop.missing", "yawDeg": 10}]
    ).placement_overrides
    with pytest.raises(OverrideError, match="does not exist"):
        apply_placement_overrides({}, placement, overrides_id="ov", policy=ConflictPolicy.FAIL)
    issues = apply_placement_overrides(
        {}, placement, overrides_id="ov", policy=ConflictPolicy.REPORT
    )
    assert [(i.code, i.severity) for i in issues] == [("OVERRIDE_TARGET_MISSING", Severity.WARNING)]
