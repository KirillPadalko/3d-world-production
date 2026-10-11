"""Regenerate ``examples/expected-output`` from the example inputs.

Run after any intentional change to generation behaviour, review the diff,
and commit the result together with the change:

    uv run python scripts/regenerate_expected_output.py

The golden test (tests/integration/test_expected_output.py) compares fresh
output against these files.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from environment_generator.pipeline import InputBundle, Pipeline, PipelineOptions

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
OUTPUT = EXAMPLES / "expected-output"


@dataclass(frozen=True)
class Case:
    name: str
    location: str
    recipe: str
    overrides: str | None = None

    def bundle(self) -> InputBundle:
        return InputBundle(
            blueprint=EXAMPLES / "locations" / self.location / "location.blueprint.json",
            recipe=EXAMPLES / "recipes" / self.recipe,
            overrides=EXAMPLES / "overrides" / self.overrides if self.overrides else None,
        )


CASES = (
    Case("rural-crossroads.stylized-rural", "rural-crossroads", "stylized-rural.recipe.json"),
    Case(
        "rural-crossroads.stylized-rural.designer-pass-01",
        "rural-crossroads",
        "stylized-rural.recipe.json",
        "rural-crossroads.designer-pass.overrides.json",
    ),
    Case("industrial-outskirts.war-torn", "industrial-outskirts", "war-torn.recipe.json"),
    Case(
        "dacha-forest-edge.dacha-overgrown.designer-pass-01",
        "dacha-forest-edge",
        "dacha-overgrown.recipe.json",
        "dacha-forest-edge.designer-pass.overrides.json",
    ),
)


def generate(case: Case, directory: Path) -> bool:
    options = PipelineOptions(output_dir=directory, write_preview=True, include_timings=False)
    result = Pipeline().run(case.bundle(), options)
    if not result.success:
        print(f"{case.name}: FAILED - {result.error}", file=sys.stderr)
    return result.success


def main() -> int:
    ok = True
    for case in CASES:
        directory = OUTPUT / case.name
        if directory.exists():
            shutil.rmtree(directory)
        case_ok = generate(case, directory)
        ok = ok and case_ok
        print(f"{case.name}: {'ok' if case_ok else 'failed'} -> {directory.relative_to(ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
