"""Semantic checks that go beyond what the JSON Schema contracts can express."""

from __future__ import annotations

import fnmatch
from collections.abc import Sequence

from environment_generator.core.geometry import (
    Vec2,
    bounds_of,
    bounds_overlap,
    polygon_area,
    polygon_is_simple,
    polyline_length,
    rectangle_corners,
)
from environment_generator.core.issues import ValidationIssue
from environment_generator.core.spatial import Footprint, SpatialIndex
from environment_generator.models.assets import AssetRegistryDocument
from environment_generator.models.blueprint import (
    FeatureCollection,
    LocationBlueprint,
)
from environment_generator.models.geometry import (
    PointGeometry,
    PolygonGeometry,
    PolylineGeometry,
    RectangleGeometry,
    area_outline,
    geometry_points,
)
from environment_generator.models.overrides import LocationOverrides
from environment_generator.models.recipe import GeneratorName, LocationRecipe

#: Points may lie this far outside the extent before they count as outside.
EXTENT_TOLERANCE_M = 0.5
MIN_POLYGON_AREA_M2 = 0.5
MIN_POLYLINE_LENGTH_M = 0.5
LOW_CONFIDENCE = 0.3
MIN_BUILDING_SIDE_M = 1.5

Geometry = PointGeometry | PolylineGeometry | PolygonGeometry | RectangleGeometry


def _check_geometry(location: str, geometry: Geometry) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if isinstance(geometry, PolygonGeometry):
        outline = area_outline(geometry)
        if not polygon_is_simple(outline):
            issues.append(
                ValidationIssue.error(
                    "BLUEPRINT_INVALID_POLYGON", "Polygon edges cross or overlap.", location
                )
            )
        elif polygon_area(outline) < MIN_POLYGON_AREA_M2:
            issues.append(
                ValidationIssue.error(
                    "BLUEPRINT_DEGENERATE_POLYGON",
                    f"Polygon area is below {MIN_POLYGON_AREA_M2} m^2.",
                    location,
                )
            )
    elif isinstance(geometry, PolylineGeometry):
        if polyline_length(geometry.points) < MIN_POLYLINE_LENGTH_M:
            issues.append(
                ValidationIssue.error(
                    "BLUEPRINT_DEGENERATE_POLYLINE",
                    f"Polyline is shorter than {MIN_POLYLINE_LENGTH_M} m.",
                    location,
                )
            )
    return issues


def _check_extent(
    location: str, points: Sequence[Vec2], width: float, depth: float
) -> list[ValidationIssue]:
    tol = EXTENT_TOLERANCE_M
    inside = [-tol <= x <= width + tol and -tol <= y <= depth + tol for x, y in points]
    if all(inside):
        return []
    extent_bounds = (-tol, -tol, width + tol, depth + tol)
    if not any(inside) and not bounds_overlap(bounds_of(points), extent_bounds):
        return [
            ValidationIssue.error(
                "BLUEPRINT_FEATURE_OUTSIDE_EXTENT",
                "Feature lies entirely outside the extent.",
                location,
            )
        ]
    return [
        ValidationIssue.warning(
            "BLUEPRINT_FEATURE_PARTIALLY_OUTSIDE",
            "Feature extends beyond the extent; parts outside are not generated reliably.",
            location,
        )
    ]


