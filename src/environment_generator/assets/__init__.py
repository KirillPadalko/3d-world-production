"""Asset registry abstractions: archetype palettes and resolution."""

from environment_generator.assets.registry import (
    build_palette,
    builtin_registry_data,
    load_builtin_registry,
)
from environment_generator.assets.resolver import (
    AssetRequest,
    AssetResolver,
    AssetSelection,
    PaletteAssetResolver,
    is_placeholder_id,
    placeholder_archetype,
)

__all__ = [
    "AssetRequest",
    "AssetResolver",
    "AssetSelection",
    "PaletteAssetResolver",
    "build_palette",
    "builtin_registry_data",
    "is_placeholder_id",
    "load_builtin_registry",
    "placeholder_archetype",
]
