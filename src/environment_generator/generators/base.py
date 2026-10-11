"""Generator interfaces and the context they run in.

Each generator *slot* has an abstract interface (``TerrainGenerator``,
``RoadGenerator`` ...) that fixes its name, its ordering dependencies and the
asset categories it may emit. Implementations are engine-agnostic: they read
the effective site and recipe and return :class:`SceneEntity` objects.
The pipeline checks every output against the slot contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, fields
from typing import ClassVar

from pydantic.alias_generators import to_camel

from environment_generator.assets.resolver import AssetResolver, AssetSelection
from environment_generator.core.geometry import normalize_angle_deg
from environment_generator.core.issues import ValidationIssue
from environment_generator.core.rng import DeterministicRng, derive_seed, hash_unit
from environment_generator.core.spatial import SpatialIndex
from environment_generator.core.terrain import HeightSampler
from environment_generator.models.assets import AssetCategory, AssetNeed, Dimensions
from environment_generator.models.recipe import GeneratorName, LocationRecipe
from environment_generator.models.scene import (
    AtmosphereSettings,
    EntityGeometry,
    GenerationControls,
    ParameterValue,
    Provenance,
    SceneEntity,
    TerrainData,
    Transform,
    entity_footprints,
)
from environment_generator.models.site import SiteDescription


@dataclass(frozen=True, slots=True)
class WorkEstimate:
    """What a generator expects to do for given inputs (used for planning)."""

    source_features: tuple[str, ...] = ()
    estimated_entities: int = 0
    asset_needs: tuple[AssetNeed, ...] = ()


@dataclass(slots=True)
class GeneratorOutput:
    entities: list[SceneEntity] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    terrain: TerrainData | None = None
    atmosphere: AtmosphereSettings | None = None


@dataclass(slots=True)
class GenerationContext:
    """Everything a generator may read, plus the shared occupancy index.

    ``entities`` is a read-only view of what earlier generators produced.
    Generators register footprints in ``occupancy`` (via :meth:`occupy`) for
    anything later placements should avoid.
    """

    site: SiteDescription
    recipe: LocationRecipe
    controls: GenerationControls
    seed: int
    assets: AssetResolver
    terrain: HeightSampler
    occupancy: SpatialIndex
    entities: Mapping[str, SceneEntity]

    def rng(self, *labels: str | int) -> DeterministicRng:
        """A random stream that depends only on the task seed and ``labels``."""
        return DeterministicRng(derive_seed(self.seed, *labels))

    def unit(self, *labels: str | int) -> float:
        """A single uniform value in ``[0, 1)`` for ``labels``."""
        return hash_unit(self.seed, *labels)

    def entity_seed(self, *labels: str | int) -> int:
        return derive_seed(self.seed, *labels)

    def occupy(self, entity: SceneEntity) -> None:
        for footprint in entity_footprints(entity):
            self.occupancy.insert(footprint)

    def entities_of(self, category: AssetCategory) -> list[SceneEntity]:
        return [e for e in self.entities.values() if e.category is category]


class SceneGenerator(ABC):
    """Base of all generator slot interfaces."""

    slot: ClassVar[GeneratorName]
    dependencies: ClassVar[tuple[GeneratorName, ...]] = ()
    produces: ClassVar[frozenset[AssetCategory]] = frozenset()
    implementation: ClassVar[str]
    version: ClassVar[str]

    @property
    def identifier(self) -> str:
        return f"{self.implementation}@{self.version}"

    @abstractmethod
    def estimate(self, site: SiteDescription, recipe: LocationRecipe) -> WorkEstimate:
        """Describe the work for planning; must be cheap and side-effect free."""

    @abstractmethod
    def generate(self, context: GenerationContext) -> GeneratorOutput:
        """Produce entities (and terrain/atmosphere for those slots)."""

    def provenance(self, rule: str, source_feature: str | None = None) -> Provenance:
        return Provenance(
            generator=self.slot,
            implementation=self.identifier,
            rule=rule,
            source_feature=source_feature,
        )


class TerrainGenerator(SceneGenerator):
    """Produces the heightfield (``GeneratorOutput.terrain``) and water bodies."""

    slot = GeneratorName.TERRAIN
    dependencies = ()
    produces = frozenset({AssetCategory.TERRAIN, AssetCategory.WATER})


class RoadGenerator(SceneGenerator):
    slot = GeneratorName.ROADS
    dependencies = (GeneratorName.TERRAIN,)
    produces = frozenset({AssetCategory.ROAD})


class BuildingGenerator(SceneGenerator):
    slot = GeneratorName.BUILDINGS
    dependencies = (GeneratorName.TERRAIN, GeneratorName.ROADS)
    produces = frozenset({AssetCategory.BUILDING})


class FenceGenerator(SceneGenerator):
    slot = GeneratorName.FENCES
    dependencies = (GeneratorName.TERRAIN, GeneratorName.ROADS)
    produces = frozenset({AssetCategory.FENCE})


class InfrastructureGenerator(SceneGenerator):
    slot = GeneratorName.INFRASTRUCTURE
    dependencies = (
        GeneratorName.TERRAIN,
        GeneratorName.ROADS,
        GeneratorName.BUILDINGS,
        GeneratorName.FENCES,
    )
    produces = frozenset({AssetCategory.INFRASTRUCTURE})


class VegetationGenerator(SceneGenerator):
    slot = GeneratorName.VEGETATION
    dependencies = (
        GeneratorName.TERRAIN,
        GeneratorName.ROADS,
        GeneratorName.BUILDINGS,
        GeneratorName.FENCES,
        GeneratorName.INFRASTRUCTURE,
    )
    produces = frozenset({AssetCategory.VEGETATION})


class PropGenerator(SceneGenerator):
    slot = GeneratorName.PROPS
    dependencies = (
        GeneratorName.TERRAIN,
        GeneratorName.ROADS,
        GeneratorName.BUILDINGS,
        GeneratorName.FENCES,
        GeneratorName.INFRASTRUCTURE,
        GeneratorName.VEGETATION,
    )
    produces = frozenset({AssetCategory.PROP})


class AtmosphereProcessor(SceneGenerator):
    """Derives lighting and weather; produces no entities."""

    slot = GeneratorName.ATMOSPHERE
    dependencies = ()
    produces = frozenset()

    @abstractmethod
    def process(self, context: GenerationContext) -> AtmosphereSettings:
        """Compute the scene's atmosphere settings."""

    def generate(self, context: GenerationContext) -> GeneratorOutput:
        return GeneratorOutput(atmosphere=self.process(context))


