# Development

## Setup

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/) (dependency
manager; `uv.lock` pins every package).

```bash
uv sync                 # create .venv with runtime + dev dependencies from uv.lock
uv run envgen --help
```

Without uv: `python -m venv .venv && .venv/bin/pip install -e . pytest pytest-cov jsonschema ruff mypy`
(versions are then not pinned).

## Everyday commands

| Task | Command |
| --- | --- |
| All tests | `uv run pytest` |
| With coverage | `uv run pytest --cov` |
| One layer | `uv run pytest tests/unit` / `tests/integration` / `tests/contract` |
| Format | `uv run ruff format .` |
| Lint | `uv run ruff check .` (`--fix` to apply safe fixes) |
| Types (strict) | `uv run mypy` |
| Regenerate JSON Schemas | `uv run envgen schema export` |
| Check schemas are current | `uv run envgen schema check` |
| Regenerate golden output | `uv run python scripts/regenerate_expected_output.py` |
| Build sdist + wheel | `uv build` |

CI (`.github/workflows/ci.yml`) runs formatting, lint, `mypy --strict`, the
schema drift check, the test suite on Python 3.11, 3.12 and 3.13, a CLI smoke
test, and builds the wheel and runs it from a clean environment.

## Tests

| Directory | What it covers |
| --- | --- |
| `tests/unit` | core primitives (pinned PRNG values), frames and road curves (pinned Catmull-Rom values), models, recipe/registry checks, asset palette and resolver, the blueprint-to-site adapter, each generator, planner and seed precedence, layout rules, overrides (entity operations, conflicts, placement), each pipeline stage in isolation, exporter (location frame) and preview, adapters and Unity math, CLI (including `blueprint validate/format/migrate`), and the architecture rules |
| `tests/integration` | end-to-end runs of all examples, overrides, dry run, replay from plan, failure reporting, replaceable components, determinism (including separate processes with different `PYTHONHASHSEED`), golden comparison with `examples/expected-output` |
| `tests/contract` | LocationBlueprint v1.0 (`test_location_blueprint.py`: loading the dacha fixture, byte-identical round trip, deterministic and order-independent serialization, schema/semantic/reference/external diagnostics, duplicate IDs, broken road graphs, invalid polygons, missing and mismatching files, provenance, version handling and migrations); recipe/blueprint/overrides independence; committed schemas match the models, are valid 2020-12, every example validates with `jsonschema`, invalid fixtures in `tests/fixtures/invalid` are rejected by schema and models |

Helpers: `tests/blueprints.py` builds LocationBlueprint v1.0 documents
(`location_data`, `make_location`, `building`, `segment`, `fence`, `pole`,
`wire`, ...); `tests/conftest.py` builds internal site descriptions
(`make_site`, `road`, `rect_building`) and generation contexts
(`make_context`) for generator tests, and names the example files.

## Changing behaviour

### Contracts

1. Edit the model in `src/environment_generator/models/` (the blueprint lives
   in `models/blueprint/`).
2. `uv run envgen schema export` and review the schema diff.
3. Update examples, fixtures and docs (`docs/LOCATION_BLUEPRINT.md` for the
   blueprint). Within a major version only add optional fields with defaults
   (and bump the minor version); renaming, removing or changing the meaning of
   a field needs a new major `schemaVersion` and a registered `Migration`
   (`blueprint/versioning.py`) plus a changelog note.
4. `uv run envgen blueprint format --check` the example location packages
   (they are kept in canonical form).

### Generation output

Any change that alters generated output (algorithm, defaults, archetypes):

1. bump the `version` of the affected generator class and the package
   `__version__` (`src/environment_generator/__init__.py`);
2. `uv run python scripts/regenerate_expected_output.py`;
3. look at the diff and at the regenerated `preview.svg` files;
4. commit code and expected output together.

`tests/unit/test_core_primitives.py` pins PRNG reference values; changing
them changes every manifest and is a deliberate, versioned decision.

## Adding a generator implementation

```python
from environment_generator.generators import default_generators, GeneratorSet
from environment_generator.generators.base import (
    GenerationContext,
    GeneratorOutput,
    VegetationGenerator,
    WorkEstimate,
    make_entity,
)


class MyVegetation(VegetationGenerator):
    implementation = "my_vegetation"
    version = "0.1.0"

    def estimate(self, site, recipe) -> WorkEstimate:
        return WorkEstimate(source_features=(), estimated_entities=0, asset_needs=())

    def generate(self, context: GenerationContext) -> GeneratorOutput:
        rng = context.rng("my-label")  # deterministic stream
        ...  # context.assets.resolve(...), make_entity(...)
        return GeneratorOutput(entities=[...])


defaults = {g.slot.value: g for g in default_generators()}
generators = GeneratorSet(**{**defaults, "vegetation": MyVegetation()})
Pipeline(generators=generators).run(...)
```

Rules for implementations:

* Work in the generator frame (Z up, counter-clockwise yaw); the site
  description is already converted and the exporter converts back.
* Use only `context.rng(...)` / `context.unit(...)` for randomness and derive
  labels from feature IDs and local indices; never use `random`, time or
  iteration order of sets.
* Pass blueprint values through as `attributes` (they win over generator
  `parameters` with the same key) and honour `context.controls`
  (`detail_density` scales procedural detail).
* Build entity IDs from feature IDs (see the ID table in
  [GENERATION_PIPELINE.md](GENERATION_PIPELINE.md#entity-ids)) and emit only
  categories in the slot's `produces`.
* Register footprints with `context.occupy(entity)` for anything later
  generators must avoid; query `context.occupancy` to avoid earlier output.
* Report soft problems as `ValidationIssue`s in `GeneratorOutput.issues`;
  raise `EnvironmentGeneratorError` subclasses for hard failures.
* Add unit tests next to `tests/unit/test_generators.py`.

## Adding a layout rule

Subclass `validation.layout.LayoutRule`, implement
`check(context) -> Iterable[ValidationIssue]` (the context has the scene,
recomputed footprints and a spatial index), and pass
`RuleBasedLayoutValidator([*default_rules(), MyRule()])` to `Pipeline`.

## Coding standards

* Python 3.11+, full type hints, `mypy --strict` clean, ruff-formatted
  (line length 100).
* Respect the package dependency rules in
  [ARCHITECTURE.md](ARCHITECTURE.md#package-structure-and-dependency-rules);
  `tests/unit/test_architecture.py` enforces them.
* No new runtime dependencies without a strong reason; the core must run with
  the standard library and Pydantic.
* Models are immutable; produce new instances with `model_copy(update=...)`.
* Errors carry stable codes; user-facing messages say what is wrong and where.
