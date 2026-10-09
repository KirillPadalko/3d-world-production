from __future__ import annotations

import json
from pathlib import Path

import pytest

from environment_generator import __version__
from environment_generator.cli.main import main
from tests.conftest import MINIMAL_BLUEPRINT, RURAL_BLUEPRINT, RURAL_RECIPE, SCHEMAS


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
    bad.write_text(json.dumps({"schema_version": "1.0", "id": "x", "name": "X"}), encoding="utf-8")
    assert main(["validate", "-b", str(bad)]) == 3
    assert "extent" in capsys.readouterr().err


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
                "schema_version": "1.0",
                "id": "env-registry",
                "name": "Env",
                "archetypes": [
                    {
                        "id": "prop.box.plain",
                        "category": "prop",
                        "kinds": ["generic"],
                        "dimensions": {"width_m": 1, "depth_m": 1, "height_m": 1},
                        "asset_ref": "x",
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
    assert manifest["source"]["registry_id"] == "env-registry"
    assert manifest["statistics"]["placeholder_count"] > 0
