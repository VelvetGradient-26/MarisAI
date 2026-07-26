from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


MARINE_API_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"
REVERSE_GEOCODE_URL = "https://api.bigdatacloud.net/data/reverse-geocode-client"

MARINE_CURRENT_VARIABLES = [
    "sea_surface_temperature",
    "wave_height",
    "wave_direction",
    "wave_period",
    "ocean_current_velocity",
    "ocean_current_direction",
    "sea_level_height_msl",
]

FORECAST_CURRENT_VARIABLES = [
    "wind_speed_10m",
    "wind_direction_10m",
    "temperature_2m",
    "relative_humidity_2m",
    "surface_pressure",
    "visibility",
    "cloud_cover",
    "precipitation",
]


class OpenMeteoError(RuntimeError):
    pass


@dataclass(frozen=True)
class Coordinates:
    latitude: float
    longitude: float


async def get_realtime_ocean_conditions(latitude: float, longitude: float) -> dict[str, Any]:
    coords = Coordinates(latitude=latitude, longitude=longitude)
    timeout = httpx.Timeout(20.0)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        marine, weather, location_context = await asyncio.gather(
            _fetch_marine_current(client, coords),
            _fetch_weather_current(client, coords),
            _fetch_location_context(client, coords),
        )

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
        "location_context": location_context,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "current": {
            "time": marine_current.get("time") or weather_current.get("time"),
            "sea_surface_temperature": marine_current.get("sea_surface_temperature"),
            "wave_height": marine_current.get("wave_height"),
            "wave_direction": marine_current.get("wave_direction"),
            "wave_period": marine_current.get("wave_period"),
            "ocean_current_velocity": marine_current.get("ocean_current_velocity"),
            "ocean_current_direction": marine_current.get("ocean_current_direction"),
            "sea_level_height_msl": marine_current.get("sea_level_height_msl"),
            "wind_speed": weather_current.get("wind_speed_10m"),
            "wind_direction": weather_current.get("wind_direction_10m"),
            "air_temperature": weather_current.get("temperature_2m"),
            "relative_humidity": weather_current.get("relative_humidity_2m"),
            "surface_pressure": weather_current.get("surface_pressure"),
            "visibility": weather_current.get("visibility"),
            "cloud_cover": weather_current.get("cloud_cover"),
            "precipitation": weather_current.get("precipitation"),
        },
        "units": {
            "sea_surface_temperature": marine_units.get("sea_surface_temperature"),
            "wave_height": marine_units.get("wave_height"),
            "wave_direction": marine_units.get("wave_direction"),
            "wave_period": marine_units.get("wave_period"),
            "ocean_current_velocity": marine_units.get("ocean_current_velocity"),
            "ocean_current_direction": marine_units.get("ocean_current_direction"),
            "sea_level_height_msl": marine_units.get("sea_level_height_msl"),
            "wind_speed": weather_units.get("wind_speed_10m"),
            "wind_direction": weather_units.get("wind_direction_10m"),
            "air_temperature": weather_units.get("temperature_2m"),
            "relative_humidity": weather_units.get("relative_humidity_2m"),
            "surface_pressure": weather_units.get("surface_pressure"),
            "visibility": weather_units.get("visibility"),
            "cloud_cover": weather_units.get("cloud_cover"),
            "precipitation": weather_units.get("precipitation"),
        },
        "attribution": {
            "name": "Open-Meteo",
            "url": "https://open-meteo.com/",
            "provider_name": "DWD",
            "provider_url": "https://www.dwd.de/",
        },
    }


async def _fetch_marine_current(client: httpx.AsyncClient, coords: Coordinates) -> dict[str, Any]:
    return await _fetch_json(
        client,
        MARINE_API_URL,
        {
            "latitude": coords.latitude,
            "longitude": coords.longitude,
            "current": ",".join(MARINE_CURRENT_VARIABLES),
            "timezone": "auto",
            "cell_selection": "sea",
        },
        source="Open-Meteo Marine API",
    )


async def _fetch_weather_current(client: httpx.AsyncClient, coords: Coordinates) -> dict[str, Any]:
    return await _fetch_json(
        client,
        FORECAST_API_URL,
        {
            "latitude": coords.latitude,
            "longitude": coords.longitude,
            "current": ",".join(FORECAST_CURRENT_VARIABLES),
            "timezone": "auto",
            "cell_selection": "sea",
        },
        source="Open-Meteo Weather API",
    )


async def _fetch_location_context(
    client: httpx.AsyncClient, coords: Coordinates
) -> dict[str, str | None]:
    try:
        payload = await _fetch_json(
            client,
            REVERSE_GEOCODE_URL,
            {
                "latitude": coords.latitude,
                "longitude": coords.longitude,
                "localityLanguage": "en",
            },
            source="reverse geocoding API",
        )
    except OpenMeteoError:
        return {
            "ocean_name": None,
            "country_name": None,
            "locality": None,
            "continent": None,
        }

    informative = payload.get("localityInfo", {}).get("informative", [])

    return {
        "ocean_name": _extract_ocean_name(payload, informative),
        "country_name": _extract_country_name(payload, informative),
        "locality": _clean_string(payload.get("locality")),
        "continent": _clean_string(payload.get("continent")),
    }


def _extract_ocean_name(payload: dict[str, Any], informative: list[dict[str, Any]]) -> str | None:
    water_terms = ("ocean", "sea", "gulf", "bay", "channel", "strait")

    for item in informative:
        description = str(item.get("description", "")).lower()
        name = _clean_string(item.get("name"))
        if name and any(term in description for term in water_terms):
            return name

    locality = _clean_string(payload.get("locality"))
    if locality and any(term in locality.lower() for term in water_terms):
        return locality

    return None


def _extract_country_name(payload: dict[str, Any], informative: list[dict[str, Any]]) -> str | None:
    country_name = _clean_string(payload.get("countryName"))
    if country_name:
        return country_name

    locality = payload.get("locality")
    if isinstance(locality, str):
        parsed = _extract_country_from_boundary_name(locality)
        if parsed:
            return parsed

    for item in informative:
        if str(item.get("description", "")).lower() != "maritime boundary":
            continue
        parsed = _extract_country_from_boundary_name(str(item.get("name", "")))
        if parsed:
            return parsed

    return None


def _extract_country_from_boundary_name(value: str) -> str | None:
    if not value:
        return None

    match = re.search(r"\bof\s+(.+)$", value)
    if not match:
        return None

    country_name = match.group(1).strip()
    if country_name.lower().startswith("the "):
        country_name = country_name[4:]
    return country_name or None


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


async def _fetch_json(
    client: httpx.AsyncClient,
    base_url: str,
    params: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    try:
        response = await client.get(base_url, params=params)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        raise OpenMeteoError(
            f"{source} request failed with status {exc.response.status_code}: {detail}"
        ) from exc
    except (httpx.RequestError, ValueError) as exc:
        raise OpenMeteoError(f"{source} request failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise OpenMeteoError(f"{source} returned an unexpected response")
    if payload.get("error"):
        raise OpenMeteoError(f"{source} request failed: {payload.get('reason', 'unknown error')}")
    return payload
