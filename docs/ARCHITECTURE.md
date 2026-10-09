# Architecture

## Goals and non-goals

The Environment Generator is an **isolated, engine-agnostic** framework that
turns structured descriptions of real locations into stylised, game-ready
environment descriptions. This phase delivers the architecture and a working
MVP that runs on its own:

* in scope: public contracts, validation, planning, deterministic procedural
  generation, asset abstraction, a portable scene manifest, reports, CLI, a
  preview, tests and CI;
* out of scope (interfaces only): footage analysis, Blender processing, Unity
  import, any network, account or MCP integration.

Nothing in the core imports Unity, `bpy`, MCP SDKs or AI SDKs, and no adapter
pretends to work: stubs raise `AdapterUnavailableError`.

## System context

```mermaid
flowchart LR
    footage[Drone footage] -.-> analysis["LocationAnalyzer<br/>(stub)"]
    analysis -.-> blueprint
    author[Hand-authored JSON] --> blueprint[LocationBlueprint]
    recipe[LocationRecipe] --> gen
    overrides[LocationOverrides] --> gen
    registry[Asset registry] --> gen
    blueprint --> gen["Environment Generator<br/>(this repository)"]
    gen --> manifest[scene-manifest.json]
    gen --> report[generation-report.json]
    gen --> preview[preview.svg]
    manifest -.-> blender["BlenderProcessor<br/>(stub)"]
    manifest -.-> unity["Unity importer<br/>(future, C#)"]
```

Dashed arrows are future integrations. The **scene manifest is the integration
boundary**: downstream tools only need `schemas/scene-manifest.schema.json` and
the coordinate conventions in [GENERATION_PIPELINE.md](GENERATION_PIPELINE.md).

## Package structure and dependency rules

```
core  <-  models  <-  validation, assets  <-  generators  <-  planning  <-  pipeline  <-  cli
                         exporters, reporting (core + models [+ validation])
                         adapters (core + models only; never imported by the core)
```

| Package | Responsibility | May import |
| --- | --- | --- |
| `core` | Errors, validation issues, 2D geometry, PRNG and seed derivation, canonical JSON/hashing, spatial index, heightfield/noise, JSON merge patch | stdlib, pydantic |
| `models` | Public contracts (blueprint, recipe, overrides, registry, manifest), stage models (plan, scene, report), JSON Schema export | `core` |
| `validation` | Document loading, contract errors, semantic checks, layout validator and rules | `core`, `models` |
| `assets` | Built-in registry, palette filtering, `AssetResolver` | `core`, `models` |
| `generators` | Generator slot interfaces, `GenerationContext`, built-in implementations | `core`, `models`, `assets` |
| `planning` | Dependency ordering, seed derivation, plan assembly | above |
| `exporters` | `SceneExporter`, JSON manifest | `core`, `models`, `validation` |
| `reporting` | Text summary, SVG preview (reads only the manifest) | `core`, `models` |
| `pipeline` | The eight stages, override application, `Pipeline` orchestrator | all of the above |
| `adapters` | External integration interfaces, stubs, Unity coordinate math | `core`, `models` |
| `cli` | `envgen` | everything |

These rules are enforced by `tests/unit/test_architecture.py`, which parses
every source file and fails on a forbidden internal import, on any engine,
network or AI SDK import (`bpy`, `UnityEngine`, `mcp`, `anthropic`,
`openai`, `requests`, ...), or on any third-party import other than `pydantic`.

## Contracts

| Contract | Model | Schema | Direction |
| --- | --- | --- | --- |
| LocationBlueprint | `models.blueprint.LocationBlueprint` | `schemas/location-blueprint.schema.json` | input |
| LocationRecipe | `models.recipe.LocationRecipe` | `schemas/location-recipe.schema.json` | input |
| LocationOverrides | `models.overrides.LocationOverrides` | `schemas/location-overrides.schema.json` | input |
| Asset registry | `models.assets.AssetRegistryDocument` | `schemas/asset-registry.schema.json` | input |
| Scene manifest | `models.scene.SceneManifest` | `schemas/scene-manifest.schema.json` | output |

