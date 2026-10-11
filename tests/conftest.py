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
from environment_generator.models.recipe import LocationRecipe
from environment_generator.models.scene import GenerationControls, SceneEntity
from environment_generator.models.site import SiteDescription

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"
SCHEMAS = REPO_ROOT / "schemas"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

LOCATIONS = EXAMPLES / "locations"
BLUEPRINT_FILE = "location.blueprint.json"
RURAL_BLUEPRINT = LOCATIONS / "rural-crossroads" / BLUEPRINT_FILE
INDUSTRIAL_BLUEPRINT = LOCATIONS / "industrial-outskirts" / BLUEPRINT_FILE
MINIMAL_BLUEPRINT = LOCATIONS / "minimal" / BLUEPRINT_FILE
DACHA_DIR = LOCATIONS / "dacha-forest-edge"
DACHA_BLUEPRINT = DACHA_DIR / BLUEPRINT_FILE
RURAL_RECIPE = EXAMPLES / "recipes" / "stylized-rural.recipe.json"
WAR_TORN_RECIPE = EXAMPLES / "recipes" / "war-torn.recipe.json"
DACHA_RECIPE = EXAMPLES / "recipes" / "dacha-overgrown.recipe.json"
RURAL_OVERRIDES = EXAMPLES / "overrides" / "rural-crossroads.designer-pass.overrides.json"
DACHA_OVERRIDES = EXAMPLES / "overrides" / "dacha-forest-edge.designer-pass.overrides.json"

DEFAULT_CONTROLS = GenerationControls(
    structural_similarity=1.0, visual_variation=0.5, detail_density=1.0, abandonment=0.0
)


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def site_data(**changes: Any) -> dict[str, Any]:
    """A small internal site description (generator frame, Z up); keywords replace keys."""
    data: dict[str, Any] = {
        "id": "test-site",
        "name": "Test site",
        "extent": {"width_m": 100, "depth_m": 80},
        "terrain": {"relief": "flat"},
    }
    data.update(changes)
    return data


def make_site(**changes: Any) -> SiteDescription:
    return SiteDescription.model_validate(site_data(**changes))


def make_recipe(**changes: Any) -> LocationRecipe:
    """A recipe for tests; keys may be camelCase (as in files) or Python field names."""
    data: dict[str, Any] = {"schemaVersion": "1.0", "id": "test-recipe", "name": "Test recipe"}
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
    site: SiteDescription,
    recipe: LocationRecipe | None = None,
    *,
    seed: int = 1,
    registry: AssetRegistryDocument | None = None,
    entities: Mapping[str, SceneEntity] | None = None,
    occupancy: SpatialIndex | None = None,
    terrain: HeightSampler | None = None,
    controls: GenerationControls = DEFAULT_CONTROLS,
) -> GenerationContext:
    recipe = recipe or LocationRecipe.default()
    palette, _ = build_palette(registry or load_builtin_registry(), recipe, site.biome)
    resolver = PaletteAssetResolver(
        palette,
        seed=seed,
        preferred_tags=recipe.effective_preferred_tags(),
        fallback=recipe.assets.fallback,
    )
    return GenerationContext(
        site=site,
        recipe=recipe,
        controls=controls,
        seed=seed,
        assets=resolver,
        terrain=terrain or FlatGround(site.terrain.base_elevation_m),
        occupancy=occupancy if occupancy is not None else SpatialIndex(),
        entities=dict(entities or {}),
    )


@pytest.fixture
def context_factory() -> Callable[..., GenerationContext]:
    return make_context


@pytest.fixture(scope="session")
def builtin_registry() -> AssetRegistryDocument:
    return load_builtin_registry()
