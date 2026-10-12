#!/usr/bin/env python3
"""Frame extraction for the video-to-blueprint skill (ffmpeg / ffprobe).

Subcommands::

    probe   VIDEO                         describe a video as JSON
    extract VIDEO --package DIR [...]     copy the video into a location package, extract
                                          frames, labelled contact sheets and an index,
                                          then rebuild analysis/source.json
    source  --package DIR                 rebuild analysis/source.json from the indexes
    grid    --package DIR --frame ID      copy of a frame with a labelled 0.1 grid
    crop    --package DIR --frame ID --box U0 V0 U1 V1
                                          full-resolution detail of a frame region
    render  SVG [--output PNG]            rasterise an SVG (the generator's preview.svg)
                                          so it can be compared with a frame

Layout written into the package::

    media/<video>                         the footage (and its telemetry sidecar)
    frames/<extractionId>/<frameId>.jpg   extracted frames
    frames/<extractionId>/sheets/         contact sheets (frame ID and time on each tile)
    analysis/frames-<extractionId>.json   index: frames, times, telemetry, sheets
    analysis/source.json                  a LocationBlueprint `source` section built
                                          only from files that exist

Frame IDs are derived from the extraction ID and the timestamp in milliseconds
(``vid-dji-0042-x01-00012500``), so re-running an extraction yields the same IDs.
Image coordinates used by ``grid`` and ``crop`` are normalised: ``u`` from the
left edge (0) to the right edge (1), ``v`` from the top edge (0) to the bottom (1).

Only the standard library is used; ffmpeg and ffprobe must be on PATH.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import itertools
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TOOL_NAME = "video-to-blueprint/frames.py"
TOOL_VERSION = "1"
INDEX_VERSION = 1
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
#: Diagonal of a 36 x 24 mm frame; "35 mm equivalent" focal lengths refer to it.
FULL_FRAME_DIAGONAL_MM = math.hypot(36.0, 24.0)

METHODS = {"interval": "fixed_interval", "scene": "keyframes", "manual": "manual"}
VIDEO_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".mts": "video/mp2t",
    ".ts": "video/mp2t",
}
SIDECAR_SUFFIXES = (".SRT", ".srt")


class FramesError(Exception):
    """A problem the user has to fix (missing tool, bad option, unreadable video)."""


# --------------------------------------------------------------------------- pure helpers


def slug(text: str, max_length: int = 36) -> str:
    """Lower-case ID fragment: ``DJI_0042 (1)`` -> ``dji_0042-1``."""
    value = re.sub(r"[^a-z0-9_]+", "-", text.lower()).strip("-_")
    value = value[:max_length].rstrip("-_")
    return value or "video"


def media_id_for(path: Path) -> str:
    return f"vid-{slug(path.stem)}"


def frame_id(extraction_id: str, timestamp_s: float) -> str:
    return f"{extraction_id}-{round(timestamp_s * 1000):08d}"


def check_id(value: str, what: str) -> str:
    if not ID_PATTERN.match(value):
        raise FramesError(
            f"{what} '{value}' is not a valid blueprint ID "
            "(lower-case letters, digits, '-' and '_', at most 64 characters)"
        )
    return value


def ms_round(value: float) -> float:
    return round(value * 1000) / 1000


def interval_timestamps(
    duration_s: float, every_s: float, start_s: float = 0.0, end_s: float | None = None
) -> list[float]:
    """``start, start + every, ...`` strictly before the end (and the last frame)."""
    if every_s <= 0:
        raise FramesError("--every must be positive")
    stop = duration_s if end_s is None else min(end_s, duration_s)
    times: list[float] = []
    k = 0
    while True:
        t = ms_round(start_s + k * every_s)
        if t >= stop - 1e-6:
            break
        times.append(t)
        k += 1
    return times


def thin_timestamps(
    candidates: Iterable[float],
    *,
    start_s: float,
    stop_s: float,
    min_gap_s: float,
    max_gap_s: float | None,
) -> list[float]:
    """Keep ``start`` and candidates at least ``min_gap`` apart; fill gaps above ``max_gap``."""
    kept = [ms_round(start_s)]
    for t in sorted(candidates):
        if start_s <= t < stop_s and t - kept[-1] >= min_gap_s:
            kept.append(ms_round(t))
    if max_gap_s is None:
        return kept
    filled: list[float] = []
    bounds = [*kept, stop_s]
    for left, right in itertools.pairwise(bounds):
        filled.append(left)
        pieces = math.ceil((right - left) / max_gap_s - 1e-9)
        filled.extend(ms_round(left + (right - left) * i / pieces) for i in range(1, pieces))
    return [t for t in filled if t < stop_s - 1e-6]


def cap_timestamps(times: Sequence[float], max_frames: int) -> list[float]:
    """Evenly spaced subset of at most ``max_frames`` (first and last kept)."""
    if max_frames <= 0 or len(times) <= max_frames:
        return list(times)
    if max_frames == 1:
        return [times[0]]
    step = (len(times) - 1) / (max_frames - 1)
    return [times[round(i * step)] for i in range(max_frames)]


def parse_showinfo(stderr: str) -> list[float]:
    """``pts_time`` values printed by ffmpeg's ``showinfo`` filter."""
    return [float(m) for m in re.findall(r"pts_time:\s*([0-9.]+)", stderr)]


