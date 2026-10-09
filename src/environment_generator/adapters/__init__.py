"""Integration points with external systems, isolated from the core.

Nothing in here is imported by the core packages. Stubs raise
:class:`~environment_generator.core.errors.AdapterUnavailableError`; they never
simulate success.
"""

from environment_generator.adapters.base import AdapterInfo, AdapterStatus
from environment_generator.adapters.blender import BlenderProcessor, UnconfiguredBlenderProcessor
from environment_generator.adapters.location_analysis import (
    FootageReference,
    LocationAnalyzer,
    UnconfiguredLocationAnalyzer,
)
from environment_generator.adapters.unity import (
    UnconfiguredUnityIntegrator,
    UnitySceneIntegrator,
    entity_to_unity_transform,
    to_unity_position,
    to_unity_rotation,
    to_unity_scale,
    to_unity_yaw,
)


def available_adapters() -> list[AdapterInfo]:
    """Every integration point and whether it works in this build."""
    return [
        AdapterInfo(
            name="location-analysis",
            status=AdapterStatus.STUB,
            interface="environment_generator.adapters.LocationAnalyzer",
            workflow_step="drone footage -> LocationBlueprint",
            description="No analysis backend; author blueprints by hand for now.",
        ),
        AdapterInfo(
            name="asset-registry-json",
            status=AdapterStatus.LOCAL,
            interface="environment_generator.assets.AssetResolver",
            workflow_step="asset selection",
            description="Built-in or file-based archetype registry (--registry).",
        ),
        AdapterInfo(
            name="scene-manifest-json",
            status=AdapterStatus.LOCAL,
            interface="environment_generator.exporters.SceneExporter",
            workflow_step="portable scene export",
            description="Writes scene-manifest.json; the boundary for engine integration.",
        ),
        AdapterInfo(
            name="blender",
            status=AdapterStatus.STUB,
            interface="environment_generator.adapters.BlenderProcessor",
            workflow_step="Blender processing",
            description="Interface only; intended to run Blender out of process.",
        ),
        AdapterInfo(
            name="unity",
            status=AdapterStatus.STUB,
            interface="environment_generator.adapters.UnitySceneIntegrator",
            workflow_step="Unity scene integration",
            description="Interface only; coordinate conversion helpers are implemented.",
        ),
    ]


__all__ = [
    "AdapterInfo",
    "AdapterStatus",
    "BlenderProcessor",
    "FootageReference",
    "LocationAnalyzer",
    "UnconfiguredBlenderProcessor",
    "UnconfiguredLocationAnalyzer",
    "UnconfiguredUnityIntegrator",
    "UnitySceneIntegrator",
    "available_adapters",
    "entity_to_unity_transform",
    "to_unity_position",
    "to_unity_rotation",
    "to_unity_scale",
    "to_unity_yaw",
]
