from __future__ import annotations

import pytest

from environment_generator.assets.registry import (
    archetype_matches_recipe,
    build_palette,
    builtin_registry_data,
)
from environment_generator.assets.resolver import (
    AssetRequest,
    PaletteAssetResolver,
    fit_score,
    is_placeholder_id,
)
from environment_generator.core.errors import AssetResolutionError
from environment_generator.models.assets import (
    AssetCategory,
    AssetNeed,
    AssetPalette,
    AssetRegistryDocument,
)
from environment_generator.models.blueprint import Biome
from environment_generator.models.recipe import FallbackPolicy, LocationRecipe
from tests.conftest import make_recipe


def palette_for(
    registry: AssetRegistryDocument,
    recipe: LocationRecipe | None = None,
    biome: Biome = Biome.TEMPERATE,
) -> AssetPalette:
    palette, _ = build_palette(registry, recipe or LocationRecipe.default(), biome)
    return palette


def test_builtin_registry_is_valid_and_fresh(builtin_registry: AssetRegistryDocument) -> None:
    assert builtin_registry.id == "builtin-stylized"
    assert len({a.id for a in builtin_registry.archetypes}) == len(builtin_registry.archetypes)
    data = builtin_registry_data()
    data["id"] = "mutated"
    assert builtin_registry_data()["id"] == "builtin-stylized"
    categories = {a.category for a in builtin_registry.archetypes}
    assert categories == set(AssetCategory)


def test_palette_filters_by_tags_and_biome(builtin_registry: AssetRegistryDocument) -> None:
    recipe = make_recipe(assets={"excluded_tags": ["weathered"], "required_tags": ["stylized"]})
    palette = palette_for(builtin_registry, recipe, Biome.BOREAL)
    ids = {a.id for a in palette.archetypes}
    assert "vegetation.tree.dead" not in ids  # excluded tag
    assert "vegetation.tree.oak" not in ids  # temperate only
    assert "vegetation.tree.spruce" in ids
    assert palette.excluded_archetypes == len(builtin_registry.archetypes) - len(ids)
    archetype = next(a for a in builtin_registry.archetypes if a.id == "vegetation.tree.oak")
    assert archetype_matches_recipe(archetype, LocationRecipe.default(), Biome.TEMPERATE)


def test_palette_reports_unmet_needs(builtin_registry: AssetRegistryDocument) -> None:
    needs = [
        AssetNeed(category=AssetCategory.BUILDING, kinds=["house"], reason="a"),
        AssetNeed(category=AssetCategory.BUILDING, kinds=["castle"], reason="b"),
        AssetNeed(category=AssetCategory.BUILDING, kinds=["castle"], reason="c"),
    ]
    palette, issues = build_palette(
        builtin_registry, LocationRecipe.default(), Biome.TEMPERATE, needs
    )
    assert [n.kinds for n in palette.unmet_needs] == [["castle"]]
    assert [i.code for i in issues] == ["ASSET_KIND_UNAVAILABLE"]


def test_resolver_is_deterministic_per_entity(builtin_registry: AssetRegistryDocument) -> None:
    palette = palette_for(builtin_registry)
    resolver = PaletteAssetResolver(palette, seed=5)
    picks = {
        resolver.resolve(AssetRequest(AssetCategory.VEGETATION, ("tree",), f"veg.{i}")).archetype.id
        for i in range(60)
    }
    assert len(picks) > 1  # variety across entities
    request = AssetRequest(AssetCategory.VEGETATION, ("tree",), "veg.42")
    first = resolver.resolve(request)
    again = PaletteAssetResolver(palette, seed=5).resolve(request)
    assert (first.archetype.id, first.variant) == (again.archetype.id, again.variant)
    assert first.variant < first.archetype.variants


def test_resolver_prefers_matching_condition_and_size(
    builtin_registry: AssetRegistryDocument,
) -> None:
    resolver = PaletteAssetResolver(palette_for(builtin_registry), seed=1)
    ruined = resolver.resolve(
        AssetRequest(AssetCategory.BUILDING, ("house",), "b.1", size=(9, 7), condition="ruined")
    )
    assert ruined.archetype.id == "building.ruin.house_shell"
    road = resolver.resolve(
        AssetRequest(AssetCategory.ROAD, ("dirt_track",), "r.1", surface="dirt")
    )
    assert road.archetype.id == "road.profile.dirt"


def test_resolver_falls_back_in_kind_order(builtin_registry: AssetRegistryDocument) -> None:
    resolver = PaletteAssetResolver(palette_for(builtin_registry), seed=1)
    selection = resolver.resolve(
        AssetRequest(AssetCategory.INFRASTRUCTURE, ("unknown_pole", "utility_pole"), "x")
    )
    assert selection.matched_kind == "utility_pole"
    assert not selection.placeholder


def test_placeholder_and_error_fallbacks(builtin_registry: AssetRegistryDocument) -> None:
    palette = palette_for(builtin_registry)
    request = AssetRequest(
        AssetCategory.BUILDING, ("castle",), "b.castle", size=(30, 20), height=25
    )
    placeholder = PaletteAssetResolver(palette, seed=1).resolve(request)
    assert placeholder.placeholder
    assert placeholder.archetype.id == "placeholder.building.castle"
    assert is_placeholder_id(placeholder.archetype.id)
    assert placeholder.archetype.dimensions.width_m == 30
    strict = PaletteAssetResolver(palette, seed=1, fallback=FallbackPolicy.ERROR)
    with pytest.raises(AssetResolutionError, match="castle"):
        strict.resolve(request)
    with pytest.raises(ValueError):
        strict.resolve(AssetRequest(AssetCategory.BUILDING, (), "b"))


def test_preferred_tags_shift_the_mix(builtin_registry: AssetRegistryDocument) -> None:
    palette = palette_for(builtin_registry)

    def dead_trees(preferred: tuple[str, ...]) -> int:
        resolver = PaletteAssetResolver(palette, seed=3, preferred_tags=preferred)
        return sum(
            resolver.resolve(
                AssetRequest(AssetCategory.VEGETATION, ("tree",), f"v.{i}")
            ).archetype.id
            == "vegetation.tree.dead"
            for i in range(400)
        )

    assert dead_trees(("weathered",)) > dead_trees(())


def test_fit_score_penalties(builtin_registry: AssetRegistryDocument) -> None:
    house = next(a for a in builtin_registry.archetypes if a.id == "building.house.small_gable")
    perfect = AssetRequest(
        AssetCategory.BUILDING, ("house",), "b", size=(9, 7), floors=1, roof="gable"
    )
    assert fit_score(house, perfect) == 0.0
    worse = AssetRequest(
        AssetCategory.BUILDING, ("house",), "b", size=(18, 7), floors=5, roof="flat"
    )
    assert fit_score(house, worse) < -4.0
    assert resolver_get(builtin_registry, house.id)


def resolver_get(registry: AssetRegistryDocument, archetype_id: str) -> bool:
    resolver = PaletteAssetResolver(palette_for(registry), seed=0)
    return resolver.get(archetype_id) is not None and resolver.get("nope.nope") is None
