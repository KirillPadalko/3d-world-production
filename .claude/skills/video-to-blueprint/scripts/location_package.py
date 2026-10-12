#!/usr/bin/env python3
"""Create a location package's blueprint and keep its ``source`` in step with the frames.

Run from the repository root with ``uv run python``, because it uses the
environment_generator package to validate and write canonical JSON::

    init --package DIR --location-id ID --name NAME --width M --depth M [options]
        write DIR/location.blueprint.json: a valid, empty blueprint whose `source`
        is analysis/source.json (written by frames.py). Never replaces a file.
    sync-source --package DIR [--write]
        compare the blueprint's source media, frame extractions, frames and frame
        indexes with analysis/source.json; with --write, update them (a backup
        <blueprint>.bak is written first; refused if cited frames would vanish
        or the document would gain errors).
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from environment_generator.blueprint import (
    DEFAULT_FILENAME,
    dumps_blueprint,
    save_blueprint,
    validate_document,
)
from environment_generator.core.issues import Severity

SKILL = "video-to-blueprint skill"
SKILL_VERSION = "1"
FRAMES_TOOL = "video-to-blueprint/frames.py"
#: Lists in `source` that frames.py owns, merged by ID.
OWNED = ("media", "frameExtractions", "frames")

COORDINATE_SYSTEM = {
    "unit": "meter",
    "upAxis": "+y",
    "eastAxis": "+x",
    "northAxis": "+z",
    "handedness": "left",
    "yawConvention": "degrees_clockwise_from_north",
    "origin": "southwest_corner",
}


class PackageError(Exception):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PackageError(f"{path} not found") from exc
    except json.JSONDecodeError as exc:
        raise PackageError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PackageError(f"{path} does not hold a JSON object")
    return data


def errors_of(document: dict[str, Any], package: Path) -> list[str]:
    result = validate_document(document, package_root=package)
    return [
        f"{issue.code} {issue.path or ''}: {issue.message}"
        for issue in result.issues
        if issue.severity is Severity.ERROR
    ]


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def initial_document(args: argparse.Namespace, package: Path) -> dict[str, Any]:
    source_path = package / "analysis" / "source.json"
    if source_path.exists():
        source = read_json(source_path)
    elif args.allow_no_frames:
        source = {"type": "manual", "description": "No frames extracted yet."}
    else:
        raise PackageError(
            f"{source_path} not found: run frames.py extract first "
            "(or pass --allow-no-frames for a blueprint without footage)"
        )
    calibration: dict[str, Any] = {"method": args.calibration}
    calibration["notes"] = args.calibration_notes or (
        "Not calibrated: sizes and positions are visual estimates from reference objects."
        if args.calibration == "none"
        else "See source.referencePoints and the analysis notes."
    )
    source["calibration"] = calibration
    metadata: dict[str, Any] = {
        "createdAt": args.created_at or now_utc(),
        "createdBy": {"name": SKILL, "version": SKILL_VERSION},
        "biome": args.biome,
        "season": args.season,
    }
    if args.author:
        metadata["authors"] = args.author
    if args.tag:
        metadata["tags"] = args.tag
    if args.region:
        metadata["region"] = args.region
    coordinate_system: dict[str, Any] = {
        **COORDINATE_SYSTEM,
        "bounds": {"widthM": args.width, "depthM": args.depth},
    }
    if args.geo:
        geo: dict[str, Any] = {"latitude": args.geo[0], "longitude": args.geo[1]}
        if args.heading is not None:
            geo["headingDeg"] = args.heading % 360.0
        if args.geo_accuracy is not None:
            geo["accuracyM"] = args.geo_accuracy
        coordinate_system["geoReference"] = geo
    document: dict[str, Any] = {
        "schemaVersion": "1.0",
        "locationId": args.location_id,
        "name": args.name,
    }
    if args.description:
        document["description"] = args.description
    document |= {"metadata": metadata, "coordinateSystem": coordinate_system, "source": source}
    return document


def cmd_init(args: argparse.Namespace) -> int:
    package = Path(args.package).resolve()
    target = package / DEFAULT_FILENAME
    if target.exists():
        raise PackageError(
            f"{target} exists; edit it, or use `sync-source` to update its source section"
        )
    document = initial_document(args, package)
    result = validate_document(document, package_root=package)
    errors = [i for i in result.issues if i.severity is Severity.ERROR]
    if result.blueprint is None or errors:
        details = "\n".join(f"  {i.code} {i.path or ''}: {i.message}" for i in result.issues)
        raise PackageError(f"the new blueprint would be invalid:\n{details}")
    save_blueprint(result.blueprint, target)
    source = document["source"]
    print(f"Created {target}")
    print(
        f"  source: {len(source.get('media', []))} media, "
        f"{len(source.get('frameExtractions', []))} extraction(s), "
        f"{len(source.get('frames', []))} frame(s)"
    )
    for issue in result.issues:
        print(f"  {issue.severity.value}: {issue.code} {issue.message}")
    return 0


def _merge(
    current: list[dict[str, Any]], fresh: list[dict[str, Any]], owned: set[str]
) -> list[Any]:
    """Fresh items replace current items with the same ID; items in ``owned`` groups
    that are no longer fresh are dropped; everything else is kept in place."""
    fresh_ids = {item["id"] for item in fresh}
    kept = [item for item in current if item["id"] not in fresh_ids and item["id"] not in owned]
    return kept + fresh


def merged_source(blueprint: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    current = copy.deepcopy(blueprint.get("source") or {"type": "video"})
    if current.get("type") in {"manual", "synthetic"}:
        current["type"] = "mixed"
    # Extractions written by frames.py (recognised by their index report) are owned by
    # it: their frames are replaced by the current ones. Media are only ever added or
    # updated, and everything authored by hand is kept.
    owned_extractions = {
        str(item["id"]).removesuffix("-index")
        for item in current.get("analysisReports", [])
        if (item.get("tool") or {}).get("name") == FRAMES_TOOL
    } | {item["id"] for item in analysis.get("frameExtractions", [])}
    owned_frames = {
        item["id"]
        for item in current.get("frames", [])
        if item.get("extractionId") in owned_extractions
    }
    current["media"] = _merge(current.get("media", []), analysis.get("media", []), set())
    current["frameExtractions"] = _merge(
        current.get("frameExtractions", []), analysis.get("frameExtractions", []), owned_extractions
    )
    current["frames"] = _merge(current.get("frames", []), analysis.get("frames", []), owned_frames)
    reports = [
        item
        for item in current.get("analysisReports", [])
        if (item.get("tool") or {}).get("name") != FRAMES_TOOL
    ]
    current["analysisReports"] = reports + analysis.get("analysisReports", [])
    for key in ("media", "frameExtractions", "frames", "analysisReports"):
        if not current[key]:
            del current[key]
    if "description" not in current and "description" in analysis:
        current["description"] = analysis["description"]
    return current


def cited_frames(document: dict[str, Any]) -> dict[str, list[str]]:
    """frame ID -> IDs of the objects citing it (any `frameIds` list in the document)."""
    cited: dict[str, list[str]] = {}

    def walk(value: Any, owner: str | None) -> None:
        if isinstance(value, dict):
            owner = value.get("id", owner) if isinstance(value.get("id"), str) else owner
            for key, item in value.items():
                if key == "frameIds" and isinstance(item, list):
                    for frame in item:
                        cited.setdefault(str(frame), []).append(owner or "?")
                else:
                    walk(item, owner)
        elif isinstance(value, list):
            for item in value:
                walk(item, owner)

    walk({k: v for k, v in document.items() if k != "source"}, None)
    walk((document.get("source") or {}).get("observations", []), None)
    return cited


def describe_change(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    lines = []
    for key in (*OWNED, "analysisReports"):
        old = {item["id"]: item for item in before.get(key, [])}
        new = {item["id"]: item for item in after.get(key, [])}
        added = sorted(new.keys() - old.keys())
        removed = sorted(old.keys() - new.keys())
        changed = sorted(k for k in new.keys() & old.keys() if new[k] != old[k])
        if added or removed or changed:
            lines.append(f"  {key}: +{len(added)} -{len(removed)} ~{len(changed)}")
    return lines


def cmd_sync(args: argparse.Namespace) -> int:
    package = Path(args.package).resolve()
    target = package / DEFAULT_FILENAME
    document = read_json(target)
    analysis = read_json(package / "analysis" / "source.json")
    updated = copy.deepcopy(document)
    updated["source"] = merged_source(document, analysis)
    changes = describe_change(document.get("source") or {}, updated["source"])
    if not changes:
        print("source is up to date")
        return 0
    print("source changes:")
    print("\n".join(changes))
    before_frames = {item["id"] for item in (document.get("source") or {}).get("frames", [])}
    after_frames = {item["id"] for item in updated["source"].get("frames", [])}
    lost = {
        frame: owners
        for frame, owners in cited_frames(updated).items()
        if frame in before_frames and frame not in after_frames
    }
    if lost:
        details = "\n".join(
            f"  {frame} (cited by {', '.join(owners)})" for frame, owners in sorted(lost.items())
        )
        raise PackageError(f"these cited frames would no longer exist:\n{details}")
    if not args.write:
        print("dry run: pass --write to update the blueprint")
        return 0
    before, after = errors_of(document, package), errors_of(updated, package)
    if len(after) > len(before):
        details = "\n".join(f"  {line}" for line in after if line not in before)
        raise PackageError(f"the update would add errors:\n{details}")
    backup = target.with_name(target.name + ".bak")
    shutil.copy2(target, backup)
    result = validate_document(updated, package_root=package)
    if result.blueprint is not None and not after:
        text = dumps_blueprint(result.blueprint)
    else:
        text = json.dumps(updated, indent=2, ensure_ascii=False) + "\n"
    target.write_text(text, encoding="utf-8")
    print(f"updated {target.name} (backup: {backup.name})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="location_package.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a new blueprint in a location package")
    init.add_argument("--package", required=True)
    init.add_argument("--location-id", required=True)
    init.add_argument("--name", required=True)
    init.add_argument("--description")
    init.add_argument("--width", type=float, required=True, help="bounds along +X (east), m")
    init.add_argument("--depth", type=float, required=True, help="bounds along +Z (north), m")
    init.add_argument("--biome", default="unknown")
    init.add_argument("--season", default="unknown")
    init.add_argument("--region")
    init.add_argument("--author", action="append")
    init.add_argument("--tag", action="append")
    init.add_argument("--created-at", help="ISO 8601 with time zone (default: now)")
    init.add_argument(
        "--calibration",
        default="none",
        choices=["none", "manual_scale", "reference_points", "gps", "photogrammetry", "survey"],
    )
    init.add_argument("--calibration-notes")
    init.add_argument("--geo", type=float, nargs=2, metavar=("LAT", "LON"))
    init.add_argument("--heading", type=float, help="compass bearing of local +Z, degrees")
    init.add_argument("--geo-accuracy", type=float, help="metres")
    init.add_argument("--allow-no-frames", action="store_true")
    init.set_defaults(func=cmd_init)

    sync = sub.add_parser("sync-source", help="update source from analysis/source.json")
    sync.add_argument("--package", required=True)
    sync.add_argument("--write", action="store_true")
    sync.set_defaults(func=cmd_sync)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    func: Callable[[argparse.Namespace], int] = args.func
    try:
        return func(args)
    except PackageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