def parse_rate(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    if "/" in value:
        num, den = value.split("/", 1)
        return float(num) / float(den) if float(den) else None
    return float(value)


def parse_iso6709(value: str) -> dict[str, float] | None:
    """``+55.7558+037.6173+150.000/`` -> latitude / longitude (altitude ignored)."""
    match = re.match(r"^\s*([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)", value)
    if not match:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"latitude": lat, "longitude": lon}


def nadir_ground_width_m(
    altitude_m: float, focal_35mm: float, width_px: int, height_px: int
) -> float:
    """Ground distance across the image width for a camera pointing straight down.

    ``focal_35mm`` is the 35 mm equivalent focal length (defined on the
    43.27 mm full-frame diagonal), so the equivalent image width is the
    diagonal share of the frame's aspect ratio.
    """
    equivalent_width_mm = FULL_FRAME_DIAGONAL_MM * width_px / math.hypot(width_px, height_px)
    return altitude_m * equivalent_width_mm / focal_35mm


# --------------------------------------------------------------------------- telemetry


@dataclass(frozen=True)
class TelemetryCue:
    start_s: float
    end_s: float
    values: dict[str, float] = field(default_factory=dict)


_SRT_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})")
_NUMBER = r"([-+]?\d+(?:\.\d+)?)"
_KEYS = {
    "latitude": "latitude",
    "longitude": "longitude",
    "longtitude": "longitude",  # spelled like this by some DJI firmware
    "rel_alt": "relativeAltitudeM",
    "abs_alt": "absoluteAltitudeM",
    "altitude": "absoluteAltitudeM",
    "focal_len": "focalLength35mm",
    "gb_pitch": "gimbalPitchDeg",
    "gimbal_pitch": "gimbalPitchDeg",
}
_KEY_VALUE = re.compile(r"\b(" + "|".join(_KEYS) + r")\s*:\s*" + _NUMBER, re.IGNORECASE)
_GPS = re.compile(r"\bGPS\s*\(\s*" + _NUMBER + r"\s*,\s*" + _NUMBER, re.IGNORECASE)
_HEIGHT = re.compile(r"(?:^|[\s,])H\s*" + _NUMBER + r"\s*m\b")
_BAROMETER = re.compile(r"\bBAROMETER\s*:\s*" + _NUMBER, re.IGNORECASE)


def _srt_seconds(match: re.Match[str]) -> float:
    hours, minutes, seconds, millis = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis.ljust(3, "0")) / 1000


def parse_telemetry_text(text: str) -> dict[str, float]:
    """Flight values from one subtitle cue (DJI formats; unknown values are left out)."""
    values: dict[str, float] = {}
    for key, number in _KEY_VALUE.findall(text):
        values.setdefault(_KEYS[key.lower()], float(number))
    gps = _GPS.search(text)
    if gps and "latitude" not in values:
        # DJI writes GPS(longitude, latitude, ...).
        values["longitude"], values["latitude"] = float(gps.group(1)), float(gps.group(2))
    if "relativeAltitudeM" not in values:
        height = _HEIGHT.search(text) or _BAROMETER.search(text)
        if height:
            values["relativeAltitudeM"] = float(height.group(1))
    lat, lon = values.get("latitude"), values.get("longitude")
    if (
        lat is not None
        and lon is not None
        and ((lat == 0 and lon == 0) or not (-90 <= lat <= 90 and -180 <= lon <= 180))
    ):
        del values["latitude"], values["longitude"]
    return values


