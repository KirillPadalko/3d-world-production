"""Module boundary rules (see docs/ARCHITECTURE.md).

These tests parse the source with :mod:`ast` so they fail on any new import
that breaks the layering, even one guarded by ``TYPE_CHECKING``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = "environment_generator"
SOURCE = Path(__file__).resolve().parents[2] / "src" / PACKAGE

#: Which internal packages each package may import.
ALLOWED: dict[str, set[str]] = {
    "core": {"core"},
    "models": {"core", "models"},
    "validation": {"core", "models", "validation"},
    "assets": {"core", "models", "assets"},
    "generators": {"core", "models", "assets", "generators"},
    "planning": {"core", "models", "assets", "generators", "planning", ""},
    "exporters": {"core", "models", "validation", "exporters", ""},
    "reporting": {"core", "models", "reporting"},
    "adapters": {"core", "models", "adapters"},
    "pipeline": {
        "core",
        "models",
        "validation",
        "assets",
        "generators",
        "planning",
        "exporters",
        "reporting",
        "pipeline",
        "",
    },
    "cli": {
        "core",
        "models",
        "validation",
        "assets",
        "generators",
        "planning",
        "exporters",
        "reporting",
        "pipeline",
        "adapters",
        "cli",
        "",
    },
}

#: Third-party modules the core must never import (engines, DCC tools, AI/MCP SDKs).
FORBIDDEN_EXTERNAL = {
    "bpy",
    "bmesh",
    "mathutils",
    "UnityEngine",
    "unity",
    "mcp",
    "anthropic",
    "openai",
    "requests",
    "httpx",
    "numpy",
}
ALLOWED_EXTERNAL = {"pydantic"}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


def _package_of(path: Path) -> str:
    relative = path.relative_to(SOURCE)
    return relative.parts[0] if len(relative.parts) > 1 else ""


SOURCES = sorted(SOURCE.rglob("*.py"))


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(SOURCE)))
def test_internal_layering(path: Path) -> None:
    package = _package_of(path)
    if package == "":
        return  # top-level modules (__init__, __main__) may wire anything
    allowed = ALLOWED[package]
    for name in _imports(path):
        if name == PACKAGE:
            assert "" in allowed, (
                f"{path.relative_to(SOURCE)} must not import the top-level package"
            )
            continue
        if not name.startswith(PACKAGE + "."):
            continue
        target = name.split(".")[1]
        assert target in allowed, f"{path.relative_to(SOURCE)} must not import {name}"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(SOURCE)))
def test_no_engine_or_network_dependencies(path: Path) -> None:
    for name in _imports(path):
        root = name.split(".")[0]
        assert root not in FORBIDDEN_EXTERNAL, f"{path.relative_to(SOURCE)} imports {name}"


def test_only_declared_third_party_dependencies() -> None:
    import sys

    stdlib = set(sys.stdlib_module_names)
    for path in SOURCES:
        for name in _imports(path):
            root = name.split(".")[0]
            if root == PACKAGE or root in stdlib or root == "__future__":
                continue
            assert root in ALLOWED_EXTERNAL, f"{path.relative_to(SOURCE)} imports undeclared {name}"
