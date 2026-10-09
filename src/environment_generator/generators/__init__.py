"""Generator interfaces and the local MVP implementations."""

from environment_generator.generators.atmosphere import PresetAtmosphereProcessor
from environment_generator.generators.base import (
    AtmosphereProcessor,
    BuildingGenerator,
    FenceGenerator,
    GenerationContext,
    GeneratorOutput,
    GeneratorSet,
    InfrastructureGenerator,
    PropGenerator,
    RoadGenerator,
    SceneGenerator,
    TerrainGenerator,
    VegetationGenerator,
    WorkEstimate,
)
from environment_generator.generators.buildings import FootprintBuildingGenerator
from environment_generator.generators.fences import PanelFenceGenerator
from environment_generator.generators.infrastructure import StandardInfrastructureGenerator
from environment_generator.generators.props import ClutterPropGenerator
from environment_generator.generators.roads import PolylineRoadGenerator
from environment_generator.generators.terrain import HeightfieldTerrainGenerator
from environment_generator.generators.vegetation import ScatterVegetationGenerator


def default_generators() -> GeneratorSet:
    """The built-in implementation for every slot."""
    return GeneratorSet(
        terrain=HeightfieldTerrainGenerator(),
        roads=PolylineRoadGenerator(),
        buildings=FootprintBuildingGenerator(),
        fences=PanelFenceGenerator(),
        infrastructure=StandardInfrastructureGenerator(),
        vegetation=ScatterVegetationGenerator(),
        props=ClutterPropGenerator(),
        atmosphere=PresetAtmosphereProcessor(),
    )


__all__ = [
    "AtmosphereProcessor",
    "BuildingGenerator",
    "ClutterPropGenerator",
    "FenceGenerator",
    "FootprintBuildingGenerator",
    "GenerationContext",
    "GeneratorOutput",
    "GeneratorSet",
    "HeightfieldTerrainGenerator",
    "InfrastructureGenerator",
    "PanelFenceGenerator",
    "PolylineRoadGenerator",
    "PresetAtmosphereProcessor",
    "PropGenerator",
    "RoadGenerator",
    "ScatterVegetationGenerator",
    "SceneGenerator",
    "StandardInfrastructureGenerator",
    "TerrainGenerator",
    "VegetationGenerator",
    "WorkEstimate",
    "default_generators",
]