def parse_srt(text: str) -> list[TelemetryCue]:
    cues: list[TelemetryCue] = []
    for block in re.split(r"\r?\n\s*\r?\n", text.strip().lstrip("﻿")):
        lines = block.splitlines()
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue
        times = list(_SRT_TIME.finditer(lines[timing]))
        if len(times) != 2:
            continue
        body = re.sub(r"<[^>]+>", " ", " ".join(lines[timing + 1 :]))
        cues.append(
            TelemetryCue(_srt_seconds(times[0]), _srt_seconds(times[1]), parse_telemetry_text(body))
        )
    cues.sort(key=lambda cue: cue.start_s)
    return cues


def telemetry_at(cues: Sequence[TelemetryCue], t: float) -> dict[str, float] | None:
    """Values of the cue covering ``t`` (or the nearest one within a second)."""
    if not cues:
        return None
    starts = [cue.start_s for cue in cues]
    i = bisect.bisect_right(starts, t) - 1
    candidates = [cues[j] for j in (i, i + 1) if 0 <= j < len(cues)]

    def distance(cue: TelemetryCue) -> float:
        return (
            0.0 if cue.start_s <= t < cue.end_s else min(abs(cue.start_s - t), abs(cue.end_s - t))
        )

    best = min(candidates, key=distance)
    if distance(best) > 1.0 or not best.values:
        return None
    return dict(best.values)


def scale_hint(
    telemetry: dict[str, float] | None, width_px: int, height_px: int
) -> dict[str, Any] | None:
    """Ground width of a frame from altitude and focal length, if the camera looked down."""
    if not telemetry:
        return None
    altitude = telemetry.get("relativeAltitudeM")
    focal = telemetry.get("focalLength35mm")
    if altitude is None or focal is None or altitude <= 1 or focal <= 1:
        return None
    pitch = telemetry.get("gimbalPitchDeg")
    if pitch is not None and abs(pitch + 90) > 15:
        return {"oblique": True, "gimbalPitchDeg": pitch}
    width_m = nadir_ground_width_m(altitude, focal, width_px, height_px)
    return {
        "assumesNadir": pitch is None,
        "nadirGroundWidthM": round(width_m, 2),
        "nadirGroundHeightM": round(width_m * height_px / width_px, 2),
        "metresPerPixel": round(width_m / width_px, 4),
    }


# --------------------------------------------------------------------------- ffmpeg


def require_tools() -> None:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise FramesError(
            f"{' and '.join(missing)} not found on PATH. Install FFmpeg "
            "(apt install ffmpeg, brew install ffmpeg, winget install ffmpeg)."
        )


def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(command), capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL
    )
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-8:])
        raise FramesError(f"{command[0]} failed ({result.returncode}):\n{tail}")
    return result


def ffmpeg_version() -> str:
    first = run(["ffmpeg", "-hide_banner", "-version"]).stdout.splitlines()[0]
    match = re.match(r"ffmpeg version (\S+)", first)
    return match.group(1) if match else "unknown"


@dataclass(frozen=True)
class VideoInfo:
    duration_s: float
    width: int
    height: int
    fps: float | None
    codec: str | None
    rotation_deg: int
    created_at: str | None
    geo_tag: dict[str, float] | None

    def as_json(self) -> dict[str, Any]:
        return {
            "durationS": self.duration_s,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "codec": self.codec,
            "rotationDeg": self.rotation_deg,
            "createdAt": self.created_at,
            "geoTag": self.geo_tag,
        }


