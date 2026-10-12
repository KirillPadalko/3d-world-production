#!/usr/bin/env python3
"""Validate a blueprint and review it the way the video-to-blueprint skill requires.

Run from the repository root::

    uv run python .claude/skills/video-to-blueprint/scripts/review_blueprint.py \
        locations/<id>/location.blueprint.json [--json] [--strict] [--limit N]

Two layers of findings, in one report:

1. the contract validation of ``envgen blueprint validate`` (codes from
   docs/LOCATION_BLUEPRINT.md#validation-and-diagnostics);
2. review checks for blueprints derived from footage (codes ``REVIEW_*``):
   provenance and evidence, confidence against calibration, sizes against
   ``size_rules.json``, archetypes against the asset registry, copy-paste
   mistakes and whether ``source`` matches the extracted frames.

Exit code: 0 when there is no error (warnings allowed), 1 with errors, 2 with
warnings under ``--strict``. Review checks never change the file.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from environment_generator.assets import load_builtin_registry
from environment_generator.blueprint import EntityIndex, validate_source
from environment_generator.core.issues import Severity, ValidationIssue
from environment_generator.models.assets import AssetRegistryDocument
from environment_generator.models.blueprint import LocationBlueprint, ProvenanceCategory

SKILL_DIR = Path(__file__).resolve().parents[1]
RULES_PATH = SKILL_DIR / "size_rules.json"
FOOTAGE_SOURCES = {"video", "images", "mixed", "survey", "satellite"}
MEASURED = {ProvenanceCategory.OBSERVED, ProvenanceCategory.INFERRED}
#: Collections that describe physical things (gameplay and source items are not checked).
PHYSICAL = {
    "roadNodes",
    "roadSegments",
    "surfaceZones",
    "slopeZones",
    "waterBodies",
    "plots",
    "buildings",
    "vegetationZones",
    "trees",
    "fences",
    "infrastructure",
    "props",
    "landmarks",
}
ARCHETYPE_CATEGORIES = {
    "buildings": "building",
    "fences": "fence",
    "infrastructure": "infrastructure",
    "props": "prop",
    "trees": "vegetation",
}
UNCALIBRATED_MAX_CONFIDENCE = 0.8


def finding(
    severity: str,
    code: str,
    message: str,
    *,
    path: str | None = None,
    entity_ids: Sequence[str] = (),
    suggestion: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        severity=Severity(severity),
        code=code,
        message=message,
        category="review",
        path=path,
        entity_ids=tuple(entity_ids),
        suggestion=suggestion,
    )


def polygon_area(points: Sequence[Sequence[float]]) -> float:
    total = 0.0
    for (x1, z1), (x2, z2) in zip(points, [*points[1:], points[0]], strict=True):
        total += x1 * z2 - x2 * z1
    return abs(total) / 2


def range_finding(
    value: float,
    limits: dict[str, list[float]],
    *,
    what: str,
    path: str,
    entity_id: str,
    upper_only: bool = False,
) -> ValidationIssue | None:
    low, high = limits["plausible"]
    if upper_only:
        low = 0.0
    if not low <= value <= high:
        return finding(
            "warning",
            "REVIEW_SIZE_IMPLAUSIBLE",
            f"{what} {value:g} is outside the plausible range {low:g}-{high:g}",
            path=path,
            entity_ids=[entity_id],
            suggestion="re-measure against two reference objects (reference/sizes.md); "
            "a factor of 2-3 usually means a wrong scale or a unit mix-up",
        )
    low, high = limits["typical"]
    if upper_only:
        low = 0.0
    if not low <= value <= high:
        return finding(
            "info",
            "REVIEW_SIZE_UNUSUAL",
            f"{what} {value:g} is outside the typical range {low:g}-{high:g}",
            path=path,
            entity_ids=[entity_id],
            suggestion="fine if the footage shows it; otherwise re-measure",
        )
    return None


class Reviewer:
    def __init__(
        self,
        blueprint: LocationBlueprint,
        package: Path,
        rules: dict[str, Any],
        registry: AssetRegistryDocument,
    ) -> None:
        self.blueprint = blueprint
        self.package = package
        self.rules = rules
        self.registry = registry
        self.index = EntityIndex.build(blueprint)
        self.findings: list[ValidationIssue] = []

    def add(self, issue: ValidationIssue | None) -> None:
        if issue is not None:
            self.findings.append(issue)

    def run(self) -> list[ValidationIssue]:
        self.provenance()
        self.sizes()
        self.archetypes()
        self.copy_paste()
        self.source_in_step()
        return self.findings

    # ------------------------------------------------------------------ provenance

    def physical(self) -> Iterable[tuple[str, str, Any]]:
        for obj in self.index.objects.values():
            if obj.kind in PHYSICAL:
                yield obj.kind, obj.path, obj.item

    def provenance(self) -> None:
        source = self.blueprint.source
        from_footage = source is not None and source.type.value in FOOTAGE_SOURCES
        calibration = source.calibration if source else None
        uncalibrated = calibration is None or calibration.method == "none"
        calibration_error = calibration.estimated_error_m if calibration else None
        physical = list(self.physical())
        if not physical:
            self.add(
                finding(
                    "warning",
                    "REVIEW_NO_ENTITIES",
                    "the blueprint describes nothing yet",
                    suggestion="map roads, plots, buildings, fences and vegetation first",
                )
            )
        measured_ids = []
        for kind, path, item in physical:
            prov = getattr(item, "provenance", None)
            entity = [item.id]
            if prov is None:
                if from_footage:
                    self.add(
                        finding(
                            "warning",
                            "REVIEW_PROVENANCE_MISSING",
                            f"{kind} entity has no provenance",
                            path=path,
                            entity_ids=entity,
                            suggestion="say whether it is observed, inferred or manual "
                            "(reference/provenance.md)",
                        )
                    )
                continue
            if prov.category not in MEASURED:
                continue
            measured_ids.append(item.id)
            if prov.category is ProvenanceCategory.OBSERVED and not (
                prov.frame_ids or prov.observation_ids
            ):
                self.add(
                    finding(
                        "warning",
                        "REVIEW_OBSERVED_WITHOUT_EVIDENCE",
                        "observed, but cites no frame or observation",
                        path=f"{path}.provenance",
                        entity_ids=entity,
                        suggestion="add the frameIds it is visible in, or make it inferred",
                    )
                )
            if prov.category is ProvenanceCategory.INFERRED and not (
                prov.notes or prov.observation_ids or prov.frame_ids
            ):
                self.add(
                    finding(
                        "warning",
                        "REVIEW_INFERRED_WITHOUT_REASON",
                        "inferred, but neither notes, observations nor frames explain why",
                        path=f"{path}.provenance",
                        entity_ids=entity,
                        suggestion="write the evidence into provenance.notes "
                        "('fence line continues behind the hedge in f-...')",
                    )
                )
            if (
                uncalibrated
                and prov.confidence is not None
                and prov.confidence > UNCALIBRATED_MAX_CONFIDENCE
            ):
                self.add(
                    finding(
                        "warning",
                        "REVIEW_CONFIDENCE_ABOVE_CALIBRATION",
                        f"confidence {prov.confidence:g} without calibration "
                        f"(at most {UNCALIBRATED_MAX_CONFIDENCE:g})",
                        path=f"{path}.provenance.confidence",
                        entity_ids=entity,
                        suggestion="lower it, or calibrate (reference points, GPS telemetry) "
                        "and record source.calibration",
                    )
                )
            if prov.position_accuracy_m is None and kind != "roadSegments":
                self.add(
                    finding(
                        "info",
                        "REVIEW_POSITION_ACCURACY_MISSING",
                        "no positionAccuracyM",
                        path=f"{path}.provenance",
                        entity_ids=entity,
                        suggestion="state the 1-sigma horizontal error in metres",
                    )
                )
            elif prov.position_accuracy_m is not None and (
                (calibration_error is not None and prov.position_accuracy_m < calibration_error)
                or (uncalibrated and prov.position_accuracy_m < 0.5)
            ):
                floor = calibration_error if calibration_error is not None else 0.5
                self.add(
                    finding(
                        "warning",
                        "REVIEW_POSITION_ACCURACY_OPTIMISTIC",
                        f"positionAccuracyM {prov.position_accuracy_m:g} is better than "
                        f"the calibration allows ({floor:g} m)",
                        path=f"{path}.provenance.positionAccuracyM",
                        entity_ids=entity,
                        suggestion="an entity cannot be placed more precisely than the map",
                    )
                )
        if measured_ids and source is not None and source.type.value in {"manual", "synthetic"}:
            self.add(
                finding(
                    "warning",
                    "REVIEW_SOURCE_NOT_FOOTAGE",
                    f"{len(measured_ids)} entities are observed or inferred, "
                    f"but source.type is '{source.type.value}'",
                    path="source.type",
                    entity_ids=measured_ids[:10],
                    suggestion="use type video / images / mixed and list the real material",
                )
            )
        if source is not None and source.frames:
            cited = {
                frame
                for _, _, item in physical
                if getattr(item, "provenance", None) is not None
                for frame in item.provenance.frame_ids
            }
            cited |= {f for obs in source.observations for f in obs.frame_ids}
            self.add(
                finding(
                    "info",
                    "REVIEW_EVIDENCE_COVERAGE",
                    f"{len(cited)} of {len(source.frames)} frames are cited as evidence",
                    path="source.frames",
                )
            )

    # ------------------------------------------------------------------ sizes

    def sizes(self) -> None:
        rules = self.rules
        bp = self.blueprint
        for i, building in enumerate(bp.buildings):
            limits = rules["buildings"].get(building.building_type.value)
            path = f"buildings[{i}].dimensions"
            # A ruin or a collapsed roof can be as low as it likes.
            damaged = building.condition < 0.5 or building.roof_type.value == "collapsed"
            if limits:
                for field_name, value in (
                    ("widthM", building.dimensions.width_m),
                    ("depthM", building.dimensions.depth_m),
                    ("heightM", building.dimensions.height_m),
                ):
                    self.add(
                        range_finding(
                            value,
                            limits[field_name],
                            what=f"{building.building_type.value} {field_name}",
                            path=f"{path}.{field_name}",
                            entity_id=building.id,
                            upper_only=damaged and field_name == "heightM",
                        )
                    )
            if building.floors:
                floors = rules["floors"]
                ceiling = building.floors * floors["storeyHeightM"] + floors["roofAllowanceM"]
                if building.dimensions.height_m > ceiling:
                    self.add(
                        finding(
                            "warning",
                            "REVIEW_HEIGHT_FOR_FLOORS",
                            f"heightM {building.dimensions.height_m:g} is too tall for "
                            f"{building.floors} floor(s) (at most about {ceiling:g})",
                            path=f"{path}.heightM",
                            entity_ids=[building.id],
                            suggestion="count the window rows again or re-measure the height",
                        )
                    )
        for i, plot in enumerate(bp.plots):
            limits = rules["plots"].get(plot.plot_type.value)
            if limits:
                self.add(
                    range_finding(
                        round(polygon_area(plot.polygon), 1),
                        limits["areaM2"],
                        what=f"{plot.plot_type.value} area (m2)",
                        path=f"plots[{i}].polygon",
                        entity_id=plot.id,
                    )
                )
        for i, fence in enumerate(bp.fences):
            limits = rules["fences"].get(fence.fence_type.value)
            if limits:
                self.add(
                    range_finding(
                        fence.height_m,
                        limits["heightM"],
                        what=f"{fence.fence_type.value} fence heightM",
                        path=f"fences[{i}].heightM",
                        entity_id=fence.id,
                    )
                )
        for i, item in enumerate(bp.infrastructure):
            kind = item.infrastructure_type
            height = getattr(item, "height_m", None)
            limits = rules["infrastructure"].get(str(getattr(kind, "value", kind)))
            if limits and height is not None:
                self.add(
                    range_finding(
                        height,
                        limits["heightM"],
                        what=f"{getattr(kind, 'value', kind)} heightM",
                        path=f"infrastructure[{i}].heightM",
                        entity_id=item.id,
                    )
                )
        for i, tree in enumerate(bp.trees):
            limits = rules["trees"].get(tree.species, rules["trees"]["unknown"])
            for field_name, measured in (
                ("heightM", tree.height_m),
                ("crownDiameterM", tree.crown_diameter_m),
            ):
                if measured is not None:
                    self.add(
                        range_finding(
                            measured,
                            limits[field_name],
                            what=f"{tree.species} tree {field_name}",
                            path=f"trees[{i}].{field_name}",
                            entity_id=tree.id,
                        )
                    )
        for i, segment in enumerate(bp.roads.segments):
            limits = rules["roads"].get(segment.importance.value)
            if limits:
                self.add(
                    range_finding(
                        segment.width_m,
                        limits["widthM"],
                        what=f"{segment.importance.value} road widthM",
                        path=f"roads.segments[{i}].widthM",
                        entity_id=segment.id,
                    )
                )

    # ------------------------------------------------------------------ archetypes

    def archetypes(self) -> None:
        names: dict[str, set[str]] = {}
        for archetype in self.registry.archetypes:
            bucket = names.setdefault(archetype.category.value, set())
            bucket.add(archetype.id)
            bucket.update(archetype.kinds)
        for collection, category in ARCHETYPE_CATEGORIES.items():
            for i, item in enumerate(getattr(self.blueprint, _snake(collection))):
                hint = getattr(item, "archetype", None)
                if hint and hint not in names.get(category, set()):
                    self.add(
                        finding(
                            "warning",
                            "REVIEW_ARCHETYPE_UNKNOWN",
                            f"archetype '{hint}' is neither an archetype ID nor a kind "
                            f"of any {category} archetype in registry '{self.registry.id}'",
                            path=f"{collection}[{i}].archetype",
                            entity_ids=[item.id],
                            suggestion="pick one from `uv run envgen assets list --category "
                            f"{category}`, or remove it so the type decides",
                        )
                    )

    # ------------------------------------------------------------------ copy-paste

    def copy_paste(self) -> None:
        for collection in ("buildings", "trees", "infrastructure", "props"):
            seen: dict[tuple[float, float], Any] = {}
            for i, item in enumerate(getattr(self.blueprint, collection)):
                transform = getattr(item, "transform", None)
                if transform is None:
                    continue
                key = (transform.position[0], transform.position[2])
                other = seen.setdefault(key, item)
                if other is item:
                    continue
                # A lamp on its pole shares the pole's position on purpose.
                if other.id == getattr(item, "parent_id", None) or item.id == getattr(
                    other, "parent_id", None
                ):
                    continue
                self.add(
                    finding(
                        "warning",
                        "REVIEW_DUPLICATE_POSITION",
                        f"same position as {other.id}",
                        path=f"{collection}[{i}].transform.position",
                        entity_ids=[item.id, other.id],
                        suggestion="a copied entity that was never moved?",
                    )
                )
        buildings = self.blueprint.buildings
        if len(buildings) >= 3 and all(b.transform.yaw_deg == 0 for b in buildings):
            self.add(
                finding(
                    "info",
                    "REVIEW_YAW_ALL_ZERO",
                    f"all {len(buildings)} buildings face exactly north (yawDeg 0)",
                    path="buildings",
                    suggestion="yawDeg is the direction the entrance side faces",
                )
            )

    # ------------------------------------------------------------------ source

    def source_in_step(self) -> None:
        analysis_path = self.package / "analysis" / "source.json"
        if not analysis_path.exists():
            return
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        source = self.blueprint.source
        listed = {f.id for f in source.frames} if source else set()
        listed_media = {m.id for m in source.media} if source else set()
        missing = [f["id"] for f in analysis.get("frames", []) if f["id"] not in listed]
        missing_media = [m["id"] for m in analysis.get("media", []) if m["id"] not in listed_media]
        if missing or missing_media:
            self.add(
                finding(
                    "warning",
                    "REVIEW_SOURCE_OUT_OF_DATE",
                    f"analysis/source.json has {len(missing)} frame(s) and "
                    f"{len(missing_media)} media item(s) that the blueprint does not list",
                    path="source",
                    entity_ids=(missing_media + missing)[:10],
                    suggestion="uv run python .claude/skills/video-to-blueprint/scripts/"
                    "location_package.py sync-source --package <dir> --write",
                )
            )


def _snake(name: str) -> str:
    return "".join(f"_{c.lower()}" if c.isupper() else c for c in name)


def load_registry(path: str | None) -> AssetRegistryDocument:
    if path is None:
        return load_builtin_registry()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return AssetRegistryDocument.model_validate(data, by_alias=True, by_name=False)


def review(
    blueprint_path: Path, *, rules_path: Path = RULES_PATH, registry: str | None = None
) -> tuple[list[ValidationIssue], list[ValidationIssue], bool]:
    """(contract diagnostics, review findings, whether the review ran)."""
    result = validate_source(blueprint_path)
    if result.blueprint is None:
        return list(result.issues), [], False
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    reviewer = Reviewer(
        result.blueprint, blueprint_path.resolve().parent, rules, load_registry(registry)
    )
    return list(result.issues), reviewer.run(), True


ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


def render_text(name: str, issues: Sequence[ValidationIssue], reviewed: bool, limit: int) -> str:
    counts = Counter(issue.severity for issue in issues)
    lines = [
        f"{name}: {counts[Severity.ERROR]} error(s), {counts[Severity.WARNING]} warning(s), "
        f"{counts[Severity.INFO]} info"
    ]
    if not reviewed:
        lines.append("review checks run once the document passes the schema phase")
    by_code: dict[tuple[Severity, str], list[ValidationIssue]] = {}
    for issue in sorted(issues, key=lambda i: (ORDER[i.severity], i.code, i.path or "")):
        by_code.setdefault((issue.severity, issue.code), []).append(issue)
    for (severity, code), group in by_code.items():
        lines.append(f"\n{severity.value.upper()} {code} ({len(group)})")
        shown = group[:limit]
        shared = {i.suggestion for i in shown}
        for issue in shown:
            where = issue.path or "-"
            ids = f" [{', '.join(issue.entity_ids)}]" if issue.entity_ids else ""
            lines.append(f"  {where}{ids}: {issue.message}")
            if len(shared) > 1 and issue.suggestion:
                lines.append(f"      fix: {issue.suggestion}")
        if len(group) > limit:
            lines.append(f"  ... {len(group) - limit} more")
        if len(shared) == 1 and shown[0].suggestion:
            lines.append(f"  fix: {shown[0].suggestion}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="review_blueprint.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("blueprint")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--strict", action="store_true", help="exit 2 when warnings remain")
    parser.add_argument("--limit", type=int, default=15, help="lines per code in text output")
    parser.add_argument("--rules", default=str(RULES_PATH))
    parser.add_argument("--registry", help="asset registry JSON (default: built-in)")
    args = parser.parse_args(argv)
    path = Path(args.blueprint)
    if not path.is_file():
        print(f"error: {path} not found", file=sys.stderr)
        return 1
    contract, findings, reviewed = review(path, rules_path=Path(args.rules), registry=args.registry)
    issues = [*contract, *findings]
    if args.json:
        payload = {
            "document": str(path),
            "valid": not any(i.severity is Severity.ERROR for i in contract),
            "reviewed": reviewed,
            "counts": {s.value: sum(1 for i in issues if i.severity is s) for s in ORDER},
            "diagnostics": [i.model_dump(mode="json", exclude_none=True) for i in issues],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(render_text(path.name, issues, reviewed, max(1, args.limit)))
    if any(i.severity is Severity.ERROR for i in issues):
        return 1
    if args.strict and any(i.severity is Severity.WARNING for i in issues):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
