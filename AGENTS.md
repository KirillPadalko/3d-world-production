# Notes for coding agents

This repository is a standalone Python package (`src/environment_generator`)
with a CLI (`envgen`). Read `docs/ARCHITECTURE.md` first; the input contract is
specified in `docs/LOCATION_BLUEPRINT.md`.

## Commands

```bash
uv sync                                   # install from uv.lock
uv run pytest                             # all tests (must stay green)
uv run ruff format . && uv run ruff check .
uv run mypy                               # strict
uv run envgen schema export               # after changing any model in models/
uv run envgen blueprint validate examples/locations/dacha-forest-edge/location.blueprint.json
uv run python scripts/regenerate_expected_output.py   # after changing generated output
```

## Invariants

* The core never imports Unity, `bpy`, MCP or AI SDKs, or network libraries;
  runtime dependency is `pydantic` only. `tests/unit/test_architecture.py`
  enforces package layering.
* Output is deterministic: use `context.rng(...)` for randomness, derive
  entity IDs from blueprint feature IDs, sort what you emit.
* Changing generated output requires bumping the generator `version` and the
  package `__version__`, regenerating `examples/expected-output`, and
  committing both.
* Public contracts live in `models/` (LocationBlueprint v1.0 in
  `models/blueprint/`); `schemas/` is generated from them and must be
  re-exported after changes (CI checks drift). Public JSON is camelCase; a
  breaking blueprint change needs a new major `schemaVersion` and a
  migration.
* One spatial frame for public documents: metres, +X east, +Y up, +Z north,
  yaw clockwise from north. Generators work in a Z-up frame; convert only via
  `core/frames.py` (site adapter in, exporter out). Never reinterpret axes
  silently.
* Never mutate an input blueprint; never overwrite a blueprint file without an
  explicit user action; never invent source references or random IDs.
* Adapters for external systems stay in `adapters/` and must fail loudly
  (`AdapterUnavailableError`) until they are really implemented.

## Integrating into Unity

The integration contract is `scene-manifest.json`
(`schemas/scene-manifest.schema.json`). It already uses Unity's axes
(positions, scales and `Quaternion.Euler(rotationDeg)` are used unchanged).
Follow `docs/ADAPTERS.md#unity-integration-guide-for-the-future-importer` for
terrain, entities, annotations and lighting.
