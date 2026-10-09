"""Validation of the generated layout.

The validator recomputes footprints from the finished scene instead of
trusting what generators registered, so it independently checks any
generator implementation. Rules are small classes; pass a custom list to
:class:`RuleBasedLayoutValidator` to extend or replace them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from environment_generator.core.issues import ValidationIssue, sort_issues
from environment_generator.core.spatial import Footprint, SpatialIndex
from environment_generator.core.terrain import HeightSampler
from environment_generator.models.assets import AssetCategory
from environment_generator.models.recipe import LayoutValidationRecipe
from environment_generator.models.report import LayoutValidationResult
from environment_generator.models.scene import Scene, SceneEntity, entity_footprints

MAX_IDS_PER_ISSUE = 20
EXTENT_TOLERANCE_M = 0.5


@dataclass
class LayoutContext:
    scene: Scene
    settings: LayoutValidationRecipe
    known_archetypes: frozenset[str]
    terrain: HeightSampler | None
    footprints: dict[str, list[Footprint]] = field(default_factory=dict)
    index: SpatialIndex = field(default_factory=SpatialIndex)


class LayoutRule(ABC):
    """One layout check."""

    name: str

    @abstractmethod
    def check(self, context: LayoutContext) -> Iterable[ValidationIssue]: ...


class EnvironmentValidator(ABC):
    """Interface: validate a generated scene."""

    @abstractmethod
    def validate(
        self,
        scene: Scene,
        *,
        settings: LayoutValidationRecipe,
        known_archetypes: Iterable[str],
    ) -> LayoutValidationResult: ...


class UniqueIdsRule(LayoutRule):
    name = "unique_ids"

    def check(self, context: LayoutContext) -> Iterable[ValidationIssue]:
        counts = Counter(e.id for e in context.scene.entities)
        duplicates = sorted(i for i, n in counts.items() if n > 1)
        if duplicates:
            yield ValidationIssue.error(
                "LAYOUT_DUPLICATE_ID",
                f"{len(duplicates)} entity id(s) are not unique.",
                entity_ids=duplicates[:MAX_IDS_PER_ISSUE],
            )


class ExtentRule(LayoutRule):
    name = "within_extent"

    def check(self, context: LayoutContext) -> Iterable[ValidationIssue]:
        extent = context.scene.extent
        tol = EXTENT_TOLERANCE_M

        def inside(x: float, y: float) -> bool:
            return -tol <= x <= extent.width_m + tol and -tol <= y <= extent.depth_m + tol

        outside = [
            e.id
            for e in context.scene.entities
            if e.geometry is None and not inside(e.transform.position[0], e.transform.position[1])
        ]
        if outside:
            yield ValidationIssue.error(
                "LAYOUT_OUT_OF_BOUNDS",
                f"{len(outside)} entity position(s) lie outside the extent.",
                entity_ids=outside[:MAX_IDS_PER_ISSUE],
            )
        partial = [
            e.id
            for e in context.scene.entities
            if e.geometry is not None and not all(inside(p[0], p[1]) for p in e.geometry.points)
        ]
        if partial:
            yield ValidationIssue.warning(
                "LAYOUT_GEOMETRY_OUTSIDE_EXTENT",
                f"{len(partial)} entity geometry(ies) extend beyond the extent.",
                entity_ids=partial[:MAX_IDS_PER_ISSUE],
            )


class ArchetypeRule(LayoutRule):
    name = "known_archetypes"

    def check(self, context: LayoutContext) -> Iterable[ValidationIssue]:
        unknown = [
            e.id
            for e in context.scene.entities
            if not e.placeholder and e.archetype_id not in context.known_archetypes
        ]
        if unknown:
            yield ValidationIssue.error(
                "LAYOUT_UNKNOWN_ARCHETYPE",
                f"{len(unknown)} entity(ies) reference archetypes missing from the palette.",
                entity_ids=unknown[:MAX_IDS_PER_ISSUE],
            )
        placeholders = [e.id for e in context.scene.entities if e.placeholder]
        if placeholders:
            kinds = sorted({e.archetype_id for e in context.scene.entities if e.placeholder})
            yield ValidationIssue.warning(
                "LAYOUT_PLACEHOLDER_ASSETS",
                f"{len(placeholders)} entity(ies) use placeholder archetypes: {', '.join(kinds)}.",
                entity_ids=placeholders[:MAX_IDS_PER_ISSUE],
            )


class BuildingSpacingRule(LayoutRule):
    name = "building_spacing"

    def check(self, context: LayoutContext) -> Iterable[ValidationIssue]:
        spacing = context.settings.min_building_spacing_m
        buildings = [e for e in context.scene.entities if e.category is AssetCategory.BUILDING]
        index = SpatialIndex()
        for building in buildings:
            for footprint in context.footprints[building.id]:
                grown = footprint.inflated(spacing / 2.0)
                for other in index.query(grown):
                    yield ValidationIssue.error(
                        "LAYOUT_BUILDING_OVERLAP",
                        f"Buildings are closer than {spacing} m.",
                        entity_ids=[other.owner_id, building.id],
                    )
                index.insert(grown)


def _overlaps(context: LayoutContext, entity: SceneEntity, layer: AssetCategory) -> list[str]:
    hits: set[str] = set()
    for footprint in context.footprints[entity.id]:
        for other in context.index.query(footprint, layers={layer.value}, exclude_owner=entity.id):
            hits.add(other.owner_id)
    return sorted(hits)


class ObstructionRule(LayoutRule):
    """Solid objects on roads or in water; overlaps between solids and buildings."""

    name = "obstructions"

    _ERROR_ON_ROAD = frozenset(
        {AssetCategory.BUILDING, AssetCategory.INFRASTRUCTURE, AssetCategory.PROP}
    )
    _ERROR_IN_WATER = frozenset(
        {AssetCategory.BUILDING, AssetCategory.INFRASTRUCTURE, AssetCategory.PROP}
    )

    def check(self, context: LayoutContext) -> Iterable[ValidationIssue]:
        settings = context.settings
        for entity in context.scene.entities:
            category = entity.category
            if category in (AssetCategory.TERRAIN, AssetCategory.ROAD, AssetCategory.WATER):
                continue
            if settings.check_road_obstruction:
                roads = _overlaps(context, entity, AssetCategory.ROAD)
                if roads:
                    make = (
                        ValidationIssue.error
                        if category in self._ERROR_ON_ROAD
                        else ValidationIssue.warning
                    )
                    yield make(
                        "LAYOUT_ROAD_OBSTRUCTED",
                        f"{category.value} '{entity.id}' overlaps a road.",
                        entity_ids=[entity.id, *roads],
                    )
            if settings.check_water_obstruction:
                water = _overlaps(context, entity, AssetCategory.WATER)
                if water:
                    make = (
                        ValidationIssue.error
                        if category in self._ERROR_IN_WATER
                        else ValidationIssue.warning
                    )
                    yield make(
                        "LAYOUT_WATER_OBSTRUCTED",
                        f"{category.value} '{entity.id}' stands in water.",
                        entity_ids=[entity.id, *water],
                    )
            if category is not AssetCategory.BUILDING:
                buildings = _overlaps(context, entity, AssetCategory.BUILDING)
                if buildings:
                    yield ValidationIssue.warning(
                        "LAYOUT_SOLID_OVERLAP",
                        f"{category.value} '{entity.id}' intersects a building.",
                        entity_ids=[entity.id, *buildings],
                    )


class GroundContactRule(LayoutRule):
    name = "ground_contact"

    _GROUNDED = frozenset(
        {
            AssetCategory.BUILDING,
            AssetCategory.FENCE,
            AssetCategory.INFRASTRUCTURE,
            AssetCategory.VEGETATION,
            AssetCategory.PROP,
        }
    )

    def check(self, context: LayoutContext) -> Iterable[ValidationIssue]:
        if context.terrain is None:
            return
        tolerance = context.settings.ground_tolerance_m
        floating = []
        for entity in context.scene.entities:
            if entity.category not in self._GROUNDED or entity.geometry is not None:
                continue
            x, y, z = entity.transform.position
            if abs(z - context.terrain.height_at(x, y)) > tolerance:
                floating.append(entity.id)
        if floating:
            yield ValidationIssue.warning(
                "LAYOUT_GROUND_CONTACT",
                f"{len(floating)} entity(ies) are more than {tolerance} m off the terrain.",
                entity_ids=floating[:MAX_IDS_PER_ISSUE],
            )


class EntityBudgetRule(LayoutRule):
    name = "entity_budget"

    def check(self, context: LayoutContext) -> Iterable[ValidationIssue]:
        count = len(context.scene.entities)
        limit = context.settings.max_entities
        if count > limit:
            yield ValidationIssue.error(
                "LAYOUT_ENTITY_BUDGET", f"{count} entities exceed the budget of {limit}."
            )
        elif count > 0.9 * limit:
            yield ValidationIssue.warning(
                "LAYOUT_ENTITY_BUDGET", f"{count} entities are close to the budget of {limit}."
            )


def default_rules() -> list[LayoutRule]:
    return [
        UniqueIdsRule(),
        ExtentRule(),
        ArchetypeRule(),
        BuildingSpacingRule(),
        ObstructionRule(),
        GroundContactRule(),
        EntityBudgetRule(),
    ]


class RuleBasedLayoutValidator(EnvironmentValidator):
    def __init__(self, rules: Sequence[LayoutRule] | None = None) -> None:
        self._rules = list(rules) if rules is not None else default_rules()

    def validate(
        self,
        scene: Scene,
        *,
        settings: LayoutValidationRecipe,
        known_archetypes: Iterable[str],
    ) -> LayoutValidationResult:
        terrain = scene.terrain.to_heightfield() if scene.terrain is not None else None
        context = LayoutContext(
            scene=scene,
            settings=settings,
            known_archetypes=frozenset(known_archetypes),
            terrain=terrain,
        )
        for entity in scene.entities:
            footprints = entity_footprints(entity)
            context.footprints[entity.id] = footprints
            context.index.extend(footprints)
        issues: list[ValidationIssue] = []
        for rule in self._rules:
            issues.extend(rule.check(context))
        return LayoutValidationResult(
            issues=sort_issues(issues),
            rules=[rule.name for rule in self._rules],
            checked_entities=len(scene.entities),
        )
