"""Asset resolution: choosing an archetype for a semantic request."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from environment_generator.core.errors import AssetResolutionError
from environment_generator.core.rng import DeterministicRng, derive_seed
from environment_generator.models.assets import (
    Archetype,
    AssetCategory,
    AssetPalette,
    Dimensions,
)
from environment_generator.models.recipe import FallbackPolicy

#: Archetypes scoring within this margin of the best are all eligible.
NEAR_BEST_MARGIN = 0.5
#: Selection weight multiplier per matched preferred tag.
PREFERRED_TAG_BOOST = 2.0

PLACEHOLDER_PREFIX = "placeholder"

_PLACEHOLDER_DIMENSIONS: dict[AssetCategory, tuple[float, float, float]] = {
    AssetCategory.TERRAIN: (1.0, 1.0, 0.0),
    AssetCategory.WATER: (1.0, 1.0, 0.0),
    AssetCategory.ROAD: (1.0, 1.0, 0.05),
    AssetCategory.BUILDING: (8.0, 6.0, 6.0),
    AssetCategory.FENCE: (2.0, 0.2, 1.2),
    AssetCategory.INFRASTRUCTURE: (0.5, 0.5, 6.0),
    AssetCategory.VEGETATION: (3.0, 3.0, 5.0),
    AssetCategory.PROP: (1.0, 1.0, 1.0),
}


@dataclass(frozen=True, slots=True)
class AssetRequest:
    """What a generator needs. ``kinds`` are acceptable kinds in preference order."""

    category: AssetCategory
    kinds: tuple[str, ...]
    entity_id: str
    size: tuple[float, float] | None = None
    height: float | None = None
    floors: int | None = None
    roof: str | None = None
    condition: str | None = None
    surface: str | None = None


@dataclass(frozen=True, slots=True)
class AssetSelection:
    archetype: Archetype
    variant: int
    matched_kind: str
    placeholder: bool
    fit_score: float


class AssetResolver(ABC):
    """Interface: map semantic requests to archetypes deterministically."""

    @abstractmethod
    def resolve(self, request: AssetRequest) -> AssetSelection:
        """Select an archetype for ``request``. Same request -> same answer."""

    @abstractmethod
    def get(self, archetype_id: str) -> Archetype | None:
        """Look up an archetype by id (``None`` if unknown)."""


def placeholder_archetype(
    category: AssetCategory,
    kind: str,
    size: tuple[float, float] | None = None,
    height: float | None = None,
) -> Archetype:
    """Synthesised stand-in used when the palette has nothing suitable."""
    default_w, default_d, default_h = _PLACEHOLDER_DIMENSIONS[category]
    width, depth = size if size is not None else (default_w, default_d)
    return Archetype(
        id=f"{PLACEHOLDER_PREFIX}.{category.value}.{kind}",
        category=category,
        kinds=[kind],
        tags=["placeholder"],
        dimensions=Dimensions(
            width_m=width, depth_m=depth, height_m=height if height is not None else default_h
        ),
        asset_ref=f"placeholder://{category.value}/{kind}",
        description="Generated placeholder: no registry archetype matched the request.",
    )


def is_placeholder_id(archetype_id: str) -> bool:
    return archetype_id.startswith(PLACEHOLDER_PREFIX + ".")


class PaletteAssetResolver(AssetResolver):
    """Scores palette archetypes against a request and picks deterministically.

    1. Candidates: archetypes of the category supporting the first requested
       kind that has any; later kinds are fallbacks.
    2. Fit score: penalties for footprint/height mismatch and for violating soft
       constraints (floors, roof, condition, surface).
    3. Archetypes within :data:`NEAR_BEST_MARGIN` of the best score are drawn
       by weight (boosted by preferred tags) using a seed derived from the
       entity id, so selection is stable per entity yet varied across entities.
    """

    def __init__(
        self,
        palette: AssetPalette,
        *,
        seed: int,
        preferred_tags: Sequence[str] = (),
        fallback: FallbackPolicy = FallbackPolicy.PLACEHOLDER,
    ) -> None:
        self._seed = seed
        self._preferred = frozenset(preferred_tags)
        self._fallback = fallback
        self._by_id = {a.id: a for a in palette.archetypes}
        self._by_category: dict[AssetCategory, list[Archetype]] = {}
        for archetype in sorted(palette.archetypes, key=lambda a: a.id):
            self._by_category.setdefault(archetype.category, []).append(archetype)

    def get(self, archetype_id: str) -> Archetype | None:
        return self._by_id.get(archetype_id)

    def resolve(self, request: AssetRequest) -> AssetSelection:
        if not request.kinds:
            raise ValueError("an asset request needs at least one kind")
        pool = self._by_category.get(request.category, [])
        for kind in request.kinds:
            candidates = [a for a in pool if kind in a.kinds]
            if candidates:
                return self._pick(candidates, kind, request)
        if self._fallback is FallbackPolicy.ERROR:
            raise AssetResolutionError(
                f"No {request.category.value} archetype for kind(s) "
                f"{', '.join(request.kinds)} (entity {request.entity_id}) and the recipe "
                "forbids placeholders."
            )
        archetype = placeholder_archetype(
            request.category, request.kinds[0], request.size, request.height
        )
        return AssetSelection(archetype, 0, request.kinds[0], True, 0.0)

    def _pick(
        self, candidates: list[Archetype], kind: str, request: AssetRequest
    ) -> AssetSelection:
        scored = [(fit_score(a, request), a) for a in candidates]
        best = max(score for score, _ in scored)
        eligible = [(s, a) for s, a in scored if s >= best - NEAR_BEST_MARGIN]
        weights = [
            a.weight * PREFERRED_TAG_BOOST ** len(self._preferred.intersection(a.tags))
            for _, a in eligible
        ]
        rng = DeterministicRng(derive_seed(self._seed, "asset", request.entity_id))
        score, archetype = eligible[rng.weighted_index(weights)]
        variant = derive_seed(self._seed, "variant", request.entity_id) % archetype.variants
        return AssetSelection(archetype, variant, kind, False, round(score, 6))


def _ratio_penalty(requested: float, nominal: float) -> float:
    if requested <= 0 or nominal <= 0:
        return 0.0
    return abs(math.log(requested / nominal))


def fit_score(archetype: Archetype, request: AssetRequest) -> float:
    """Higher is better; 0 is a perfect fit."""
    score = 0.0
    dims = archetype.dimensions
    if request.size is not None:
        score -= 2.0 * _ratio_penalty(request.size[0], dims.width_m)
        score -= 2.0 * _ratio_penalty(request.size[1], dims.depth_m)
    if request.height is not None:
        score -= _ratio_penalty(request.height, dims.height_m)
    constraints = archetype.constraints
    if request.floors is not None:
        if constraints.min_floors is not None and request.floors < constraints.min_floors:
            score -= min(3.0, float(constraints.min_floors - request.floors))
        if constraints.max_floors is not None and request.floors > constraints.max_floors:
            score -= min(3.0, float(request.floors - constraints.max_floors))
    if _violates(request.roof, constraints.roofs):
        score -= 1.0
    if _violates(request.condition, constraints.conditions):
        score -= 3.0
    if _violates(request.surface, constraints.surfaces):
        score -= 3.0
    return score


def _violates(value: str | None, allowed: Sequence[str] | None) -> bool:
    """True when both are given and ``value`` is not allowed."""
    return value is not None and allowed is not None and value not in allowed
