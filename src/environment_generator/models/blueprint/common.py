"""Shared types of the LocationBlueprint contract.

Spatial convention (see docs/LOCATION_BLUEPRINT.md): metres; +X east, +Y up,
+Z north (a left-handed frame, like Unity); origin at the south-west corner of
the horizontal bounds; yaw in degrees clockwise from north (+Z) around +Y.
Horizontal geometry is written as ``[x, z]`` pairs; full positions as
``[x, y, z]``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, TypeVar

from pydantic import AfterValidator, Field, JsonValue, StringConstraints

from environment_generator.models.base import ContractModel

K = TypeVar("K", bound=str)
V = TypeVar("V")

#: Schema version written by this implementation.
BLUEPRINT_SCHEMA_VERSION = "1.0"

#: Stable entity IDs: lower-case ASCII, digits, ``-`` and ``_``; no dots, no spaces.
ENTITY_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
#: Archetype names: ``wooden_house_medium`` or dotted registry IDs.
ARCHETYPE_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$"
#: Open vocabulary values (species, gameplay roles, methods): snake_case words.
VOCABULARY_PATTERN = r"^[a-z][a-z0-9_]{0,47}$"
#: Extension keys must be prefixed with ``x-`` (e.g. ``x-studio.road-ruts``).
EXTENSION_KEY_PATTERN = r"^x-[a-z0-9][a-z0-9_.-]{0,63}$"
#: Relative POSIX path inside the location package: no leading ``/``, drive
#: letter, backslash, URL scheme, empty, ``.`` or ``..`` segment.
RELATIVE_PATH_PATTERN = (
    r"^(?!/)(?![A-Za-z]:)(?!.*\\)(?!.*://)(?!.*//)"
    r"(?!(?:.*/)?\.{1,2}(?:/|$))[^\x00-\x1f]{1,1024}$"
)
SHA256_PATTERN = r"^[0-9a-f]{64}$"
HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"

EntityId = Annotated[str, StringConstraints(pattern=ENTITY_ID_PATTERN)]
ArchetypeName = Annotated[str, StringConstraints(pattern=ARCHETYPE_PATTERN, max_length=128)]
Vocabulary = Annotated[str, StringConstraints(pattern=VOCABULARY_PATTERN)]
Tag = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_:-]{0,47}$")]
RelativePath = Annotated[str, StringConstraints(pattern=RELATIVE_PATH_PATTERN)]
Text = Annotated[str, StringConstraints(max_length=2000)]
Label = Annotated[str, StringConstraints(min_length=1, max_length=200)]

#: Horizontal coordinate in metres (generous bounds; the semantic validator
#: checks against the declared horizontal bounds).
Coordinate = Annotated[float, Field(ge=-100_000.0, le=100_000.0)]
Elevation = Annotated[float, Field(ge=-1000.0, le=9000.0)]
#: ``[x, z]``.
PointXZ = tuple[Coordinate, Coordinate]
#: ``[x, y, z]`` with ``y`` the elevation.
Position3 = tuple[Coordinate, Elevation, Coordinate]
#: Polygon ring as ``[x, z]`` points; implicitly closed, first point not repeated.
Polygon = Annotated[list[PointXZ], Field(min_length=3, max_length=10_000)]
#: Open path as ``[x, z]`` points.
Polyline = Annotated[list[PointXZ], Field(min_length=2, max_length=10_000)]
Normalized = Annotated[float, Field(ge=0.0, le=1.0)]
YawDeg = Annotated[float, Field(ge=0.0, lt=360.0)]
PositiveMetres = Annotated[float, Field(gt=0.0, le=10_000.0)]
Seed = Annotated[int, Field(ge=0, le=(1 << 63) - 1)]


def sorted_json(value: JsonValue) -> JsonValue:
    """JSON value with object keys sorted recursively (array order is kept)."""
    if isinstance(value, dict):
        return {key: sorted_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [sorted_json(item) for item in value]
    return value


def sorted_keys(value: dict[K, V]) -> dict[K, V]:
    """Map with keys in sorted order, so serialization never depends on input order."""
    return {key: value[key] for key in sorted(value)}


#: Namespaced extension data; consumers must ignore keys they do not understand.
#: Object keys are sorted on load (JSON objects are unordered).
Extensions = Annotated[
    dict[Annotated[str, StringConstraints(pattern=EXTENSION_KEY_PATTERN)], JsonValue],
    AfterValidator(sorted_json),
]


class BlueprintModel(ContractModel):
    """Base of every LocationBlueprint model (camelCase JSON, strict, immutable)."""


class ProvenanceCategory(StrEnum):
    """How a value came to be."""

    OBSERVED = "observed"
    """Measured or detected directly in source material (footage, survey)."""
    INFERRED = "inferred"
    """Estimated from indirect evidence (e.g. a fence line hidden by trees)."""
    MANUAL = "manual"
    """Authored or corrected by a person without a measurement claim."""
    PROCEDURAL = "procedural"
    """Added by a generator or tool, not observed."""


class Provenance(BlueprintModel):
    """Where an entity's data came from and how much it can be trusted.

    Optional everywhere: an entity without provenance is a manual authoring
    decision with no measurement claim.
    """

    category: ProvenanceCategory
    confidence: Normalized | None = Field(
        default=None,
        description="0 = guess, 1 = certain. Expected for observed and inferred values.",
    )
    method: Vocabulary | None = Field(
        default=None, description="e.g. photogrammetry, visual_estimate, survey, gps."
    )
    position_accuracy_m: Annotated[float, Field(ge=0.0, le=10_000.0)] | None = Field(
        default=None, description="Estimated horizontal position error (1 sigma), metres."
    )
    frame_ids: list[EntityId] = Field(
        default_factory=list, description="source.frames this entity was seen in."
    )
    observation_ids: list[EntityId] = Field(
        default_factory=list, description="source.observations supporting this entity."
    )
    notes: Text | None = None


class FileReference(BlueprintModel):
    """An external file inside the location package (never embedded data)."""

    path: RelativePath = Field(
        description="POSIX path relative to the location package root (the blueprint's folder)."
    )
    media_type: Annotated[str, StringConstraints(pattern=r"^[a-z]+/[a-z0-9.+-]+$")] | None = None
    sha256: Annotated[str, StringConstraints(pattern=SHA256_PATTERN)] | None = Field(
        default=None, description="Lower-case hex digest; verified when present."
    )
    size_bytes: Annotated[int, Field(ge=0)] | None = None


class Transform(BlueprintModel):
    """Placement of a point entity in the location frame."""

    position: Position3 = Field(description="[x, y, z] in metres; y is the elevation.")
    yaw_deg: YawDeg = Field(
        default=0.0, description="Heading of the entity's front (+Z local), clockwise from north."
    )
    snap_to_terrain: bool = Field(
        default=True,
        description="Consumers place the entity on the terrain surface; y is then advisory.",
    )


class EntityBase(BlueprintModel):
    """Fields shared by every identified entity."""

    id: EntityId
    label: Label | None = Field(default=None, description="Human-readable name; never a key.")
    tags: list[Tag] = Field(default_factory=list, max_length=32)
    previous_ids: list[EntityId] = Field(
        default_factory=list,
        description="Former IDs of this entity (renames); overrides that use them still resolve.",
    )
    provenance: Provenance | None = None
    extensions: Extensions = Field(default_factory=dict)


class CoverLevel(StrEnum):
    NONE = "none"
    PARTIAL = "partial"
    FULL = "full"


class MovementEffect(StrEnum):
    NONE = "none"
    SLOW = "slow"
    BLOCK = "block"


class GameplayHints(BlueprintModel):
    """Per-entity gameplay intent. ``null`` means "resolve downstream"."""

    movement: MovementEffect | None = None
    projectile_cover: CoverLevel | None = None
    vision: CoverLevel | None = Field(default=None, description="Visual occlusion.")


class HeightRange(BlueprintModel):
    min_m: Annotated[float, Field(ge=0.0, le=200.0)]
    max_m: Annotated[float, Field(ge=0.0, le=200.0)]
