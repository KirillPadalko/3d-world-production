"""LocationOverrides: explicit, targeted edits on top of a blueprint and recipe.

Overrides capture designer decisions that must survive regeneration:

* ``seed`` and ``recipe_patch`` adjust the recipe (RFC 7396 merge patch);
* ``feature_operations`` add, remove or patch blueprint features *before*
  generation;
* ``entity_operations`` remove or adjust generated entities by their stable ID
  *after* generation.

Operations are applied in document order.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from environment_generator.models.base import (
    Angle,
    ArchetypeId,
    ContractModel,
    Description,
    EntityId,
    Identifier,
    Metadata,
    Point3,
    PositiveFloat,
    Seed,
)
from environment_generator.models.blueprint import FeatureCollection


class RemoveFeature(ContractModel):
    op: Literal["remove"]
    collection: FeatureCollection
    id: Identifier


class PatchFeature(ContractModel):
    """Merge-patch (RFC 7396) one feature; the result is validated again."""

    op: Literal["patch"]
    collection: FeatureCollection
    id: Identifier
    patch: dict[str, Any] = Field(min_length=1)


class AddFeature(ContractModel):
    op: Literal["add"]
    collection: FeatureCollection
    feature: dict[str, Any] = Field(description="A complete feature of the target collection.")


FeatureOperation = Annotated[RemoveFeature | PatchFeature | AddFeature, Field(discriminator="op")]


class RemoveEntity(ContractModel):
    op: Literal["remove"]
    entity_id: EntityId


class SetArchetype(ContractModel):
    op: Literal["set_archetype"]
    entity_id: EntityId
    archetype_id: ArchetypeId
    variant: Annotated[int, Field(ge=0)] | None = None


class SetTransform(ContractModel):
    """Replace parts of an entity transform; omitted parts are kept."""

    op: Literal["set_transform"]
    entity_id: EntityId
    position: Point3 | None = None
    yaw_deg: Angle | None = None
    scale: tuple[PositiveFloat, PositiveFloat, PositiveFloat] | None = None


EntityOperation = Annotated[RemoveEntity | SetArchetype | SetTransform, Field(discriminator="op")]


class LocationOverrides(ContractModel):
    """Designer overrides for one blueprint (public contract v1.0)."""

    schema_version: Literal["1.0"]
    id: Identifier
    blueprint_id: Identifier = Field(description="Overrides only apply to this blueprint.")
    recipe_id: Identifier | None = Field(
        default=None, description="When set, overrides only apply together with this recipe."
    )
    description: Description | None = None
    strict: bool = Field(
        default=True,
        description="Fail when an entity operation targets an unknown entity (else warn).",
    )
    seed: Seed | None = None
    recipe_patch: dict[str, Any] = Field(default_factory=dict)
    feature_operations: list[FeatureOperation] = Field(default_factory=list, max_length=10_000)
    entity_operations: list[EntityOperation] = Field(default_factory=list, max_length=10_000)
    metadata: Metadata = Field(default_factory=dict)
