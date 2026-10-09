"""Applying LocationOverrides to recipes, blueprints and generated entities."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from environment_generator.assets.resolver import AssetResolver
from environment_generator.core.errors import ContractValidationError, OverrideError
from environment_generator.core.geometry import normalize_angle_deg
from environment_generator.core.issues import ValidationIssue
from environment_generator.core.patch import json_merge_patch
from environment_generator.models.assets import Dimensions
from environment_generator.models.blueprint import FeatureCollection, LocationBlueprint
from environment_generator.models.overrides import (
    AddFeature,
    EntityOperation,
    FeatureOperation,
    PatchFeature,
    RemoveEntity,
    RemoveFeature,
    SetArchetype,
    SetTransform,
)
from environment_generator.models.recipe import LocationRecipe
from environment_generator.models.scene import SceneEntity
from environment_generator.validation.contract import parse_document


def apply_recipe_patch(recipe: LocationRecipe, patch: dict[str, Any]) -> LocationRecipe:
    if not patch:
        return recipe
    patched = json_merge_patch(recipe.model_dump(mode="json"), patch)
    try:
        return parse_document(LocationRecipe, patched, "recipe(after overrides)")
    except ContractValidationError as exc:
        raise OverrideError("recipe_patch produces an invalid recipe", issues=exc.issues) from exc


def _index_of(items: list[dict[str, Any]], feature_id: str) -> int | None:
    for index, item in enumerate(items):
        if item.get("id") == feature_id:
            return index
    return None


def apply_feature_operations(
    blueprint: LocationBlueprint,
    operations: Sequence[FeatureOperation],
    overrides_id: str,
) -> tuple[LocationBlueprint, list[str]]:
    """Apply add/remove/patch operations in order; returns the new blueprint and a log."""
    if not operations:
        return blueprint, []
    data = blueprint.model_dump(mode="json")
    applied: list[str] = []
    for position, operation in enumerate(operations):
        where = f"{overrides_id}#feature_operations[{position}]"
        items: list[dict[str, Any]] = data[operation.collection.value]
        if isinstance(operation, AddFeature):
            feature_id = operation.feature.get("id")
            if not isinstance(feature_id, str):
                raise OverrideError(f"{where}: the added feature needs a string 'id'")
            if _index_of(items, feature_id) is not None:
                raise OverrideError(
                    f"{where}: {operation.collection.value}/{feature_id} already exists"
                )
            items.append(dict(operation.feature))
            applied.append(f"add {operation.collection.value}/{feature_id}")
            continue
        index = _index_of(items, operation.id)
        if index is None:
            raise OverrideError(
                f"{where}: {operation.collection.value}/{operation.id} does not exist"
            )
        if isinstance(operation, RemoveFeature):
            del items[index]
            applied.append(f"remove {operation.collection.value}/{operation.id}")
        elif isinstance(operation, PatchFeature):
            items[index] = json_merge_patch(items[index], operation.patch)
            applied.append(f"patch {operation.collection.value}/{operation.id}")
    try:
        return parse_document(LocationBlueprint, data, "blueprint(after overrides)"), applied
    except ContractValidationError as exc:
        raise OverrideError(
            "feature_operations produce an invalid blueprint", issues=exc.issues
        ) from exc


def drop_low_confidence(
    blueprint: LocationBlueprint, min_confidence: float
) -> tuple[LocationBlueprint, list[str]]:
    """Remove features whose confidence is below ``min_confidence``."""
    if min_confidence <= 0.0:
        return blueprint, []
    dropped: list[str] = []
    updates: dict[str, list[Any]] = {}
    for collection in FeatureCollection:
        kept = []
        for feature in blueprint.collection(collection):
            if feature.confidence < min_confidence:
                dropped.append(f"{collection.value}/{feature.id}")
            else:
                kept.append(feature)
        updates[collection.value] = kept
    if not dropped:
        return blueprint, []
    return blueprint.model_copy(update=updates), dropped


def _scaled_dimensions(entity: SceneEntity, scale: tuple[float, float, float]) -> Dimensions:
    old = entity.transform.scale
    dims = entity.dimensions
    return Dimensions(
        width_m=dims.width_m / old[0] * scale[0] if old[0] else dims.width_m,
        depth_m=dims.depth_m / old[1] * scale[1] if old[1] else dims.depth_m,
        height_m=dims.height_m / old[2] * scale[2] if old[2] else dims.height_m,
    )


def apply_entity_operations(
    entities: dict[str, SceneEntity],
    operations: Sequence[EntityOperation],
    *,
    overrides_id: str | None,
    strict: bool,
    assets: AssetResolver,
) -> list[ValidationIssue]:
    """Apply entity operations in place. Unknown targets fail when ``strict``."""
    issues: list[ValidationIssue] = []
    for position, operation in enumerate(operations):
        where = f"{overrides_id}#entity_operations[{position}]"
        entity = entities.get(operation.entity_id)
        if entity is None:
            message = f"{where}: entity '{operation.entity_id}' was not generated"
            if strict:
                raise OverrideError(message)
            issues.append(ValidationIssue.warning("OVERRIDE_UNKNOWN_ENTITY", message, where))
            continue
        provenance = entity.provenance.model_copy(
            update={"overrides": [*entity.provenance.overrides, where]}
        )
        if isinstance(operation, RemoveEntity):
            del entities[operation.entity_id]
            continue
        if isinstance(operation, SetArchetype):
            archetype = assets.get(operation.archetype_id)
            if archetype is None:
                raise OverrideError(
                    f"{where}: archetype '{operation.archetype_id}' is not in the palette"
                )
            if archetype.category is not entity.category:
                raise OverrideError(
                    f"{where}: archetype '{archetype.id}' is a {archetype.category.value}, "
                    f"entity is a {entity.category.value}"
                )
            variant = operation.variant if operation.variant is not None else 0
            if variant >= archetype.variants:
                raise OverrideError(
                    f"{where}: variant {variant} out of range for '{archetype.id}' "
                    f"({archetype.variants} variant(s))"
                )
            scale = entity.transform.scale
            dims = entity.dimensions
            if entity.geometry is None:
                nominal = archetype.dimensions
                dims = Dimensions(
                    width_m=nominal.width_m * scale[0],
                    depth_m=nominal.depth_m * scale[1],
                    height_m=nominal.height_m * scale[2],
                )
            entities[entity.id] = entity.model_copy(
                update={
                    "archetype_id": archetype.id,
                    "asset_ref": archetype.asset_ref,
                    "variant": variant,
                    "placeholder": False,
                    "dimensions": dims,
                    "provenance": provenance,
                }
            )
        elif isinstance(operation, SetTransform):
            transform = entity.transform
            position_value = (
                operation.position if operation.position is not None else transform.position
            )
            rotation = transform.rotation_deg
            if operation.yaw_deg is not None:
                rotation = (rotation[0], rotation[1], normalize_angle_deg(operation.yaw_deg))
            scale = operation.scale if operation.scale is not None else transform.scale
            entities[entity.id] = entity.model_copy(
                update={
                    "transform": transform.model_copy(
                        update={
                            "position": position_value,
                            "rotation_deg": rotation,
                            "scale": scale,
                        }
                    ),
                    "dimensions": _scaled_dimensions(entity, scale),
                    "provenance": provenance,
                }
            )
    return issues