The Pydantic models are the single source of truth. `envgen schema export`
writes the JSON Schemas (2020-12) and CI runs `envgen schema check` so the
committed files cannot drift. Contract tests validate every example against
the committed schemas with the independent `jsonschema` validator and check
that invalid fixtures are rejected by both the schema and the models.

Rules that JSON Schema cannot express (unique feature IDs, simple polygons,
features inside the extent, fence gaps within the fence, overlapping
buildings, recipe applicability) are **semantic checks** in
`validation/semantic.py`.

All models are immutable (`frozen=True`), reject unknown fields
(`extra="forbid"`) and reject NaN/infinity, so typos fail loudly and every
output is serialisable.

## Interfaces

| Interface | Module | Built-in implementation |
| --- | --- | --- |
| `TerrainGenerator` | `generators/base.py` | `HeightfieldTerrainGenerator` |
| `RoadGenerator` | `generators/base.py` | `PolylineRoadGenerator` |
| `BuildingGenerator` | `generators/base.py` | `FootprintBuildingGenerator` |
| `FenceGenerator` | `generators/base.py` | `PanelFenceGenerator` |
| `InfrastructureGenerator` | `generators/base.py` | `StandardInfrastructureGenerator` |
| `VegetationGenerator` | `generators/base.py` | `ScatterVegetationGenerator` |
| `PropGenerator` | `generators/base.py` | `ClutterPropGenerator` |
| `AtmosphereProcessor` | `generators/base.py` | `PresetAtmosphereProcessor` |
| `AssetResolver` | `assets/resolver.py` | `PaletteAssetResolver` |
| `SceneExporter` | `exporters/base.py` | `JsonManifestExporter` |
| `EnvironmentValidator` | `validation/layout.py` | `RuleBasedLayoutValidator` (+ `LayoutRule`s) |
| `LocationAnalyzer` | `adapters/location_analysis.py` | `UnconfiguredLocationAnalyzer` (stub) |
| `BlenderProcessor` | `adapters/blender.py` | `UnconfiguredBlenderProcessor` (stub) |
| `UnitySceneIntegrator` | `adapters/unity.py` | `UnconfiguredUnityIntegrator` (stub) |

Every generator slot interface derives from `SceneGenerator` and fixes:

* `slot` - its name in the plan and the recipe section that enables it;
* `dependencies` - ordering constraints (e.g. vegetation runs after buildings
  so it can avoid them);
* `produces` - the asset categories it may emit (checked by the pipeline);
* `estimate(blueprint, recipe)` - cheap, side-effect-free work estimate with
  source features and asset needs (used for planning and asset checks);
* `generate(context)` - the actual work, returning a `GeneratorOutput`.

`GeneratorSet` holds exactly one implementation per slot and rejects an
implementation placed in the wrong slot. Implementations identify themselves
as `implementation@version`; the identifier is stored in the plan and in every
entity's provenance, and generating from a saved plan fails if the configured
implementation differs.

### GenerationContext

Generators receive a `GenerationContext` with the effective blueprint and
recipe, their task seed, the `AssetResolver`, a `HeightSampler` (flat until the
terrain generator has run), the shared `SpatialIndex` of occupied footprints
and a read-only view of the entities produced so far. `context.rng(*labels)`
returns an independent random stream for any label path.

## Key design decisions

1. **Pydantic models as the source of truth, JSON Schema generated.** One
   definition, typed Python access, and language-neutral contracts for future
   producers (analysis tools) and consumers (Unity importer).
2. **The manifest is the integration boundary.** Generators never call an
   engine. Engines read a self-describing JSON file with explicit coordinate
   conventions, archetype references and provenance.
