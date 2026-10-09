"""Adapter metadata shared by every integration point."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AdapterStatus(StrEnum):
    """``local`` adapters work today; ``stub`` adapters only define an interface."""

    LOCAL = "local"
    STUB = "stub"


@dataclass(frozen=True)
class AdapterInfo:
    name: str
    status: AdapterStatus
    interface: str
    workflow_step: str
    description: str