def _normalise_time(value: str | None) -> str | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def video_info(probe: dict[str, Any]) -> VideoInfo:
    streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
    if not streams:
        raise FramesError("no video stream found")
    stream = streams[0]
    fmt = probe.get("format", {})
    duration = stream.get("duration") or fmt.get("duration")
    if duration in (None, "N/A"):
        raise FramesError("the video duration is unknown")
    rotation = 0
    for side in stream.get("side_data_list", []) or []:
        if "rotation" in side:
            rotation = int(float(side["rotation"]))
    tags = {**fmt.get("tags", {}), **stream.get("tags", {})}
    if not rotation and "rotate" in tags:
        rotation = int(float(tags["rotate"]))
    width, height = int(stream["width"]), int(stream["height"])
    if abs(rotation) % 180 == 90:
        width, height = height, width
    geo = None
    for key in ("location", "com.apple.quicktime.location.ISO6709", "location-eng"):
        if key in tags:
            geo = parse_iso6709(str(tags[key]))
            if geo:
                break
    return VideoInfo(
        duration_s=round(float(duration), 3),
        width=width,
        height=height,
        fps=(
            round(rate, 3)
            if (rate := parse_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate")))
            else None
        ),
        codec=stream.get("codec_name"),
        rotation_deg=rotation % 360,
        created_at=_normalise_time(tags.get("creation_time")),
        geo_tag=geo,
    )


def ffprobe(path: Path) -> dict[str, Any]:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    data: dict[str, Any] = json.loads(result.stdout)
    return data


def extract_frame(video: Path, t: float, output: Path, max_width: int | None) -> bool:
    """Write the first frame at or after ``t``; False when ``t`` is past the end."""
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    command += ["-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-an", "-sn"]
    if max_width:
        command += ["-vf", f"scale='min({max_width},iw)':-2:flags=lanczos"]
    command += ["-q:v", "2", "-map_metadata", "-1", str(output)]
    run(command)
    return output.exists() and output.stat().st_size > 0


def scene_times(video: Path, threshold: float, start_s: float, stop_s: float) -> list[float]:
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-ss", f"{start_s:.3f}"]
    command += ["-t", f"{stop_s - start_s:.3f}", "-i", str(video), "-an", "-sn", "-dn"]
    command += ["-vf", f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"]
    result = run(command)
    return [ms_round(start_s + t) for t in parse_showinfo(result.stderr)]


def _drawtext(text: str, x: str, y: str, size: str) -> str:
    return (
        f"drawtext=text='{text}':expansion=none:x={x}:y={y}:fontsize={size}"
        ":fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=3"
    )


def image_size(path: Path) -> tuple[int, int]:
    info = ffprobe(path)
    stream = info["streams"][0]
    return int(stream["width"]), int(stream["height"])


def make_sheets(
    frames: Sequence[tuple[str, float, Path]],
    sheet_dir: Path,
    *,
    columns: int,
    rows: int,
    thumb_width: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Contact sheets of labelled thumbnails; returns the sheet list and whether labels worked."""
    if not frames:
        return [], False
    sheet_dir.mkdir(parents=True, exist_ok=True)
    font = max(12, thumb_width // 30)
    labelled = True
    with tempfile.TemporaryDirectory() as tmp:
        thumbs = Path(tmp)
        for n, (fid, t, path) in enumerate(frames, start=1):
            base = f"scale={thumb_width}:-2:flags=lanczos"
            label = _drawtext(f"{fid}  {t:.1f} s", "4", "4", str(font))
            out = thumbs / f"{n:05d}.jpg"
            command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
            command += ["-i", str(path), "-frames:v", "1", "-q:v", "3"]
            if labelled:
                try:
                    run([*command, "-vf", f"{base},{label}", str(out)])
                    continue
                except FramesError:
                    labelled = False  # ffmpeg without libfreetype / fonts
            run([*command, "-vf", base, str(out)])
        per_sheet = columns * rows
        for old in sheet_dir.glob("sheet-*.jpg"):
            old.unlink()
        run(
            [
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-framerate", "1", "-start_number", "1", "-i", str(thumbs / "%05d.jpg"),
                "-vf", f"tile={columns}x{rows}:padding=4:margin=4:color=0x202020",
                "-q:v", "3", str(sheet_dir / "sheet-%03d.jpg"),
            ]
        )  # fmt: skip
    sheets = []
    for i in range(math.ceil(len(frames) / per_sheet)):
        chunk = frames[i * per_sheet : (i + 1) * per_sheet]
        sheets.append({"file": f"sheet-{i + 1:03d}.jpg", "frameIds": [fid for fid, _, _ in chunk]})
    return sheets, labelled


def grid_filter(width: int, height: int, divisions: int) -> str:
    font = max(12, min(width, height) // 45)
    parts = [f"drawgrid=w=iw/{divisions}:h=ih/{divisions}:t=2:c=yellow@0.7"]
    for i in range(1, divisions):
        label = f"{i / divisions:.2f}".rstrip("0")
        parts.append(_drawtext(label, f"W*{i}/{divisions}+3", "3", str(font)))
        parts.append(_drawtext(label, "3", f"H*{i}/{divisions}+3", str(font)))
    return ",".join(parts)


# --------------------------------------------------------------------------- files


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_reference(path: Path, package: Path, media_type: str, *, checksum: bool) -> dict[str, Any]:
    reference: dict[str, Any] = {
        "path": path.relative_to(package).as_posix(),
        "mediaType": media_type,
    }
    if checksum:
        reference["sha256"] = sha256_of(path)
        reference["sizeBytes"] = path.stat().st_size
    return reference


def safe_name(name: str) -> str:
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    clean = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "media"
    return f"{clean}.{suffix}" if suffix else clean


def place_in_package(source: Path, package: Path, folder: str = "media") -> Path:
    """The file inside the package: used in place, or copied to ``media/``."""
    source = source.resolve()
    root = package.resolve()
    if source.is_relative_to(root):
        return source
    target = root / folder / safe_name(source.name)
    if target.exists():
        if target.stat().st_size == source.stat().st_size and sha256_of(target) == sha256_of(
            source
        ):
            return target
        raise FramesError(
            f"{target.relative_to(root).as_posix()} already exists with different content; "
            "rename the video or remove the old copy"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_indexes(package: Path) -> list[dict[str, Any]]:
    indexes = []
    for path in sorted((package / "analysis").glob("frames-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("indexVersion") != INDEX_VERSION:
            raise FramesError(f"{path} has an unknown indexVersion")
        data["_path"] = path
        indexes.append(data)
    return indexes


def build_source(package: Path, indexes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """A blueprint ``source`` section listing exactly the media, frames and indexes on disk."""
    media: dict[str, dict[str, Any]] = {}
    extractions: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    for index in sorted(indexes, key=lambda item: str(item["extraction"]["id"])):
        for item in index["sourceMedia"]:
            known = media.get(item["id"])
            if known is not None and known["file"] != item["file"]:
                raise FramesError(f"media ID '{item['id']}' refers to two different files")
            media[item["id"]] = item
        extraction = index["extraction"]
        extractions.append({k: v for k, v in extraction.items() if k != "parameters"})
        for frame in index["frames"]:
            frames.append(
                {
                    "id": frame["id"],
                    "mediaId": extraction["mediaId"],
                    "extractionId": extraction["id"],
                    "timestampS": frame["timestampS"],
                    "file": {"path": frame["file"], "mediaType": "image/jpeg"},
                }
            )
        path: Path = index["_path"]
        reports.append(
            {
                "id": f"{extraction['id']}-index",
                "file": file_reference(path, package, "application/json", checksum=True),
                "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
            }
        )
    count = sum(1 for item in media.values() if item["kind"] == "video")
    return {
        "type": "video",
        "description": (
            f"{count} video(s); frames extracted with {TOOL_NAME} "
            f"({len(extractions)} extraction(s), {len(frames)} frame(s))."
        ),
        "media": [media[key] for key in sorted(media)],
        "frameExtractions": extractions,
        "frames": frames,
        "analysisReports": reports,
    }


def rebuild_source(package: Path) -> Path:
    indexes = read_indexes(package)
    if not indexes:
        raise FramesError(f"no analysis/frames-*.json in {package}; run `extract` first")
    path = package / "analysis" / "source.json"
    write_json(path, build_source(package, indexes))
    return path


# --------------------------------------------------------------------------- commands


def known_media_id(package: Path, video: Path) -> str | None:
    """The media ID earlier extractions used for this file (IDs never change)."""
    relative = video.relative_to(package).as_posix()
    for index in read_indexes(package):
        for item in index["sourceMedia"]:
            if item["kind"] == "video" and item["file"]["path"] == relative:
                return str(item["id"])
    return None


def next_extraction_id(package: Path, media_id: str) -> str:
    used = {index["extraction"]["id"] for index in read_indexes(package)}
    n = 1
    while f"{media_id}-x{n:02d}" in used:
        n += 1
    return f"{media_id}-x{n:02d}"


def planned_times(args: argparse.Namespace, video: Path, info: VideoInfo) -> list[float]:
    start = max(0.0, args.start or 0.0)
    last = info.duration_s - (0.5 / info.fps if info.fps else 0.02)
    stop = min(args.end, last) if args.end is not None else last
    if stop <= start:
        raise FramesError("--start is after the end of the video (or --end)")
    if args.method == "interval":
        times = interval_timestamps(stop, args.every, start)
    elif args.method == "scene":
        candidates = scene_times(video, args.threshold, start, stop)
        times = thin_timestamps(
            candidates, start_s=start, stop_s=stop, min_gap_s=args.min_gap, max_gap_s=args.max_gap
        )
    else:
        if not args.at:
            raise FramesError("--method manual needs at least one --at SECONDS")
        times = sorted({ms_round(t) for t in args.at if start <= t < stop})
        if not times:
            raise FramesError("no --at time lies inside the video")
    return cap_timestamps(times, args.max_frames)


def find_sidecar(video: Path) -> Path | None:
    for suffix in SIDECAR_SUFFIXES:
        candidate = video.with_suffix(suffix)
        if candidate.exists():
            return candidate
    return None


def cmd_probe(args: argparse.Namespace) -> int:
    require_tools()
    video = Path(args.video)
    info = video_info(ffprobe(video))
    sidecar = find_sidecar(video)
    print(
        json.dumps(
            {
                **info.as_json(),
                "file": video.name,
                "sizeBytes": video.stat().st_size,
                "telemetrySidecar": sidecar.name if sidecar else None,
                "suggestedMediaId": media_id_for(video),
            },
            indent=2,
        )
    )
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    require_tools()
    package = Path(args.package).resolve()
    source_video = Path(args.video)
    if not source_video.is_file():
        raise FramesError(f"video not found: {source_video}")
    package.mkdir(parents=True, exist_ok=True)
    video = place_in_package(source_video, package)
    info = video_info(ffprobe(video))
    known = known_media_id(package, video)
    if args.media_id and known and args.media_id != known:
        raise FramesError(f"this video is already registered as media '{known}'")
    media_id = check_id(args.media_id or known or media_id_for(video), "media ID")
    extraction_id = check_id(
        args.extraction_id or next_extraction_id(package, media_id), "extraction ID"
    )
    index_path = package / "analysis" / f"frames-{extraction_id}.json"
    frame_dir = package / "frames" / extraction_id
    if index_path.exists() or frame_dir.exists():
        if not args.force:
            raise FramesError(
                f"extraction '{extraction_id}' exists; pass --force to replace it "
                "(frame IDs depend only on the timestamps, so citations stay valid "
                "for frames that are extracted again)"
            )
        shutil.rmtree(frame_dir, ignore_errors=True)
        index_path.unlink(missing_ok=True)
    for other in read_indexes(package):
        for item in other["sourceMedia"]:
            if (
                item["id"] == media_id
                and item["file"]["path"] != video.relative_to(package).as_posix()
            ):
                raise FramesError(
                    f"media ID '{media_id}' is used for another file; pass --media-id"
                )

    times = planned_times(args, video, info)
    frame_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(frame_id(extraction_id, t), t) for t in times]
    for fid, _ in jobs:
        check_id(fid, "frame ID")

    def work(job: tuple[str, float]) -> tuple[str, float, Path] | None:
        fid, t = job
        out = frame_dir / f"{fid}.jpg"
        return (fid, t, out) if extract_frame(video, t, out, args.width) else None

    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        done = [item for item in pool.map(work, jobs) if item is not None]
    if not done:
        raise FramesError("no frame could be extracted")
    frame_w, frame_h = image_size(done[0][2])

    sidecar = Path(args.telemetry) if args.telemetry else find_sidecar(source_video)
    cues: list[TelemetryCue] = []
    source_media = [
        {
            "id": media_id,
            "kind": "video",
            "file": file_reference(
                video, package, VIDEO_TYPES.get(video.suffix.lower(), "video/mp4"), checksum=True
            ),
            **({"capturedAt": info.created_at} if info.created_at else {}),
            "durationS": info.duration_s,
            "description": (
                f"{info.width}x{info.height}"
                + (f", {info.fps:g} fps" if info.fps else "")
                + (f", {info.codec}" if info.codec else "")
            ),
        }
    ]
    if sidecar is not None and not args.no_telemetry:
        if not sidecar.is_file():
            raise FramesError(f"telemetry file not found: {sidecar}")
        sidecar_in_package = place_in_package(sidecar, package)
        cues = parse_srt(sidecar_in_package.read_text(encoding="utf-8", errors="replace"))
        source_media.append(
            {
                "id": f"{media_id}-telemetry",
                "kind": "other",
                "file": file_reference(
                    sidecar_in_package, package, "application/x-subrip", checksum=True
                ),
                "description": f"Flight telemetry subtitles for {media_id}",
            }
        )

    frames = []
    for fid, t, path in done:
        telemetry = telemetry_at(cues, t)
        entry: dict[str, Any] = {
            "id": fid,
            "timestampS": t,
            "file": path.relative_to(package).as_posix(),
        }
        if telemetry:
            entry["telemetry"] = telemetry
            hint = scale_hint(telemetry, frame_w, frame_h)
            if hint:
                entry["scaleHint"] = hint
        frames.append(entry)

    sheets, labelled = make_sheets(
        done,
        frame_dir / "sheets",
        columns=args.sheet_columns,
        rows=args.sheet_rows,
        thumb_width=args.thumb_width,
    )
    for sheet in sheets:
        sheet["file"] = (frame_dir / "sheets" / sheet["file"]).relative_to(package).as_posix()

    method = METHODS[args.method]
    extraction: dict[str, Any] = {
        "id": extraction_id,
        "mediaId": media_id,
        "method": method,
        **({"intervalS": args.every} if args.method == "interval" else {}),
        "frameCount": len(frames),
        "outputDirectory": frame_dir.relative_to(package).as_posix(),
        "tool": {"name": "ffmpeg", "version": ffmpeg_version()[:64]},
        "parameters": {
            "method": args.method,
            "start": args.start,
            "end": args.end,
            "every": args.every if args.method == "interval" else None,
            "threshold": args.threshold if args.method == "scene" else None,
            "minGap": args.min_gap if args.method == "scene" else None,
            "maxGap": args.max_gap if args.method == "scene" else None,
            "at": sorted(args.at) if args.method == "manual" else None,
            "maxFrames": args.max_frames,
            "width": args.width,
        },
    }
    with_telemetry = [f for f in frames if "telemetry" in f]
    index = {
        "indexVersion": INDEX_VERSION,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "video": info.as_json(),
        "frameSize": {"width": frame_w, "height": frame_h},
        "sourceMedia": source_media,
        "extraction": extraction,
        "frames": frames,
        "sheets": sheets,
        "sheetLabels": labelled,
        "telemetry": (
            {
                "cues": len(cues),
                "framesWithTelemetry": len(with_telemetry),
                "firstFix": next(
                    (
                        {
                            "latitude": f["telemetry"]["latitude"],
                            "longitude": f["telemetry"]["longitude"],
                        }
                        for f in with_telemetry
                        if "latitude" in f["telemetry"]
                    ),
                    None,
                ),
            }
            if cues
            else None
        ),
    }
    write_json(index_path, index)
    source_path = rebuild_source(package)

    print(f"Extracted {len(frames)} frame(s) from {video.relative_to(package).as_posix()}")
    print(f"  extraction  {extraction_id} ({method})")
    print(f"  frames      {frame_dir.relative_to(package).as_posix()}/")
    print(f"  sheets      {len(sheets)} contact sheet(s), labels {'on' if labelled else 'off'}")
    if cues:
        print(f"  telemetry   {len(cues)} cue(s), {len(with_telemetry)} frame(s) matched")
    print(f"  index       {index_path.relative_to(package).as_posix()}")
    print(f"  source      {source_path.relative_to(package).as_posix()}")
    return 0


def cmd_source(args: argparse.Namespace) -> int:
    path = rebuild_source(Path(args.package).resolve())
    print(path)
    return 0


def find_frame(package: Path, wanted: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for index in read_indexes(package):
        for frame in index["frames"]:
            if frame["id"] == wanted:
                return index, frame
    raise FramesError(f"frame '{wanted}' is not in any analysis/frames-*.json of {package}")


def cmd_grid(args: argparse.Namespace) -> int:
    require_tools()
    package = Path(args.package).resolve()
    _, frame = find_frame(package, args.frame)
    image = package / frame["file"]
    width, height = image_size(image)
    output = Path(args.output) if args.output else image.parent / "grid" / image.name
    output.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(image),
            "-vf", grid_filter(width, height, args.divisions), "-q:v", "2", str(output),
        ]
    )  # fmt: skip
    print(output)
    return 0


def cmd_crop(args: argparse.Namespace) -> int:
    require_tools()
    package = Path(args.package).resolve()
    index, frame = find_frame(package, args.frame)
    u0, v0, u1, v1 = args.box
    if not (0 <= u0 < u1 <= 1 and 0 <= v0 < v1 <= 1):
        raise FramesError("--box needs 0 <= U0 < U1 <= 1 and 0 <= V0 < V1 <= 1")
    name = "-".join(f"{round(value * 1000):04d}" for value in args.box)
    output = (
        Path(args.output)
        if args.output
        else (package / frame["file"]).parent / "crops" / f"{frame['id']}-{name}.jpg"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    crop = (
        f"crop=w=iw*{u1 - u0:.4f}:h=ih*{v1 - v0:.4f}:x=iw*{u0:.4f}:y=ih*{v0:.4f},"
        f"scale='if(gte(iw,ih),{args.size},-2)':'if(gte(iw,ih),-2,{args.size})':flags=lanczos"
    )
    video = package / index["sourceMedia"][0]["file"]["path"]
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    if video.exists():
        command += ["-ss", f"{frame['timestampS']:.3f}", "-i", str(video)]
    else:
        print(f"warning: {video.name} is missing; cropping the extracted frame", file=sys.stderr)
        command += ["-i", str(package / frame["file"])]
    run([*command, "-frames:v", "1", "-vf", crop, "-q:v", "2", str(output)])
    print(output)
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    svg = Path(args.svg)
    if not svg.is_file():
        raise FramesError(f"{svg} not found")
    output = Path(args.output) if args.output else svg.with_suffix(".png")
    attempts: list[list[str]] = []
    if shutil.which("ffmpeg"):
        ffmpeg = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
        scale = ["-vf", f"scale={args.width}:-2", "-frames:v", "1"]
        attempts.append([*ffmpeg, "-i", str(svg), *scale, str(output)])
    if shutil.which("rsvg-convert"):
        attempts.append(["rsvg-convert", "-w", str(args.width), "-o", str(output), str(svg)])
    for tool in ("magick", "convert"):
        if shutil.which(tool):
            attempts.append(
                [tool, "-density", "150", str(svg), "-resize", str(args.width), str(output)]
            )
            break
    problems = []
    for command in attempts:
        try:
            run(command)
        except FramesError as exc:
            problems.append(str(exc))
            continue
        print(output)
        return 0
    raise FramesError(
        "no SVG rasteriser worked (ffmpeg with librsvg, rsvg-convert or ImageMagick); "
        "open the SVG in a browser instead" + ("\n" + "\n".join(problems) if problems else "")
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="frames.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="describe a video")
    probe.add_argument("video")
    probe.set_defaults(func=cmd_probe)

    extract = sub.add_parser("extract", help="extract frames into a location package")
    extract.add_argument("video")
    extract.add_argument("--package", required=True, help="location package folder")
    extract.add_argument("--method", choices=sorted(METHODS), default="interval")
    extract.add_argument("--every", type=float, default=2.0, help="interval method: seconds")
    extract.add_argument("--threshold", type=float, default=0.3, help="scene method: 0..1")
    extract.add_argument("--min-gap", type=float, default=1.0, help="scene method: seconds")
    extract.add_argument(
        "--max-gap", type=float, default=10.0, help="scene method: add frames in longer gaps"
    )
    extract.add_argument("--at", type=float, action="append", help="manual method: seconds")
    extract.add_argument("--start", type=float, default=0.0)
    extract.add_argument("--end", type=float, default=None)
    extract.add_argument("--max-frames", type=int, default=400)
    extract.add_argument("--width", type=int, default=1920, help="downscale wider frames")
    extract.add_argument("--media-id")
    extract.add_argument("--extraction-id")
    extract.add_argument("--telemetry", help="DJI .SRT file (default: <video>.SRT if present)")
    extract.add_argument("--no-telemetry", action="store_true")
    extract.add_argument("--sheet-columns", type=int, default=4)
    extract.add_argument("--sheet-rows", type=int, default=3)
    extract.add_argument("--thumb-width", type=int, default=400)
    extract.add_argument("--jobs", type=int, default=4)
    extract.add_argument("--force", action="store_true", help="replace an existing extraction")
    extract.set_defaults(func=cmd_extract)

    source = sub.add_parser("source", help="rebuild analysis/source.json")
    source.add_argument("--package", required=True)
    source.set_defaults(func=cmd_source)

    grid = sub.add_parser("grid", help="frame with a labelled measuring grid")
    grid.add_argument("--package", required=True)
    grid.add_argument("--frame", required=True)
    grid.add_argument("--divisions", type=int, default=10)
    grid.add_argument("--output")
    grid.set_defaults(func=cmd_grid)

    crop = sub.add_parser("crop", help="full-resolution crop of a frame region")
    crop.add_argument("--package", required=True)
    crop.add_argument("--frame", required=True)
    crop.add_argument("--box", type=float, nargs=4, required=True, metavar=("U0", "V0", "U1", "V1"))
    crop.add_argument("--size", type=int, default=1536, help="long side of the output, pixels")
    crop.add_argument("--output")
    crop.set_defaults(func=cmd_crop)

    render = sub.add_parser("render", help="rasterise an SVG preview to PNG")
    render.add_argument("svg")
    render.add_argument("--output")
    render.add_argument("--width", type=int, default=1600)
    render.set_defaults(func=cmd_render)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    func: Callable[[argparse.Namespace], int] = args.func
    try:
        return func(args)
    except FramesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
