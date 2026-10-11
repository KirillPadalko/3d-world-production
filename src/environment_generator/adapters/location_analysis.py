"""Location analysis adapter (drone footage -> LocationBlueprint).

STATUS: STUB. No analysis backend exists in this phase. The interface pins
down what a future implementation (photogrammetry, segmentation models, a
remote analysis service or an MCP tool) must return: a
:class:`~environment_generator.models.LocationBlueprint` that satisfies
``schemas/location-blueprint.schema.json``. Hand-written blueprints are the
current input.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated

from pydantic import Field

from environment_generator.core.errors import AdapterUnavailableError
from environment_generator.models.base import ContractModel, Description
from environment_generator.models.blueprint import LocationBlueprint


class FootageReference(ContractModel):
    """A pointer to source material; the adapter decides how to fetch it."""

    uri: Annotated[str, Field(min_length=1, max_length=2000)]
    captured_at: datetime | None = None
    notes: Description | None = None


class LocationAnalyzer(ABC):
    """Interface: turn source footage into a blueprint."""

    @abstractmethod
    def analyze(self, footage: Sequence[FootageReference]) -> LocationBlueprint:
        """Analyse footage and return a contract-valid blueprint."""


class UnconfiguredLocationAnalyzer(LocationAnalyzer):
    """Stub that always fails loudly instead of pretending to analyse."""

    def analyze(self, footage: Sequence[FootageReference]) -> LocationBlueprint:
        raise AdapterUnavailableError(
            "Location analysis is not implemented in this phase. Author a LocationBlueprint by "
            "hand (see examples/locations and docs/LOCATION_BLUEPRINT.md) or implement "
            "LocationAnalyzer; see docs/ADAPTERS.md."
        )
