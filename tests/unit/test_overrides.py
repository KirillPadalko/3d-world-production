from __future__ import annotations

import pytest

from environment_generator.assets.registry import build_palette, load_builtin_registry
from environment_generator.assets.resolver import PaletteAssetResolver
from environment_generator.core.errors import OverrideError
from environment_generator.models.assets import AssetCategory, Dimensions
from environment_generator.models.blueprint import Condition
from environment_generator.models.overrides import LocationOverrides
from environment_generator.models.recipe import GeneratorName, LocationRecipe
from environment_generator.models.scene import Provenance, SceneEntity, Transform
from environment_generator.pipeline.overrides import (
    apply_entity_operations,
    apply_feature_operations,
    apply_recipe_patch,
    drop_low_confidence,
)
from tests.conftest import make_blueprint, rect_building


def overrides(**data: object) -> LocationOverrides:
    return LocationOverrides.model_validate(
        {"schema_version": "1.0", "id": "ov", "blueprint_id": "test-site", **data}
    )


def test_recipe_patch_merges_and_validates() -> None:
    recipe = LocationRecipe.default()
    patched = apply_recipe_patch(recipe, {"vegetation": {"density_scale": 0.5}, "seed": 4})
    assert patched.vegetation.density_scale == 0.5
    assert patched.vegetation.min_spacing_m == recipe.vegetation.min_spacing_m
    assert patched.seed == 4
    assert apply_recipe_patch(recipe, {}) is recipe
    with pytest.raises(OverrideError) as excinfo:
        apply_recipe_patch(recipe, {"vegetation": {"density_scale": -1}})
    assert excinfo.value.issues


def test_feature_operations_apply_in_order() -> None:
    blueprint = make_blueprint(
        buildings=[rect_building("b-1", [20, 20], [8, 6]), rect_building("b-2", [60, 20], [8, 6])]
    )
    ops = overrides(
        feature_operations=[
            {"op": "remove", "collection": "buildings", "id": "b-1"},
            {
                "op": "patch",
                "collection": "buildings",
                "id": "b-2",
                "patch": {"condition": "ruined"},
            },
            {
                "op": "add",
                "collection": "buildings",
                "feature": rect_building("b-3", [40, 60], [8, 6]),
            },
        ]
    ).feature_operations
    result, log = apply_feature_operations(blueprint, ops, "ov")
    assert [b.id for b in result.buildings] == ["b-2", "b-3"]
    assert result.buildings[0].condition is Condition.RUINED
    assert log == ["remove buildings/b-1", "patch buildings/b-2", "add buildings/b-3"]
    assert [b.id for b in blueprint.buildings] == ["b-1", "b-2"]  # original untouched


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        ({"op": "remove", "collection": "buildings", "id": "nope"}, "does not exist"),
        (
            {
                "op": "add",
                "collection": "buildings",
                "feature": rect_building("b-1", [1, 1], [2, 2]),
            },
            "already exists",
        ),
        ({"op": "add", "collection": "buildings", "feature": {"kind": "house"}}, "string 'id'"),
        (
            {"op": "patch", "collection": "buildings", "id": "b-1", "patch": {"floors": 0}},
            "invalid blueprint",
        ),
    ],
)
def test_feature_operation_errors(operation: dict[str, object], message: str) -> None:
    blueprint = make_blueprint(buildings=[rect_building("b-1", [20, 20], [8, 6])])
    with pytest.raises(OverrideError, match=message):
        apply_feature_operations(
            blueprint, overrides(feature_operations=[operation]).feature_operations, "ov"
        )


def test_drop_low_confidence() -> None:
    blueprint = make_blueprint(
        buildings=[
            rect_building("b-1", [20, 20], [8, 6], confidence=0.2),
            rect_building("b-2", [60, 20], [8, 6]),
        ]
    )
    result, dropped = drop_low_confidence(blueprint, 0.5)
    assert dropped == ["buildings/b-1"]
    assert [b.id for b in result.buildings] == ["b-2"]
    assert drop_low_confidence(blueprint, 0.0) == (blueprint, [])


def _entity(entity_id: str = "prop.p") -> SceneEntity:
    return SceneEntity(
        id=entity_id,
        category=AssetCategory.PROP,
        kind="crate",
        archetype_id="prop.crate.wooden",
        asset_ref="envgen://prop/crate/wooden",
        transform=Transform(position=(1, 2, 0), scale=(2.0, 2.0, 2.0)),
        dimensions=Dimensions(width_m=2, depth_m=2, height_m=2),
        provenance=Provenance(generator=GeneratorName.PROPS, implementation="t@1", rule="t"),
    )


def _resolver() -> PaletteAssetResolver:
    registry = load_builtin_registry()
    palette, _ = build_palette(registry, LocationRecipe.default(), make_blueprint().biome)
    return PaletteAssetResolver(palette, seed=0)


def test_entity_operations() -> None:
    entities = {"prop.p": _entity(), "prop.q": _entity("prop.q")}
    ops = overrides(
        entity_operations=[
            {
                "op": "set_archetype",
                "entity_id": "prop.p",
                "archetype_id": "prop.barrel.steel",
                "variant": 1,
            },
            {"op": "set_transform", "entity_id": "prop.p", "yaw_deg": -90, "scale": [1, 1, 1]},
            {"op": "remove", "entity_id": "prop.q"},
        ]
    ).entity_operations
    issues = apply_entity_operations(
        entities, ops, overrides_id="ov", strict=True, assets=_resolver()
    )
    assert issues == []
    assert set(entities) == {"prop.p"}
    updated = entities["prop.p"]
    assert updated.archetype_id == "prop.barrel.steel" and updated.variant == 1
    assert updated.transform.rotation_deg[2] == 270.0
    assert updated.dimensions.width_m == pytest.approx(0.6)  # barrel at scale 1 after both ops
    assert updated.provenance.overrides == ["ov#entity_operations[0]", "ov#entity_operations[1]"]


def test_entity_operation_errors_and_lenient_mode() -> None:
    resolver = _resolver()
    missing = overrides(
        entity_operations=[{"op": "remove", "entity_id": "prop.missing"}]
    ).entity_operations
    with pytest.raises(OverrideError, match="was not generated"):
        apply_entity_operations({}, missing, overrides_id="ov", strict=True, assets=resolver)
    issues = apply_entity_operations({}, missing, overrides_id="ov", strict=False, assets=resolver)
    assert [i.code for i in issues] == ["OVERRIDE_UNKNOWN_ENTITY"]
    for archetype, message in [
        ("prop.nothing.here", "not in the palette"),
        ("building.house.small_gable", "is a building"),
    ]:
        op = overrides(
            entity_operations=[
                {"op": "set_archetype", "entity_id": "prop.p", "archetype_id": archetype}
            ]
        ).entity_operations
        with pytest.raises(OverrideError, match=message):
            apply_entity_operations(
                {"prop.p": _entity()}, op, overrides_id="ov", strict=True, assets=resolver
            )
    bad_variant = overrides(
        entity_operations=[
            {
                "op": "set_archetype",
                "entity_id": "prop.p",
                "archetype_id": "prop.generic.box",
                "variant": 3,
            }
        ]
    ).entity_operations
    with pytest.raises(OverrideError, match="out of range"):
        apply_entity_operations(
            {"prop.p": _entity()}, bad_variant, overrides_id="ov", strict=True, assets=resolver
        )
