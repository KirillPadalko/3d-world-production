"""Create missing Unity ``.meta`` files for the importer package.

Unity ignores assets without ``.meta`` files in immutable packages (installed
from a git URL), so every file and folder of the package needs one. GUIDs are
derived from the package-relative path, so running this again is a no-op and
regenerating a deleted ``.meta`` yields the same GUID.

    uv run python scripts/unity_package_meta.py          # write missing files
    uv run python scripts/unity_package_meta.py --check  # exit 1 if any is missing
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

PACKAGE = (
    Path(__file__).resolve().parents[1]
    / "integrations"
    / "unity"
    / "com.environment-generator.importer"
)

_TAIL = "  userData: \n  assetBundleName: \n  assetBundleVariant: \n"
IMPORTERS = {
    ".cs": "MonoImporter:\n  externalObjects: {}\n  serializedVersion: 2\n  defaultReferences: []\n"
    "  executionOrder: 0\n  icon: {instanceID: 0}\n" + _TAIL,
    ".asmdef": "AssemblyDefinitionImporter:\n  externalObjects: {}\n" + _TAIL,
    ".json": "TextScriptImporter:\n  externalObjects: {}\n" + _TAIL,
    ".md": "TextScriptImporter:\n  externalObjects: {}\n" + _TAIL,
}
PACKAGE_MANIFEST = "PackageManifestImporter:\n  externalObjects: {}\n" + _TAIL
FOLDER = "folderAsset: yes\nDefaultImporter:\n  externalObjects: {}\n" + _TAIL


def guid_for(relative: str) -> str:
    return hashlib.md5(f"{PACKAGE.name}/{relative}".encode()).hexdigest()


def assets(package: Path = PACKAGE) -> list[Path]:
    """Files and folders Unity imports (no .meta files, no hidden or ``~`` folders)."""
    found = []
    for path in sorted(package.rglob("*")):
        parts = path.relative_to(package).parts
        if any(p.startswith(".") or p.endswith("~") for p in parts) or path.suffix == ".meta":
            continue
        found.append(path)
    return found


def meta_text(path: Path, package: Path = PACKAGE) -> str:
    relative = path.relative_to(package).as_posix()
    if path.is_dir():
        body = FOLDER
    elif relative == "package.json":
        body = PACKAGE_MANIFEST
    elif path.suffix in IMPORTERS:
        body = IMPORTERS[path.suffix]
    else:
        body = "DefaultImporter:\n  externalObjects: {}\n" + _TAIL
    return f"fileFormatVersion: 2\nguid: {guid_for(relative)}\n{body}"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    missing = [p for p in assets() if not Path(f"{p}.meta").exists()]
    for path in missing:
        if check:
            print(f"missing: {path.relative_to(PACKAGE)}.meta")
        else:
            Path(f"{path}.meta").write_text(meta_text(path), encoding="utf-8")
            print(f"wrote {path.relative_to(PACKAGE)}.meta")
    return 1 if check and missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