3. **Own PRNG and hash-derived seeds.** Python's `random` only guarantees the
   `random()` stream across versions; xoshiro256** + SplitMix64 is fully
   specified and portable to C#. Seeds are derived per generator, per feature
   and per candidate, so enabling, disabling or editing one thing does not
   reshuffle the rest.
4. **Stable, semantic entity IDs** derived from blueprint feature IDs and local
   indices (`vegetation.forest-east.00042`), never from global counters. This
   makes entity-level overrides possible and keeps engine-side references valid
   across regenerations.
5. **Independent layout validation.** The validator recomputes footprints from
   the finished scene instead of trusting the generators' occupancy index, so
   it also checks third-party generator implementations.
6. **Explicit placeholders.** When no archetype fits, the resolver either fails
   (recipe `fallback: error`) or emits a clearly marked `placeholder.*`
   archetype that the report and preview flag. Nothing is silently substituted.
7. **Stages with typed inputs and outputs.** Each stage is a class with a
   `run(input) -> StageOutcome[output]` method, so it can be tested, replaced
   or run alone. The plan is self-contained (effective blueprint, recipe,
   palette, seeds), so generation can be replayed from a saved plan.
8. **Small dependency footprint.** Runtime: `pydantic` only. Development:
   `pytest`, `pytest-cov`, `jsonschema`, `ruff`, `mypy`. `uv.lock` pins versions.

## Extension points

* **Replace a generator:** subclass the slot interface (or an existing
  implementation), set `implementation`/`version`, and pass a `GeneratorSet`
  to `Pipeline(generators=...)`.
* **Add layout rules:** subclass `LayoutRule` and pass
  `RuleBasedLayoutValidator([*default_rules(), MyRule()])` to
  `Pipeline(validator=...)`.
* **Another output format:** implement `SceneExporter` and pass it to
  `Pipeline(exporter=...)`.
* **Engine assets:** supply a registry with the same schema whose `asset_ref`
  values are engine asset keys (`--registry`).
* **External systems:** implement an adapter interface in `adapters/`; see
  [ADAPTERS.md](ADAPTERS.md).

## Error handling

All expected failures raise a subclass of `EnvironmentGeneratorError` carrying
a stable `code`, an `exit_code` and a list of `ValidationIssue`s
(`severity`, `code`, `message`, `location`, `entity_ids`).

| Exception | Code | Exit | Raised by |
| --- | --- | --- | --- |
| `InputLoadError` | `INPUT_LOAD_ERROR` | 3 | missing/unreadable file, invalid JSON |
| `ContractValidationError` | `CONTRACT_VALIDATION_ERROR` | 3 | model/schema violations (all documents reported together) |
| `SemanticValidationError` | `SEMANTIC_VALIDATION_ERROR` | 3 | semantic checks |
| `OverrideError` | `OVERRIDE_ERROR` | 3 | overrides that cannot be applied |
| `AssetResolutionError` | `ASSET_RESOLUTION_ERROR` | 4 | missing archetypes with `fallback: error` |
| `PlanningError` | `PLANNING_ERROR` | 4 | dependency cycles, plan/generator mismatch |
| `GenerationError` | `GENERATION_ERROR` | 4 | a generator crashed or broke its slot contract |
| `LayoutValidationError` | `LAYOUT_VALIDATION_ERROR` | 5 | layout errors with `fail_on_error` |
| `ExportError` | `EXPORT_ERROR` | 6 | manifest or report cannot be written |
| `AdapterUnavailableError` | `ADAPTER_UNAVAILABLE` | 7 | a stub adapter was called |

`Pipeline.run` never raises these: it records the failed stage, marks later
stages as skipped, writes `generation-report.json` (when an output directory
is given) and returns a `PipelineResult` with `error` set. Unexpected
exceptions (bugs) propagate.

## Logging

Modules log through `logging.getLogger(__name__)`; the pipeline logs stage
start/finish at INFO. The CLI configures logging on stderr (`-v` INFO, `-vv`
DEBUG, or `ENVGEN_LOG_LEVEL`); stdout carries only command output.
