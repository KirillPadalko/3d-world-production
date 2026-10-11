"""External files referenced by a blueprint (heightmaps, masks, source media).

Paths are relative to the **location package root**: by default the folder
that contains the blueprint file. They may never leave that folder (checked
again after resolving symbolic links).
"""

from __future__ import annotations

import hashlib
import math
import sys
from array import array
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from environment_generator.blueprint.diagnostics import Category, diagnostic
from environment_generator.core.errors import ExternalDataError
from environment_generator.core.issues import ValidationIssue
from environment_generator.models.blueprint import (
    FileReference,
    Heightmap,
    LocationBlueprint,
    RasterEncoding,
    RowOrder,
)
from environment_generator.models.blueprint.terrain import ENCODING_BYTES, RasterGrid

_HASH_CHUNK = 1 << 20


@dataclass(frozen=True)
class FileUse:
    """Where a file reference occurs and whether generation needs it."""

    path: str
    reference: FileReference
    required: bool
    owner_id: str | None
    raster: RasterGrid | None = None


def iter_file_references(blueprint: LocationBlueprint) -> Iterator[FileUse]:
    terrain = blueprint.terrain
    if terrain.heightmap is not None:
        yield FileUse(
            "terrain.heightmap.file", terrain.heightmap.file, True, None, terrain.heightmap
        )
    for i, mask in enumerate(terrain.masks):
        yield FileUse(f"terrain.masks[{i}].file", mask.file, True, mask.id, mask)
    source = blueprint.source
    if source is None:
        return
    for i, media in enumerate(source.media):
        yield FileUse(f"source.media[{i}].file", media.file, False, media.id)
    for i, frame in enumerate(source.frames):
        if frame.file is not None:
            yield FileUse(f"source.frames[{i}].file", frame.file, False, frame.id)
    for i, report in enumerate(source.analysis_reports):
        yield FileUse(f"source.analysisReports[{i}].file", report.file, False, report.id)


def resolve_package_path(root: Path, relative: str) -> Path:
    """Absolute path of ``relative`` inside ``root``; refuses to leave the package."""
    base = root.resolve()
    target = (base / relative).resolve()
    if target != base and base not in target.parents:
        raise ExternalDataError(f"'{relative}' resolves outside the location package")
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def check_files(blueprint: LocationBlueprint, root: Path | None) -> list[ValidationIssue]:
    """Existence, containment, size, checksum and raster shape of every reference."""
    uses = list(iter_file_references(blueprint))
    if not uses:
        return []
    if root is None:
        return [
            diagnostic(
                "warning",
                "EXTERNAL_FILES_NOT_CHECKED",
                f"{len(uses)} external file reference(s) were not checked: no package root.",
                category=Category.EXTERNAL,
                suggestion="Load the blueprint from a file or pass the package root.",
            )
        ]
    issues: list[ValidationIssue] = []
    for use in uses:
        owner = [use.owner_id] if use.owner_id else []
        try:
            path = resolve_package_path(root, use.reference.path)
        except ExternalDataError as exc:
            issues.append(
                diagnostic(
                    "error",
                    "EXTERNAL_PATH_ESCAPES_PACKAGE",
                    str(exc),
                    category=Category.EXTERNAL,
                    path=use.path,
                    entity_ids=owner,
                    suggestion="Keep external files inside the location package folder.",
                )
            )
            continue
        if not path.is_file():
            issues.append(
                diagnostic(
                    "error" if use.required else "warning",
                    "EXTERNAL_FILE_MISSING",
                    f"File '{use.reference.path}' does not exist in the location package."
                    + ("" if use.required else " (source material; not needed to generate)"),
                    category=Category.EXTERNAL,
                    path=use.path,
                    entity_ids=owner,
                    suggestion="Add the file or fix the relative path.",
                )
            )
            continue
        size = path.stat().st_size
        expected = use.reference.size_bytes
        if expected is not None and expected != size:
            issues.append(
                diagnostic(
                    "error",
                    "EXTERNAL_FILE_SIZE_MISMATCH",
                    f"'{use.reference.path}' has {size} bytes, sizeBytes says {expected}.",
                    category=Category.EXTERNAL,
                    path=use.path,
                    entity_ids=owner,
                    suggestion="Update sizeBytes or replace the file with the intended one.",
                )
            )
        if use.reference.sha256 is not None and _sha256(path) != use.reference.sha256:
            issues.append(
                diagnostic(
                    "error",
                    "EXTERNAL_FILE_CHECKSUM_MISMATCH",
                    f"'{use.reference.path}' does not match its sha256.",
                    category=Category.EXTERNAL,
                    path=use.path,
                    entity_ids=owner,
                    suggestion="Recompute sha256 if the file was intentionally replaced.",
                )
            )
        if use.raster is not None:
            raster = use.raster
            expected_size = raster.columns * raster.rows * ENCODING_BYTES[raster.encoding]
            if size != expected_size:
                issues.append(
                    diagnostic(
                        "error",
                        "EXTERNAL_RASTER_SIZE_MISMATCH",
                        f"'{use.reference.path}' has {size} bytes; {raster.columns} x "
                        f"{raster.rows} {raster.encoding.value} needs {expected_size}.",
                        category=Category.EXTERNAL,
                        path=use.path,
                        entity_ids=owner,
                        suggestion="Check columns, rows and encoding against the file.",
                    )
                )
    return issues


@dataclass(frozen=True)
class HeightSamples:
    """Decoded heightmap in metres, rows ordered south to north."""

    columns: int
    rows: int
    heights: list[list[float]]

    @property
    def minimum(self) -> float:
        return min(min(row) for row in self.heights)

    @property
    def maximum(self) -> float:
        return max(max(row) for row in self.heights)


def read_heightmap(heightmap: Heightmap, root: Path) -> HeightSamples:
    """Decode a raw little-endian heightmap into metres (rows south to north)."""
    path = resolve_package_path(root, heightmap.file.path)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ExternalDataError(f"Cannot read heightmap '{heightmap.file.path}': {exc}") from exc
    typecode = "H" if heightmap.encoding is RasterEncoding.RAW_U16_LE else "f"
    values = array(typecode)
    expected = heightmap.columns * heightmap.rows * values.itemsize
    if len(payload) != expected:
        raise ExternalDataError(
            f"Heightmap '{heightmap.file.path}' has {len(payload)} bytes, expected {expected}."
        )
    values.frombytes(payload)
    if sys.byteorder == "big":  # pragma: no cover - CI runs little-endian
        values.byteswap()
    scale, offset = heightmap.height_scale_m, heightmap.height_offset_m
    rows: list[list[float]] = []
    for r in range(heightmap.rows):
        start = r * heightmap.columns
        row = [offset + float(v) * scale for v in values[start : start + heightmap.columns]]
        if not all(math.isfinite(h) for h in row):
            raise ExternalDataError(
                f"Heightmap '{heightmap.file.path}' contains non-finite values."
            )
        rows.append(row)
    if heightmap.row_order is RowOrder.NORTH_TO_SOUTH:
        rows.reverse()
    return HeightSamples(heightmap.columns, heightmap.rows, rows)
