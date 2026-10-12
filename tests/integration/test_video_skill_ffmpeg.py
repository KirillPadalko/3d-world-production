"""The video-to-blueprint skill end to end on a generated video (needs ffmpeg).

video -> frames, sheets, telemetry, source -> new blueprint -> entities citing
frames -> a second extraction -> sync-source -> review -> generation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from environment_generator.blueprint import load_blueprint
from environment_generator.models.blueprint.source import Source
from environment_generator.pipeline import InputBundle, Pipeline, PipelineOptions
from tests.video_skill import HAS_FFMPEG, dji_srt, load, make_video

pytestmark = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")

frames = load("frames")
package = load("location_package")
review = load("review_blueprint")


@pytest.fixture(scope="module")
def footage(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("footage")
    video = make_video(folder / "DJI 0042.MP4")
    (folder / "DJI 0042.SRT").write_text(dji_srt(6.0), encoding="utf-8")
    return video


def _index(pkg: Path, extraction: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (pkg / "analysis" / f"frames-{extraction}.json").read_text(encoding="utf-8")
    )
    return data


def test_extract_writes_frames_sheets_telemetry_and_source(footage: Path, tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    assert frames.main(["extract", str(footage), "--package", str(pkg), "--every", "1"]) == 0
    media = pkg / "media" / "DJI_0042.MP4"
    assert media.read_bytes() == footage.read_bytes()
    assert (pkg / "media" / "DJI_0042.SRT").exists()

    index = _index(pkg, "vid-dji_0042-x01")
    ids = [f["id"] for f in index["frames"]]
    assert ids == [f"vid-dji_0042-x01-{t * 1000:08d}" for t in range(6)]
    for frame in index["frames"]:
        assert (pkg / frame["file"]).stat().st_size > 0
        assert frame["telemetry"]["relativeAltitudeM"] == 60.0
        assert frame["scaleHint"]["nadirGroundWidthM"] == pytest.approx(94.27, abs=0.05)
    sheets = index["sheets"]
    assert len(sheets) == 1 and sheets[0]["frameIds"] == ids
    assert (pkg / sheets[0]["file"]).exists()
    assert index["video"]["createdAt"] == "2026-05-01T10:00:00Z"

    source = Source.model_validate(
        json.loads((pkg / "analysis" / "source.json").read_text(encoding="utf-8")),
        by_alias=True,
        by_name=False,
    )
    assert [m.id for m in source.media] == ["vid-dji_0042", "vid-dji_0042-telemetry"]
    assert source.media[0].file.sha256 is not None
    assert len(source.frames) == 6

    # Re-running the same extraction is refused; --force gives the same frame IDs.
    args = ["extract", str(footage), "--package", str(pkg), "--every", "1"]
    assert frames.main([*args, "--extraction-id", "vid-dji_0042-x01"]) == 1
    assert frames.main([*args, "--extraction-id", "vid-dji_0042-x01", "--force"]) == 0
    assert [f["id"] for f in _index(pkg, "vid-dji_0042-x01")["frames"]] == ids


def test_scene_method_finds_the_cuts(footage: Path, tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    code = frames.main(
        ["extract", str(footage), "--package", str(pkg), "--method", "scene", "--no-telemetry"]
    )
    assert code == 0
    index = _index(pkg, "vid-dji_0042-x01")
    times = [f["timestampS"] for f in index["frames"]]
    assert times[0] == 0.0
    assert any(abs(t - 2.0) < 0.2 for t in times) and any(abs(t - 4.0) < 0.2 for t in times)
    assert index["extraction"]["method"] == "keyframes"
    assert index["telemetry"] is None


def test_grid_crop_and_render(footage: Path, tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    frames.main(["extract", str(footage), "--package", str(pkg), "--every", "2", "--width", "320"])
    frame = "vid-dji_0042-x01-00002000"
    assert frames.main(["grid", "--package", str(pkg), "--frame", frame]) == 0
    assert (pkg / "frames" / "vid-dji_0042-x01" / "grid" / f"{frame}.jpg").exists()
    box = ["0.25", "0.25", "0.75", "0.5"]
    assert frames.main(["crop", "--package", str(pkg), "--frame", frame, "--box", *box]) == 0
    crop = pkg / "frames" / "vid-dji_0042-x01" / "crops" / f"{frame}-0250-0250-0750-0500.jpg"
    # From the 640 px video, not the 320 px frame: 320 x 90 source pixels, scaled up.
    assert frames.image_size(crop) == (1536, 432)
    assert frames.main(["crop", "--package", str(pkg), "--frame", "nope", "--box", *box]) == 1
    svg = tmp_path / "preview.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
        '<rect width="40" height="20" fill="#4a7"/></svg>',
        encoding="utf-8",
    )
    try:
        frames.cmd_render(frames.build_parser().parse_args(["render", str(svg), "--width", "80"]))
    except frames.FramesError as exc:
        pytest.skip(f"no SVG rasteriser available: {exc}")
    assert frames.image_size(svg.with_suffix(".png")) == (80, 40)


def test_package_review_and_generation(footage: Path, tmp_path: Path) -> None:
    pkg = tmp_path / "dacha-test"
    assert frames.main(["extract", str(footage), "--package", str(pkg), "--every", "2"]) == 0
    init = [
        "init", "--package", str(pkg), "--location-id", "dacha-test", "--name", "Dacha test",
        "--width", "80", "--depth", "60", "--biome", "temperate", "--season", "summer",
        "--created-at", "2026-10-12T10:00:00Z", "--calibration", "gps",
        "--calibration-notes", "Footprint from DJI telemetry, checked against a car.",
    ]  # fmt: skip
    assert package.main(init) == 0
    blueprint_path = pkg / "location.blueprint.json"
    blueprint = load_blueprint(blueprint_path)
    assert blueprint.source is not None and len(blueprint.source.frames) == 3

    seen = {
        "category": "observed",
        "confidence": 0.75,
        "frameIds": ["vid-dji_0042-x01-00002000"],
        "positionAccuracyM": 1.5,
    }
    document = json.loads(blueprint_path.read_text(encoding="utf-8"))
    document["roads"] = {
        "nodes": [
            {"id": "n-west", "position": [0.0, 20.0], "nodeType": "boundary", "provenance": seen},
            {"id": "n-east", "position": [80.0, 20.0], "nodeType": "boundary", "provenance": seen},
        ],
        "segments": [
            {"id": "rd-main", "sourceNodeId": "n-west", "targetNodeId": "n-east",
             "widthM": 4.5, "surface": "gravel", "importance": "primary", "provenance": seen},
        ],
    }  # fmt: skip
    document["buildings"] = [
        {"id": "b-house-01", "provenance": seen, "archetype": "wooden_house_small",
         "buildingType": "house", "transform": {"position": [30.0, 0.0, 40.0], "yawDeg": 180.0},
         "dimensions": {"widthM": 6.5, "depthM": 5.5, "heightM": 5.5}, "floors": 1},
    ]  # fmt: skip
    blueprint_path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    contract, findings, reviewed = review.review(blueprint_path)
    assert reviewed
    assert [i.code for i in [*contract, *findings] if i.severity.value != "info"] == []

    # A second extraction for a detail; the blueprint learns about it via sync-source.
    detail = ["extract", str(footage), "--package", str(pkg), "--method", "manual", "--at", "3.5"]
    assert frames.main(detail) == 0
    _, findings, _ = review.review(blueprint_path)
    assert "REVIEW_SOURCE_OUT_OF_DATE" in {i.code for i in findings}
    before = blueprint_path.read_bytes()
    assert package.main(["sync-source", "--package", str(pkg)]) == 0  # dry run
    assert blueprint_path.read_bytes() == before
    assert package.main(["sync-source", "--package", str(pkg), "--write"]) == 0
    assert (pkg / "location.blueprint.json.bak").read_bytes() == before
    synced = load_blueprint(blueprint_path)
    assert synced.source is not None
    assert "vid-dji_0042-x02-00003500" in {f.id for f in synced.source.frames}
    _, findings, _ = review.review(blueprint_path)
    assert "REVIEW_SOURCE_OUT_OF_DATE" not in {i.code for i in findings}

    # Removing an extraction whose frames are cited is refused.
    (pkg / "analysis" / "frames-vid-dji_0042-x01.json").unlink()
    assert frames.main(["source", "--package", str(pkg)]) == 0
    assert package.main(["sync-source", "--package", str(pkg), "--write"]) == 1

    result = Pipeline().run(
        InputBundle(blueprint=blueprint_path, recipe=None),
        PipelineOptions(output_dir=tmp_path / "out", write_preview=True),
    )
    assert result.success, result.error
    assert result.manifest is not None
    ids = {entity.id for entity in result.manifest.entities}
    assert "building.b-house-01" in ids
