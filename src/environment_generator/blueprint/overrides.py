"""Applying LocationOverrides entity operations to a blueprint.

The source blueprint is never mutated: operations run on a JSON copy and the
result is validated again as a complete blueprint. Conflict handling:

* ``conflictPolicy: fail`` (default) - the first conflict raises
  :class:`OverrideError` carrying every diagnostic so far;
* ``conflictPolicy: report`` - the operation is skipped, a warning is
  recorded and the operation is listed in ``unresolved``.

Either way no override is discarded silently. An invalid *result* (for
example a deleted building still referenced by a landmark) always fails.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from environment_generator.blueprint.diagnostics import Category, diagnostic
from environment_generator.blueprint.validation import validate_document
from environment_generator.core.errors import OverrideError
from environment_generator.core.issues import Severity, ValidationIssue
from environment_generator.core.patch import json_merge_patch
from environment_generator.models.blueprint import LocationBlueprint
from environment_generator.models.overrides import (
    AddEntity,
    ConflictPolicy,
    DeleteEntity,
    EntityCollection,
    EntityOperation,
    LocationOverrides,
    ReplaceArchetype,
    UpdateEntity,
)

#: Where each collection lives in the JSON document.
COLLECTION_PATHS: dict[EntityCollection, tuple[str, ...]] = {
    EntityCollection.ROAD_NODES: ("roads", "nodes"),
    EntityCollection.ROAD_SEGMENTS: ("roads", "segments"),
    EntityCollection.PLOTS: ("plots",),
    EntityCollection.BUILDINGS: ("buildings",),
    EntityCollection.VEGETATION_ZONES: ("vegetationZones",),
    EntityCollection.TREES: ("trees",),
    EntityCollection.FENCES: ("fences",),
    EntityCollection.INFRASTRUCTURE: ("infrastructure",),
    EntityCollection.PROPS: ("props",),
    EntityCollection.LANDMARKS: ("landmarks",),
    EntityCollection.WATER_BODIES: ("terrain", "waterBodies"),
    EntityCollection.SURFACE_ZONES: ("terrain", "surfaceZones"),
}

#: Collections whose entities carry an ``archetype``.
ARCHETYPE_COLLECTIONS = frozenset(
    {
        EntityCollection.BUILDINGS,
        EntityCollection.TREES,
        EntityCollection.FENCES,
        EntityCollection.INFRASTRUCTURE,
        EntityCollection.PROPS,
    }
)


@dataclass(frozen=True)
class OverrideOutcome:
    blueprint: LocationBlueprint
    applied: tuple[str, ...]
    unresolved: tuple[str, ...]
    issues: tuple[ValidationIssue, ...]
    #: Entity ID -> references (``<overridesId>#entityOperations[i]``) of the
    #: operations that changed or added it; generated entities inherit them.
    trace: dict[str, tuple[str, ...]] = field(default_factory=dict)


class _ConflictError(Exception):
    def __init__(self, code: str, message: str, entity_id: str | None, suggestion: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.entity_id = entity_id
        self.suggestion = suggestion


def _container(data: dict[str, Any], collection: EntityCollection) -> list[dict[str, Any]]:
    node: Any = data
    keys = COLLECTION_PATHS[collection]
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    items = node.setdefault(keys[-1], [])
    assert isinstance(items, list)
    return items


def _iter_entities(
    data: dict[str, Any],
) -> Iterator[tuple[EntityCollection, list[dict[str, Any]], int]]:
    for collection in EntityCollection:
        items = _container(data, collection)
        for index in range(len(items)):
            yield collection, items, index


@dataclass
class _Found:
    collection: EntityCollection
    items: list[dict[str, Any]]
    index: int
    renamed: bool

    @property
    def entity(self) -> dict[str, Any]:
        return self.items[self.index]


def _find(data: dict[str, Any], target_id: str) -> _Found | None:
    for collection, items, index in _iter_entities(data):
        if items[index].get("id") == target_id:
            return _Found(collection, items, index, False)
    for collection, items, index in _iter_entities(data):
        if target_id in items[index].get("previousIds", []):
            return _Found(collection, items, index, True)
    return None


def _target(data: dict[str, Any], op: UpdateEntity | ReplaceArchetype | DeleteEntity) -> _Found:
    found = _find(data, op.id)
    if found is None:
        raise _ConflictError(
            "OVERRIDE_TARGET_MISSING",
            f"Entity '{op.id}' does not exist in the blueprint.",
            op.id,
            "Fix the ID, or remove the operation if the entity was deleted on purpose.",
        )
    if op.expected_type is not None and found.collection is not op.expected_type:
        raise _ConflictError(
            "OVERRIDE_TYPE_MISMATCH",
            f"Entity '{op.id}' is now in {found.collection.value}, "
            f"the override expects {op.expected_type.value}.",
            op.id,
            "Review the override: the entity's type changed since it was written.",
        )
    return found


def _apply(
    data: dict[str, Any], op: EntityOperation, notes: list[ValidationIssue], where: str
) -> tuple[str, str]:
    """Apply one operation; returns ``(log entry, affected entity ID)``."""
    if isinstance(op, AddEntity):
        entity_id = op.entity.get("id")
        if not isinstance(entity_id, str):
            raise _ConflictError(
                "OVERRIDE_ADD_WITHOUT_ID",
                "The added entity has no string 'id'.",
                None,
                "Give the new entity a stable ID.",
            )
        if _find(data, entity_id) is not None:
            raise _ConflictError(
                "OVERRIDE_ID_CONFLICT",
                f"ID '{entity_id}' already exists (or is a former ID).",
                entity_id,
                "Choose an ID that was never used in this location.",
            )
        _container(data, op.collection).append(dict(op.entity))
        return f"add {op.collection.value}/{entity_id}", entity_id

    found = _target(data, op)
    entity_id = str(found.entity["id"])
    if found.renamed:
        notes.append(
            diagnostic(
                "info",
                "OVERRIDE_TARGET_RENAMED",
                f"'{op.id}' resolved through previousIds to '{entity_id}'.",
                category=Category.OVERRIDE,
                path=where,
                entity_ids=[entity_id],
                suggestion=f"Update the override to reference '{entity_id}'.",
            )
        )
    ref = f"{found.collection.value}/{entity_id}"
    if isinstance(op, DeleteEntity):
        del found.items[found.index]
        return f"delete {ref}", entity_id
    if isinstance(op, ReplaceArchetype):
        is_wire = found.entity.get("infrastructureType") == "wire"
        if found.collection not in ARCHETYPE_COLLECTIONS or is_wire:
            raise _ConflictError(
                "OVERRIDE_NO_ARCHETYPE",
                f"{ref} has no archetype to replace.",
                entity_id,
                "Use 'update' to change other fields.",
            )
        found.items[found.index] = {**found.entity, "archetype": op.archetype}
        return f"replaceArchetype {ref} -> {op.archetype}", entity_id
    if "id" in op.patch and op.patch["id"] != entity_id:
        raise _ConflictError(
            "OVERRIDE_ID_CHANGE",
            "An update cannot change an entity ID.",
            entity_id,
            "Delete and re-add the entity, keeping the old ID in previousIds.",
        )
    found.items[found.index] = json_merge_patch(found.entity, op.patch)
    return f"update {ref}", entity_id


def apply_entity_operations(
    blueprint: LocationBlueprint,
    overrides: LocationOverrides,
    *,
    package_root: Path | None = None,
) -> OverrideOutcome:
    """Return a new blueprint with the operations applied."""
    if overrides.location_id != blueprint.location_id:
        raise OverrideError(
            f"Overrides '{overrides.id}' target location '{overrides.location_id}', "
            f"not '{blueprint.location_id}'.",
            issues=[
                diagnostic(
                    "error",
                    "OVERRIDE_LOCATION_MISMATCH",
                    "The overrides belong to a different location.",
                    category=Category.OVERRIDE,
                    path="locationId",
                    suggestion="Use overrides written for this locationId.",
                )
            ],
        )
    data = blueprint.model_dump(mode="json", by_alias=True)
    applied: list[str] = []
    unresolved: list[str] = []
    notes: list[ValidationIssue] = []
    trace: dict[str, list[str]] = {}
    report = overrides.conflict_policy is ConflictPolicy.REPORT
    for i, op in enumerate(overrides.entity_operations):
        where = f"{overrides.id}#entityOperations[{i}]"
        try:
            entry, entity_id = _apply(data, op, notes, where)
            applied.append(entry)
            trace.setdefault(entity_id, []).append(where)
        except _ConflictError as conflict:
            issue = diagnostic(
                Severity.WARNING if report else Severity.ERROR,
                conflict.code,
                conflict.message,
                category=Category.OVERRIDE,
                path=where,
                entity_ids=[conflict.entity_id] if conflict.entity_id else [],
                suggestion=conflict.suggestion,
            )
            notes.append(issue)
            if not report:
                raise OverrideError(f"{where}: {conflict.message}", issues=notes) from None
            unresolved.append(f"{where}: {conflict.message}")
    if not overrides.entity_operations:
        return OverrideOutcome(blueprint, (), (), ())
    result = validate_document(data, package_root=package_root, check_external=False)
    if result.blueprint is None or not result.valid:
        errors = [i for i in result.issues if i.severity is Severity.ERROR]
        raise OverrideError(
            f"Overrides '{overrides.id}' produce an invalid blueprint ({len(errors)} error(s)).",
            issues=[*notes, *errors],
        )
    return OverrideOutcome(
        result.blueprint,
        tuple(applied),
        tuple(unresolved),
        tuple(notes),
        {k: tuple(v) for k, v in sorted(trace.items())},
    )
