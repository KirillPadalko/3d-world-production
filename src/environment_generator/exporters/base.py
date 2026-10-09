"""Scene exporter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from environment_generator.models.pipeline import GenerationPlan
from environment_generator.models.scene import Scene, SceneManifest


@dataclass(frozen=True)
class ExportResult:
    manifest: SceneManifest
    path: Path | None


class SceneExporter(ABC):
    """Interface: turn a generated scene into a portable artefact."""

    @abstractmethod
    def export(self, scene: Scene, plan: GenerationPlan, destination: Path | None) -> ExportResult:
        """Build the manifest and, when ``destination`` is a directory, write it there."""
