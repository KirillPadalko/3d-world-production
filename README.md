# Environment Generator

[![CI](https://github.com/KirillPadalko/3d-world-production/actions/workflows/ci.yml/badge.svg)](https://github.com/KirillPadalko/3d-world-production/actions/workflows/ci.yml)

A standalone, deterministic procedural environment generator for an isometric
tactical game. It turns a **LocationBlueprint** (the engine-independent
description of a real place, contract v1.0) and a **LocationRecipe** (how to
stylise it), plus optional **LocationOverrides** (designer edits), into a
portable, engine-agnostic **scene manifest**: terrain, roads, buildings,
fences, infrastructure, vegetation, props and atmosphere, each entity with a
stable ID, archetype, transform, parameters and provenance.

![Dacha settlement at the forest edge](examples/expected-output/dacha-forest-edge.dacha-overgrown.designer-pass-01/preview.svg)

*Top-down preview of the dacha fixture with the `dacha-overgrown` recipe and a
designer pass (`examples/expected-output/dacha-forest-edge.dacha-overgrown.designer-pass-01`,
589 entities).*

## Where this fits

```
drone footage -> frames -> location analysis -> LocationBlueprint -> LocationRecipe -> asset selection
  -> procedural generation -> scene manifest -> Blender processing -> Unity integration -> validation
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                 implemented here (blueprint -> validated manifest)
```

| Part of the workflow | Status |
| --- | --- |
| LocationBlueprint v1.0 contract: models, JSON Schema, versioning, migrations, structured diagnostics | **Implemented** ([spec](docs/LOCATION_BLUEPRINT.md)) |
| Recipe / overrides contracts (Pydantic + JSON Schema) | **Implemented** |
| Validation (version, schema, semantic, references, external files, generated layout) | **Implemented** |
| Planning, 8 generator slots, asset resolution, manifest export, reports | **Implemented** |
| CLI, SVG preview, dry run, replay from a saved plan | **Implemented** |
| Unity coordinate helpers (the manifest already uses Unity's axes) | **Implemented** |
| Drone footage / location analysis | Interface + stub (fails loudly) |
| Blender processing | Interface + stub (fails loudly) |
| Unity scene import | **Unity Editor package** in [`integrations/unity`](integrations/unity/com.environment-generator.importer/README.md) (core unit-tested with .NET; not yet compiled inside Unity in CI) |

No external services, accounts, API keys, MCP servers, Unity or Blender are
needed. The core imports only the standard library and Pydantic.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # creates .venv from uv.lock (reproducible)

uv run envgen blueprint validate examples/locations/dacha-forest-edge/location.blueprint.json

uv run envgen generate \
  --blueprint examples/locations/dacha-forest-edge/location.blueprint.json \
  --recipe    examples/recipes/dacha-overgrown.recipe.json \
  --overrides examples/overrides/dacha-forest-edge.designer-pass.overrides.json \
  --output-dir out/dacha --preview

uv run envgen verify out/dacha/scene-manifest.json
```

`out/dacha` now contains `scene-manifest.json`, `generation-report.json` and
`preview.svg`. Running the same command again produces byte-identical files.

Without uv: `python -m venv .venv && .venv/bin/pip install -e .` and use
`.venv/bin/envgen`.

## Command line

| Command | Purpose |
| --- | --- |
| `envgen blueprint validate FILE [--json] [--no-external]` | Validate one blueprint: version, schema, semantics, references, files |
| `envgen blueprint format FILE [--check \| --output OUT]` | Canonical, deterministic JSON |
| `envgen blueprint migrate FILE (--output OUT \| --in-place)` | Upgrade to the current schema version (never overwrites silently) |
| `envgen validate -b BLUEPRINT [-r RECIPE] [-o OVERRIDES]` | Validate blueprint, recipe and overrides together, no generation |
| `envgen plan -b ... [--seed N] [--output plan.json]` | Dry run: stages 1-4, prints and optionally saves the plan |
| `envgen generate -b ... -d DIR [--seed N] [--dry-run] [--preview] [--write-plan] [--no-timings]` | Full pipeline |
| `envgen generate --plan plan.json -d DIR` | Generate from a saved plan (stages 5-8) |
| `envgen preview MANIFEST [--output file.svg]` | Render a manifest as a top-down SVG |
| `envgen verify MANIFEST` | Check a manifest against its content hash |
| `envgen schema export\|check [--output-dir schemas]` | Regenerate / drift-check the public JSON Schemas |
| `envgen assets list [--registry FILE] [--category C]` | Inspect an asset registry |
| `envgen adapters list` | Show integration points and whether they are real or stubs |

Exit codes: `0` success, `2` usage, `3` invalid input, `4` asset/planning/generation
failure, `5` layout validation failed, `6` export failure, `7` adapter unavailable.
`--recipe` defaults to a built-in recipe; `--registry` defaults to the built-in
archetype registry (or `ENVGEN_ASSET_REGISTRY`).

## Library use

```python
from pathlib import Path
from environment_generator.pipeline import InputBundle, Pipeline, PipelineOptions

result = Pipeline().run(
    InputBundle(
        blueprint=Path("examples/locations/minimal/location.blueprint.json"),
        recipe=None,  # built-in default recipe
        seed_override=7,
    ),
    PipelineOptions(output_dir=Path("out/minimal"), write_preview=True),
)
if not result.success:
    raise SystemExit(result.error)
for entity in result.manifest.entities:
    print(entity.id, entity.archetype_id, entity.transform.position)
```

Every stage is also usable on its own (`LoadInputsStage`, `ResolveInputsStage`,
`ResolveAssetsStage`, `PlanGenerationStage`, `GenerateSceneStage`,
`ValidateLayoutStage`, `ExportManifestStage`, `BuildReportStage`), and any
generator, the validator or the exporter can be replaced through the
`Pipeline` constructor. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Inputs and outputs

All public documents are camelCase JSON in one spatial frame: metres, `+X`
east, `+Y` up, `+Z` north, yaw in degrees clockwise from north.

* **LocationBlueprint** ([spec](docs/LOCATION_BLUEPRINT.md),
  [schema](schemas/location-blueprint.schema.json)) - what is there: bounds,
  terrain (external heightmap and masks, surface and slope zones, water), a
  road graph with splines, plots, buildings (condition, abandonment), vegetation
  zones with species weights, trees, fences with missing sections,
  infrastructure, props, landmarks, gameplay annotations (movement, projectile
  cover and vision kept apart) and atmosphere. Every entity has a stable ID
  and provenance (`observed`, `inferred`, `manual`, `procedural` + confidence).
  It lives in a *location package* folder with its external files.
* **LocationRecipe** ([schema](schemas/location-recipe.schema.json)) - how to turn
  any blueprint into a game map: seeds and generation controls (falling back
  to the blueprint), asset filters, per-generator settings and layout limits.
  It contains no geometry or observations.
* **LocationOverrides** ([schema](schemas/location-overrides.schema.json)) -
  designer edits for one location by stable ID: `update` (merge patch),
  `replaceArchetype`, `delete`, `add`, and placement overrides of generated
  entities; conflicts fail or are reported, never dropped; the blueprint file
  is never modified.
* **Asset registry** ([schema](schemas/asset-registry.schema.json)) - abstract
  archetypes with nominal dimensions, tags, variants, biomes, tactical cover
  hints and an opaque `assetRef` that an engine maps to real assets.
* **Scene manifest** ([schema](schemas/scene-manifest.schema.json)) - the
  output: heightfield, atmosphere, entities sorted by ID, landmarks and
  gameplay annotations, statistics and a `sha256` content hash.

Examples live in [`examples/`](examples/): four location packages under
`examples/locations/` (including the
[dacha fixture](docs/LOCATION_BLUEPRINT.md#the-dacha-fixture)), recipes and
overrides. Expected outputs for four input combinations are committed under
[`examples/expected-output/`](examples/expected-output/) and checked by the
golden tests.

## Determinism

Same blueprint + recipe + overrides + registry + generator version + seed
=> byte-identical manifest, on any platform, across processes and
`PYTHONHASHSEED` values. The generator uses its own specified PRNG
(xoshiro256** seeded through SplitMix64), derives every random stream from
labelled SHA-256 hashes (per generator, per feature, per candidate), sorts
everything it emits and rounds floats to 0.1 mm in outputs. Entity IDs are
derived from blueprint feature IDs, so local edits do not renumber unrelated
entities. Details: [docs/GENERATION_PIPELINE.md](docs/GENERATION_PIPELINE.md#determinism).

## Repository layout

```
schemas/                     public JSON Schemas (generated from the models, drift-checked in CI)
src/environment_generator/
  core/          errors, issues, geometry, frames, curves, PRNG, hashing, spatial index, terrain
  models/        Pydantic contracts (models/blueprint/ = LocationBlueprint v1.0) and stage models
  blueprint/     blueprint services: versioning, IO, validation, overrides, site adapter
  validation/    contract loading, recipe/registry checks, layout validator + rules
  assets/        registry loading, palette filtering, deterministic asset resolver
  generators/    generator slot interfaces + built-in implementations
  planning/      dependency ordering and seed derivation
  pipeline/      the eight stages, override application, orchestrator
  exporters/     portable JSON manifest exporter
  reporting/     text summary and SVG preview
  adapters/      external integration interfaces (stubs) + Unity coordinate helpers
  cli/           envgen command line
integrations/unity/          Unity Editor importer package (C#) and its .NET tests
examples/                    location packages, recipes, overrides, expected output
tests/                       unit, integration (end-to-end, determinism, golden), contract
scripts/                     maintenance scripts (regenerate expected output, Unity .meta files)
docs/                        architecture, pipeline, adapters, development, roadmap
```

## Documentation

* [LocationBlueprint v1.0](docs/LOCATION_BLUEPRINT.md) - the input contract: fields, conventions, IDs, provenance, versioning, validation
* [Architecture](docs/ARCHITECTURE.md) - boundaries, interfaces, design decisions
* [Generation pipeline](docs/GENERATION_PIPELINE.md) - stages, coordinate system, IDs, determinism, manifest format
* [Adapters](docs/ADAPTERS.md) - integration points and a Unity integration guide
* [Development](docs/DEVELOPMENT.md) - setup, tests, schemas, adding generators
* [Roadmap](docs/ROADMAP.md) - next phases and known limitations

## License

MIT, see [LICENSE](LICENSE).
