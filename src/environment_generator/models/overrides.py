"""LocationOverrides: explicit author changes, referenced by stable ID.

Two kinds of operations, applied in document order:

* ``entityOperations`` change the **blueprint** before generation: ``update``
  (JSON merge patch of an entity), ``replaceArchetype``, ``delete`` and
  ``add``. The source blueprint is never mutated; a new effective blueprint is
  produced.
* ``placementOverrides`` change **generated** entities (by manifest entity ID)
  after generation: position, yaw and scale.

Conflicts (missing target, unexpected type, duplicate ID, invalid result)
are never discarded silently: with ``conflictPolicy: "fail"`` (default) the
run stops; with ``"report"`` the operation is skipped and reported as a
warning in the generation report.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from environment_generator.models.base import (
    ContractModel,
    Description,
    EntityId,
    Identifier,
    Metadata,
    PositiveFloat,
)
from environment_generator.models.blueprint.common import (
    ArchetypeName,
    Position3,
    YawDeg,
)
from environment_generator.models.blueprint.common import (
    EntityId as BlueprintEntityId,
)


class EntityCollection(StrEnum):
    """Blueprint collections addressable by overrides (JSON key names)."""

    ROAD_NODES = "roadNodes"
    ROAD_SEGMENTS = "roadSegments"
    PLOTS = "plots"
    BUILDINGS = "buildings"
    VEGETATION_ZONES = "vegetationZones"
    TREES = "trees"
    FENCES = "fences"
    INFRASTRUCTURE = "infrastructure"
    PROPS = "props"
    LANDMARKS = "landmarks"
    WATER_BODIES = "waterBodies"
    SURFACE_ZONES = "surfaceZones"


class ConflictPolicy(StrEnum):
    FAIL = "fail"
    REPORT = "report"


class UpdateEntity(ContractModel):
    """RFC 7396 merge patch of one entity; ``id`` cannot change."""

    op: Literal["update"]
    id: BlueprintEntityId
    expected_type: EntityCollection | None = Field(
        default=None, description="Fail if the entity is no longer in this collection."
    )
    patch: dict[str, Any] = Field(min_length=1)


class ReplaceArchetype(ContractModel):
    op: Literal["replaceArchetype"]
    id: BlueprintEntityId
    expected_type: EntityCollection | None = None
    archetype: ArchetypeName


class DeleteEntity(ContractModel):
    op: Literal["delete"]
    id: BlueprintEntityId
    expected_type: EntityCollection | None = None


class AddEntity(ContractModel):
    op: Literal["add"]
    collection: EntityCollection
    entity: dict[str, Any] = Field(description="A complete entity of the target collection.")


EntityOperation = Annotated[
    UpdateEntity | ReplaceArchetype | DeleteEntity | AddEntity, Field(discriminator="op")
]


class PlacementOverride(ContractModel):
    """Move, turn or scale a generated entity (manifest frame and IDs)."""

    entity_id: EntityId = Field(description="Manifest entity ID, e.g. building.b-12.")
    position: Position3 | None = None
    yaw_deg: YawDeg | None = None
    scale: tuple[PositiveFloat, PositiveFloat, PositiveFloat] | None = None


class LocationOverrides(ContractModel):
    """Author changes for one location (public contract v1.0)."""

    schema_version: Literal["1.0"]
    id: Identifier
    location_id: BlueprintEntityId = Field(description="Overrides only apply to this location.")
    recipe_id: Identifier | None = Field(
        default=None, description="When set, overrides only apply together with this recipe."
    )
    description: Description | None = None
    author: Annotated[str, StringConstraints(max_length=200)] | None = None
    conflict_policy: ConflictPolicy = ConflictPolicy.FAIL
    entity_operations: list[EntityOperation] = Field(default_factory=list, max_length=10_000)
    placement_overrides: list[PlacementOverride] = Field(default_factory=list, max_length=10_000)
    metadata: Metadata = Field(default_factory=dict)
