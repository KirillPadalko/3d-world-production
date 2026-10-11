"""Blueprint validation in separate phases.

1. **version** - ``schemaVersion`` against the versioning policy;
2. **schema** - structure, types, enumerations and numeric bounds (the model,
   equivalent to ``schemas/location-blueprint.schema.json``);
3. **semantic** - geometry, ranges, IDs and plausibility rules JSON Schema
   cannot express;
4. **reference** - road graph, plots, parents, landmarks, gameplay and
   provenance references;
5. **external** - files referenced by the blueprint.

Later phases need a parsed model, so a version or schema error stops
validation. Input is never repaired.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from environment_generator.blueprint.diagnostics import Category, ValidationReport, diagnostic
from environment_generator.blueprint.files import check_files, read_heightmap
from environment_generator.blueprint.index import EntityIndex, IndexedObject
from environment_generator.blueprint.versioning import (
    DEFAULT_MIGRATIONS,
    MigrationRegistry,
    SchemaVersion,
    VersionStatus,
    check_version,
)
from environment_generator.core.errors import ExternalDataError
from environment_generator.core.frames import location_yaw_to_generator
from environment_generator.core.geometry import (
    Vec2,
    bounds_of,
    bounds_overlap,
    distance,
    minimum_area_rectangle,
    point_in_polygon,
    polygon_area,
    polygon_centroid,
    polygon_is_simple,
    polyline_length,
    rectangle_corners,
)
from environment_generator.core.issues import Severity, ValidationIssue, has_errors
from environment_generator.core.spatial import Footprint, SpatialIndex
from environment_generator.models.blueprint import (
    Building,
    EntityBase,
    InfrastructurePoint,
    LocationBlueprint,
    ProvenanceCategory,
    Wire,
)

#: Points may lie this far outside the bounds before they count as outside.
BOUNDS_TOLERANCE_M = 0.5
MIN_POLYGON_AREA_M2 = 0.01
MIN_POLYLINE_LENGTH_M = 0.1
LOW_CONFIDENCE = 0.3
LANDMARK_LINK_DISTANCE_M = 50.0
ELEVATION_MARGIN_M = 5.0

#: Kinds a landmark may point at.
LANDMARK_TARGETS = frozenset({"buildings", "trees", "roadNodes", "infrastructure"})
#: Kinds a prop's parent may be.
PROP_PARENTS = frozenset({"plots", "buildings", "infrastructure", "props", "trees"})
#: Kinds an infrastructure item's parent may be.
INFRASTRUCTURE_PARENTS = frozenset({"buildings", "infrastructure", "fences", "plots"})
#: Kinds gameplay annotations may reference.
SOURCE_KINDS = frozenset(
    {
        "sourceMedia",
        "frameExtractions",
        "frames",
        "analysisReports",
        "referencePoints",
        "observations",
    }
)

_SCHEMA_HINTS: dict[str, str] = {
    "missing": "Add the required field.",
    "extra_forbidden": "Remove the field; vendor-specific data belongs in 'extensions' "
    "under an 'x-' prefixed key.",
    "enum": "Use one of the values listed in the schema.",
    "literal_error": "Use the exact value required by the schema.",
    "greater_than": "Use a value within the documented range.",
    "greater_than_equal": "Use a value within the documented range.",
    "less_than": "Use a value within the documented range.",
    "less_than_equal": "Use a value within the documented range.",
    "too_short": "Polygons need at least 3 points, polylines at least 2.",
    "too_long": "Shorten the list or split the entity.",
    "timezone_aware": "Write timestamps with a time zone, e.g. 2026-10-09T08:30:00Z.",
    "union_tag_invalid": "Check the type discriminator value against the schema.",
    "string_type": "Use a JSON string.",
    "float_type": "Use a JSON number.",
    "int_type": "Use a JSON integer.",
    "bool_type": "Use true or false.",
}
_COORDINATE_HINT = (
    "LocationBlueprint v1.0 uses metres, +X east, +Y up, +Z north, yaw clockwise from north "
    "and a south-west origin. Convert the coordinates; never just relabel axes."
)


# --------------------------------------------------------------------------- results


@dataclass
class BlueprintValidation:
    """Outcome of :func:`validate_document`."""

    status: VersionStatus
    version: SchemaVersion | None
    blueprint: LocationBlueprint | None
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.blueprint is not None and not has_errors(self.issues)

    def report(self, document: str | None = None) -> ValidationReport:
        return ValidationReport.build(
            self.issues,
            document=document,
            schema_version=str(self.version) if self.version else None,
        )


# --------------------------------------------------------------------------- schema phase


def _walk_path(document: Any, loc: Sequence[int | str]) -> tuple[str, str | None]:
    """Readable path and nearest enclosing entity ID for a pydantic error location.

    Keys and indices present in the document are followed; discriminator tags
    that pydantic inserts for tagged unions are skipped; a missing field ends
    the path.
    """
    text = ""
    current: Any = document
    entity_id: str | None = None
    for part in loc:
        if part == "[key]":
            continue  # the error is about the map key itself, already in the path
        if isinstance(current, list) and isinstance(part, int) and 0 <= part < len(current):
            text += f"[{part}]"
            current = current[part]
        elif isinstance(current, dict) and isinstance(part, str) and part in current:
            text += f".{part}" if text else part
            current = current[part]
        elif isinstance(current, dict) and isinstance(part, str) and part in current.values():
            continue  # union tag such as "utility_pole"
        else:
            text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
            current = None
        if isinstance(current, dict) and isinstance(current.get("id"), str):
            entity_id = current["id"]
    return text or "$", entity_id


def schema_diagnostics(
    error: ValidationError, document: Mapping[str, Any]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for detail in error.errors(include_url=False):
        path, entity_id = _walk_path(document, tuple(detail["loc"]))
        kind = detail["type"]
        hint = _SCHEMA_HINTS.get(kind)
        if path.startswith("coordinateSystem") and kind in {"literal_error", "missing"}:
            hint = _COORDINATE_HINT
        elif kind == "string_pattern_mismatch":
            if path.endswith("path") or ".file" in path or "Directory" in path:
                hint = "Use a relative POSIX path inside the location package (no '..', "
                hint += "no leading '/', no backslashes, no URL)."
            elif path.endswith(("id", "Id")) or "Ids" in path or "previousIds" in path:
                hint = "IDs use lower-case letters, digits, '-' and '_' (max 64 characters)."
            else:
                hint = "The value does not match the documented format."
        issues.append(
            diagnostic(
                "error",
                "SCHEMA_" + kind.upper(),
                detail["msg"],
                category=Category.SCHEMA,
                path=path,
                entity_ids=[entity_id] if entity_id else [],
                suggestion=hint,
            )
        )
    return issues


# --------------------------------------------------------------------------- semantic phase


class _Collector:
    def __init__(self, blueprint: LocationBlueprint, category: Category) -> None:
        bounds = blueprint.coordinate_system.bounds
        self.width = bounds.width_m
        self.depth = bounds.depth_m
        self.category = category
        self.issues: list[ValidationIssue] = []

    def add(
        self,
        severity: str,
        code: str,
        message: str,
        path: str,
        entity_ids: Iterable[str | None] = (),
        suggestion: str | None = None,
    ) -> None:
        self.issues.append(
            diagnostic(
                severity,
                code,
                message,
                category=self.category,
                path=path,
                entity_ids=[e for e in entity_ids if e],
                suggestion=suggestion,
            )
        )

    def inside(self, point: Vec2) -> bool:
        tol = BOUNDS_TOLERANCE_M
        return -tol <= point[0] <= self.width + tol and -tol <= point[1] <= self.depth + tol

    def bounds_check(
        self, path: str, entity_id: str | None, points: Sequence[Vec2], *, lenient: bool = False
    ) -> None:
        flags = [self.inside(p) for p in points]
        if all(flags):
            return
        extent = (-BOUNDS_TOLERANCE_M, -BOUNDS_TOLERANCE_M, self.width, self.depth)
        fully_outside = not any(flags) and not bounds_overlap(bounds_of(points), extent)
        if fully_outside and not lenient:
            self.add(
                "error",
                "ENTITY_OUTSIDE_BOUNDS",
                "The geometry lies entirely outside the horizontal bounds.",
                path,
                [entity_id],
                "Check the coordinates (local metres from the south-west corner) or the bounds.",
            )
        else:
            self.add(
                "warning",
                "ENTITY_PARTIALLY_OUTSIDE_BOUNDS",
                "Part of the geometry lies outside the horizontal bounds.",
                path,
                [entity_id],
                "Clip the geometry to the bounds if it is not meant to leave the location.",
            )


def _points(raw: Sequence[Sequence[float]]) -> list[Vec2]:
    return [(float(p[0]), float(p[1])) for p in raw]


def _check_polygon(
    c: _Collector, path: str, entity_id: str | None, raw: Sequence[Sequence[float]]
) -> None:
    points = _points(raw)
    if distance(points[0], points[-1]) < 1e-9:
        c.add(
            "error",
            "POLYGON_CLOSING_POINT_REPEATED",
            "The first point is repeated at the end; polygons are implicitly closed.",
            path,
            [entity_id],
            "Remove the last point.",
        )
        points = points[:-1]
    for i in range(len(points) - 1):
        if distance(points[i], points[i + 1]) < 1e-9:
            c.add(
                "error",
                "POLYGON_DUPLICATE_POINT",
                f"Points {i} and {i + 1} are identical.",
                f"{path}[{i + 1}]",
                [entity_id],
                "Remove the duplicate point.",
            )
            return
    if len(points) < 3 or not polygon_is_simple(points):
        c.add(
            "error",
            "POLYGON_SELF_INTERSECTING",
            "Polygon edges cross or touch each other.",
            path,
            [entity_id],
            "Reorder the points so the outline does not cross itself.",
        )
        return
    if polygon_area(points) < MIN_POLYGON_AREA_M2:
        c.add(
            "error",
            "POLYGON_DEGENERATE",
            f"Polygon area is below {MIN_POLYGON_AREA_M2} m^2.",
            path,
            [entity_id],
            "Remove the entity or give it a real outline.",
        )
        return
    c.bounds_check(path, entity_id, points)


def _check_polyline(
    c: _Collector,
    path: str,
    entity_id: str | None,
    raw: Sequence[Sequence[float]],
    *,
    closed: bool = False,
) -> None:
    points = _points(raw)
    for i in range(len(points) - 1):
        if distance(points[i], points[i + 1]) < 1e-9:
            c.add(
                "error",
                "POLYLINE_DUPLICATE_POINT",
                f"Points {i} and {i + 1} are identical.",
                f"{path}[{i + 1}]",
                [entity_id],
                "Remove the duplicate point.",
            )
            return
    if closed and len(points) > 2 and distance(points[0], points[-1]) < 1e-9:
        c.add(
            "error",
            "POLYLINE_CLOSING_POINT_REPEATED",
            "closed=true already connects the last point to the first.",
            path,
            [entity_id],
            "Remove the repeated last point.",
        )
    if polyline_length(points) < MIN_POLYLINE_LENGTH_M:
        c.add(
            "error",
            "POLYLINE_DEGENERATE",
            f"The path is shorter than {MIN_POLYLINE_LENGTH_M} m.",
            path,
            [entity_id],
        )
        return
    c.bounds_check(path, entity_id, points)


def _check_position(
    c: _Collector,
    blueprint: LocationBlueprint,
    path: str,
    entity_id: str,
    position: tuple[float, float, float],
    snap: bool,
) -> None:
    c.bounds_check(path, entity_id, [(position[0], position[2])])
    elevation = blueprint.terrain.elevation
    if not snap and elevation is not None:
        y = position[1]
        if y < elevation.min_m - ELEVATION_MARGIN_M or y > elevation.max_m + ELEVATION_MARGIN_M:
            c.add(
                "warning",
                "TRANSFORM_ELEVATION_OUT_OF_RANGE",
                f"y = {y} m is far outside terrain.elevation [{elevation.min_m}, "
                f"{elevation.max_m}] and snapToTerrain is false.",
                path,
                [entity_id],
                "Fix y or set snapToTerrain to true.",
            )


def _building_outline(b: Building) -> list[Vec2]:
    """Footprint rectangle from transform and dimensions (``[x, z]`` corners)."""
    return rectangle_corners(
        (b.transform.position[0], b.transform.position[2]),
        b.dimensions.width_m,
        b.dimensions.depth_m,
        location_yaw_to_generator(b.transform.yaw_deg),
    )


def _check_building(c: _Collector, blueprint: LocationBlueprint, path: str, b: Building) -> None:
    _check_position(
        c,
        blueprint,
        f"{path}.transform.position",
        b.id,
        b.transform.position,
        b.transform.snap_to_terrain,
    )
    dims = b.dimensions
    if b.footprint is not None:
        _check_polygon(c, f"{path}.footprint", b.id, b.footprint)
        points = _points(b.footprint)
        if len(points) >= 3 and polygon_area(points) >= MIN_POLYGON_AREA_M2:
            center = polygon_centroid(points)
            position = (b.transform.position[0], b.transform.position[2])
            if distance(center, position) > max(dims.width_m, dims.depth_m) / 2.0:
                c.add(
                    "warning",
                    "BUILDING_FOOTPRINT_MISMATCH",
                    "The footprint centre is far from transform.position.",
                    f"{path}.footprint",
                    [b.id],
                    "transform.position is the footprint centre at ground level.",
                )
            try:
                _, w, d, _ = minimum_area_rectangle(points)
            except ValueError:
                return
            fitted = sorted((w, d))
            declared = sorted((dims.width_m, dims.depth_m))
            ratios = [f / x for f, x in zip(fitted, declared, strict=True)]
            if any(r < 0.75 or r > 1.33 for r in ratios):
                c.add(
                    "warning",
                    "BUILDING_FOOTPRINT_MISMATCH",
                    f"The footprint ({fitted[1]:.1f} x {fitted[0]:.1f} m) does not match "
                    f"dimensions ({declared[1]:.1f} x {declared[0]:.1f} m).",
                    f"{path}.dimensions",
                    [b.id],
                )
    if b.floors is not None and dims.height_m < b.floors * 2.0:
        c.add(
            "warning",
            "BUILDING_HEIGHT_IMPLAUSIBLE",
            f"{b.floors} floor(s) in {dims.height_m} m.",
            f"{path}.dimensions.heightM",
            [b.id],
        )


def _provenance_checks(
    c: _Collector, blueprint: LocationBlueprint, objects: Iterable[IndexedObject]
) -> None:
    measured: list[str] = []
    for obj in objects:
        item = obj.item
        if not isinstance(item, EntityBase) or item.provenance is None:
            continue
        prov = item.provenance
        if prov.category in (ProvenanceCategory.OBSERVED, ProvenanceCategory.INFERRED):
            measured.append(item.id)
            if prov.confidence is None:
                c.add(
                    "warning",
                    "PROVENANCE_CONFIDENCE_MISSING",
                    f"{prov.category.value} data should state its confidence.",
                    f"{obj.path}.provenance",
                    [item.id],
                    "Add provenance.confidence (0..1).",
                )
        if prov.confidence is not None and prov.confidence < LOW_CONFIDENCE:
            c.add(
                "info",
                "PROVENANCE_LOW_CONFIDENCE",
                f"Confidence {prov.confidence:.2f} is low; recipes may filter it out.",
                f"{obj.path}.provenance.confidence",
                [item.id],
            )
    if not measured:
        return
    source = blueprint.source
    calibration = source.calibration if source is not None else None
    if source is None:
        c.add(
            "warning",
            "PROVENANCE_WITHOUT_SOURCE",
            f"{len(measured)} entit(ies) claim observed/inferred provenance but the blueprint "
            "has no source section.",
            "source",
            measured[:20],
            "Describe the source material, or mark authored entities as 'manual'.",
        )
    if calibration is None or calibration.method == "none":
        c.add(
            "warning",
            "UNCALIBRATED_MEASUREMENTS",
            "Positions derived from source material are not calibrated; treat sizes and "
            "distances as approximate.",
            "source.calibration",
            measured[:20],
            "Add source.calibration (e.g. reference_points or gps) when scale is known.",
        )


def semantic_diagnostics(
    blueprint: LocationBlueprint, index: EntityIndex | None = None
) -> list[ValidationIssue]:
    """Rules beyond the schema. Returns semantic diagnostics only."""
    index = index or EntityIndex.build(blueprint)
    c = _Collector(blueprint, Category.SEMANTIC)

    for first, second in index.duplicates:
        c.add(
            "error",
            "DUPLICATE_ID",
            f"ID '{second.id}' is already used by {first.path}.",
            f"{second.path}.id",
            [second.id],
            "Every ID must be unique across the whole document.",
        )
    for previous, owner in index.alias_conflicts:
        c.add(
            "error",
            "PREVIOUS_ID_CONFLICT",
            f"previousIds entry '{previous}' of '{owner}' collides with another ID or alias.",
            f"{index.objects[owner].path}.previousIds",
            [owner],
            "Former IDs must not be reused by any other entity.",
        )

    meta = blueprint.metadata
    if meta.updated_at is not None and meta.updated_at < meta.created_at:
        c.add(
            "error", "METADATA_TIME_ORDER", "updatedAt is before createdAt.", "metadata.updatedAt"
        )

    seeds = Counter(blueprint.generation.subsystem_seeds.values())
    for seed, count in seeds.items():
        if count > 1:
            names = sorted(
                k.value for k, v in blueprint.generation.subsystem_seeds.items() if v == seed
            )
            c.add(
                "warning",
                "SUBSYSTEM_SEED_REUSED",
                f"Subsystems {', '.join(names)} share seed {seed}; their random streams correlate.",
                "generation.subsystemSeeds",
                suggestion="Give each subsystem its own seed or omit it to derive one.",
            )

    terrain = blueprint.terrain
    if terrain.elevation is not None and terrain.elevation.min_m > terrain.elevation.max_m:
        c.add(
            "error",
            "RANGE_INVERTED",
            "terrain.elevation.minM is greater than maxM.",
            "terrain.elevation",
            suggestion="Swap the values.",
        )
    for i, zone in enumerate(terrain.surface_zones):
        _check_polygon(c, f"terrain.surfaceZones[{i}].polygon", zone.id, zone.polygon)
    for i, slope in enumerate(terrain.slope_zones):
        _check_polygon(c, f"terrain.slopeZones[{i}].polygon", slope.id, slope.polygon)
    for i, water in enumerate(terrain.water_bodies):
        _check_polygon(c, f"terrain.waterBodies[{i}].polygon", water.id, water.polygon)

    nodes = {n.id: n for n in blueprint.roads.nodes}
    for i, node in enumerate(blueprint.roads.nodes):
        c.bounds_check(f"roads.nodes[{i}].position", node.id, [node.position], lenient=True)
    degree: Counter[str] = Counter()
    for i, segment in enumerate(blueprint.roads.segments):
        path = f"roads.segments[{i}]"
        degree[segment.source_node_id] += 1
        degree[segment.target_node_id] += 1
        control = _points(segment.curve.control_points)
        if segment.source_node_id == segment.target_node_id and len(control) < 2:
            c.add(
                "error",
                "ROAD_SEGMENT_DEGENERATE",
                "A segment from a node to itself needs at least two control points.",
                path,
                [segment.id],
            )
        source = nodes.get(segment.source_node_id)
        target = nodes.get(segment.target_node_id)
        if source is not None and target is not None:
            full = [source.position, *control, target.position]
            for k in range(len(full) - 1):
                if distance(full[k], full[k + 1]) < 1e-9:
                    c.add(
                        "error",
                        "ROAD_CURVE_DUPLICATE_POINT",
                        "Two consecutive curve points (including the end nodes) are identical.",
                        f"{path}.curve.controlPoints",
                        [segment.id],
                        "Control points must not repeat the node positions.",
                    )
                    break
        if control:
            c.bounds_check(f"{path}.curve.controlPoints", segment.id, control, lenient=True)
    for i, node in enumerate(blueprint.roads.nodes):
        count = degree[node.id]
        path = f"roads.nodes[{i}]"
        if count == 0:
            c.add("warning", "ROAD_NODE_ISOLATED", "No segment uses this node.", path, [node.id])
        elif node.node_type.value == "junction" and count < 3:
            c.add(
                "warning",
                "ROAD_NODE_DEGREE_MISMATCH",
                f"A junction should join at least 3 segments; it joins {count}.",
                f"{path}.nodeType",
                [node.id],
            )
        elif node.node_type.value in {"dead_end", "boundary"} and count > 1:
            c.add(
                "warning",
                "ROAD_NODE_DEGREE_MISMATCH",
                f"A {node.node_type.value} node should end one segment; it joins {count}.",
                f"{path}.nodeType",
                [node.id],
            )

    for i, plot in enumerate(blueprint.plots):
        _check_polygon(c, f"plots[{i}].polygon", plot.id, plot.polygon)
    footprints = [_building_outline(b) for b in blueprint.buildings]
    occupied = SpatialIndex(cell_size=16.0)
    for i, building in enumerate(blueprint.buildings):
        _check_building(c, blueprint, f"buildings[{i}]", building)
        footprint = Footprint.from_polygon(building.id, "building", footprints[i])
        for other in occupied.query(footprint):
            c.add(
                "warning",
                "BUILDING_OVERLAP",
                f"The footprint overlaps building '{other.owner_id}'.",
                f"buildings[{i}].transform",
                [building.id, other.owner_id],
                "Check positions, dimensions and yaw; adjoining buildings should only touch.",
            )
        occupied.insert(footprint)
    for i, vegetation in enumerate(blueprint.vegetation_zones):
        path = f"vegetationZones[{i}]"
        _check_polygon(c, f"{path}.polygon", vegetation.id, vegetation.polygon)
        species = Counter(s.species for s in vegetation.species)
        for name, count in species.items():
            if count > 1:
                c.add(
                    "error",
                    "VEGETATION_SPECIES_DUPLICATE",
                    f"Species '{name}' is listed {count} times.",
                    f"{path}.species",
                    [vegetation.id],
                    "List each species once; weights are relative.",
                )
        if (
            vegetation.height_range is not None
            and vegetation.height_range.min_m > vegetation.height_range.max_m
        ):
            c.add(
                "error",
                "RANGE_INVERTED",
                "heightRange.minM > maxM.",
                f"{path}.heightRange",
                [vegetation.id],
            )
    for i, tree in enumerate(blueprint.trees):
        _check_position(
            c,
            blueprint,
            f"trees[{i}].transform.position",
            tree.id,
            tree.transform.position,
            tree.transform.snap_to_terrain,
        )
    for i, fence in enumerate(blueprint.fences):
        path = f"fences[{i}]"
        _check_polyline(c, f"{path}.path", fence.id, fence.path, closed=fence.closed)
        sections = sorted((s.start, s.end) for s in fence.missing_sections)
        for k, (start, end) in enumerate(sections):
            if start >= end:
                c.add(
                    "error",
                    "MISSING_SECTION_INVALID",
                    f"Missing section [{start}, {end}] must have start < end.",
                    f"{path}.missingSections",
                    [fence.id],
                )
            if k > 0 and start < sections[k - 1][1]:
                c.add(
                    "error",
                    "MISSING_SECTION_OVERLAP",
                    "Missing sections overlap.",
                    f"{path}.missingSections",
                    [fence.id],
                    "Merge overlapping sections.",
                )
        if sections and sum(max(0.0, e - s) for s, e in sections) >= 0.999:
            c.add(
                "warning",
                "FENCE_FULLY_MISSING",
                "Missing sections cover the whole fence.",
                f"{path}.missingSections",
                [fence.id],
                "Delete the fence instead.",
            )
    for i, item in enumerate(blueprint.infrastructure):
        path = f"infrastructure[{i}]"
        if isinstance(item, InfrastructurePoint):
            _check_position(
                c,
                blueprint,
                f"{path}.transform.position",
                item.id,
                item.transform.position,
                item.transform.snap_to_terrain,
            )
        elif isinstance(item, Wire):
            for k in range(len(item.pole_ids) - 1):
                if item.pole_ids[k] == item.pole_ids[k + 1]:
                    c.add(
                        "error",
                        "WIRE_DUPLICATE_POLE",
                        "The same pole appears twice in a row.",
                        f"{path}.poleIds[{k + 1}]",
                        [item.id],
                    )
    for i, prop in enumerate(blueprint.props):
        _check_position(
            c,
            blueprint,
            f"props[{i}].transform.position",
            prop.id,
            prop.transform.position,
            prop.transform.snap_to_terrain,
        )
    for i, landmark in enumerate(blueprint.landmarks):
        point = (landmark.position[0], landmark.position[2])
        if not c.inside(point):
            c.add(
                "info",
                "LANDMARK_OUTSIDE_BOUNDS",
                "The landmark lies outside the playable bounds (allowed for distant landmarks).",
                f"landmarks[{i}].position",
                [landmark.id],
            )

    gameplay = blueprint.gameplay
    for i, area in enumerate(gameplay.navigation_areas):
        path = f"gameplay.navigationAreas[{i}]"
        if area.polygon is None and not area.entity_ids:
            c.add(
                "error",
                "NAVIGATION_AREA_EMPTY",
                "A navigation area needs a polygon, entityIds, or both.",
                path,
                [area.id],
            )
        if area.polygon is not None:
            _check_polygon(c, f"{path}.polygon", area.id, area.polygon)
    for i, cover in enumerate(gameplay.cover_zones):
        _check_polygon(c, f"gameplay.coverZones[{i}].polygon", cover.id, cover.polygon)
    for i, combat in enumerate(gameplay.combat_zones):
        _check_polygon(c, f"gameplay.combatZones[{i}].polygon", combat.id, combat.polygon)
    for i, spawn in enumerate(gameplay.spawn_clearances):
        path = f"gameplay.spawnClearances[{i}].position"
        c.bounds_check(path, spawn.id, [spawn.position])
        if any(point_in_polygon(spawn.position, outline) for outline in footprints):
            c.add(
                "warning",
                "SPAWN_CLEARANCE_BLOCKED",
                "The spawn centre lies inside a building footprint.",
                path,
                [spawn.id],
            )
    for i, sight in enumerate(gameplay.line_of_sight):
        ends = [
            (sight.from_position[0], sight.from_position[2]),
            (sight.to_position[0], sight.to_position[2]),
        ]
        c.bounds_check(f"gameplay.lineOfSight[{i}]", sight.id, ends, lenient=True)

    _provenance_checks(c, blueprint, index.objects.values())
    return c.issues


# --------------------------------------------------------------------------- reference phase


def reference_diagnostics(
    blueprint: LocationBlueprint, index: EntityIndex | None = None
) -> list[ValidationIssue]:
    """Every ID reference must point at an existing object of an allowed kind."""
    index = index or EntityIndex.build(blueprint)
    c = _Collector(blueprint, Category.REFERENCE)

    def ref(
        path: str,
        owner: str | None,
        target_id: str,
        allowed: frozenset[str] | set[str],
        what: str,
    ) -> IndexedObject | None:
        target = index.get(target_id)
        if target is None:
            current = index.aliases.get(target_id)
            if current is not None:
                c.add(
                    "error",
                    "REFERENCE_USES_PREVIOUS_ID",
                    f"'{target_id}' is a former ID of '{current}'.",
                    path,
                    [owner],
                    f"Reference the current ID '{current}'.",
                )
            else:
                c.add(
                    "error",
                    "REFERENCE_NOT_FOUND",
                    f"{what} '{target_id}' does not exist.",
                    path,
                    [owner],
                    "Fix the ID or add the missing entity.",
                )
            return None
        if target.kind not in allowed:
            c.add(
                "error",
                "REFERENCE_WRONG_TYPE",
                f"{what} '{target_id}' is a {target.kind} entry; expected "
                f"{' or '.join(sorted(allowed))}.",
                path,
                [owner],
            )
            return None
        return target

    for i, segment in enumerate(blueprint.roads.segments):
        path = f"roads.segments[{i}]"
        ref(f"{path}.sourceNodeId", segment.id, segment.source_node_id, {"roadNodes"}, "Road node")
        ref(f"{path}.targetNodeId", segment.id, segment.target_node_id, {"roadNodes"}, "Road node")
    for i, building in enumerate(blueprint.buildings):
        if building.plot_id is not None:
            ref(f"buildings[{i}].plotId", building.id, building.plot_id, {"plots"}, "Plot")
    for i, fence in enumerate(blueprint.fences):
        if fence.plot_id is not None:
            ref(f"fences[{i}].plotId", fence.id, fence.plot_id, {"plots"}, "Plot")

    parents: dict[str, str] = {}
    for i, item in enumerate(blueprint.infrastructure):
        path = f"infrastructure[{i}]"
        if isinstance(item, InfrastructurePoint) and item.parent_id is not None:
            target = ref(
                f"{path}.parentId", item.id, item.parent_id, INFRASTRUCTURE_PARENTS, "Parent"
            )
            if target is not None and isinstance(target.item, Wire):
                c.add(
                    "error",
                    "REFERENCE_WRONG_TYPE",
                    "A wire cannot be a parent.",
                    f"{path}.parentId",
                    [item.id],
                )
            parents[item.id] = item.parent_id
        elif isinstance(item, Wire):
            for k, pole_id in enumerate(item.pole_ids):
                target = ref(f"{path}.poleIds[{k}]", item.id, pole_id, {"infrastructure"}, "Pole")
                if target is None:
                    continue
                pole = target.item
                if not isinstance(pole, InfrastructurePoint):
                    c.add(
                        "error",
                        "REFERENCE_WRONG_TYPE",
                        f"'{pole_id}' is a wire, not a pole.",
                        f"{path}.poleIds[{k}]",
                        [item.id],
                    )
                elif pole.infrastructure_type not in {"utility_pole", "light", "water_tower"}:
                    c.add(
                        "warning",
                        "WIRE_UNUSUAL_SUPPORT",
                        f"Wire attached to a {pole.infrastructure_type}.",
                        f"{path}.poleIds[{k}]",
                        [item.id],
                    )
    for i, prop in enumerate(blueprint.props):
        if prop.parent_id is not None:
            ref(f"props[{i}].parentId", prop.id, prop.parent_id, PROP_PARENTS, "Parent")
            parents[prop.id] = prop.parent_id
    for start, parent in parents.items():
        if start == parent:
            c.add(
                "error",
                "PARENT_CYCLE",
                "An entity cannot be its own parent.",
                index.objects[start].path + ".parentId",
                [start],
            )
            continue
        seen = {start}
        current: str | None = parent
        while current is not None and current in parents:
            if current in seen:
                c.add(
                    "error",
                    "PARENT_CYCLE",
                    f"Parent chain of '{start}' loops back to itself.",
                    index.objects[start].path + ".parentId",
                    [start],
                    "Parent references must form a tree.",
                )
                break
            seen.add(current)
            current = parents.get(current)

    for i, landmark in enumerate(blueprint.landmarks):
        if landmark.linked_entity_id is None:
            continue
        target = ref(
            f"landmarks[{i}].linkedEntityId",
            landmark.id,
            landmark.linked_entity_id,
            LANDMARK_TARGETS,
            "Linked entity",
        )
        position = _object_position(target.item) if target is not None else None
        if position is not None:
            gap = distance(position, (landmark.position[0], landmark.position[2]))
            if gap > LANDMARK_LINK_DISTANCE_M:
                c.add(
                    "warning",
                    "LANDMARK_FAR_FROM_LINKED_ENTITY",
                    f"The landmark is {gap:.0f} m from the entity it marks.",
                    f"landmarks[{i}].position",
                    [landmark.id],
                )

    entity_kinds = set(_ENTITY_KINDS)
    gameplay = blueprint.gameplay
    for i, area in enumerate(gameplay.navigation_areas):
        for k, target_id in enumerate(area.entity_ids):
            ref(
                f"gameplay.navigationAreas[{i}].entityIds[{k}]",
                area.id,
                target_id,
                entity_kinds,
                "Entity",
            )
    for i, zone in enumerate(gameplay.cover_zones):
        for k, target_id in enumerate(zone.linked_entity_ids):
            ref(
                f"gameplay.coverZones[{i}].linkedEntityIds[{k}]",
                zone.id,
                target_id,
                entity_kinds,
                "Entity",
            )
    for k, target_id in enumerate(gameplay.connectivity.entrance_ids):
        ref(
            f"gameplay.connectivity.entranceIds[{k}]",
            None,
            target_id,
            {"roadNodes", "plots"},
            "Entrance",
        )

    for obj in list(index.objects.values()):
        entity = obj.item
        if not isinstance(entity, EntityBase) or entity.provenance is None:
            continue
        for k, frame_id in enumerate(entity.provenance.frame_ids):
            ref(f"{obj.path}.provenance.frameIds[{k}]", entity.id, frame_id, {"frames"}, "Frame")
        for k, observation_id in enumerate(entity.provenance.observation_ids):
            ref(
                f"{obj.path}.provenance.observationIds[{k}]",
                entity.id,
                observation_id,
                {"observations"},
                "Observation",
            )

    source = blueprint.source
    if source is not None:
        for i, extraction in enumerate(source.frame_extractions):
            ref(
                f"source.frameExtractions[{i}].mediaId",
                extraction.id,
                extraction.media_id,
                {"sourceMedia"},
                "Media",
            )
        for i, frame in enumerate(source.frames):
            ref(f"source.frames[{i}].mediaId", frame.id, frame.media_id, {"sourceMedia"}, "Media")
            if frame.extraction_id is not None:
                ref(
                    f"source.frames[{i}].extractionId",
                    frame.id,
                    frame.extraction_id,
                    {"frameExtractions"},
                    "Frame extraction",
                )
        for i, observation in enumerate(source.observations):
            for k, frame_id in enumerate(observation.frame_ids):
                ref(
                    f"source.observations[{i}].frameIds[{k}]",
                    observation.id,
                    frame_id,
                    {"frames"},
                    "Frame",
                )
            if observation.report_id is not None:
                ref(
                    f"source.observations[{i}].reportId",
                    observation.id,
                    observation.report_id,
                    {"analysisReports"},
                    "Analysis report",
                )
        if source.calibration is not None:
            for k, point_id in enumerate(source.calibration.reference_point_ids):
                ref(
                    f"source.calibration.referencePointIds[{k}]",
                    None,
                    point_id,
                    {"referencePoints"},
                    "Reference point",
                )
    return c.issues


_ENTITY_KINDS = (
    "roadNodes",
    "roadSegments",
    "plots",
    "buildings",
    "vegetationZones",
    "trees",
    "fences",
    "infrastructure",
    "props",
    "landmarks",
    "surfaceZones",
    "slopeZones",
    "waterBodies",
)


def _object_position(item: Any) -> Vec2 | None:
    transform = getattr(item, "transform", None)
    if transform is not None:
        return (transform.position[0], transform.position[2])
    position = getattr(item, "position", None)
    if isinstance(position, tuple) and len(position) == 2:
        return (float(position[0]), float(position[1]))
    return None


# --------------------------------------------------------------------------- external phase


def external_diagnostics(
    blueprint: LocationBlueprint, package_root: Path | None
) -> list[ValidationIssue]:
    issues = check_files(blueprint, package_root)
    heightmap = blueprint.terrain.heightmap
    elevation = blueprint.terrain.elevation
    if (
        heightmap is None
        or package_root is None
        or elevation is None
        or any(i.path == "terrain.heightmap.file" and i.severity is Severity.ERROR for i in issues)
    ):
        return issues
    try:
        samples = read_heightmap(heightmap, package_root)
    except ExternalDataError as exc:
        issues.append(
            diagnostic(
                "error",
                "HEIGHTMAP_UNREADABLE",
                exc.message,
                category=Category.EXTERNAL,
                path="terrain.heightmap",
            )
        )
        return issues
    if samples.minimum < elevation.min_m - 0.5 or samples.maximum > elevation.max_m + 0.5:
        issues.append(
            diagnostic(
                "warning",
                "HEIGHTMAP_ELEVATION_MISMATCH",
                f"Heightmap spans {samples.minimum:.2f}..{samples.maximum:.2f} m but "
                f"terrain.elevation says {elevation.min_m}..{elevation.max_m} m.",
                category=Category.EXTERNAL,
                path="terrain.heightmap",
                suggestion="Check heightScaleM / heightOffsetM or the declared elevation range.",
            )
        )
    return issues


# --------------------------------------------------------------------------- entry points


def validate_model(
    blueprint: LocationBlueprint,
    *,
    package_root: Path | None = None,
    check_external: bool = True,
) -> list[ValidationIssue]:
    """Semantic, reference and (optionally) external checks of a parsed blueprint."""
    index = EntityIndex.build(blueprint)
    issues = [*semantic_diagnostics(blueprint, index), *reference_diagnostics(blueprint, index)]
    if check_external:
        issues.extend(external_diagnostics(blueprint, package_root))
    return issues


def validate_document(
    document: Mapping[str, Any],
    *,
    package_root: Path | None = None,
    check_external: bool = True,
    registry: MigrationRegistry = DEFAULT_MIGRATIONS,
) -> BlueprintValidation:
    """Run every phase on a raw JSON document."""
    status, version, issues = check_version(document, registry=registry)
    if issues:
        return BlueprintValidation(status, version, None, issues)
    try:
        blueprint = LocationBlueprint.model_validate(dict(document), by_alias=True, by_name=False)
    except ValidationError as exc:
        return BlueprintValidation(status, version, None, schema_diagnostics(exc, document))
    issues = validate_model(blueprint, package_root=package_root, check_external=check_external)
    return BlueprintValidation(status, version, blueprint, issues)