def validate_blueprint(blueprint: LocationBlueprint) -> list[ValidationIssue]:
    """Cross-field checks: unique ids, sane geometry, extent, gaps, overlaps."""
    issues: list[ValidationIssue] = []
    width, depth = blueprint.extent.width_m, blueprint.extent.depth_m

    for collection in FeatureCollection:
        seen: set[str] = set()
        for feature in blueprint.collection(collection):
            location = f"{collection.value}/{feature.id}"
            if feature.id in seen:
                issues.append(
                    ValidationIssue.error(
                        "BLUEPRINT_DUPLICATE_ID",
                        f"Duplicate id '{feature.id}' in {collection.value}.",
                        location,
                    )
                )
            seen.add(feature.id)
            geometry: Geometry = getattr(feature, "geometry")  # noqa: B009 - every feature has one
            issues.extend(_check_geometry(location, geometry))
            issues.extend(_check_extent(location, geometry_points(geometry), width, depth))
            if feature.confidence < LOW_CONFIDENCE:
                issues.append(
                    ValidationIssue.info(
                        "BLUEPRINT_LOW_CONFIDENCE",
                        f"Confidence {feature.confidence:.2f} is low; "
                        "consider recipe filters.min_confidence.",
                        location,
                    )
                )

    for point in blueprint.terrain.elevation_points:
        x, y = point.position
        if not (0.0 <= x <= width and 0.0 <= y <= depth):
            issues.append(
                ValidationIssue.warning(
                    "BLUEPRINT_ELEVATION_POINT_OUTSIDE",
                    f"Spot height at ({x}, {y}) lies outside the extent.",
                    "terrain.elevation_points",
                )
            )

    for fence in blueprint.fences:
        points = list(fence.geometry.points)
        if fence.closed:
            points.append(points[0])
        total = polyline_length(points)
        for gap in fence.gaps:
            if gap.offset_m + gap.width_m > total + 1e-6:
                issues.append(
                    ValidationIssue.error(
                        "BLUEPRINT_FENCE_GAP_OUT_OF_RANGE",
                        f"Gap at {gap.offset_m} m (+{gap.width_m} m) exceeds the fence length "
                        f"{total:.2f} m.",
                        f"fences/{fence.id}",
                    )
                )

    index = SpatialIndex(cell_size=16.0)
    for building in sorted(blueprint.buildings, key=lambda b: b.id):
        location = f"buildings/{building.id}"
        geometry = building.geometry
        if isinstance(geometry, RectangleGeometry):
            outline = rectangle_corners(
                geometry.center, geometry.size[0], geometry.size[1], geometry.rotation_deg
            )
            if min(geometry.size) < MIN_BUILDING_SIDE_M:
                issues.append(
                    ValidationIssue.warning(
                        "BLUEPRINT_TINY_BUILDING",
                        f"A footprint side is below {MIN_BUILDING_SIDE_M} m.",
                        location,
                    )
                )
        else:
            outline = area_outline(geometry)
            if not polygon_is_simple(outline):
                continue
        footprint = Footprint.from_polygon(building.id, "building", outline)
        overlaps = index.query(footprint)
        for other in overlaps:
            issues.append(
                ValidationIssue.warning(
                    "BLUEPRINT_BUILDING_OVERLAP",
                    f"Footprint overlaps building '{other.owner_id}'.",
                    location,
                )
            )
        index.insert(footprint)
    return issues


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
    fill = recipe.buildings.zone_fill
    if fill.enabled and not fill.zone_kinds:
        issues.append(
            ValidationIssue.warning(
                "RECIPE_EMPTY_ZONE_FILL",
                "Zone infill is enabled but no zone kinds are listed.",
                "recipe.buildings.zone_fill",
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
                    "min_floors is greater than max_floors.",
                    location,
                )
            )
    return issues


def validate_compatibility(
    blueprint: LocationBlueprint, recipe: LocationRecipe, overrides: LocationOverrides | None
) -> list[ValidationIssue]:
    """Check that recipe and overrides are meant for this blueprint."""
    issues: list[ValidationIssue] = []
    if recipe.applies_to and not any(
        fnmatch.fnmatchcase(blueprint.id, pattern) for pattern in recipe.applies_to
    ):
        issues.append(
            ValidationIssue.error(
                "RECIPE_NOT_APPLICABLE",
                f"Recipe '{recipe.id}' applies to {recipe.applies_to}, not '{blueprint.id}'.",
                "recipe.applies_to",
            )
        )
    if overrides is not None:
        if overrides.blueprint_id != blueprint.id:
            issues.append(
                ValidationIssue.error(
                    "OVERRIDES_BLUEPRINT_MISMATCH",
                    f"Overrides target blueprint '{overrides.blueprint_id}', got '{blueprint.id}'.",
                    "overrides.blueprint_id",
                )
            )
        if overrides.recipe_id is not None and overrides.recipe_id != recipe.id:
            issues.append(
                ValidationIssue.error(
                    "OVERRIDES_RECIPE_MISMATCH",
                    f"Overrides target recipe '{overrides.recipe_id}', got '{recipe.id}'.",
                    "overrides.recipe_id",
                )
            )
    return issues
