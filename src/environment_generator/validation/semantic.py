"""Semantic checks on recipes, registries and their fit to a blueprint.

Blueprint checks live in :mod:`environment_generator.blueprint.validation`.
"""

from __future__ import annotations

import fnmatch

from environment_generator.core.issues import ValidationIssue
from environment_generator.models.assets import AssetRegistryDocument
from environment_generator.models.blueprint import LocationBlueprint
from environment_generator.models.overrides import LocationOverrides
from environment_generator.models.recipe import GeneratorName, LocationRecipe


def validate_recipe(recipe: LocationRecipe) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not any(recipe.generator_enabled(name) for name in GeneratorName):
        issues.append(
            ValidationIssue.warning(
                "RECIPE_NOTHING_ENABLED",
                "Every generator is disabled; the scene will be empty.",
                "recipe",
            )
        )
    return issues


def validate_registry(registry: AssetRegistryDocument) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for archetype in registry.archetypes:
        location = f"registry:{archetype.id}"
        if archetype.id in seen:
            issues.append(
                ValidationIssue.error(
                    "REGISTRY_DUPLICATE_ARCHETYPE",
                    f"Duplicate archetype id '{archetype.id}'.",
                    location,
                )
            )
        seen.add(archetype.id)
        if archetype.id.startswith("placeholder."):
            issues.append(
                ValidationIssue.error(
                    "REGISTRY_RESERVED_ID", "The 'placeholder.' prefix is reserved.", location
                )
            )
        constraints = archetype.constraints
        if (
            constraints.min_floors is not None
            and constraints.max_floors is not None
            and constraints.min_floors > constraints.max_floors
        ):
            issues.append(
                ValidationIssue.error(
                    "REGISTRY_INVALID_CONSTRAINTS",
                    "minFloors is greater than maxFloors.",
                    location,
                )
            )
    return issues


def validate_compatibility(
    blueprint: LocationBlueprint, recipe: LocationRecipe, overrides: LocationOverrides | None
) -> list[ValidationIssue]:
    """Check that the recipe and overrides are meant for this location."""
    issues: list[ValidationIssue] = []
    location_id = blueprint.location_id
    if recipe.applies_to and not any(
        fnmatch.fnmatchcase(location_id, pattern) for pattern in recipe.applies_to
    ):
        issues.append(
            ValidationIssue.error(
                "RECIPE_NOT_APPLICABLE",
                f"Recipe '{recipe.id}' applies to {recipe.applies_to}, not '{location_id}'.",
                "recipe.appliesTo",
                suggestion="Use a recipe meant for this location or widen appliesTo.",
            )
        )
    if overrides is not None:
        if overrides.location_id != location_id:
            issues.append(
                ValidationIssue.error(
                    "OVERRIDES_LOCATION_MISMATCH",
                    f"Overrides target location '{overrides.location_id}', got '{location_id}'.",
                    "overrides.locationId",
                    suggestion="Overrides are written for exactly one location.",
                )
            )
        if overrides.recipe_id is not None and overrides.recipe_id != recipe.id:
            issues.append(
                ValidationIssue.error(
                    "OVERRIDES_RECIPE_MISMATCH",
                    f"Overrides target recipe '{overrides.recipe_id}', got '{recipe.id}'.",
                    "overrides.recipeId",
                )
            )
    return issues