@dataclass(frozen=True)
class GeneratorSet:
    """One implementation per slot. Replace any field to swap an implementation."""

    terrain: TerrainGenerator
    roads: RoadGenerator
    buildings: BuildingGenerator
    fences: FenceGenerator
    infrastructure: InfrastructureGenerator
    vegetation: VegetationGenerator
    props: PropGenerator
    atmosphere: AtmosphereProcessor

    def __post_init__(self) -> None:
        for f in fields(self):
            generator = getattr(self, f.name)
            if generator.slot.value != f.name:
                raise TypeError(f"{type(generator).__name__} cannot fill the '{f.name}' slot")

    def get(self, name: GeneratorName) -> SceneGenerator:
        generator: SceneGenerator = getattr(self, name.value)
        return generator

    def __iter__(self) -> Iterator[SceneGenerator]:
        for name in GeneratorName:
            yield self.get(name)


# --------------------------------------------------------------------------- helpers


def sorted_parameters(values: Mapping[str, ParameterValue | None]) -> dict[str, ParameterValue]:
    """Drop ``None`` values, use camelCase keys and sort them for stable output."""
    camel = {to_camel(k): v for k, v in values.items() if v is not None}
    return dict(sorted(camel.items()))


def kinds_with_hint(hint: str | None, *kinds: str) -> tuple[str, ...]:
    """Asset kinds to request: the semantic archetype hint first, then generic kinds."""
    if hint and hint not in kinds:
        return (hint, *kinds)
    return kinds


def make_entity(
    generator: SceneGenerator,
    *,
    entity_id: str,
    category: AssetCategory,
    kind: str,
    selection: AssetSelection,
    position: tuple[float, float, float],
    yaw_deg: float = 0.0,
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
    rule: str,
    source_feature: str | None = None,
    parameters: Mapping[str, ParameterValue | None] | None = None,
    attributes: Mapping[str, ParameterValue] | None = None,
    tags: Sequence[str] = (),
    geometry: EntityGeometry | None = None,
    dimensions: Dimensions | None = None,
) -> SceneEntity:
    """Assemble a :class:`SceneEntity` with consistent dimensions and provenance.

    ``attributes`` are blueprint values passed through unchanged; they win over
    generator ``parameters`` with the same (camelCase) key, so a coarse
    generator value never hides a more specific blueprint value.
    """
    archetype = selection.archetype
    if dimensions is None:
        nominal = archetype.dimensions
        dimensions = Dimensions(
            width_m=nominal.width_m * scale[0],
            depth_m=nominal.depth_m * scale[1],
            height_m=nominal.height_m * scale[2],
        )
    params: dict[str, ParameterValue | None] = {
        to_camel(key): value for key, value in (parameters or {}).items()
    }
    params.update(attributes or {})
    if archetype.cover is not None:
        params.setdefault("cover", archetype.cover.value)
    return SceneEntity(
        id=entity_id,
        category=category,
        kind=kind,
        archetype_id=archetype.id,
        asset_ref=archetype.asset_ref,
        variant=selection.variant,
        placeholder=selection.placeholder,
        transform=Transform(
            position=position, rotation_deg=(0.0, 0.0, normalize_angle_deg(yaw_deg)), scale=scale
        ),
        dimensions=dimensions,
        geometry=geometry,
        parameters=sorted_parameters(params),
        tags=sorted(set(tags)),
        provenance=generator.provenance(rule, source_feature),
    )


def feature_ref(collection: str, feature_id: str) -> str:
    return f"{collection}/{feature_id}"


def numeric_parameter(entity: SceneEntity, key: str, default: float = 0.0) -> float:
    """A numeric entity parameter as ``float`` (``default`` if absent or not numeric)."""
    value = entity.parameters.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)
