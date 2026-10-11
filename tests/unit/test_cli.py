from __future__ import annotations

import json
from pathlib import Path

import pytest

from environment_generator import __version__
from environment_generator.cli.main import main
from tests.blueprints import location_data
from tests.conftest import (
    DACHA_BLUEPRINT,
    MINIMAL_BLUEPRINT,
    RURAL_BLUEPRINT,
    RURAL_RECIPE,
    SCHEMAS,
)


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_validate_ok_and_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", "-b", str(RURAL_BLUEPRINT), "-r", str(RURAL_RECIPE)]) == 0
    assert "Inputs are valid" in capsys.readouterr().out
    assert main(["validate", "-b", str(MINIMAL_BLUEPRINT), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_validate_reports_contract_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    data = location_data()
    del data["coordinateSystem"]
    bad.write_text(json.dumps(data), encoding="utf-8")
    assert main(["validate", "-b", str(bad)]) == 3
    assert "coordinateSystem" in capsys.readouterr().err


def test_plan_writes_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "plan.json"
    assert main(["plan", "-b", str(MINIMAL_BLUEPRINT), "--seed", "4", "--output", str(target)]) == 0
    plan = json.loads(target.read_text(encoding="utf-8"))
    assert plan["seed"] == 4 and plan["tasks"]
    assert "DRY RUN succeeded" in capsys.readouterr().out


def test_generate_preview_verify_round_trip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    code = main(
        [
            "generate",
            "-b",
            str(MINIMAL_BLUEPRINT),
            "-d",
            str(out),
            "--preview",
            "--write-plan",
            "--no-timings",
        ]
    )
    assert code == 0
    assert {p.name for p in out.iterdir()} == {
        "scene-manifest.json",
        "generation-report.json",
        "generation-plan.json",
        "preview.svg",
    }
    assert main(["verify", str(out / "scene-manifest.json")]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1].startswith("OK sha256:")

    replay = tmp_path / "replay"
    assert main(["generate", "--plan", str(out / "generation-plan.json"), "-d", str(replay)]) == 0
    assert (replay / "scene-manifest.json").read_bytes() == (
        out / "scene-manifest.json"
    ).read_bytes()

    preview = tmp_path / "custom.svg"
    assert main(["preview", str(out / "scene-manifest.json"), "--output", str(preview)]) == 0
    assert preview.read_text(encoding="utf-8").startswith("<svg")


def test_verify_detects_tampering(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert main(["generate", "-b", str(MINIMAL_BLUEPRINT), "-d", str(out)]) == 0
    manifest_path = out / "scene-manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["entities"][0]["transform"]["position"][0] += 1.0
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    assert main(["verify", str(manifest_path)]) == 3


def test_generate_dry_run_and_failure_exit_codes(tmp_path: Path) -> None:
    out = tmp_path / "dry"
    assert main(["generate", "-b", str(MINIMAL_BLUEPRINT), "-d", str(out), "--dry-run"]) == 0
    assert {p.name for p in out.iterdir()} == {"generation-plan.json", "generation-report.json"}

    bad = tmp_path / "missing.json"
    failed = tmp_path / "failed"
    assert main(["generate", "-b", str(bad), "-d", str(failed)]) == 3
    report = json.loads((failed / "generation-report.json").read_text(encoding="utf-8"))
    assert report["success"] is False
    assert report["error"]["code"] == "INPUT_LOAD_ERROR"
    assert report["error"]["stage"] == "load_inputs"


def test_generate_argument_errors(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["generate", "-d", str(tmp_path)])
    with pytest.raises(SystemExit):
        main(["generate", "--plan", "p.json", "-b", str(MINIMAL_BLUEPRINT), "-d", str(tmp_path)])


def test_schema_check_and_export(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema", "check", "--output-dir", str(SCHEMAS)]) == 0
    assert main(["schema", "check", "--output-dir", str(tmp_path)]) == 3
    assert main(["schema", "export", "--output-dir", str(tmp_path)]) == 0
    assert main(["schema", "check", "--output-dir", str(tmp_path)]) == 0
    assert "up to date" in capsys.readouterr().out


def test_assets_and_adapters_listing(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["assets", "list", "--category", "fence"]) == 0
    out = capsys.readouterr().out
    assert "fence.panel.wooden" in out and "building." not in out
    assert main(["adapters", "list"]) == 0
    assert "[stub ]" in capsys.readouterr().out


def test_registry_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "id": "env-registry",
                "name": "Env",
                "archetypes": [
                    {
                        "id": "prop.box.plain",
                        "category": "prop",
                        "kinds": ["other"],
                        "dimensions": {"widthM": 1, "depthM": 1, "heightM": 1},
                        "assetRef": "x",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ENVGEN_ASSET_REGISTRY", str(registry))
    monkeypatch.setenv("ENVGEN_LOG_LEVEL", "error")
    out = tmp_path / "out"
    assert main(["generate", "-b", str(MINIMAL_BLUEPRINT), "-d", str(out)]) == 0
    manifest = json.loads((out / "scene-manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"]["registryId"] == "env-registry"
    assert manifest["statistics"]["placeholderCount"] > 0


def test_blueprint_validate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["blueprint", "validate", str(DACHA_BLUEPRINT)]) == 0
    assert "valid (schema 1.0; 0 error(s)" in capsys.readouterr().out
    bad = tmp_path / "location.blueprint.json"
    bad.write_text(
        json.dumps(
            location_data(
                terrain={
                    "heightmap": {
                        "file": {"path": "missing.r16"},
                        "encoding": "raw_u16_le",
                        "columns": 2,
                        "rows": 2,
                        "rowOrder": "south_to_north",
                        "heightScaleM": 0.01,
                    }
                }
            )
        ),
        encoding="utf-8",
    )
    assert main(["blueprint", "validate", str(bad), "--json"]) == 3
    report = json.loads(capsys.readouterr().out)
    assert report["valid"] is False
    assert [d["code"] for d in report["diagnostics"]] == ["EXTERNAL_FILE_MISSING"]
    assert report["diagnostics"][0]["path"] == "terrain.heightmap.file"
    assert main(["blueprint", "validate", str(bad), "--no-external"]) == 0


def test_blueprint_format(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["blueprint", "format", "--check", str(DACHA_BLUEPRINT)]) == 0
    messy = tmp_path / "messy.json"
    messy.write_text(json.dumps(location_data(status="draft")), encoding="utf-8")
    assert main(["blueprint", "format", "--check", str(messy)]) == 3
    capsys.readouterr()
    assert main(["blueprint", "format", str(messy)]) == 0
    canonical = capsys.readouterr().out
    assert '"status"' not in canonical  # defaults are omitted
    target = tmp_path / "clean.json"
    assert main(["blueprint", "format", str(messy), "--output", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == canonical
    assert main(["blueprint", "format", str(messy), "--output", str(messy)]) == 6
    assert main(["blueprint", "format", str(messy), "--output", str(target)]) == 6  # exists


def test_blueprint_migrate_never_overwrites_without_consent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "location.blueprint.json"
    source.write_text(json.dumps(location_data()), encoding="utf-8")
    original = source.read_bytes()
    with pytest.raises(SystemExit):
        main(["blueprint", "migrate", str(source)])  # --output or --in-place is required
    assert main(["blueprint", "migrate", str(source), "--output", str(source)]) == 6
    assert source.read_bytes() == original
    assert main(["blueprint", "migrate", str(source), "--in-place"]) == 0
    assert "Already current" in capsys.readouterr().out
    assert source.read_bytes() == original
    future = tmp_path / "future.json"
    future.write_text(json.dumps(location_data(schemaVersion="2.0")), encoding="utf-8")
    assert main(["blueprint", "migrate", str(future), "--output", str(tmp_path / "o.json")]) == 3
