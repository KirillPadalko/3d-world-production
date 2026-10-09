# Notes for coding agents

This repository is a standalone Python package (`src/environment_generator`)
with a CLI (`envgen`). Read `docs/ARCHITECTURE.md` first.

## Commands

```bash
uv sync                                   # install from uv.lock
uv run pytest                             # all tests (must stay green)
uv run ruff format . && uv run ruff check .
uv run mypy                               # strict
uv run envgen schema export               # after changing any model in models/
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
* Public contracts live in `models/`; `schemas/` is generated from them and
  must be re-exported after changes (CI checks drift).
* Adapters for external systems stay in `adapters/` and must fail loudly
  (`AdapterUnavailableError`) until they are really implemented.

## Integrating into Unity

The integration contract is `scene-manifest.json`
(`schemas/scene-manifest.schema.json`). Follow
`docs/ADAPTERS.md#unity-integration-guide-for-the-future-importer` for
coordinate conversion (positions `(x, z, y)`, yaw `-yaw`), terrain, entities
and lighting.
