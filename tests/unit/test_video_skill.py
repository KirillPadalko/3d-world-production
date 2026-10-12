"""The video-to-blueprint skill: pure helpers, review checks and the skill's own files.

Tests that need ffmpeg are in tests/integration/test_video_skill_ffmpeg.py.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, get_args

import pytest

from environment_generator.models.blueprint import (
    BuildingType,
    FenceType,
    PlotType,
    RoadImportance,
)
from environment_generator.models.blueprint.source import Source
from environment_generator.models.blueprint.structures import PointInfrastructureType
from tests.conftest import LOCATIONS
from tests.video_skill import SCRIPTS, SKILL, dji_srt, load

frames = load("frames")
scale = load("scale")
package = load("location_package")
review = load("review_blueprint")


# --------------------------------------------------------------------------- frames.py


def test_ids_are_valid_blueprint_ids() -> None:
    assert frames.media_id_for(Path("DJI 0042 (1).MP4")) == "vid-dji-0042-1"
    assert frames.media_id_for(Path("!!!.mov")) == "vid-video"
    long_id = frames.media_id_for(Path("x" * 200 + ".mp4"))
    fid = frames.frame_id(f"{long_id}-x01", 3599.9994)
    assert fid.endswith("-03599999")
    assert frames.check_id(fid, "frame ID") == fid
    with pytest.raises(frames.FramesError):
        frames.check_id("Bad.ID", "media ID")


def test_interval_timestamps_stop_before_the_end() -> None:
    assert frames.interval_timestamps(10.0, 3.0) == [0.0, 3.0, 6.0, 9.0]
    assert frames.interval_timestamps(9.0, 3.0) == [0.0, 3.0, 6.0]
    assert frames.interval_timestamps(20.0, 0.25, start_s=1.0, end_s=2.0) == [
        1.0,
        1.25,
        1.5,
        1.75,
    ]
    with pytest.raises(frames.FramesError):
        frames.interval_timestamps(10.0, 0.0)


def test_scene_thinning_keeps_gaps_and_fills_long_ones() -> None:
    kept = frames.thin_timestamps(
        [0.5, 1.2, 1.5, 8.0], start_s=0.0, stop_s=20.0, min_gap_s=1.0, max_gap_s=5.0
    )
    assert kept == [0.0, 1.2, 4.6, 8.0, 12.0, 16.0]
    assert frames.thin_timestamps([], start_s=2.0, stop_s=5.0, min_gap_s=1.0, max_gap_s=None) == [
        2.0
    ]


def test_cap_keeps_first_and_last() -> None:
    times = [float(i) for i in range(10)]
    assert frames.cap_timestamps(times, 4) == [0.0, 3.0, 6.0, 9.0]
    assert frames.cap_timestamps(times, 20) == times
    assert frames.cap_timestamps(times, 1) == [0.0]


def test_ffmpeg_output_parsing() -> None:
    stderr = (
        "[Parsed_showinfo_2 @ 0x1] n:   0 pts:  76800 pts_time:3       duration: 512\n"
        "[Parsed_showinfo_2 @ 0x1] n:   1 pts: 153600 pts_time:6.04    duration: 512\n"
    )
    assert frames.parse_showinfo(stderr) == [3.0, 6.04]
    assert frames.parse_rate("30000/1001") == pytest.approx(29.97, abs=0.01)
    assert frames.parse_rate("0/0") is None
    assert frames.parse_iso6709("+55.7558+037.6173+150.000/") == {
        "latitude": 55.7558,
        "longitude": 37.6173,
    }
    assert frames.parse_iso6709("nowhere") is None


def test_video_info_handles_rotation_tags_and_time_zones() -> None:
    probe = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 3840,
                "height": 2160,
                "avg_frame_rate": "30000/1001",
                "duration": "12.345678",
                "side_data_list": [{"rotation": -90}],
                "tags": {"creation_time": "2026-05-01T12:00:00.000000+02:00"},
            },
            {"codec_type": "audio"},
        ],
        "format": {"duration": "12.4", "tags": {"location": "+55.7558+037.6173/"}},
    }
    info = frames.video_info(probe)
    assert (info.width, info.height, info.rotation_deg) == (2160, 3840, 270)
    assert info.duration_s == 12.346
    assert info.created_at == "2026-05-01T10:00:00Z"
    assert info.geo_tag == {"latitude": 55.7558, "longitude": 37.6173}
    with pytest.raises(frames.FramesError):
        frames.video_info({"streams": [{"codec_type": "audio"}], "format": {}})


def test_nadir_footprint() -> None:
    # 24 mm (35 mm equivalent) at 60 m, 16:9: about 94 m across.
    assert frames.nadir_ground_width_m(60.0, 24.0, 1920, 1080) == pytest.approx(94.27, abs=0.05)
    assert scale.footprint(60.0, 24.0, 16 / 9)["groundWidthM"] == pytest.approx(94.27, abs=0.05)


def test_telemetry_formats() -> None:
    modern = frames.parse_telemetry_text(
        "[iso: 100] [focal_len: 24.00] [latitude: 55.751244] [longitude: 37.618423] "
        "[rel_alt: 45.300 abs_alt: 210.123] [gb_pitch: -89.9]"
    )
    assert modern == {
        "focalLength35mm": 24.0,
        "latitude": 55.751244,
        "longitude": 37.618423,
        "relativeAltitudeM": 45.3,
        "absoluteAltitudeM": 210.123,
        "gimbalPitchDeg": -89.9,
    }
    mavic2 = frames.parse_telemetry_text(
        "F/2.8, SS 320, ISO 100, EV 0, GPS (37.6184, 55.7512, 19), D 25.3m, H 45.3m, H.S 0.0m/s"
    )
    assert mavic2 == {"longitude": 37.6184, "latitude": 55.7512, "relativeAltitudeM": 45.3}
    phantom = frames.parse_telemetry_text(
        "HOME(37.6,55.7) 2018.05.20 GPS(37.6184,55.7512,19) BAROMETER:45.3 ISO:100"
    )
    assert phantom["relativeAltitudeM"] == 45.3 and phantom["latitude"] == 55.7512
    typo = frames.parse_telemetry_text("[latitude : 41.1] [longtitude : 2.1] [altitude: 123.4]")
    assert typo == {"latitude": 41.1, "longitude": 2.1, "absoluteAltitudeM": 123.4}
    assert frames.parse_telemetry_text("[latitude: 0.0] [longitude: 0.0]") == {}


def test_srt_cues_and_lookup() -> None:
    cues = frames.parse_srt("﻿" + dji_srt(1.0, fps=5))
    assert len(cues) == 5
    assert cues[1].start_s == pytest.approx(0.2) and cues[1].end_s == pytest.approx(0.4)
    at = frames.telemetry_at(cues, 0.25)
    assert at is not None and at["relativeAltitudeM"] == 60.0
    assert frames.telemetry_at(cues, 1.5) is not None  # nearest cue within a second
    assert frames.telemetry_at(cues, 5.0) is None
    hint = frames.scale_hint(at, 1920, 1080)
    assert hint is not None and hint["assumesNadir"] is True
    assert hint["nadirGroundWidthM"] == pytest.approx(94.27, abs=0.05)
    assert frames.scale_hint({**at, "gimbalPitchDeg": -45.0}, 1920, 1080) == {
        "oblique": True,
        "gimbalPitchDeg": -45.0,
    }
    assert frames.scale_hint({"latitude": 1.0}, 1920, 1080) is None


def _index(tmp: Path, extraction: str, media: dict[str, Any], times: list[float]) -> None:
    index = {
        "indexVersion": frames.INDEX_VERSION,
        "sourceMedia": [media],
        "extraction": {
            "id": extraction,
            "mediaId": media["id"],
            "method": "fixed_interval",
            "intervalS": 1.0,
            "frameCount": len(times),
            "outputDirectory": f"frames/{extraction}",
            "tool": {"name": "ffmpeg", "version": "6.1"},
            "parameters": {"method": "interval"},
        },
        "frames": [
            {
                "id": frames.frame_id(extraction, t),
                "timestampS": t,
                "file": f"frames/{extraction}/{frames.frame_id(extraction, t)}.jpg",
            }
            for t in times
        ],
    }
    frames.write_json(tmp / "analysis" / f"frames-{extraction}.json", index)


def test_source_section_is_a_valid_contract_section(tmp_path: Path) -> None:
    media = {
        "id": "vid-clip",
        "kind": "video",
        "file": {"path": "media/clip.mp4", "mediaType": "video/mp4"},
        "durationS": 3.0,
    }
    _index(tmp_path, "vid-clip-x02", media, [1.5])
    _index(tmp_path, "vid-clip-x01", media, [0.0, 1.0, 2.0])
    source = frames.build_source(tmp_path, frames.read_indexes(tmp_path))
    model = Source.model_validate(source, by_alias=True, by_name=False)
    assert [e.id for e in model.frame_extractions] == ["vid-clip-x01", "vid-clip-x02"]
    assert [f.id for f in model.frames] == [
        "vid-clip-x01-00000000",
        "vid-clip-x01-00001000",
        "vid-clip-x01-00002000",
        "vid-clip-x02-00001500",
    ]
    report = model.analysis_reports[0]
    index_file = tmp_path / "analysis" / "frames-vid-clip-x01.json"
    assert report.file.sha256 == hashlib.sha256(index_file.read_bytes()).hexdigest()
    other = {**media, "file": {"path": "media/other.mp4", "mediaType": "video/mp4"}}
    _index(tmp_path, "vid-clip-x03", other, [0.0])
    with pytest.raises(frames.FramesError, match="two different files"):
        frames.build_source(tmp_path, frames.read_indexes(tmp_path))


def test_files_are_copied_into_the_package_once(tmp_path: Path) -> None:
    outside = tmp_path / "in" / "My clip.MP4"
    outside.parent.mkdir()
    outside.write_bytes(b"video")
    pkg = tmp_path / "pkg"
    copied = frames.place_in_package(outside, pkg)
    assert copied == (pkg / "media" / "My_clip.MP4").resolve()
    assert frames.place_in_package(outside, pkg) == copied
    assert frames.place_in_package(copied, pkg) == copied
    outside.write_bytes(b"other video")
    with pytest.raises(frames.FramesError, match="different content"):
        frames.place_in_package(outside, pkg)


# --------------------------------------------------------------------------- scale.py


@pytest.mark.parametrize(
    ("bearing", "expected"),
    [(0.0, (50.0, 25.0)), (90.0, (25.0, -50.0)), (180.0, (-50.0, -25.0)), (270.0, (-25.0, 50.0))],
)
def test_straight_down_mapping(bearing: float, expected: tuple[float, float]) -> None:
    x, z = scale.image_to_ground(
        (0.5, 0.5), origin=(0.0, 1.0), ground_width_m=100.0, ground_height_m=50.0,
        up_bearing_deg=bearing,
    )  # fmt: skip
    assert (x, z) == pytest.approx(expected)


def test_map_command_with_anchor_keeps_shapes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shapes = tmp_path / "shapes.json"
    shapes.write_text(
        json.dumps({"plot": [[0.5, 0.5], [0.6, 0.5], [0.6, 0.4]], "pole": [0.5, 0.4]})
    )
    code = scale.main(
        ["map", "--ground-width", "100", "--aspect", "2", "--anchor", "0.5", "0.5", "40", "30",
         "--json", str(shapes)]
    )  # fmt: skip
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"plot": [[40.0, 30.0], [50.0, 30.0], [50.0, 35.0]], "pole": [40.0, 35.0]}
    assert scale.main(["map", "--ground-width", "100", "--point", "a", "0", "0"]) == 1


def test_ground_homography_recovers_a_projective_mapping() -> None:
    truth = [[40.0, 10.0, -5.0], [3.0, -60.0, 50.0], [0.2, 0.9, 1.0]]

    def project(p: tuple[float, float]) -> tuple[float, float]:
        w = truth[2][0] * p[0] + truth[2][1] * p[1] + truth[2][2]
        return (
            (truth[0][0] * p[0] + truth[0][1] * p[1] + truth[0][2]) / w,
            (truth[1][0] * p[0] + truth[1][1] * p[1] + truth[1][2]) / w,
        )

    image = [(0.1, 0.2), (0.9, 0.25), (0.8, 0.9), (0.15, 0.85), (0.5, 0.5)]
    h = scale.fit_homography(image, [project(p) for p in image])
    for p in [(0.3, 0.6), (0.7, 0.4), (0.05, 0.95)]:
        assert scale.map_ground(h, p) == pytest.approx(project(p), abs=1e-6)
    with pytest.raises(scale.ScaleError, match="collinear"):
        scale.fit_homography(
            [(0.1, 0.1), (0.2, 0.2), (0.3, 0.3), (0.4, 0.4)], [(0, 0), (1, 0), (1, 1), (0, 1)]
        )
    with pytest.raises(scale.ScaleError, match="four"):
        scale.fit_homography(image[:3], [project(p) for p in image[:3]])


def test_estimates_and_their_confidence() -> None:
    estimate = scale.ratio_estimate(4.15, 0.060, 0.115, ref_min=4.0, ref_max=4.3)
    assert estimate["valueM"] == pytest.approx(7.954, abs=1e-3)
    assert estimate["relativeError"] == pytest.approx(0.146, abs=1e-3)
    assert estimate["suggestedConfidence"] == 0.65
    with pytest.raises(scale.ScaleError):
        scale.ratio_estimate(4.15, 0.06, 0.1, ref_min=4.2, ref_max=4.3)
    agree = scale.combine([(7.2, 0.6), (6.8, 0.9)])
    assert agree["consistent"] is True
    assert agree["valueM"] == pytest.approx(7.077, abs=1e-3)
    assert agree["sigmaM"] == pytest.approx(0.499, abs=1e-3)
    disagree = scale.combine([(7.2, 0.6), (6.8, 0.9), (12.0, 0.5)])
    assert disagree["consistent"] is False
    assert disagree["sigmaM"] >= 2.5  # the spread, not the formal error
    assert [scale.confidence_for(e) for e in (0.04, 0.1, 0.2, 0.3, 0.5)] == [
        0.9,
        0.8,
        0.65,
        0.5,
        0.3,
    ]


def test_yaw_and_fractions_along_a_fence() -> None:
    assert scale.yaw_from_image(90.0, 300.0) == 30.0
    assert scale.yaw_from_image(0.0, 360.0) == 0.0
    path = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    assert scale.along_path(path, (5.0, 1.0))["fraction"] == 0.25
    assert scale.along_path(path, (10.0, 5.0))["fraction"] == 0.75
    closed = scale.along_path(path, (5.0, 5.0), closed=True)
    assert closed["pathLengthM"] == pytest.approx(20 + math.sqrt(200), abs=0.01)


# --------------------------------------------------------------------------- package and review


def _footage_blueprint(tmp: Path, **extra: Any) -> Path:
    """A small footage-derived package with real files for media and frames."""
    (tmp / "media").mkdir(parents=True)
    (tmp / "frames").mkdir()
    video = tmp / "media" / "clip.mp4"
    video.write_bytes(b"not really a video")
    frame_ids = ["vid-clip-x01-00000000", "vid-clip-x01-00001000"]
    for fid in frame_ids:
        (tmp / "frames" / f"{fid}.jpg").write_bytes(b"jpg")
    seen = {
        "category": "observed",
        "confidence": 0.7,
        "frameIds": [frame_ids[0]],
        "positionAccuracyM": 2.0,
    }
    document: dict[str, Any] = {
        "schemaVersion": "1.0",
        "locationId": "clip-place",
        "name": "Clip place",
        "metadata": {"createdAt": "2026-10-12T10:00:00Z"},
        "coordinateSystem": {
            **package.COORDINATE_SYSTEM,
            "bounds": {"widthM": 100.0, "depthM": 80.0},
        },
        "source": {
            "type": "video",
            "media": [
                {
                    "id": "vid-clip",
                    "kind": "video",
                    "file": {
                        "path": "media/clip.mp4",
                        "sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                        "sizeBytes": video.stat().st_size,
                    },
                }
            ],
            "frames": [
                {"id": fid, "mediaId": "vid-clip", "file": {"path": f"frames/{fid}.jpg"}}
                for fid in frame_ids
            ],
            "calibration": {"method": "manual_scale", "estimatedErrorM": 1.5},
        },
        "plots": [
            {"id": "plot-01", "provenance": seen, "plotType": "dacha_plot",
             "polygon": [[10.0, 10.0], [40.0, 10.0], [40.0, 30.0], [10.0, 30.0]]},
        ],
        "buildings": [
            {"id": "b-house-01", "provenance": seen, "archetype": "wooden_house_small",
             "buildingType": "house", "transform": {"position": [25.0, 0.0, 20.0], "yawDeg": 180.0},
             "dimensions": {"widthM": 6.5, "depthM": 5.5, "heightM": 5.5}, "floors": 1},
        ],
    }  # fmt: skip
    for key, value in extra.items():
        document[key] = value
    path = tmp / "location.blueprint.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def _codes(issues: list[Any]) -> set[str]:
    return {issue.code for issue in issues}


def test_review_is_quiet_on_a_careful_blueprint(tmp_path: Path) -> None:
    contract, findings, reviewed = review.review(_footage_blueprint(tmp_path))
    assert reviewed
    assert [i.code for i in contract] == []
    assert _codes(findings) == {"REVIEW_EVIDENCE_COVERAGE"}


def test_review_flags_dishonest_or_implausible_data(tmp_path: Path) -> None:
    uncited = {"category": "observed", "confidence": 0.95, "positionAccuracyM": 0.2}
    path = _footage_blueprint(
        tmp_path,
        trees=[
            {"id": "t-apple-01", "species": "apple", "heightM": 14.0,
             "transform": {"position": [50.0, 0.0, 50.0]}, "provenance": uncited},
            {"id": "t-apple-02", "species": "apple", "transform": {"position": [50.0, 0.0, 50.0]},
             "provenance": {"category": "inferred", "confidence": 0.4}},
        ],
        fences=[{"id": "f-01", "fenceType": "wooden_picket", "heightM": 5.0,
                 "path": [[10.0, 10.0], [40.0, 10.0]]}],
        props=[{"id": "pr-01", "propType": "car", "archetype": "lada_2107",
                "transform": {"position": [60.0, 0.0, 20.0]}, "provenance": uncited}],
    )  # fmt: skip
    document = json.loads(path.read_text())
    document["source"]["calibration"] = {"method": "none"}
    path.write_text(json.dumps(document))
    contract, findings, _ = review.review(path)
    assert "UNCALIBRATED_MEASUREMENTS" in _codes(contract)
    assert {
        "REVIEW_OBSERVED_WITHOUT_EVIDENCE",
        "REVIEW_INFERRED_WITHOUT_REASON",
        "REVIEW_CONFIDENCE_ABOVE_CALIBRATION",
        "REVIEW_POSITION_ACCURACY_OPTIMISTIC",
        "REVIEW_POSITION_ACCURACY_MISSING",
        "REVIEW_PROVENANCE_MISSING",
        "REVIEW_SIZE_IMPLAUSIBLE",
        "REVIEW_DUPLICATE_POSITION",
        "REVIEW_ARCHETYPE_UNKNOWN",
    } <= _codes(findings)
    implausible = {i.entity_ids[0] for i in findings if i.code == "REVIEW_SIZE_IMPLAUSIBLE"}
    assert implausible == {"t-apple-01", "f-01"}


def test_review_rules_for_buildings(tmp_path: Path) -> None:
    path = _footage_blueprint(tmp_path)
    document = json.loads(path.read_text())
    house = document["buildings"][0]
    house["dimensions"]["heightM"] = 14.0
    ruin = {
        **house,
        "id": "b-ruin-01",
        "condition": 0.2,
        "transform": {"position": [70.0, 0.0, 60.0]},
    }
    ruin["dimensions"] = {"widthM": 8.0, "depthM": 6.0, "heightM": 1.5}
    document["buildings"].append(ruin)
    path.write_text(json.dumps(document))
    _, findings, _ = review.review(path)
    by_code = {(i.code, i.entity_ids[0]) for i in findings if i.entity_ids}
    assert ("REVIEW_HEIGHT_FOR_FLOORS", "b-house-01") in by_code
    assert ("REVIEW_SIZE_UNUSUAL", "b-house-01") in by_code
    assert not any(entity == "b-ruin-01" for _, entity in by_code)


def test_review_reports_schema_errors_without_running(tmp_path: Path) -> None:
    path = tmp_path / "location.blueprint.json"
    path.write_text(json.dumps({"schemaVersion": "1.0", "locationId": "x"}))
    contract, findings, reviewed = review.review(path)
    assert not reviewed and findings == []
    assert "SCHEMA_MISSING" in _codes(contract)
    assert review.main([str(path)]) == 1


def test_review_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _footage_blueprint(tmp_path)
    assert review.main([str(path)]) == 0
    assert "0 error(s), 0 warning(s)" in capsys.readouterr().out
    assert review.main([str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] and payload["reviewed"]
    assert payload["diagnostics"][0]["category"] == "review"
    document = json.loads(path.read_text())
    del document["buildings"][0]["provenance"]
    path.write_text(json.dumps(document))
    assert review.main([str(path)]) == 0
    assert review.main([str(path), "--strict"]) == 2


@pytest.mark.parametrize("location", ["dacha-forest-edge", "minimal", "industrial-outskirts"])
def test_review_has_no_warnings_on_the_examples(location: str) -> None:
    contract, findings, reviewed = review.review(LOCATIONS / location / "location.blueprint.json")
    assert reviewed
    assert [i.code for i in [*contract, *findings] if i.severity.value != "info"] == []


def test_init_writes_a_valid_blueprint_and_never_overwrites(tmp_path: Path) -> None:
    args = [
        "init", "--package", str(tmp_path), "--location-id", "clip-place", "--name", "Clip place",
        "--width", "100", "--depth", "80", "--created-at", "2026-10-12T10:00:00Z",
        "--geo", "55.75", "37.61", "--heading", "370",
    ]  # fmt: skip
    assert package.main(args) == 1  # no analysis/source.json yet
    assert package.main([*args, "--allow-no-frames"]) == 0
    target = tmp_path / "location.blueprint.json"
    document = json.loads(target.read_text())
    assert document["coordinateSystem"]["geoReference"]["headingDeg"] == 10.0
    assert document["source"]["calibration"]["method"] == "none"
    before = target.read_bytes()
    assert package.main([*args, "--allow-no-frames"]) == 1
    assert target.read_bytes() == before


def test_merged_source_keeps_hand_written_material() -> None:
    blueprint = {
        "source": {
            "type": "manual",
            "media": [{"id": "photo-01", "kind": "image", "file": {"path": "media/p.jpg"}}],
            "frameExtractions": [{"id": "old-x01", "mediaId": "vid", "method": "keyframes"}],
            "frames": [{"id": "old-x01-00000000", "mediaId": "vid", "extractionId": "old-x01"}],
            "analysisReports": [
                {"id": "old-x01-index", "file": {"path": "analysis/frames-old-x01.json"},
                 "tool": {"name": package.FRAMES_TOOL}},
                {"id": "rep-notes", "file": {"path": "analysis/notes.md"},
                 "tool": {"name": "claude"}},
            ],
            "calibration": {"method": "manual_scale"},
        }
    }  # fmt: skip
    analysis = {
        "media": [{"id": "vid", "kind": "video", "file": {"path": "media/v.mp4"}}],
        "frameExtractions": [{"id": "vid-x01", "mediaId": "vid", "method": "fixed_interval"}],
        "frames": [{"id": "vid-x01-00000000", "mediaId": "vid", "extractionId": "vid-x01"}],
        "analysisReports": [
            {"id": "vid-x01-index", "file": {"path": "analysis/frames-vid-x01.json"},
             "tool": {"name": package.FRAMES_TOOL}},
        ],
    }  # fmt: skip
    merged = package.merged_source(blueprint, analysis)
    assert merged["type"] == "mixed"
    assert [m["id"] for m in merged["media"]] == ["photo-01", "vid"]
    assert [e["id"] for e in merged["frameExtractions"]] == ["vid-x01"]
    assert [f["id"] for f in merged["frames"]] == ["vid-x01-00000000"]
    assert [r["id"] for r in merged["analysisReports"]] == ["rep-notes", "vid-x01-index"]
    assert merged["calibration"] == {"method": "manual_scale"}
    cited = package.cited_frames(
        {"trees": [{"id": "t-1", "provenance": {"frameIds": ["old-x01-00000000"]}}]}
    )
    assert cited == {"old-x01-00000000": ["t-1"]}


# --------------------------------------------------------------------------- the skill's files


def test_size_rules_use_the_contract_vocabulary() -> None:
    rules = json.loads((SKILL / "size_rules.json").read_text(encoding="utf-8"))
    vocabularies = {
        "buildings": {v.value for v in BuildingType},
        "plots": {v.value for v in PlotType},
        "fences": {v.value for v in FenceType},
        "infrastructure": set(get_args(PointInfrastructureType)),
        "roads": {v.value for v in RoadImportance},
    }
    for section, allowed in vocabularies.items():
        assert set(rules[section]) == allowed, section
    assert "unknown" in rules["trees"]
    for section in ("buildings", "plots", "fences", "infrastructure", "roads", "trees"):
        for kind, fields in rules[section].items():
            for name, ranges in fields.items():
                (tl, th), (pl, ph) = ranges["typical"], ranges["plausible"]
                assert 0 < pl <= tl < th <= ph, f"{section}.{kind}.{name}"


def test_skill_document_links_and_commands_resolve() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    front = re.match(r"^---\nname: (.+)\ndescription: (.+)\n---\n", text)
    assert front is not None
    assert front.group(1) == SKILL.name
    assert 50 < len(front.group(2)) <= 1024
    documents = [SKILL / "SKILL.md", *sorted((SKILL / "reference").glob("*.md"))]
    for document in documents:
        body = document.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", body):
            if "://" not in target:
                assert (document.parent / target).exists(), f"{document.name} -> {target}"
    subcommands = {
        name: set(load(name).build_parser()._subparsers._group_actions[0].choices)
        for name in ("frames", "scale", "location_package")
    }
    for document in documents:
        body = document.read_text(encoding="utf-8")
        for script, command in re.findall(r"\$S/(\w+)\.py (\w[\w-]*)", body):
            assert (SCRIPTS / f"{script}.py").exists(), script
            if script in subcommands:
                assert command in subcommands[script], f"{script}.py {command}"
