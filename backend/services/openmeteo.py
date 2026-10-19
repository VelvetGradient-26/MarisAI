from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx

from services.ports import find_nearest_port

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


# A future time for a safety question, in words the assistant can pass
# through without doing time-zone arithmetic itself. Resolved in the point's
# own local time (Open-Meteo `timezone=auto`), never server or UTC time.
When = Literal["now", "tonight", "tomorrow_morning", "tomorrow_afternoon", "tomorrow_evening"]

_WHEN_HOUR: dict[str, tuple[int, int]] = {
    # (days ahead, local hour)
    "tomorrow_morning": (1, 6),
    "tomorrow_afternoon": (1, 14),
    "tomorrow_evening": (1, 18),
}
_TONIGHT_HOUR = 21
FORECAST_DAYS = 4
MAX_HOURS_AHEAD = 72


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def resolve_target(when: When, hours_ahead: int | None, now_local: datetime) -> datetime:
    """The local wall-clock hour a question refers to.

    `hours_ahead` (1-72) overrides `when`. The result is on the hour, because
    the hourly forecast is.
    """
    if hours_ahead is not None:
        target = now_local + timedelta(hours=hours_ahead)
        return target.replace(minute=0, second=0, microsecond=0)
    if when == "now":
        return now_local.replace(minute=0, second=0, microsecond=0)
    if when == "tonight":
        target = now_local.replace(hour=_TONIGHT_HOUR, minute=0, second=0, microsecond=0)
        return target if target > now_local else target + timedelta(days=1)
    days, hour = _WHEN_HOUR[when]
    return (now_local + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)


def _hourly_value(payload: dict[str, Any], variable: str, stamp: str) -> Any:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    values = hourly.get(variable) or []
    if stamp in times:
        index = times.index(stamp)
        if index < len(values):
            return values[index]
    return None


async def get_forecast_ocean_conditions(
    latitude: float, longitude: float, *, when: When, hours_ahead: int | None = None
) -> dict[str, Any]:
    """Sea state at a future local hour, in the same `current`-shaped block
    `get_realtime_ocean_conditions` returns, plus `valid_time` (local ISO
    hour) and the point's `timezone`. A value the forecast does not carry for
    that hour is None, never a substitute.
    """
    common = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": "auto",
        "cell_selection": "sea",
        "forecast_days": FORECAST_DAYS,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=True) as client:
        marine, weather = await asyncio.gather(
            _fetch_json(
                client,
                MARINE_API_URL,
                {**common, "hourly": "wave_height,wave_direction,wave_period"},
                source="Open-Meteo Marine API",
            ),
            _fetch_json(
                client,
                FORECAST_API_URL,
                {**common, "hourly": "wind_speed_10m,wind_direction_10m,precipitation,visibility"},
                source="Open-Meteo Weather API",
            ),
        )

    offset = timedelta(seconds=int(weather.get("utc_offset_seconds") or marine.get("utc_offset_seconds") or 0))
    now_local = _now_utc().astimezone(timezone(offset))
    target = resolve_target(when, hours_ahead, now_local)
    stamp = target.strftime("%Y-%m-%dT%H:00")

    return {
        "requested": {"latitude": latitude, "longitude": longitude},
        "valid_time": stamp,
        "utc_offset_seconds": int(offset.total_seconds()),
        "timezone": weather.get("timezone") or marine.get("timezone"),
        "fetched_at": _now_utc().isoformat(),
        "current": {
            "time": stamp,
            "wave_height": _hourly_value(marine, "wave_height", stamp),
            "wave_direction": _hourly_value(marine, "wave_direction", stamp),
            "wave_period": _hourly_value(marine, "wave_period", stamp),
            "wind_speed": _hourly_value(weather, "wind_speed_10m", stamp),
            "wind_direction": _hourly_value(weather, "wind_direction_10m", stamp),
            "precipitation": _hourly_value(weather, "precipitation", stamp),
            "visibility": _hourly_value(weather, "visibility", stamp),
        },
        "units": {
            "wave_height": (marine.get("hourly_units") or {}).get("wave_height"),
            "wind_speed": (weather.get("hourly_units") or {}).get("wind_speed_10m"),
        },
        "attribution": {"name": "Open-Meteo", "url": "https://open-meteo.com/"},
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
) -> dict[str, Any]:
    nearest_port = find_nearest_port(coords.latitude, coords.longitude)

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
            "nearest_port": nearest_port,
            "locality": None,
            "continent": None,
        }

    informative = payload.get("localityInfo", {}).get("informative", [])

    return {
        "ocean_name": _extract_ocean_name(payload, informative),
        "nearest_port": nearest_port,
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
