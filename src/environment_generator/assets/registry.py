"""Built-in registry access and palette construction."""

from __future__ import annotations

import fnmatch
import json
from collections.abc import Iterable
from functools import lru_cache
from importlib import resources

from environment_generator.core.hashing import fingerprint
from environment_generator.core.issues import ValidationIssue
from environment_generator.models.assets import (
    Archetype,
    AssetCategory,
    AssetNeed,
    AssetPalette,
    AssetRegistryDocument,
)
from environment_generator.models.recipe import LocationRecipe
from environment_generator.models.site import Biome

BUILTIN_REGISTRY_FILE = "builtin-registry.json"


@lru_cache(maxsize=1)
def _builtin_registry_text() -> str:
    resource = resources.files("environment_generator.assets").joinpath(
        "data", BUILTIN_REGISTRY_FILE
    )
    return resource.read_text(encoding="utf-8")


def builtin_registry_data() -> dict[str, object]:
    """Raw JSON of the registry shipped with the package (a fresh copy)."""
    data = json.loads(_builtin_registry_text())
    if not isinstance(data, dict):  # pragma: no cover - packaged file is validated by tests
        raise TypeError("built-in registry must be a JSON object")
    return data


def load_builtin_registry() -> AssetRegistryDocument:
    return AssetRegistryDocument.model_validate(
        builtin_registry_data(), by_alias=True, by_name=False
    )


def archetype_matches_recipe(archetype: Archetype, recipe: LocationRecipe, biome: Biome) -> bool:
    """Hard filters: allowed IDs, required/excluded tags and biome support."""
    allowed = recipe.assets.allowed_archetypes
    if allowed and not any(fnmatch.fnmatchcase(archetype.id, pattern) for pattern in allowed):
        return False
    tags = set(archetype.tags)
    if not set(recipe.assets.required_tags) <= tags:
        return False
    if tags & set(recipe.assets.excluded_tags):
        return False
    return not archetype.biomes or biome in archetype.biomes


def _need_satisfied(need: AssetNeed, archetypes: Iterable[Archetype]) -> bool:
    return any(
        a.category is need.category
        and (a.id == need.kinds[0] or any(kind in a.kinds for kind in need.kinds))
        for a in archetypes
    )


def build_palette(
    registry: AssetRegistryDocument,
    recipe: LocationRecipe,
    biome: Biome,
    needs: Iterable[AssetNeed] = (),
) -> tuple[AssetPalette, list[ValidationIssue]]:
    """Filter a registry down to the archetypes usable for one run.

    Returns the palette and issues describing needs that no archetype covers
    (each such request will fall back to a placeholder or fail, depending on
    the recipe's fallback policy).
    """
    selected = sorted(
        (a for a in registry.archetypes if archetype_matches_recipe(a, recipe, biome)),
        key=lambda a: a.id,
    )
    counts = dict.fromkeys(AssetCategory, 0)
    for archetype in selected:
        counts[archetype.category] += 1

    unmet: list[AssetNeed] = []
    seen: set[tuple[AssetCategory, tuple[str, ...]]] = set()
    issues: list[ValidationIssue] = []
    for need in needs:
        key = (need.category, tuple(need.kinds))
        if key in seen:
            continue
        seen.add(key)
        if not _need_satisfied(need, selected):
            unmet.append(need)
            issues.append(
                ValidationIssue.warning(
                    "ASSET_KIND_UNAVAILABLE",
                    f"No {need.category.value} archetype for kind(s) {', '.join(need.kinds)} "
                    "after recipe filtering.",
                    location=need.reason,
                )
            )

    palette = AssetPalette(
        registry_id=registry.id,
        registry_fingerprint=fingerprint(registry.model_dump(mode="json")),
        archetypes=selected,
        excluded_archetypes=len(registry.archetypes) - len(selected),
        category_counts=counts,
        unmet_needs=unmet,
    )
    return palette, issues
