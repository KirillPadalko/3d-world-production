"""Lighting and weather from the observed conditions and the recipe."""

from __future__ import annotations

import math
from dataclasses import dataclass

from environment_generator.generators.base import (
    AtmosphereProcessor,
    GenerationContext,
    WorkEstimate,
)
from environment_generator.models.recipe import LocationRecipe
from environment_generator.models.scene import RGB, AtmosphereSettings, Foliage, Precipitation
from environment_generator.models.site import (
    Season,
    SiteDescription,
    TimeOfDay,
    Weather,
)


@dataclass(frozen=True)
class _Light:
    elevation_deg: float
    azimuth_deg: float  # compass bearing in the northern hemisphere
    color: RGB
    intensity: float
    ambient_color: RGB
    ambient_intensity: float


@dataclass(frozen=True)
class _WeatherLook:
    cloud_cover: float
    fog_density: float
    precipitation: Precipitation
    precipitation_intensity: float
    wind_speed_mps: float
    light_factor: float


LIGHTING: dict[TimeOfDay, _Light] = {
    TimeOfDay.DAWN: _Light(6.0, 80.0, (1.0, 0.72, 0.52), 0.6, (0.45, 0.5, 0.65), 0.35),
    TimeOfDay.MORNING: _Light(28.0, 115.0, (1.0, 0.92, 0.82), 0.95, (0.55, 0.62, 0.75), 0.5),
    TimeOfDay.NOON: _Light(58.0, 180.0, (1.0, 0.98, 0.95), 1.15, (0.6, 0.68, 0.8), 0.6),
    TimeOfDay.AFTERNOON: _Light(38.0, 230.0, (1.0, 0.94, 0.85), 1.0, (0.58, 0.64, 0.76), 0.55),
    TimeOfDay.DUSK: _Light(5.0, 285.0, (1.0, 0.6, 0.42), 0.55, (0.42, 0.42, 0.6), 0.3),
    # At night the key light is moonlight.
    TimeOfDay.NIGHT: _Light(35.0, 200.0, (0.62, 0.7, 0.95), 0.12, (0.12, 0.15, 0.28), 0.12),
}

WEATHER: dict[Weather, _WeatherLook] = {
    Weather.CLEAR: _WeatherLook(0.05, 0.002, "none", 0.0, 2.0, 1.0),
    Weather.PARTLY_CLOUDY: _WeatherLook(0.4, 0.004, "none", 0.0, 4.0, 0.9),
    Weather.OVERCAST: _WeatherLook(0.9, 0.008, "none", 0.0, 5.0, 0.6),
    Weather.FOG: _WeatherLook(0.7, 0.045, "none", 0.0, 1.0, 0.5),
    Weather.RAIN: _WeatherLook(0.95, 0.015, "rain", 0.6, 7.0, 0.45),
    Weather.STORM: _WeatherLook(1.0, 0.02, "rain", 1.0, 14.0, 0.35),
    Weather.SNOW: _WeatherLook(0.9, 0.02, "snow", 0.6, 4.0, 0.55),
    Weather.LIGHT_RAIN: _WeatherLook(0.85, 0.01, "rain", 0.3, 5.0, 0.55),
}

FOLIAGE: dict[Season, Foliage] = {
    Season.SPRING: "fresh",
    Season.SUMMER: "full",
    Season.AUTUMN: "autumn",
    Season.WINTER: "bare",
}

_FOG_GREY: RGB = (0.7, 0.72, 0.75)
FOG_MIN = 0.002
FOG_MAX = 0.06


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


class PresetAtmosphereProcessor(AtmosphereProcessor):
    """Table-driven lighting presets.

    Precedence for each of time of day / weather / season: recipe value, then
    the site observation, then afternoon / clear / summer. The key light
    azimuth accounts for the hemisphere and the site's heading when a geo
    reference is present.
    """

    implementation = "preset_atmosphere"
    version = "1.1.0"

    def estimate(self, site: SiteDescription, recipe: LocationRecipe) -> WorkEstimate:
        return WorkEstimate(("atmosphere",), 0, ())

    def process(self, context: GenerationContext) -> AtmosphereSettings:
        site = context.site
        recipe = context.recipe
        observed = site.atmosphere
        time_of_day = recipe.atmosphere.time_of_day or observed.time_of_day or TimeOfDay.AFTERNOON
        weather = recipe.atmosphere.weather or observed.weather or Weather.CLEAR
        recipe_season = recipe.atmosphere.season
        if recipe_season is Season.UNKNOWN:
            recipe_season = None
        season = recipe_season or observed.season or Season.SUMMER
        light = LIGHTING[time_of_day]
        look = WEATHER[weather]

        azimuth = light.azimuth_deg
        geo = site.geo_reference
        if geo is not None:
            if geo.latitude < 0 and time_of_day is not TimeOfDay.NIGHT:
                azimuth = (180.0 - azimuth) % 360.0
            azimuth = (azimuth - geo.heading_deg) % 360.0
        elevation = light.elevation_deg
        az, el = math.radians(azimuth), math.radians(elevation)
        # Light travels from the sky position towards the scene.
        direction = (
            -math.sin(az) * math.cos(el),
            -math.cos(az) * math.cos(el),
            -math.sin(el),
        )
        fog_density = look.fog_density
        if observed.fog_density is not None and observed.fog_density > 0:
            # Normalised 0..1 observation -> exponential fog coefficient 0.002..0.06.
            fog_density = max(fog_density, FOG_MIN + (FOG_MAX - FOG_MIN) * observed.fog_density)
        fog_density *= recipe.atmosphere.fog_density_scale
        wind_speed = (
            recipe.atmosphere.wind_speed_mps
            if recipe.atmosphere.wind_speed_mps is not None
            else look.wind_speed_mps
        )
        precipitation: Precipitation = look.precipitation
        if precipitation == "rain" and season is Season.WINTER:
            precipitation = "snow"
        return AtmosphereSettings(
            time_of_day=time_of_day,
            weather=weather,
            season=season,
            key_light_azimuth_deg=azimuth,
            key_light_elevation_deg=elevation,
            key_light_direction=direction,
            key_light_color=_mix(light.color, _FOG_GREY, look.cloud_cover * 0.5),
            key_light_intensity=light.intensity * look.light_factor,
            ambient_color=light.ambient_color,
            ambient_intensity=light.ambient_intensity,
            fog_color=_mix(light.ambient_color, _FOG_GREY, 0.6),
            fog_density=fog_density,
            cloud_cover=look.cloud_cover,
            precipitation=precipitation,
            precipitation_intensity=look.precipitation_intensity,
            wind_speed_mps=wind_speed,
            wind_direction_deg=context.unit("wind") * 360.0,
            foliage=FOLIAGE[season],
            style_theme=recipe.style.theme,
            weathering=recipe.style.weathering,
            ground_wetness=observed.ground_wetness if observed.ground_wetness is not None else 0.0,
            saturation=observed.saturation if observed.saturation is not None else 1.0,
            contrast=observed.contrast if observed.contrast is not None else 1.0,
            abandonment=context.controls.abandonment,
            vegetation_condition=(
                observed.vegetation_condition if observed.vegetation_condition is not None else 1.0
            ),
            palette=list(observed.palette),
        )
