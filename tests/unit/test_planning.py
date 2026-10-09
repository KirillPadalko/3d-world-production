from __future__ import annotations

import pytest

from environment_generator.assets.registry import build_palette
from environment_generator.core.errors import PlanningError
from environment_generator.generators import default_generators
from environment_generator.models.recipe import GeneratorName
from environment_generator.pipeline.stages import InputBundle, LoadInputsStage, ResolveInputsStage
from environment_generator.planning.planner import GenerationPlanner, task_seed, topological_order
from tests.conftest import RURAL_BLUEPRINT, RURAL_RECIPE, blueprint_data


def resolved_inputs(recipe: object = None):  # type: ignore[no-untyped-def]
    loaded = LoadInputsStage().run(InputBundle(blueprint=RURAL_BLUEPRINT, recipe=recipe))
    return ResolveInputsStage().run(loaded.output).output


def test_topological_order_is_canonical_and_detects_cycles() -> None:
    order = topological_order(
        {
            GeneratorName.PROPS: [GeneratorName.ROADS],
            GeneratorName.ROADS: [],
            GeneratorName.ATMOSPHERE: [],
            GeneratorName.TERRAIN: [],
        }
    )
    assert order == [
        GeneratorName.TERRAIN,
        GeneratorName.ROADS,
        GeneratorName.PROPS,
        GeneratorName.ATMOSPHERE,
    ]
    with pytest.raises(PlanningError, match="cycle"):
        topological_order(
            {GeneratorName.ROADS: [GeneratorName.PROPS], GeneratorName.PROPS: [GeneratorName.ROADS]}
        )


def test_plan_contains_ordered_tasks_with_stable_seeds() -> None:
    resolved = resolved_inputs(RURAL_RECIPE)
    planner = GenerationPlanner(default_generators())
    palette, _ = build_palette(resolved.registry, resolved.recipe, resolved.blueprint.biome)
    plan = planner.plan(resolved, palette)
    assert [t.generator.value for t in plan.tasks] == [
        "terrain",
        "roads",
        "buildings",
        "fences",
        "infrastructure",
        "vegetation",
        "props",
        "atmosphere",
    ]
    assert plan.seed == 1337
    assert plan.tasks[0].seed == task_seed(1337, GeneratorName.TERRAIN)
    assert len({t.seed for t in plan.tasks}) == len(plan.tasks)
    assert plan.estimated_entities == sum(t.estimated_entities for t in plan.tasks)
    vegetation = next(t for t in plan.tasks if t.generator is GeneratorName.VEGETATION)
    assert "vegetation/forest-east" in vegetation.source_features
    assert vegetation.implementation == "scatter_vegetation@1.0.0"


def test_disabled_generators_drop_out_without_shifting_seeds() -> None:
    data = blueprint_data()
    recipe = {
        "schema_version": "1.0",
        "id": "r",
        "name": "R",
        "seed": 9,
        "terrain": {"enabled": False},
        "props": {"enabled": False},
    }
    loaded = LoadInputsStage().run(InputBundle(blueprint=data, recipe=recipe)).output
    resolved = ResolveInputsStage().run(loaded).output
    palette, _ = build_palette(resolved.registry, resolved.recipe, resolved.blueprint.biome)
    plan = GenerationPlanner(default_generators()).plan(resolved, palette)
    names = [t.generator for t in plan.tasks]
    assert GeneratorName.TERRAIN not in names and GeneratorName.PROPS not in names
    assert plan.disabled_generators == [GeneratorName.TERRAIN, GeneratorName.PROPS]
    roads = next(t for t in plan.tasks if t.generator is GeneratorName.ROADS)
    assert roads.depends_on == []  # terrain dependency dropped
    assert roads.seed == task_seed(9, GeneratorName.ROADS)
