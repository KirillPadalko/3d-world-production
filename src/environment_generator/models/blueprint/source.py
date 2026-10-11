"""Source provenance: media, extracted frames, analysis reports, calibration."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StringConstraints

from environment_generator.models.blueprint.common import (
    BlueprintModel,
    EntityId,
    FileReference,
    Label,
    Normalized,
    Position3,
    Provenance,
    RelativePath,
    Text,
    Vocabulary,
    sorted_keys,
)

ExternalIdKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")]
ExternalIds = Annotated[
    dict[ExternalIdKey, Annotated[str, StringConstraints(min_length=1, max_length=256)]],
    AfterValidator(sorted_keys),
]


class SourceType(StrEnum):
    MANUAL = "manual"
    VIDEO = "video"
    IMAGES = "images"
    SURVEY = "survey"
    SATELLITE = "satellite"
    MIXED = "mixed"
    SYNTHETIC = "synthetic"


class MediaKind(StrEnum):
    VIDEO = "video"
    IMAGE = "image"
    IMAGE_SEQUENCE = "image_sequence"
    POINT_CLOUD = "point_cloud"
    DOCUMENT = "document"
    OTHER = "other"


class ToolInfo(BlueprintModel):
    name: Label
    version: Annotated[str, StringConstraints(max_length=64)] | None = None


class SourceMedia(BlueprintModel):
    """A piece of source material (video, photo set, survey export)."""

    id: EntityId
    kind: MediaKind
    file: FileReference
    captured_at: datetime | None = None
    duration_s: Annotated[float, Field(ge=0.0)] | None = None
    description: Text | None = None
    external_ids: ExternalIds = Field(
        default_factory=dict, description="Identifiers in other systems (e.g. a capture ID)."
    )


class FrameExtraction(BlueprintModel):
    """How frames were extracted from a media item."""

    id: EntityId
    media_id: EntityId
    method: Literal["fixed_interval", "keyframes", "manual"]
    interval_s: Annotated[float, Field(gt=0.0)] | None = None
    frame_count: Annotated[int, Field(ge=0)] | None = None
    output_directory: RelativePath | None = None
    tool: ToolInfo | None = None


class Frame(BlueprintModel):
    """One extracted frame that entities may cite as evidence."""

    id: EntityId
    media_id: EntityId
    extraction_id: EntityId | None = None
    timestamp_s: Annotated[float, Field(ge=0.0)] | None = None
    file: FileReference | None = None


class AnalysisReport(BlueprintModel):
    id: EntityId
    file: FileReference
    tool: ToolInfo | None = None
    created_at: datetime | None = None


class Calibration(BlueprintModel):
    """How local coordinates were scaled and anchored to reality."""

    method: Literal["none", "manual_scale", "reference_points", "gps", "photogrammetry", "survey"]
    scale_confidence: Normalized | None = None
    estimated_error_m: Annotated[float, Field(ge=0.0)] | None = None
    reference_point_ids: list[EntityId] = Field(default_factory=list)
    notes: Text | None = None


class GeoPoint(BlueprintModel):
    latitude: Annotated[float, Field(ge=-90.0, le=90.0)]
    longitude: Annotated[float, Field(ge=-180.0, le=180.0)]


class ReferencePoint(BlueprintModel):
    """A point identified in both the source material and the local frame."""

    id: EntityId
    position: Position3
    description: Text | None = None
    geo: GeoPoint | None = None
    provenance: Provenance | None = None


class Observation(BlueprintModel):
    """A finding from analysis that entities can cite."""

    id: EntityId
    description: Text
    kind: Vocabulary | None = None
    frame_ids: list[EntityId] = Field(default_factory=list)
    report_id: EntityId | None = None
    confidence: Normalized | None = None


class Source(BlueprintModel):
    """Optional description of the material the blueprint was derived from."""

    type: SourceType
    description: Text | None = None
    media: list[SourceMedia] = Field(default_factory=list, max_length=1000)
    frame_extractions: list[FrameExtraction] = Field(default_factory=list, max_length=1000)
    frames: list[Frame] = Field(default_factory=list, max_length=100_000)
    analysis_reports: list[AnalysisReport] = Field(default_factory=list, max_length=1000)
    calibration: Calibration | None = None
    reference_points: list[ReferencePoint] = Field(default_factory=list, max_length=1000)
    observations: list[Observation] = Field(default_factory=list, max_length=100_000)
    external_ids: ExternalIds = Field(default_factory=dict)
