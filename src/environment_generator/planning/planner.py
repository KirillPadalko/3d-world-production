"""Generation planning: which generators run, in which order, with which seeds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from environment_generator import __version__
from environment_generator.core.errors import PlanningError
from environment_generator.core.rng import derive_seed
from environment_generator.generators.base import GeneratorSet
from environment_generator.models.assets import AssetNeed, AssetPalette
from environment_generator.models.blueprint import LocationBlueprint
from environment_generator.models.pipeline import GenerationPlan, GenerationTask, ResolvedInputs
from environment_generator.models.recipe import GeneratorName, LocationRecipe


def topological_order(
    dependencies: Mapping[GeneratorName, Sequence[GeneratorName]],
) -> list[GeneratorName]:
    """Kahn's algorithm; ties are broken by canonical slot order for determinism."""
    canonical = list(GeneratorName)
    remaining = {name: list(deps) for name, deps in dependencies.items()}
    order: list[GeneratorName] = []
    while remaining:
        ready = [
            name
            for name in canonical
            if name in remaining and all(dep in order for dep in remaining[name])
        ]
        if not ready:
            cycle = ", ".join(sorted(remaining))
            raise PlanningError(f"Generator dependencies form a cycle between: {cycle}")
        order.append(ready[0])
        del remaining[ready[0]]
    return order


def task_seed(master_seed: int, name: GeneratorName) -> int:
    """Per-generator seed; independent of which other generators are enabled."""
    return derive_seed(master_seed, "generator", name.value)


class GenerationPlanner:
    def __init__(self, generators: GeneratorSet) -> None:
        self._generators = generators

    def enabled(self, recipe: LocationRecipe) -> list[GeneratorName]:
        return [g.slot for g in self._generators if recipe.generator_enabled(g.slot)]

    def asset_needs(self, blueprint: LocationBlueprint, recipe: LocationRecipe) -> list[AssetNeed]:
        """Archetype kinds the enabled generators will request."""
        needs: list[AssetNeed] = []
        for name in self.enabled(recipe):
            needs.extend(self._generators.get(name).estimate(blueprint, recipe).asset_needs)
        return needs

    def plan(self, resolved: ResolvedInputs, palette: AssetPalette) -> GenerationPlan:
        blueprint, recipe = resolved.blueprint, resolved.recipe
        enabled = self.enabled(recipe)
        enabled_set = set(enabled)
        dependencies = {
            name: [d for d in self._generators.get(name).dependencies if d in enabled_set]
            for name in enabled
        }
        tasks: list[GenerationTask] = []
        for name in topological_order(dependencies):
            generator = self._generators.get(name)
            estimate = generator.estimate(blueprint, recipe)
            tasks.append(
                GenerationTask(
                    generator=name,
                    implementation=generator.identifier,
                    seed=task_seed(resolved.seed, name),
                    depends_on=dependencies[name],
                    source_features=sorted(set(estimate.source_features)),
                    estimated_entities=estimate.estimated_entities,
                )
            )
        return GenerationPlan(
            generator_version=__version__,
            input_fingerprint=resolved.fingerprints.combined,
            seed=resolved.seed,
            blueprint=blueprint,
            recipe=recipe,
            palette=palette,
            overrides_id=resolved.overrides_id,
            strict_overrides=resolved.strict_overrides,
            entity_operations=resolved.entity_operations,
            tasks=tasks,
            disabled_generators=[n for n in GeneratorName if n not in enabled_set],
            estimated_entities=sum(t.estimated_entities for t in tasks),
        )
