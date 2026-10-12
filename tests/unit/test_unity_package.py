"""Structure of the Unity importer package (integrations/unity).

The C# code itself is tested with ``dotnet test`` (see the package README); these
checks keep the package installable: every asset has a stable ``.meta`` file, the
manifests are valid, and the engine-free core stays free of UnityEngine.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

from tests.conftest import REPO_ROOT

PACKAGE = REPO_ROOT / "integrations" / "unity" / "com.environment-generator.importer"

_spec = importlib.util.spec_from_file_location(
    "unity_package_meta", REPO_ROOT / "scripts" / "unity_package_meta.py"
)
assert _spec is not None and _spec.loader is not None
meta = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = meta
_spec.loader.exec_module(meta)


def test_every_asset_has_a_meta_file_and_guids_are_unique() -> None:
    assets = meta.assets(PACKAGE)
    assert assets
    missing = [str(p.relative_to(PACKAGE)) for p in assets if not Path(f"{p}.meta").exists()]
    assert missing == [], "run `uv run python scripts/unity_package_meta.py`"
    metas = sorted(PACKAGE.rglob("*.meta"))
    orphans = [
        str(m.relative_to(PACKAGE)) for m in metas if not Path(str(m)[: -len(".meta")]).exists()
    ]
    assert orphans == []
    guids = [re.search(r"^guid: ([0-9a-f]{32})$", m.read_text(), re.M) for m in metas]
    assert all(guids)
    values = [g.group(1) for g in guids if g]
    assert len(set(values)) == len(values)


def test_package_manifest() -> None:
    data = json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))
    assert data["name"] == "com.environment-generator.importer"
    assert re.fullmatch(r"\d+\.\d+\.\d+", data["version"])
    assert data["unity"] == "2021.3"
    assert "com.unity.nuget.newtonsoft-json" in data["dependencies"]


def test_assembly_definitions() -> None:
    asmdefs = {
        p.relative_to(PACKAGE).as_posix(): json.loads(p.read_text(encoding="utf-8"))
        for p in PACKAGE.rglob("*.asmdef")
    }
    core = asmdefs["Runtime/Core/EnvGen.Importer.Core.asmdef"]
    runtime = asmdefs["Runtime/EnvGen.Importer.asmdef"]
    editor = asmdefs["Editor/EnvGen.Importer.Editor.asmdef"]
    assert core["noEngineReferences"] is True
    assert runtime["references"] == ["EnvGen.Importer.Core"]
    assert editor["includePlatforms"] == ["Editor"]
    assert set(editor["references"]) == {"EnvGen.Importer.Core", "EnvGen.Importer"}
    for data in asmdefs.values():
        assert data["precompiledReferences"] == ["Newtonsoft.Json.dll"]


def test_core_does_not_use_the_engine() -> None:
    for path in (PACKAGE / "Runtime" / "Core").glob("*.cs"):
        text = path.read_text(encoding="utf-8")
        assert "using UnityEngine" not in text and "using UnityEditor" not in text, path.name


def test_unity_objects_live_in_files_named_after_them() -> None:
    """Unity serializes MonoBehaviours and ScriptableObjects only from a same-named file."""
    pattern = re.compile(r"class (\w+)\s*:\s*(MonoBehaviour|ScriptableObject|EditorWindow)\b")
    found = 0
    for path in PACKAGE.rglob("*.cs"):
        for name, _ in pattern.findall(path.read_text(encoding="utf-8")):
            assert name == path.stem, f"{name} is declared in {path.name}"
            found += 1
    assert found >= 7
