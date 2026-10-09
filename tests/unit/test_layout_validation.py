from __future__ import annotations

from typing import Any

from environment_generator.core.issues import Severity
from environment_generator.models.assets import AssetCategory, Dimensions
from environment_generator.models.blueprint import Extent
from environment_generator.models.recipe import GeneratorName, LayoutValidationRecipe
from environment_generator.models.scene import (
    EntityPolyline,
    Provenance,
    Scene,
    SceneEntity,
    TerrainData,
    Transform,
)
from environment_generator.validation.layout import (
    LayoutContext,
    LayoutRule,
    RuleBasedLayoutValidator,
)

ARCHETYPES = ["building.house.small_gable", "road.profile.asphalt", "prop.crate.wooden"]


def entity(
    entity_id: str,
    category: AssetCategory,
    position: tuple[float, float, float],
    size: tuple[float, float, float] = (4.0, 4.0, 3.0),
    archetype: str = "building.house.small_gable",
    **extra: Any,
) -> SceneEntity:
    return SceneEntity(
        id=entity_id,
        category=category,
        kind="test",
        archetype_id=archetype,
        asset_ref="envgen://test",
        transform=Transform(position=position),
        dimensions=Dimensions(width_m=size[0], depth_m=size[1], height_m=size[2]),
        provenance=Provenance(generator=GeneratorName.PROPS, implementation="test@1", rule="test"),
        **extra,
    )


def road_entity() -> SceneEntity:
    return entity(
        "road.r",
        AssetCategory.ROAD,
        (0.0, 50.0, 0.0),
        archetype="road.profile.asphalt",
        geometry=EntityPolyline(type="polyline", points=[(0, 50, 0), (100, 50, 0)], width_m=6.0),
    )


def scene(*entities: SceneEntity, terrain: TerrainData | None = None) -> Scene:
    return Scene(
        blueprint_id="t",
        extent=Extent(width_m=100, depth_m=100),
        terrain=terrain,
        atmosphere=None,
        entities=list(entities),
    )


def validate(s: Scene, **settings: Any):  # type: ignore[no-untyped-def]
    return RuleBasedLayoutValidator().validate(
        s, settings=LayoutValidationRecipe(**settings), known_archetypes=ARCHETYPES
    )


def codes(result) -> dict[str, Severity]:  # type: ignore[no-untyped-def]
    return {issue.code: issue.severity for issue in result.issues}


def test_clean_scene_passes() -> None:
    result = validate(
        scene(road_entity(), entity("building.a", AssetCategory.BUILDING, (20, 20, 0)))
    )
    assert result.issues == []
    assert not result.has_errors
    assert result.checked_entities == 2
    assert "obstructions" in result.rules


def test_building_on_road_and_overlap_are_errors() -> None:
    result = validate(
        scene(
            road_entity(),
            entity("building.a", AssetCategory.BUILDING, (20, 50, 0)),
            entity("building.b", AssetCategory.BUILDING, (30, 20, 0)),
            entity("building.c", AssetCategory.BUILDING, (32, 21, 0)),
        )
    )
    found = codes(result)
    assert found["LAYOUT_ROAD_OBSTRUCTED"] is Severity.ERROR
    assert found["LAYOUT_BUILDING_OVERLAP"] is Severity.ERROR
    assert result.has_errors


def test_vegetation_on_road_is_only_a_warning() -> None:
    result = validate(scene(road_entity(), entity("veg.t", AssetCategory.VEGETATION, (40, 50, 0))))
    assert codes(result) == {"LAYOUT_ROAD_OBSTRUCTED": Severity.WARNING}
    assert (
        codes(
            validate(
                scene(road_entity(), entity("veg.t", AssetCategory.VEGETATION, (40, 50, 0))),
                check_road_obstruction=False,
            )
        )
        == {}
    )


def test_bounds_archetypes_placeholders_and_duplicates() -> None:
    result = validate(
        scene(
            entity("prop.out", AssetCategory.PROP, (150, 20, 0), archetype="prop.crate.wooden"),
            entity("prop.unknown", AssetCategory.PROP, (10, 10, 0), archetype="prop.mystery.box"),
            entity(
                "prop.ph",
                AssetCategory.PROP,
                (60, 10, 0),
                archetype="placeholder.prop.x",
                placeholder=True,
            ),
            entity("prop.dup", AssetCategory.PROP, (80, 80, 0), archetype="prop.crate.wooden"),
            entity("prop.dup", AssetCategory.PROP, (85, 85, 0), archetype="prop.crate.wooden"),
        )
    )
    found = codes(result)
    assert found["LAYOUT_OUT_OF_BOUNDS"] is Severity.ERROR
    assert found["LAYOUT_UNKNOWN_ARCHETYPE"] is Severity.ERROR
    assert found["LAYOUT_PLACEHOLDER_ASSETS"] is Severity.WARNING
    assert found["LAYOUT_DUPLICATE_ID"] is Severity.ERROR


def test_ground_contact_and_budget() -> None:
    terrain = TerrainData(
        cell_size_m=100.0,
        columns=2,
        rows=2,
        heights=[[0.0, 0.0], [0.0, 0.0]],
        min_elevation_m=0.0,
        max_elevation_m=0.0,
        ground_cover="grass",
    )
    floating = entity("prop.f", AssetCategory.PROP, (10, 10, 5), archetype="prop.crate.wooden")
    found = codes(validate(scene(floating, terrain=terrain), max_entities=1))
    assert found["LAYOUT_GROUND_CONTACT"] is Severity.WARNING
    assert found["LAYOUT_ENTITY_BUDGET"] is Severity.WARNING
    over = codes(
        validate(scene(floating, floating.model_copy(update={"id": "prop.g"})), max_entities=1)
    )
    assert over["LAYOUT_ENTITY_BUDGET"] is Severity.ERROR


def test_custom_rules_can_be_plugged_in() -> None:
    class NoProps(LayoutRule):
        name = "no_props"

        def check(self, context: LayoutContext):  # type: ignore[no-untyped-def]
            from environment_generator.core.issues import ValidationIssue

            for e in context.scene.entities:
                if e.category is AssetCategory.PROP:
                    yield ValidationIssue.error("NO_PROPS", "props are banned", entity_ids=[e.id])

    validator = RuleBasedLayoutValidator([NoProps()])
    result = validator.validate(
        scene(entity("prop.a", AssetCategory.PROP, (10, 10, 0))),
        settings=LayoutValidationRecipe(),
        known_archetypes=[],
    )
    assert result.rules == ["no_props"]
    assert [i.code for i in result.issues] == ["NO_PROPS"]
