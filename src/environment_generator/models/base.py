"""Shared model configuration and constrained types."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

#: Version of the public input contracts (blueprint, recipe, overrides, registry).
CONTRACT_VERSION = "1.0"


class ContractModel(BaseModel):
    """Strict, immutable base for every contract and stage model.

    Unknown fields are rejected so typos in hand-written documents surface as
    errors instead of being silently ignored; non-finite floats are rejected so
    outputs are always serialisable.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
TAG_PATTERN = r"^[a-z0-9][a-z0-9_:-]{0,47}$"
ENTITY_ID_PATTERN = r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*$"
ARCHETYPE_ID_PATTERN = r"^[a-z0-9_]+(\.[a-z0-9_]+)+$"

#: Feature and document identifiers. No dots: dots separate entity ID parts.
Identifier = Annotated[str, StringConstraints(pattern=IDENTIFIER_PATTERN)]
Tag = Annotated[str, StringConstraints(pattern=TAG_PATTERN)]
EntityId = Annotated[str, StringConstraints(pattern=ENTITY_ID_PATTERN, max_length=200)]
ArchetypeId = Annotated[str, StringConstraints(pattern=ARCHETYPE_ID_PATTERN, max_length=128)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(max_length=2000)]

Coordinate = Annotated[float, Field(ge=-100_000.0, le=100_000.0)]
Point2 = tuple[Coordinate, Coordinate]
Point3 = tuple[float, float, float]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
Angle = Annotated[float, Field(ge=-360.0, le=360.0)]
PositiveFloat = Annotated[float, Field(gt=0.0)]
Seed = Annotated[int, Field(ge=0, le=(1 << 63) - 1)]

MetadataValue = str | int | float | bool
Metadata = dict[Annotated[str, StringConstraints(min_length=1, max_length=64)], MetadataValue]
