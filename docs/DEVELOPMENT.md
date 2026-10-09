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
| `tests/unit` | core primitives (pinned PRNG values), models, semantic checks, asset palette and resolver, each generator, planner, layout rules, override application, each pipeline stage in isolation, exporter/preview, adapters and Unity math, CLI, and the architecture rules |
| `tests/integration` | end-to-end runs of all examples, overrides, dry run, replay from plan, failure reporting, replaceable components, determinism (including separate processes with different `PYTHONHASHSEED`), golden comparison with `examples/expected-output` |
| `tests/contract` | committed schemas match the models, schemas are valid 2020-12, every example and expected manifest validates with `jsonschema`, invalid fixtures in `tests/fixtures/invalid` are rejected by schema and models |

Helpers in `tests/conftest.py` build small blueprints (`make_blueprint`,
`road`, `rect_building`) and generation contexts (`make_context`) for
generator tests.

## Changing behaviour

### Contracts

1. Edit the model in `src/environment_generator/models/`.
2. `uv run envgen schema export` and review the schema diff.
3. Update examples, fixtures and docs. Breaking changes to a public contract
   need a new `schema_version` and a migration note in the changelog of the
   release.

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

    def estimate(self, blueprint, recipe) -> WorkEstimate:
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

* Use only `context.rng(...)` / `context.unit(...)` for randomness and derive
  labels from feature IDs and local indices; never use `random`, time or
  iteration order of sets.
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
