"""Placement overrides on generated entities.

Blueprint-level entity operations are applied before generation by
:mod:`environment_generator.blueprint.overrides`. Placement overrides refer to
*generated* entities (manifest IDs) and are written in the location frame;
they are converted to the generator frame here and applied after generation.
"""

from __future__ import annotations

from collections.abc import Sequence

from environment_generator.blueprint.diagnostics import Category, diagnostic
from environment_generator.core.errors import OverrideError
from environment_generator.core.frames import (
    location_scale_to_generator,
    location_to_generator,
    location_yaw_to_generator,
)
from environment_generator.core.issues import Severity, ValidationIssue
from environment_generator.models.assets import Dimensions
from environment_generator.models.overrides import ConflictPolicy, PlacementOverride
from environment_generator.models.scene import SceneEntity


def _scaled_dimensions(entity: SceneEntity, scale: tuple[float, float, float]) -> Dimensions:
    old = entity.transform.scale
    dims = entity.dimensions
    return Dimensions(
        width_m=dims.width_m / old[0] * scale[0] if old[0] else dims.width_m,
        depth_m=dims.depth_m / old[1] * scale[1] if old[1] else dims.depth_m,
        height_m=dims.height_m / old[2] * scale[2] if old[2] else dims.height_m,
    )


def apply_placement_overrides(
    entities: dict[str, SceneEntity],
    overrides: Sequence[PlacementOverride],
    *,
    overrides_id: str | None,
    policy: ConflictPolicy,
) -> list[ValidationIssue]:
    """Apply placement overrides in place; unknown targets follow ``policy``."""
    issues: list[ValidationIssue] = []
    for position, override in enumerate(overrides):
        where = f"{overrides_id}#placementOverrides[{position}]"
        entity = entities.get(override.entity_id)
        if entity is None:
            issue = diagnostic(
                Severity.WARNING if policy is ConflictPolicy.REPORT else Severity.ERROR,
                "OVERRIDE_TARGET_MISSING",
                f"Generated entity '{override.entity_id}' does not exist.",
                category=Category.OVERRIDE,
                path=where,
                entity_ids=[override.entity_id],
                suggestion="Check the manifest for the current entity IDs.",
            )
            if policy is ConflictPolicy.FAIL:
                raise OverrideError(f"{where}: {issue.message}", issues=[*issues, issue])
            issues.append(issue)
            continue
        transform = entity.transform
        new_position = (
            location_to_generator(override.position)
            if override.position is not None
            else transform.position
        )
        rotation = transform.rotation_deg
        if override.yaw_deg is not None:
            rotation = (rotation[0], rotation[1], location_yaw_to_generator(override.yaw_deg))
        scale = (
            location_scale_to_generator(override.scale)
            if override.scale is not None
            else transform.scale
        )
        provenance = entity.provenance.model_copy(
            update={"overrides": [*entity.provenance.overrides, where]}
        )
        entities[entity.id] = entity.model_copy(
            update={
                "transform": transform.model_copy(
                    update={"position": new_position, "rotation_deg": rotation, "scale": scale}
                ),
                "dimensions": _scaled_dimensions(entity, scale),
                "provenance": provenance,
            }
        )
    return issues
