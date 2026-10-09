"""Blender processing adapter (scene manifest -> processed assets/scenes).

STATUS: STUB. The core never imports ``bpy``. A real implementation would
run Blender as a separate process (``blender --background --python ...``)
that reads ``scene-manifest.json`` - it must not be imported into the core.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from environment_generator.core.errors import AdapterUnavailableError
from environment_generator.models.scene import SceneManifest


@dataclass(frozen=True)
class BlenderProcessingResult:
    output_files: tuple[Path, ...]
    log: str


class BlenderProcessor(ABC):
    """Interface: post-process a generated scene with Blender."""

    @abstractmethod
    def process(self, manifest: SceneManifest, output_dir: Path) -> BlenderProcessingResult:
        """Build or refine geometry for ``manifest`` and write results to ``output_dir``."""


class UnconfiguredBlenderProcessor(BlenderProcessor):
    """Stub that always fails loudly."""

    def process(self, manifest: SceneManifest, output_dir: Path) -> BlenderProcessingResult:
        raise AdapterUnavailableError(
            "Blender processing is not implemented in this phase. The scene manifest is the "
            "integration boundary; see docs/ADAPTERS.md for the intended out-of-process design."
        )
