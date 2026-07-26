from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


MARINE_API_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"

MARINE_CURRENT_VARIABLES = [
    "sea_surface_temperature",
    "wave_height",
    "wave_direction",
    "ocean_current_velocity",
    "ocean_current_direction",
]

FORECAST_CURRENT_VARIABLES = [
    "wind_speed_10m",
    "temperature_2m",
]


class OpenMeteoError(RuntimeError):
    pass


@dataclass(frozen=True)
class Coordinates:
    latitude: float
    longitude: float


def get_realtime_ocean_conditions(latitude: float, longitude: float) -> dict[str, Any]:
    coords = Coordinates(latitude=latitude, longitude=longitude)
    marine = _fetch_marine_current(coords)
    weather = _fetch_weather_current(coords)

    marine_current = marine.get("current", {})
    weather_current = weather.get("current", {})
    marine_units = marine.get("current_units", {})
    weather_units = weather.get("current_units", {})

    return {
        "requested": {
            "latitude": coords.latitude,
            "longitude": coords.longitude,
        },
        "resolved": {
            "marine": {
                "latitude": marine.get("latitude"),
                "longitude": marine.get("longitude"),
                "timezone": marine.get("timezone"),
                "timezone_abbreviation": marine.get("timezone_abbreviation"),
            },
            "weather": {
                "latitude": weather.get("latitude"),
                "longitude": weather.get("longitude"),
                "timezone": weather.get("timezone"),
                "timezone_abbreviation": weather.get("timezone_abbreviation"),
            },
        },
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "current": {
            "time": marine_current.get("time") or weather_current.get("time"),
            "sea_surface_temperature": marine_current.get("sea_surface_temperature"),
            "wave_height": marine_current.get("wave_height"),
            "wave_direction": marine_current.get("wave_direction"),
            "ocean_current_velocity": marine_current.get("ocean_current_velocity"),
            "ocean_current_direction": marine_current.get("ocean_current_direction"),
            "wind_speed": weather_current.get("wind_speed_10m"),
            "air_temperature": weather_current.get("temperature_2m"),
        },
        "units": {
            "sea_surface_temperature": marine_units.get("sea_surface_temperature"),
            "wave_height": marine_units.get("wave_height"),
            "wave_direction": marine_units.get("wave_direction"),
            "ocean_current_velocity": marine_units.get("ocean_current_velocity"),
            "ocean_current_direction": marine_units.get("ocean_current_direction"),
            "wind_speed": weather_units.get("wind_speed_10m"),
            "air_temperature": weather_units.get("temperature_2m"),
        },
    }


def _fetch_marine_current(coords: Coordinates) -> dict[str, Any]:
    return _fetch_json(
        MARINE_API_URL,
        {
            "latitude": coords.latitude,
            "longitude": coords.longitude,
            "current": ",".join(MARINE_CURRENT_VARIABLES),
            "timezone": "auto",
            "cell_selection": "sea",
        },
    )


def _fetch_weather_current(coords: Coordinates) -> dict[str, Any]:
    return _fetch_json(
        FORECAST_API_URL,
        {
            "latitude": coords.latitude,
            "longitude": coords.longitude,
            "current": ",".join(FORECAST_CURRENT_VARIABLES),
            "timezone": "auto",
            "cell_selection": "sea",
        },
    )


def _fetch_json(base_url: str, params: dict[str, Any]) -> dict[str, Any]:
    url = f"{base_url}?{urlencode(params)}"

    try:
        with urlopen(url, timeout=20) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise OpenMeteoError(f"Open-Meteo request failed with status {exc.code}: {detail}") from exc
    except URLError as exc:
        raise OpenMeteoError(f"Open-Meteo request failed: {exc.reason}") from exc
