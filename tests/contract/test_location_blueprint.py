"""LocationBlueprint v1.0 contract: loading, serialization, validation, versions.

These tests pin the behaviour another implementation must reproduce
(docs/LOCATION_BLUEPRINT.md). They use the dacha fixture and small documents
built with :mod:`tests.blueprints`.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import struct
from pathlib import Path
from typing import Any

import pytest

from environment_generator.blueprint import (
    CURRENT_VERSION,
    Migration,
    MigrationRegistry,
    SchemaVersion,
    VersionStatus,
    blueprint_to_data,
    check_version,
    dumps_blueprint,
    load_blueprint,
    migrate_document,
    migrate_file,
    parse_blueprint,
    save_blueprint,
    validate_document,
    validate_source,
)
from environment_generator.blueprint.files import read_heightmap
from environment_generator.core.errors import (
    ContractValidationError,
    ExportError,
    MigrationError,
    SemanticValidationError,
    UnsupportedVersionError,
)
from environment_generator.core.issues import Severity, ValidationIssue
from environment_generator.models.blueprint import (
    Building,
    InfrastructurePoint,
    LocationBlueprint,
    ProvenanceCategory,
    Wire,
)
from tests.blueprints import (
    building,
    fence,
    location_data,
    make_location,
    node,
    pole,
    prop,
    rect,
    segment,
    straight_road,
    tree,
    vegetation_zone,
    wire,
)
from tests.conftest import DACHA_BLUEPRINT, DACHA_DIR, LOCATIONS


def codes(issues: list[ValidationIssue]) -> set[str]:
    return {issue.code for issue in issues}


def diagnostics(data: dict[str, Any], **kwargs: Any) -> list[ValidationIssue]:
    return validate_document(data, check_external=False, **kwargs).issues


def only(issues: list[ValidationIssue], code: str) -> ValidationIssue:
    found = [issue for issue in issues if issue.code == code]
    assert len(found) == 1, [issue.format() for issue in issues]
    return found[0]


@pytest.fixture(scope="module")
def dacha() -> LocationBlueprint:
    return load_blueprint(DACHA_BLUEPRINT)


# --------------------------------------------------------------------------- loading


def test_dacha_fixture_loads_without_diagnostics() -> None:
    result = validate_source(DACHA_BLUEPRINT)
    assert result.status is VersionStatus.CURRENT
    assert result.valid
    assert result.issues == []


def test_dacha_fixture_contents(dacha: LocationBlueprint) -> None:
    assert dacha.location_id == "dacha-forest-edge"
    assert dacha.coordinate_system.bounds.width_m == 160.0
    importance = {s.id: s.importance.value for s in dacha.roads.segments}
    assert importance["s-main-west"] == "primary" and importance["s-lane"] == "secondary"
    types = {b.building_type.value for b in dacha.buildings}
    assert {"house", "garage", "shed", "bathhouse"} <= types
    assert all(b.condition <= 1 and b.abandonment <= 1 for b in dacha.buildings)
    zones = {z.zone_type.value for z in dacha.vegetation_zones}
    assert {"forest_dense", "forest_light", "overgrown_yard"} <= zones
    assert any(s.species == "unknown" for z in dacha.vegetation_zones for s in z.species)
    assert sum(len(f.missing_sections) for f in dacha.fences) >= 5
    poles = [i for i in dacha.infrastructure if isinstance(i, InfrastructurePoint)]
    assert sum(p.infrastructure_type == "utility_pole" for p in poles) == 7
    assert [w.id for w in dacha.infrastructure if isinstance(w, Wire)] == ["w-main", "w-lane"]
    assert len(dacha.landmarks) == 4
    cover = {z.id: z for z in dacha.gameplay.cover_zones}
    fence_cover = cover["cz-fence-04"]
    # Movement, projectiles and vision are separate: boards block movement and sight only.
    assert (fence_cover.movement.value, fence_cover.projectile_cover.value) == ("block", "none")
    assert fence_cover.vision.value == "full"
    assert dacha.atmosphere.weather.value == "overcast"
    assert dacha.source is not None and dacha.source.type.value == "synthetic"
    assert dacha.source.media == [] and dacha.source.frames == []  # nothing fabricated


def test_dacha_fixture_is_engine_independent() -> None:
    text = DACHA_BLUEPRINT.read_text(encoding="utf-8")
    for forbidden in (
        "prefab",
        "Assets/",
        ".unity",
        "bpy",
        "meshy",
        "instanceID",
        "C:\\",
        "/home/",
    ):
        assert forbidden.lower() not in text.lower(), forbidden


def test_dacha_heightmap_is_external_and_checked(dacha: LocationBlueprint) -> None:
    heightmap = dacha.terrain.heightmap
    assert heightmap is not None and heightmap.file.path == "terrain/heightmap.r16"
    samples = read_heightmap(heightmap, DACHA_DIR)
    assert (samples.columns, samples.rows) == (65, 65)
    elevation = dacha.terrain.elevation
    assert elevation is not None
    assert elevation.min_m <= samples.minimum <= samples.maximum <= elevation.max_m
    payload = (DACHA_DIR / heightmap.file.path).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == heightmap.file.sha256


@pytest.mark.parametrize("path", sorted(LOCATIONS.glob("*/location.blueprint.json")))
def test_every_example_location_is_valid(path: Path) -> None:
    result = validate_source(path)
    assert result.valid, [i.format() for i in result.issues]
    assert not [i for i in result.issues if i.severity is not Severity.INFO]


def test_load_raises_structured_errors() -> None:
    with pytest.raises(ContractValidationError) as info:
        parse_blueprint(location_data(buildings=[building("b", 10, 10, condition=2)]))
    issue = only(info.value.issues, "SCHEMA_LESS_THAN_EQUAL")
    assert issue.category == "schema" and issue.path == "buildings[0].condition"
    assert issue.entity_ids == ("b",)
    with pytest.raises(SemanticValidationError) as semantic:
        parse_blueprint(location_data(trees=[tree("t", 10, 10), tree("t", 20, 20)]))
    assert codes(semantic.value.issues) == {"DUPLICATE_ID"}


# --------------------------------------------------------------------------- serialization


def test_fixture_round_trip_is_byte_identical(dacha: LocationBlueprint) -> None:
    text = DACHA_BLUEPRINT.read_text(encoding="utf-8")
    assert dumps_blueprint(dacha) == text
    again = parse_blueprint(json.loads(text), package_root=DACHA_DIR)
    assert again == dacha


def test_round_trip_through_full_form(dacha: LocationBlueprint) -> None:
    full = blueprint_to_data(dacha, compact=False)
    assert full["status"] == "review" and "generation" in full and "gameplay" in full
    assert parse_blueprint(full, package_root=DACHA_DIR) == dacha
    compact = blueprint_to_data(dacha)
    assert len(json.dumps(compact)) < len(json.dumps(full))


def test_serialization_is_deterministic_and_order_independent() -> None:
    data = location_data(
        trees=[tree("t-1", 10.123456789, 20.5, label="Birke \u00fc")],
        extensions={"x-b.second": 2, "x-a.first": {"z": 1, "a": [3, 1]}},
    )
    reordered = dict(reversed(list(copy.deepcopy(data).items())))
    first = dumps_blueprint(make_location(**data))
    second = dumps_blueprint(parse_blueprint(reordered))
    assert first == second
    assert first.endswith("\n")
    assert "10.123456789" in first  # floats are written exactly, not rounded
    assert "Birke \u00fc" in first  # UTF-8, not \\u escapes
    keys = list(json.loads(first))
    assert keys[:4] == ["schemaVersion", "locationId", "name", "metadata"]
    assert list(json.loads(first)["extensions"]) == ["x-a.first", "x-b.second"]


def test_save_never_overwrites_silently(tmp_path: Path) -> None:
    blueprint = make_location()
    target = save_blueprint(blueprint, tmp_path / "location.blueprint.json")
    with pytest.raises(ExportError, match="exists"):
        save_blueprint(blueprint, target)
    save_blueprint(blueprint, target, overwrite=True)
    assert load_blueprint(target) == blueprint


def test_loading_does_not_invent_ids_or_values() -> None:
    data = location_data(trees=[tree("t-1", 10, 20)])
    first, second = parse_blueprint(data), parse_blueprint(data)
    assert first == second
    assert json.loads(dumps_blueprint(first))["trees"] == [
        {"id": "t-1", "transform": {"position": [10, 0, 20]}}
    ]


# --------------------------------------------------------------------------- schema phase


def test_schema_errors_point_at_fields_and_entities() -> None:
    data = location_data(
        roads={"nodes": [node("n-1", 0, 0), {"id": "n-2", "position": [1, 2, 3]}]},
        buildings=[building("b-1", 10, 10, buildingType="castle")],
    )
    issues = diagnostics(data)
    assert {i.category for i in issues} == {"schema"}
    paths = {(i.path, i.entity_id) for i in issues}
    assert ("roads.nodes[1].position", "n-2") in paths
    assert ("buildings[0].buildingType", "b-1") in paths
    assert all(i.severity is Severity.ERROR and i.suggestion for i in issues if i.path)


@pytest.mark.parametrize(
    ("change", "path"),
    [
        ({"coordinateSystem": {"upAxis": "+z"}}, "coordinateSystem.upAxis"),
        (
            {"coordinateSystem": {"yawConvention": "degrees_counterclockwise"}},
            "coordinateSystem.yawConvention",
        ),
        ({"coordinateSystem": {"unit": "feet"}}, "coordinateSystem.unit"),
    ],
)
def test_axes_are_never_reinterpreted(change: dict[str, Any], path: str) -> None:
    data = location_data()
    data["coordinateSystem"].update(change["coordinateSystem"])
    assert path in {i.path for i in diagnostics(data)}


@pytest.mark.parametrize(
    "bad_path",
    [
        "/abs/height.r16",
        "C:/data/h.r16",
        "..\\h.r16",
        "terrain/../../h.r16",
        "https://x/h.r16",
        "./h.r16",
    ],
)
def test_file_paths_must_stay_inside_the_package(bad_path: str) -> None:
    data = location_data(
        terrain={
            "heightmap": {
                "file": {"path": bad_path},
                "encoding": "raw_u16_le",
                "columns": 2,
                "rows": 2,
                "rowOrder": "south_to_north",
                "heightScaleM": 0.01,
            }
        }
    )
    assert "terrain.heightmap.file.path" in {i.path for i in diagnostics(data)}


def test_extensions_need_a_namespace() -> None:
    assert diagnostics(location_data(extensions={"x-studio.flag": True})) == []
    assert {i.path for i in diagnostics(location_data(extensions={"flag": True}))} == {
        "extensions.flag"
    }


# --------------------------------------------------------------------------- semantic phase


def test_duplicate_ids_are_reported_across_collections() -> None:
    data = location_data(
        roads=straight_road("x-1"),
        trees=[tree("x-1", 10, 10)],
        props=[prop("p-1", 5, 5), prop("p-1", 6, 6)],
    )
    issues = [i for i in diagnostics(data) if i.code == "DUPLICATE_ID"]
    assert sorted(i.entity_id for i in issues) == ["p-1", "x-1"]
    assert {i.path for i in issues} == {"trees[0].id", "props[1].id"}
    assert all(i.severity is Severity.ERROR and i.category == "semantic" for i in issues)


def test_previous_ids_resolve_but_must_not_collide() -> None:
    data = location_data(
        roads=straight_road(),
        buildings=[building("b-new", 30, 60, previousIds=["b-old"])],
        landmarks=[
            {
                "id": "lm",
                "landmarkType": "building",
                "position": [30, 0, 60],
                "linkedEntityId": "b-old",
            }
        ],
    )
    # Inside a document references must use current IDs (only overrides resolve aliases).
    issue = only(diagnostics(data), "REFERENCE_USES_PREVIOUS_ID")
    assert issue.severity is Severity.ERROR and "b-new" in (issue.suggestion or "")
    clash = location_data(trees=[tree("t-1", 1, 1), tree("t-2", 2, 2, previousIds=["t-1"])])
    assert "PREVIOUS_ID_CONFLICT" in codes(diagnostics(clash))


def test_broken_road_graph() -> None:
    data = location_data(
        roads={
            "nodes": [
                node("a", 0, 40, "boundary"),
                node("b", 50, 40, "junction"),
                node("c", 100, 40),
                node("lonely", 50, 70),
            ],
            "segments": [
                segment("s-1", "a", "b"),
                segment("s-2", "b", "missing"),
                segment("s-3", "c", "c"),
                segment("s-4", "a", "b", control=[[0, 40]]),
            ],
        }
    )
    issues = diagnostics(data)
    missing = only(issues, "REFERENCE_NOT_FOUND")
    assert missing.path == "roads.segments[1].targetNodeId" and missing.entity_id == "s-2"
    assert only(issues, "ROAD_NODE_ISOLATED").entity_id == "lonely"
    assert "ROAD_SEGMENT_DEGENERATE" in codes(issues)
    assert "ROAD_CURVE_DUPLICATE_POINT" in codes(issues)
    assert "ROAD_NODE_DEGREE_MISMATCH" in codes(issues)


def test_road_reference_to_wrong_kind() -> None:
    data = location_data(
        roads={"nodes": [node("a", 0, 40)], "segments": [segment("s-1", "a", "t-1")]},
        trees=[tree("t-1", 10, 10)],
    )
    assert only(diagnostics(data), "REFERENCE_WRONG_TYPE").path == "roads.segments[0].targetNodeId"


@pytest.mark.parametrize(
    ("polygon", "code"),
    [
        ([[0, 0], [10, 10], [10, 0], [0, 10]], "POLYGON_SELF_INTERSECTING"),
        ([[0, 0], [10, 0], [20, 0]], "POLYGON_DEGENERATE"),
        ([[0, 0], [10, 0], [10, 10], [0, 0]], "POLYGON_CLOSING_POINT_REPEATED"),
        ([[0, 0], [10, 0], [10, 0], [10, 10]], "POLYGON_DUPLICATE_POINT"),
    ],
)
def test_invalid_polygons(polygon: list[list[float]], code: str) -> None:
    issues = diagnostics(location_data(vegetationZones=[vegetation_zone("vz", polygon)]))
    issue = only(issues, code)
    assert issue.path is not None and issue.path.startswith("vegetationZones[0].polygon")
    assert issue.entity_id == "vz" and issue.suggestion


def test_bounds_checks() -> None:
    outside = diagnostics(location_data(buildings=[building("b", 500, 500)]))
    assert only(outside, "ENTITY_OUTSIDE_BOUNDS").severity is Severity.ERROR
    partial = diagnostics(location_data(fences=[fence("f", [[90, 10], [110, 10]])]))
    assert only(partial, "ENTITY_PARTIALLY_OUTSIDE_BOUNDS").severity is Severity.WARNING


def test_value_ranges_and_consistency() -> None:
    issues = diagnostics(
        location_data(
            metadata={"createdAt": "2026-02-01T00:00:00Z", "updatedAt": "2026-01-01T00:00:00Z"},
            terrain={"elevation": {"minM": 10, "maxM": 5}},
            buildings=[
                building("b-1", 20, 20, floors=3, height=4),
                building("b-2", 22, 21),
                building(
                    "b-3",
                    70,
                    60,
                    footprint=rect(60, 50, 90, 70),
                ),
            ],
            fences=[
                fence(
                    "f-1",
                    [[0, 70], [40, 70]],
                    missingSections=[{"start": 0.5, "end": 0.2}, {"start": 0.1, "end": 0.3}],
                )
            ],
            vegetationZones=[
                vegetation_zone(
                    "vz",
                    rect(0, 0, 10, 10),
                    species=[{"species": "birch", "weight": 1}, {"species": "birch", "weight": 2}],
                )
            ],
        )
    )
    found = codes(issues)
    assert {
        "METADATA_TIME_ORDER",
        "RANGE_INVERTED",
        "BUILDING_HEIGHT_IMPLAUSIBLE",
        "BUILDING_OVERLAP",
        "BUILDING_FOOTPRINT_MISMATCH",
        "MISSING_SECTION_INVALID",
        "VEGETATION_SPECIES_DUPLICATE",
    } <= found


def test_fence_missing_sections() -> None:
    ok = fence("f", [[0, 10], [50, 10]], missingSections=[{"start": 0.1, "end": 0.2}])
    assert diagnostics(location_data(fences=[ok])) == []
    gone = fence("f", [[0, 10], [50, 10]], missingSections=[{"start": 0, "end": 1}])
    assert "FENCE_FULLY_MISSING" in codes(diagnostics(location_data(fences=[gone])))
    overlap = fence(
        "f",
        [[0, 10], [50, 10]],
        missingSections=[{"start": 0.1, "end": 0.4}, {"start": 0.3, "end": 0.5}],
    )
    assert "MISSING_SECTION_OVERLAP" in codes(diagnostics(location_data(fences=[overlap])))


def test_infrastructure_references() -> None:
    data = location_data(
        infrastructure=[
            pole("p-1", 10, 10),
            pole("p-2", 40, 10),
            wire("w-1", ["p-1", "p-1", "p-2", "p-9"]),
            {
                "id": "lamp",
                "infrastructureType": "light",
                "transform": {"position": [10, 0, 10]},
                "parentId": "lamp-2",
            },
            {
                "id": "lamp-2",
                "infrastructureType": "light",
                "transform": {"position": [10, 0, 10]},
                "parentId": "lamp",
            },
        ],
        roads=straight_road("s-1"),
        props=[prop("pr", 5, 5, parentId="s-1")],
    )
    issues = diagnostics(data)
    assert "WIRE_DUPLICATE_POLE" in codes(issues)
    assert any(i.code == "REFERENCE_NOT_FOUND" and i.entity_id == "w-1" for i in issues)
    assert "PARENT_CYCLE" in codes(issues)
    assert any(i.code == "REFERENCE_WRONG_TYPE" and i.entity_id == "pr" for i in issues)


def test_gameplay_annotations_are_checked() -> None:
    data = location_data(
        buildings=[building("b", 50, 40)],
        gameplay={
            "navigationAreas": [{"id": "na", "areaType": "blocked"}],
            "coverZones": [
                {"id": "cz", "polygon": rect(0, 0, 5, 5), "linkedEntityIds": ["nothing"]}
            ],
            "spawnClearances": [{"id": "sp", "position": [50, 40], "radiusM": 3}],
            "connectivity": {"entranceIds": ["b"]},
        },
    )
    issues = diagnostics(data)
    assert {"NAVIGATION_AREA_EMPTY", "SPAWN_CLEARANCE_BLOCKED", "REFERENCE_NOT_FOUND"} <= codes(
        issues
    )
    assert "REFERENCE_WRONG_TYPE" in codes(issues)  # entrances must be road nodes


def test_diagnostics_are_sorted_and_reportable() -> None:
    result = validate_document(
        location_data(trees=[tree("t", 10, 10), tree("t", 500, 500)]), check_external=False
    )
    assert not result.valid
    report = result.report(document="doc.json")
    assert report.counts["error"] == len([i for i in result.issues if i.severity is Severity.ERROR])
    data = report.model_dump(mode="json")
    assert set(data["diagnostics"][0]) >= {"severity", "code", "message", "category", "path"}
    assert data["schemaVersion"] == "1.0" and data["valid"] is False
    assert list(report.by_category()) == sorted(
        report.by_category(), key=list(report.by_category()).index
    )


# --------------------------------------------------------------------------- provenance


def observed_location(**source_changes: Any) -> dict[str, Any]:
    source: dict[str, Any] = {
        "type": "video",
        "media": [{"id": "clip-1", "kind": "video", "file": {"path": "media/clip-1.mp4"}}],
        "frameExtractions": [
            {"id": "fx-1", "mediaId": "clip-1", "method": "fixed_interval", "intervalS": 2.0}
        ],
        "frames": [
            {"id": "f-0001", "mediaId": "clip-1", "extractionId": "fx-1", "timestampS": 2.0}
        ],
        "observations": [
            {"id": "obs-1", "description": "Shed visible behind the fence.", "frameIds": ["f-0001"]}
        ],
        "calibration": {"method": "reference_points", "scaleConfidence": 0.7},
    }
    source.update(source_changes)
    return location_data(
        source=source,
        buildings=[
            building(
                "b-1",
                30,
                30,
                provenance={
                    "category": "observed",
                    "confidence": 0.8,
                    "method": "photogrammetry",
                    "positionAccuracyM": 1.5,
                    "frameIds": ["f-0001"],
                    "observationIds": ["obs-1"],
                },
            ),
            building(
                "b-2",
                60,
                30,
                provenance={"category": "inferred", "confidence": 0.4, "notes": "Roof only."},
            ),
            building("b-3", 80, 60, provenance={"category": "manual"}),
            building("b-4", 80, 20, provenance={"category": "procedural", "method": "zone_fill"}),
        ],
    )


def test_provenance_round_trips_with_all_categories() -> None:
    data = observed_location()
    blueprint = parse_blueprint(data, check_external=False)
    categories = [b.provenance.category for b in blueprint.buildings if b.provenance]
    assert categories == list(ProvenanceCategory)
    text = dumps_blueprint(blueprint)
    again = parse_blueprint(json.loads(text), check_external=False)
    assert again == blueprint
    first = json.loads(text)["buildings"][0]["provenance"]
    assert first == {
        "category": "observed",
        "confidence": 0.8,
        "method": "photogrammetry",
        "positionAccuracyM": 1.5,
        "frameIds": ["f-0001"],
        "observationIds": ["obs-1"],
    }


def test_provenance_references_and_expectations() -> None:
    data = observed_location()
    data["buildings"][0]["provenance"]["frameIds"] = ["f-9999"]
    del data["buildings"][1]["provenance"]["confidence"]
    issues = diagnostics(data)
    assert only(issues, "REFERENCE_NOT_FOUND").path == "buildings[0].provenance.frameIds[0]"
    assert only(issues, "PROVENANCE_CONFIDENCE_MISSING").entity_id == "b-2"
    unsourced = observed_location()
    del unsourced["source"]
    assert "PROVENANCE_WITHOUT_SOURCE" in codes(diagnostics(unsourced))
    uncalibrated = observed_location(calibration={"method": "none"})
    assert "UNCALIBRATED_MEASUREMENTS" in codes(diagnostics(uncalibrated))


def test_missing_optional_source_media_is_not_an_error(tmp_path: Path) -> None:
    """Source media are provenance, not generation input: a missing clip only warns."""
    result = validate_document(observed_location(), package_root=tmp_path)
    missing = only(result.issues, "EXTERNAL_FILE_MISSING")
    assert missing.severity is Severity.WARNING and missing.path == "source.media[0].file"
    assert result.valid


# --------------------------------------------------------------------------- external files


def heightmap_package(tmp_path: Path, **heightmap: Any) -> tuple[Path, dict[str, Any]]:
    values = [0, 100, 200, 300]
    payload = struct.pack("<4H", *values)
    (tmp_path / "terrain").mkdir()
    (tmp_path / "terrain" / "h.r16").write_bytes(payload)
    spec: dict[str, Any] = {
        "file": {
            "path": "terrain/h.r16",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "sizeBytes": len(payload),
        },
        "encoding": "raw_u16_le",
        "columns": 2,
        "rows": 2,
        "rowOrder": "south_to_north",
        "heightScaleM": 0.01,
        "heightOffsetM": 10.0,
    }
    spec.update(heightmap)
    data = location_data(terrain={"elevation": {"minM": 10, "maxM": 13}, "heightmap": spec})
    (tmp_path / "location.blueprint.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path / "location.blueprint.json", data


def test_heightmap_is_read_relative_to_the_package(tmp_path: Path) -> None:
    path, _ = heightmap_package(tmp_path)
    blueprint = load_blueprint(path)
    assert blueprint.terrain.heightmap is not None
    samples = read_heightmap(blueprint.terrain.heightmap, tmp_path)
    assert samples.heights == [[10.0, 11.0], [12.0, 13.0]]  # row 0 = south edge


def test_row_order_north_to_south_is_flipped(tmp_path: Path) -> None:
    path, _ = heightmap_package(tmp_path, rowOrder="north_to_south")
    blueprint = load_blueprint(path)
    assert blueprint.terrain.heightmap is not None
    samples = read_heightmap(blueprint.terrain.heightmap, tmp_path)
    assert samples.heights == [[12.0, 13.0], [10.0, 11.0]]


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"file": {"path": "terrain/missing.r16"}}, "EXTERNAL_FILE_MISSING"),
        (
            {"file": {"path": "terrain/h.r16", "sha256": "0" * 64}},
            "EXTERNAL_FILE_CHECKSUM_MISMATCH",
        ),
        ({"file": {"path": "terrain/h.r16", "sizeBytes": 9}}, "EXTERNAL_FILE_SIZE_MISMATCH"),
        ({"columns": 3}, "EXTERNAL_RASTER_SIZE_MISMATCH"),
    ],
)
def test_external_file_problems(tmp_path: Path, change: dict[str, Any], code: str) -> None:
    path, _ = heightmap_package(tmp_path, **change)
    result = validate_source(path)
    issue = only(result.issues, code)
    assert issue.severity is Severity.ERROR and issue.category == "external"
    assert issue.path is not None and issue.path.startswith("terrain.heightmap")
    assert not result.valid


def test_external_files_without_a_package_root_are_reported(tmp_path: Path) -> None:
    _, data = heightmap_package(tmp_path)
    result = validate_document(data)
    assert only(result.issues, "EXTERNAL_FILES_NOT_CHECKED").severity is Severity.WARNING
    assert result.valid


def test_symlink_escaping_the_package_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside.r16"
    outside.write_bytes(b"\0" * 8)
    package = tmp_path / "pkg"
    package.mkdir()
    path, _ = heightmap_package(package)
    (package / "terrain" / "h.r16").unlink()
    (package / "terrain" / "h.r16").symlink_to(outside)
    assert "EXTERNAL_PATH_ESCAPES_PACKAGE" in codes(validate_source(path).issues)


def test_heightmap_elevation_range_must_match(tmp_path: Path) -> None:
    path, data = heightmap_package(tmp_path)
    data["terrain"]["elevation"] = {"minM": 50, "maxM": 60}
    path.write_text(json.dumps(data), encoding="utf-8")
    assert "HEIGHTMAP_ELEVATION_MISMATCH" in codes(validate_source(path).issues)


def test_fixture_package_can_be_copied_anywhere(tmp_path: Path) -> None:
    copy_dir = tmp_path / "anywhere" / "dacha"
    shutil.copytree(DACHA_DIR, copy_dir)
    assert validate_source(copy_dir / "location.blueprint.json").issues == []


# --------------------------------------------------------------------------- versions


@pytest.mark.parametrize(
    ("version", "status", "code"),
    [
        ("1.0", VersionStatus.CURRENT, None),
        ("1.7", VersionStatus.TOO_NEW, "BLUEPRINT_VERSION_TOO_NEW"),
        ("2.0", VersionStatus.UNSUPPORTED, "BLUEPRINT_VERSION_UNSUPPORTED"),
        ("0.9", VersionStatus.UNSUPPORTED, "BLUEPRINT_VERSION_UNSUPPORTED"),
        ("1", VersionStatus.INVALID, "BLUEPRINT_VERSION_INVALID"),
        (1.0, VersionStatus.INVALID, "BLUEPRINT_VERSION_INVALID"),
        (None, VersionStatus.MISSING, "BLUEPRINT_VERSION_MISSING"),
    ],
)
def test_version_classification(version: Any, status: VersionStatus, code: str | None) -> None:
    data = location_data()
    if version is None:
        del data["schemaVersion"]
    else:
        data["schemaVersion"] = version
    found, _, issues = check_version(data)
    assert found is status
    assert [i.code for i in issues] == ([code] if code else [])
    result = validate_document(data, check_external=False)
    if code is not None:
        assert result.blueprint is None
        assert [i.code for i in result.issues] == [code]
        assert result.issues[0].category == "version" and result.issues[0].suggestion


def test_legacy_snake_case_documents_are_rejected_with_guidance() -> None:
    _, _, issues = check_version({"schema_version": "1.0", "id": "old"})
    assert [i.code for i in issues] == ["BLUEPRINT_LEGACY_FORMAT"]


def test_older_minor_versions_are_readable_by_newer_releases() -> None:
    status, version, issues = check_version({"schemaVersion": "1.0"}, current=SchemaVersion(1, 3))
    assert (status, str(version), issues) == (VersionStatus.READABLE, "1.0", [])


def _rename_title(document: dict[str, Any]) -> dict[str, Any]:
    document["name"] = document.pop("title")
    document["schemaVersion"] = "1.0"
    return document


LEGACY_REGISTRY = MigrationRegistry(
    [Migration(SchemaVersion(0, 9), SchemaVersion(1, 0), "rename title to name", _rename_title)]
)


def test_migration_chain_upgrades_a_copy() -> None:
    old = {**location_data(), "schemaVersion": "0.9", "title": "Old"}
    del old["name"]
    snapshot = copy.deepcopy(old)
    status, _, issues = check_version(old, registry=LEGACY_REGISTRY)
    assert status is VersionStatus.MIGRATABLE
    assert [i.code for i in issues] == ["BLUEPRINT_MIGRATION_REQUIRED"]
    result = migrate_document(old, registry=LEGACY_REGISTRY)
    assert result.changed and result.steps == ("0.9 -> 1.0: rename title to name",)
    assert result.document["name"] == "Old" and result.document["schemaVersion"] == "1.0"
    assert old == snapshot  # the input is never modified
    assert parse_blueprint(result.document, registry=LEGACY_REGISTRY).name == "Old"
    # A migratable document is not silently migrated during validation.
    assert validate_document(old, registry=LEGACY_REGISTRY).blueprint is None


def test_future_majors_cannot_be_migrated() -> None:
    with pytest.raises(UnsupportedVersionError):
        migrate_document(location_data(schemaVersion="2.0"))
    with pytest.raises(UnsupportedVersionError):
        migrate_document(location_data(schemaVersion="1.5"))


def test_broken_migrations_are_detected() -> None:
    forgetful = MigrationRegistry(
        [Migration(SchemaVersion(0, 9), SchemaVersion(1, 0), "forgets the version", lambda d: d)]
    )
    with pytest.raises(MigrationError, match="did not set schemaVersion"):
        migrate_document({"schemaVersion": "0.9"}, registry=forgetful)
    with pytest.raises(ValueError, match="newer"):
        MigrationRegistry([Migration(CURRENT_VERSION, SchemaVersion(0, 1), "down", lambda d: d)])
    gap = MigrationRegistry(
        [Migration(SchemaVersion(0, 8), SchemaVersion(0, 9), "half way", lambda d: d)]
    )
    assert not gap.can_migrate(SchemaVersion(0, 8), CURRENT_VERSION)


def test_migrate_file_requires_explicit_consent(tmp_path: Path) -> None:
    source = tmp_path / "location.blueprint.json"
    old = {**location_data(), "schemaVersion": "0.9", "title": "Old"}
    del old["name"]
    source.write_text(json.dumps(old), encoding="utf-8")
    original = source.read_bytes()

    result, written = migrate_file(source, registry=LEGACY_REGISTRY)
    assert written is None and source.read_bytes() == original  # dry run
    with pytest.raises(ExportError, match="original"):
        migrate_file(source, output=source, registry=LEGACY_REGISTRY)
    target = tmp_path / "migrated.json"
    _, written = migrate_file(source, output=target, registry=LEGACY_REGISTRY)
    assert written == target and source.read_bytes() == original
    assert load_blueprint(target).name == "Old"
    with pytest.raises(ExportError, match="exists"):
        migrate_file(source, output=target, registry=LEGACY_REGISTRY)

    _, written = migrate_file(source, in_place=True, registry=LEGACY_REGISTRY)
    assert written == source
    backup = tmp_path / "location.blueprint.json.v0.9.bak"
    assert backup.read_bytes() == original
    assert load_blueprint(source).name == "Old"
    assert result.source_version == SchemaVersion(0, 9)


# --------------------------------------------------------------------------- model invariants


def test_models_are_immutable_and_strict(dacha: LocationBlueprint) -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic raises its own frozen error
        dacha.name = "changed"  # type: ignore[misc]
    first = dacha.buildings[0]
    assert isinstance(first, Building)
    with pytest.raises(Exception):  # noqa: B017
        first.condition = 0.0  # type: ignore[misc]


def test_wires_and_points_are_discriminated_by_type() -> None:
    blueprint = make_location(
        infrastructure=[pole("p-1", 10, 10), pole("p-2", 40, 10), wire("w", ["p-1", "p-2"])]
    )
    kinds = [type(item).__name__ for item in blueprint.infrastructure]
    assert kinds == ["InfrastructurePoint", "InfrastructurePoint", "Wire"]
