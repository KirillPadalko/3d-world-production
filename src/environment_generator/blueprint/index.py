"""Document-wide index of every identified object in a blueprint.

All ``id`` values in a blueprint share one namespace: entities, road nodes and
segments, terrain zones, gameplay annotations and source items. ``previousIds``
of renamed entities are aliases that overrides may still use.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from pydantic import BaseModel

from environment_generator.models.blueprint import EntityBase, LocationBlueprint


@dataclass(frozen=True)
class IndexedObject:
    id: str
    kind: str
    """Collection name as written in JSON, e.g. ``buildings`` or ``roadNodes``."""
    path: str
    """Field path, e.g. ``roads.nodes[3]``."""
    item: BaseModel


def iter_identified(blueprint: LocationBlueprint) -> Iterator[IndexedObject]:
    """Every object with an ``id``, in document order."""

    def walk(kind: str, prefix: str, items: list[BaseModel]) -> Iterator[IndexedObject]:
        for i, item in enumerate(items):
            yield IndexedObject(getattr(item, "id"), kind, f"{prefix}[{i}]", item)  # noqa: B009

    yield from walk("roadNodes", "roads.nodes", list(blueprint.roads.nodes))
    yield from walk("roadSegments", "roads.segments", list(blueprint.roads.segments))
    terrain = blueprint.terrain
    yield from walk("terrainMasks", "terrain.masks", list(terrain.masks))
    yield from walk("surfaceZones", "terrain.surfaceZones", list(terrain.surface_zones))
    yield from walk("slopeZones", "terrain.slopeZones", list(terrain.slope_zones))
    yield from walk("waterBodies", "terrain.waterBodies", list(terrain.water_bodies))
    yield from walk("plots", "plots", list(blueprint.plots))
    yield from walk("buildings", "buildings", list(blueprint.buildings))
    yield from walk("vegetationZones", "vegetationZones", list(blueprint.vegetation_zones))
    yield from walk("trees", "trees", list(blueprint.trees))
    yield from walk("fences", "fences", list(blueprint.fences))
    yield from walk("infrastructure", "infrastructure", list(blueprint.infrastructure))
    yield from walk("props", "props", list(blueprint.props))
    yield from walk("landmarks", "landmarks", list(blueprint.landmarks))
    gameplay = blueprint.gameplay
    yield from walk("navigationAreas", "gameplay.navigationAreas", list(gameplay.navigation_areas))
    yield from walk("coverZones", "gameplay.coverZones", list(gameplay.cover_zones))
    yield from walk("combatZones", "gameplay.combatZones", list(gameplay.combat_zones))
    yield from walk("spawnClearances", "gameplay.spawnClearances", list(gameplay.spawn_clearances))
    yield from walk("lineOfSight", "gameplay.lineOfSight", list(gameplay.line_of_sight))
    source = blueprint.source
    if source is not None:
        yield from walk("sourceMedia", "source.media", list(source.media))
        yield from walk(
            "frameExtractions", "source.frameExtractions", list(source.frame_extractions)
        )
        yield from walk("frames", "source.frames", list(source.frames))
        yield from walk("analysisReports", "source.analysisReports", list(source.analysis_reports))
        yield from walk("referencePoints", "source.referencePoints", list(source.reference_points))
        yield from walk("observations", "source.observations", list(source.observations))


@dataclass
class EntityIndex:
    objects: dict[str, IndexedObject] = field(default_factory=dict)
    duplicates: list[tuple[IndexedObject, IndexedObject]] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)
    """previous ID -> current ID."""
    alias_conflicts: list[tuple[str, str]] = field(default_factory=list)
    """(previous ID, entity ID) pairs that collide with an existing ID or alias."""

    @classmethod
    def build(cls, blueprint: LocationBlueprint) -> EntityIndex:
        index = cls()
        for obj in iter_identified(blueprint):
            existing = index.objects.get(obj.id)
            if existing is not None:
                index.duplicates.append((existing, obj))
                continue
            index.objects[obj.id] = obj
        for obj in index.objects.values():
            if not isinstance(obj.item, EntityBase):
                continue
            for previous in obj.item.previous_ids:
                if previous in index.objects or previous in index.aliases:
                    index.alias_conflicts.append((previous, obj.id))
                else:
                    index.aliases[previous] = obj.id
        return index

    def get(self, object_id: str) -> IndexedObject | None:
        return self.objects.get(object_id)

    def resolve(self, object_id: str) -> tuple[IndexedObject | None, bool]:
        """Look up by current ID, then by previous ID. Returns (object, via_alias)."""
        found = self.objects.get(object_id)
        if found is not None:
            return found, False
        current = self.aliases.get(object_id)
        if current is not None:
            return self.objects.get(current), True
        return None, False
