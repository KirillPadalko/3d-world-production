"""Portable atmosphere parameters (no shader, volume or light references)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints

from environment_generator.models.blueprint.common import (
    HEX_COLOR_PATTERN,
    BlueprintModel,
    Normalized,
    Vocabulary,
)


class Weather(StrEnum):
    CLEAR = "clear"
    PARTLY_CLOUDY = "partly_cloudy"
    OVERCAST = "overcast"
    FOG = "fog"
    LIGHT_RAIN = "light_rain"
    RAIN = "rain"
    STORM = "storm"
    SNOW = "snow"


class TimeOfDay(StrEnum):
    DAWN = "dawn"
    MORNING = "morning"
    NOON = "noon"
    AFTERNOON = "afternoon"
    DUSK = "dusk"
    NIGHT = "night"


class PaletteColor(BlueprintModel):
    role: Vocabulary = Field(description="e.g. foliage, ground, sky, accent.")
    color: Annotated[str, StringConstraints(pattern=HEX_COLOR_PATTERN)]


#: Neutral value of ``saturation`` and ``contrast``.
NEUTRAL = 1.0


class Atmosphere(BlueprintModel):
    """Observed or intended look; every value has a neutral default."""

    weather: Weather = Weather.CLEAR
    time_of_day: TimeOfDay = TimeOfDay.AFTERNOON
    ground_wetness: Normalized = Field(default=0.0, description="0 = dry, 1 = waterlogged.")
    abandonment: Normalized = Field(
        default=0.0, description="Overall impression; buildings carry their own value."
    )
    vegetation_condition: Normalized = Field(default=1.0, description="0 = dead/dry, 1 = lush.")
    fog_density: Normalized = Field(default=0.0, description="0 = none, 1 = very dense.")
    saturation: Annotated[float, Field(ge=0.0, le=2.0)] = Field(
        default=NEUTRAL, description="Colour saturation multiplier; 1 = neutral."
    )
    contrast: Annotated[float, Field(ge=0.0, le=2.0)] = Field(
        default=NEUTRAL, description="Contrast multiplier; 1 = neutral."
    )
    palette: list[PaletteColor] = Field(default_factory=list, max_length=32)
