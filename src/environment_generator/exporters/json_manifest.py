"""Portable JSON scene manifest (``scene-manifest.json``).

The internal :class:`Scene` uses the generator frame; the manifest uses the
location frame shared with LocationBlueprint (see :mod:`core.frames`). Every
spatial value is converted here, in one place.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from environment_generator import GENERATOR_NAME, __version__
from environment_generator.core.errors import ExportError
from environment_generator.core.frames import (
    generator_scale_to_location,
    generator_to_location,
    generator_yaw_to_location,
)
from environment_generator.core.hashing import fingerprint, pretty_json
from environment_generator.exporters.base import ExportResult, SceneExporter
from environment_generator.models.pipeline import GenerationPlan
from environment_generator.models.scene import (
    AtmosphereSettings,
    EntityPolygon,
    EntityPolyline,
    GeneratorInfo,
    ManifestEntity,
    ManifestSource,
    ManifestStatistics,
    ManifestTransform,
    Scene,
    SceneEntity,
    SceneManifest,
)
from environment_generator.validation.contract import load_document

MANIFEST_FILENAME = "scene-manifest.json"


def manifest_content_hash(manifest_data: dict[str, Any]) -> str:
    """Hash of a manifest's JSON data, ignoring its ``contentHash`` field."""
    body = {k: v for k, v in manifest_data.items() if k != "contentHash"}
    return fingerprint(body)


def verify_manifest(manifest: SceneManifest) -> bool:
    """True when the stored content hash matches the manifest content."""
    return manifest_content_hash(manifest.model_dump(mode="json")) == manifest.content_hash


def load_manifest(path: Path | str) -> SceneManifest:
    return load_document(SceneManifest, path, "manifest")


def manifest_entity(entity: SceneEntity) -> ManifestEntity:
    """Convert a generated entity to the location frame."""
    transform = entity.transform
    pitch, roll, yaw = transform.rotation_deg
    if pitch != 0.0 or roll != 0.0:
        # Generators only rotate around the vertical axis; refuse rather than guess.
        raise ExportError(
            f"Entity '{entity.id}' has a non-yaw rotation {transform.rotation_deg}; "
            "only yaw rotations can be exported"
        )
    geometry = entity.geometry
    if isinstance(geometry, EntityPolyline | EntityPolygon):
        geometry = geometry.model_copy(
            update={"points": [generator_to_location(p) for p in geometry.points]}
        )
    data = entity.model_dump(exclude={"transform", "geometry"})
    return ManifestEntity(
        **data,
        transform=ManifestTransform(
            position=generator_to_location(transform.position),
            rotation_deg=(0.0, generator_yaw_to_location(yaw), 0.0),
            scale=generator_scale_to_location(transform.scale),
        ),
        geometry=geometry,
    )


def manifest_atmosphere(atmosphere: AtmosphereSettings) -> AtmosphereSettings:
    """Atmosphere with its light direction vector in the location frame."""
    return atmosphere.model_copy(
        update={"key_light_direction": generator_to_location(atmosphere.key_light_direction)}
    )


def build_manifest(scene: Scene, plan: GenerationPlan) -> SceneManifest:
    entities = [manifest_entity(e) for e in sorted(scene.entities, key=lambda e: e.id)]
    by_category = Counter(e.category.value for e in entities)
    by_generator = Counter(e.provenance.generator.value for e in entities)
    data: dict[str, Any] = {
        "manifest_version": "1.0",
        "generator": GeneratorInfo(name=GENERATOR_NAME, version=__version__).model_dump(
            mode="json"
        ),
        "source": ManifestSource(
            location_id=plan.location_id,
            location_name=plan.location_name,
            recipe_id=plan.recipe.id,
            overrides_id=plan.overrides_id,
            registry_id=plan.palette.registry_id,
            seed=plan.seed,
            generator_seeds={task.generator.value: task.seed for task in plan.tasks},
            controls=plan.controls,
            input_fingerprint=plan.input_fingerprint,
        ).model_dump(mode="json"),
        "extent": scene.extent.model_dump(mode="json"),
        "terrain": scene.terrain.model_dump(mode="json") if scene.terrain else None,
        "atmosphere": (
            manifest_atmosphere(scene.atmosphere).model_dump(mode="json")
            if scene.atmosphere
            else None
        ),
        "entities": [e.model_dump(mode="json") for e in entities],
        "annotations": plan.annotations.model_dump(mode="json"),
        "statistics": ManifestStatistics(
            entity_count=len(entities),
            by_category=dict(sorted(by_category.items())),
            by_generator=dict(sorted(by_generator.items())),
            placeholder_count=sum(1 for e in entities if e.placeholder),
        ).model_dump(mode="json"),
    }
    # Validate first so the hash is computed over the exact serialised form.
    data["content_hash"] = "sha256:pending"
    manifest = SceneManifest.model_validate(data)
    dumped = manifest.model_dump(mode="json")
    return manifest.model_copy(update={"content_hash": manifest_content_hash(dumped)})


class JsonManifestExporter(SceneExporter):
    """Writes the manifest as diff-friendly JSON with floats rounded to 0.1 mm."""

    def __init__(self, filename: str = MANIFEST_FILENAME) -> None:
        self.filename = filename

    def export(self, scene: Scene, plan: GenerationPlan, destination: Path | None) -> ExportResult:
        manifest = build_manifest(scene, plan)
        if destination is None:
            return ExportResult(manifest, None)
        path = destination / self.filename
        try:
            destination.mkdir(parents=True, exist_ok=True)
            path.write_text(pretty_json(manifest.model_dump(mode="json")), encoding="utf-8")
        except OSError as exc:
            raise ExportError(f"Cannot write manifest to '{path}': {exc}") from exc
        return ExportResult(manifest, path)
