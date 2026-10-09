"""Shared fixtures and helpers for the test suite."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from environment_generator.assets.registry import build_palette, load_builtin_registry
from environment_generator.assets.resolver import PaletteAssetResolver
from environment_generator.core.spatial import SpatialIndex
from environment_generator.core.terrain import FlatGround, HeightSampler
from environment_generator.generators.base import GenerationContext
from environment_generator.models.assets import AssetRegistryDocument
from environment_generator.models.blueprint import LocationBlueprint
from environment_generator.models.recipe import LocationRecipe
from environment_generator.models.scene import SceneEntity

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"
SCHEMAS = REPO_ROOT / "schemas"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

RURAL_BLUEPRINT = EXAMPLES / "blueprints" / "rural-crossroads.blueprint.json"
INDUSTRIAL_BLUEPRINT = EXAMPLES / "blueprints" / "industrial-outskirts.blueprint.json"
MINIMAL_BLUEPRINT = EXAMPLES / "blueprints" / "minimal.blueprint.json"
RURAL_RECIPE = EXAMPLES / "recipes" / "stylized-rural.recipe.json"
WAR_TORN_RECIPE = EXAMPLES / "recipes" / "war-torn.recipe.json"
RURAL_OVERRIDES = EXAMPLES / "overrides" / "rural-crossroads.designer-pass.overrides.json"


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def blueprint_data(**changes: Any) -> dict[str, Any]:
    """A small valid blueprint document; keyword arguments replace top-level keys."""
    data: dict[str, Any] = {
        "schema_version": "1.0",
        "id": "test-site",
        "name": "Test site",
        "extent": {"width_m": 100, "depth_m": 80},
        "terrain": {"relief": "flat"},
    }
    data.update(changes)
    return data


def make_blueprint(**changes: Any) -> LocationBlueprint:
    return LocationBlueprint.model_validate(blueprint_data(**changes))


def make_recipe(**changes: Any) -> LocationRecipe:
    data: dict[str, Any] = {"schema_version": "1.0", "id": "test-recipe", "name": "Test recipe"}
    data.update(changes)
    return LocationRecipe.model_validate(data)


def road(
    feature_id: str, points: list[list[float]], kind: str = "street", **extra: Any
) -> dict[str, Any]:
    return {
        "id": feature_id,
        "kind": kind,
        "geometry": {"type": "polyline", "points": points},
        **extra,
    }


def rect_building(
    feature_id: str,
    center: list[float],
    size: list[float],
    rotation: float = 0.0,
    kind: str = "house",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": feature_id,
        "kind": kind,
        "geometry": {"type": "rectangle", "center": center, "size": size, "rotation_deg": rotation},
        **extra,
    }


def make_context(
    blueprint: LocationBlueprint,
    recipe: LocationRecipe | None = None,
    *,
    seed: int = 1,
    registry: AssetRegistryDocument | None = None,
    entities: Mapping[str, SceneEntity] | None = None,
    occupancy: SpatialIndex | None = None,
    terrain: HeightSampler | None = None,
) -> GenerationContext:
    recipe = recipe or LocationRecipe.default()
    palette, _ = build_palette(registry or load_builtin_registry(), recipe, blueprint.biome)
    resolver = PaletteAssetResolver(
        palette,
        seed=seed,
        preferred_tags=recipe.effective_preferred_tags(),
        fallback=recipe.assets.fallback,
    )
    return GenerationContext(
        blueprint=blueprint,
        recipe=recipe,
        seed=seed,
        assets=resolver,
        terrain=terrain or FlatGround(blueprint.terrain.base_elevation_m),
        occupancy=occupancy if occupancy is not None else SpatialIndex(),
        entities=dict(entities or {}),
    )


@pytest.fixture
def context_factory() -> Callable[..., GenerationContext]:
    return make_context


@pytest.fixture(scope="session")
def builtin_registry() -> AssetRegistryDocument:
    return load_builtin_registry()
