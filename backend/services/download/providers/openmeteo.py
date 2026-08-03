"""Open-Meteo provider for the Universal Ocean Data Downloader — meteorology
(air temperature, humidity, pressure, rainfall, wind gust).

Structurally the odd one out. Every other provider is a gridded store the
Copernicus toolbox hands back as an `xarray.Dataset`; Open-Meteo is a *point*
JSON API. So this module does the gridding itself: it lays a regular lat/lon
grid over the requested bbox, batches those points across requests, and
assembles the responses back into an `xarray.Dataset` with the same
`(time, latitude, longitude)` shape the Copernicus providers return. That is
the whole point of doing it here — `cleaning.py` and `service.py` never learn
that one of their providers speaks JSON.

Two API boundaries, both measured against the live service rather than taken
from the docs:

- The archive API (ERA5) reaches back to 1940 and is populated to roughly
  today-2; today-5 is used as the boundary for safety.
- The forecast API is only *allowed* back to today-93, but returns nulls that
  far back — it is genuinely populated for the recent past and ~15 days ahead.

So a range that straddles the boundary is fetched from both and concatenated,
rather than picking one API and accepting a hole at one end.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import numpy as np
import pandas as pd
import xarray as xr

ARCHIVE_API_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"

# ERA5 back to 1940; the practical floor is the API's own documented start.
COVERAGE_START = date(1940, 1, 1)
# The archive is authoritative through today - ARCHIVE_LAG_DAYS; anything
# newer comes from the forecast API instead.
ARCHIVE_LAG_DAYS = 5
# Verified: end_date is accepted up to today+15, rejected at today+16.
FORECAST_HORIZON_DAYS = 15

# ERA5's native spacing. Also what limits.py sizes an Open-Meteo request on.
GRID_SPACING_DEG = 0.25

# Coordinates per HTTP request. 100 returns in ~2s; 200 takes ~13s and 800
# exceeds the server's URI length limit outright, so this stays well clear.
_POINTS_PER_REQUEST = 100
# Concurrent in-flight requests, to stay a polite client of a free API.
_MAX_CONCURRENCY = 4

_TIMEOUT = httpx.Timeout(120.0)

# Field names are Open-Meteo's own — the registry stores them directly as each
# variable's `source_field`, so there is no translation table to keep in sync.
# Their units already match what the registry advertises (degC, %, hPa, mm)
# with one exception: gusts come back in km/h by default, so every request
# below pins `wind_speed_unit=ms`.


class OpenMeteoDownloadError(RuntimeError):
    """Open-Meteo request failed — surfaced as a clean provider error rather
    than an httpx traceback."""


def build_grid(
    west: float, south: float, east: float, north: float
) -> tuple[np.ndarray, np.ndarray]:
    """The regular lat/lon grid this provider will request points at.

    Open-Meteo snaps each requested coordinate to its own model cell and
    reports the snapped position back. Those snapped positions do not form a
    clean rectangle (and several requested points can land in one cell), so
    the *requested* grid is what becomes the dataset's axes — the values are
    nearest-cell readings at those coordinates, exactly the convention
    `.sel(method="nearest")` gives everywhere else in this feature.

    The grid is laid out from the centre of the box outwards, not from its
    south-west corner. For a bbox the two are equivalent (either way it is a
    regular 0.25deg lattice covering the area), but a point request arrives
    here as a small box centred on the point, and centring means that point
    is itself a grid node — otherwise a point query could be answered from up
    to half a cell away for no reason.
    """
    lat_steps = max(1, round((north - south) / 2 / GRID_SPACING_DEG))
    lon_steps = max(1, round((east - west) / 2 / GRID_SPACING_DEG))
    lats = (south + north) / 2 + GRID_SPACING_DEG * np.arange(-lat_steps, lat_steps + 1)
    lons = (west + east) / 2 + GRID_SPACING_DEG * np.arange(-lon_steps, lon_steps + 1)
    return np.round(lats, 6), np.round(lons, 6)


def split_date_range(
    start_date: date, end_date: date, today: date
) -> tuple[tuple[date, date] | None, tuple[date, date] | None]:
    """Split a range into the archive part and the forecast part.

    Either half can be None. A range entirely in the past is one archive
    fetch; one entirely recent is one forecast fetch; one that straddles the
    boundary is both, concatenated.
    """
    boundary = today - timedelta(days=ARCHIVE_LAG_DAYS)
    archive: tuple[date, date] | None = None
    forecast: tuple[date, date] | None = None

    if start_date < boundary:
        archive = (start_date, min(end_date, boundary - timedelta(days=1)))
    if end_date >= boundary:
        forecast = (max(start_date, boundary), end_date)
    return archive, forecast


async def _get_batch(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    url: str,
    lats: list[float],
    lons: list[float],
    fields: list[str],
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    params = {
        "latitude": ",".join(str(v) for v in lats),
        "longitude": ",".join(str(v) for v in lons),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "hourly": ",".join(fields),
        "timezone": "UTC",
        "wind_speed_unit": "ms",
        # Nudge each point to the nearest cell the model considers sea rather
        # than the nearest cell outright — this is a marine tool, and a
        # coastal point otherwise reads as the land cell beside it.
        "cell_selection": "sea",
    }
    async with semaphore:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:300]
            raise OpenMeteoDownloadError(
                f"Open-Meteo returned status {exc.response.status_code}: {detail}"
            ) from exc
        except (httpx.RequestError, ValueError) as exc:
            raise OpenMeteoDownloadError(f"Open-Meteo request failed: {exc}") from exc

    # A single-coordinate request returns one object; a multi-coordinate one
    # returns a list. Normalise so the caller only ever sees a list.
    if isinstance(payload, dict):
        if payload.get("error"):
            raise OpenMeteoDownloadError(
                f"Open-Meteo request failed: {payload.get('reason', 'unknown error')}"
            )
        return [payload]
    if not isinstance(payload, list):
        raise OpenMeteoDownloadError("Open-Meteo returned an unexpected response shape")
    return payload


async def _fetch_window(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    url: str,
    points: list[tuple[float, float]],
    fields: list[str],
    start_date: date,
    end_date: date,
) -> list[tuple[tuple[float, float], dict[str, Any]]]:
    """Fetch one date window for every point, in batches, preserving the
    point each response belongs to (responses come back in request order)."""
    batches = [
        points[i : i + _POINTS_PER_REQUEST]
        for i in range(0, len(points), _POINTS_PER_REQUEST)
    ]
    results = await asyncio.gather(
        *(
            _get_batch(
                client,
                semaphore,
                url,
                [lat for lat, _ in batch],
                [lon for _, lon in batch],
                fields,
                start_date,
                end_date,
            )
            for batch in batches
        )
    )

    paired: list[tuple[tuple[float, float], dict[str, Any]]] = []
    for batch, responses in zip(batches, results, strict=True):
        if len(responses) != len(batch):
            raise OpenMeteoDownloadError(
                f"Open-Meteo returned {len(responses)} results for {len(batch)} coordinates"
            )
        paired.extend(zip(batch, responses, strict=True))
    return paired


def _to_dataset(
    paired: list[tuple[tuple[float, float], dict[str, Any]]],
    fields: list[str],
    lats: np.ndarray,
    lons: np.ndarray,
) -> xr.Dataset:
    """Assemble per-point hourly JSON into a (time, latitude, longitude) grid."""
    lat_index = {round(float(v), 6): i for i, v in enumerate(lats)}
    lon_index = {round(float(v), 6): i for i, v in enumerate(lons)}

    times: pd.DatetimeIndex | None = None
    arrays: dict[str, np.ndarray] = {}

    for (lat, lon), payload in paired:
        hourly = payload.get("hourly")
        if not isinstance(hourly, dict) or "time" not in hourly:
            raise OpenMeteoDownloadError("Open-Meteo response is missing its hourly block")

        if times is None:
            # Open-Meteo emits naive local-time strings; `timezone=UTC` makes
            # them UTC. Kept naive to match the Copernicus datasets' naive
            # datetime64 UTC axis — a tz-aware axis would not align on merge.
            times = pd.to_datetime(hourly["time"])
            for field in fields:
                arrays[field] = np.full((len(times), lats.size, lons.size), np.nan, dtype="float64")

        i = lat_index[round(float(lat), 6)]
        j = lon_index[round(float(lon), 6)]
        for field in fields:
            values = hourly.get(field)
            if values is None:
                continue
            arrays[field][:, i, j] = np.asarray(
                [np.nan if v is None else v for v in values], dtype="float64"
            )

    if times is None:
        raise OpenMeteoDownloadError("Open-Meteo returned no data for the requested points")

    return xr.Dataset(
        {field: (("time", "latitude", "longitude"), arrays[field]) for field in fields},
        coords={"time": times, "latitude": lats, "longitude": lons},
    )


async def fetch(
    *,
    fields: list[str],
    west: float,
    south: float,
    east: float,
    north: float,
    start_date: date,
    end_date: date,
    **_ignored: Any,
) -> xr.Dataset:
    """Fetch meteorology over a bbox and date range as a gridded Dataset.

    `fields` are Open-Meteo hourly field names (already mapped from registry
    codes by the catalog), so this stays a thin, unopinionated fetcher.
    """
    lats, lons = build_grid(west, south, east, north)
    points = [(float(lat), float(lon)) for lat in lats for lon in lons]

    archive_window, forecast_window = split_date_range(start_date, end_date, date.today())

    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        windows = [
            (ARCHIVE_API_URL, archive_window),
            (FORECAST_API_URL, forecast_window),
        ]
        fetched = await asyncio.gather(
            *(
                _fetch_window(client, semaphore, url, points, fields, window[0], window[1])
                for url, window in windows
                if window is not None
            )
        )

    parts = [_to_dataset(paired, fields, lats, lons) for paired in fetched]
    if len(parts) == 1:
        return parts[0]
    # Straddled the archive/forecast boundary: the two halves are disjoint by
    # construction, but concat + de-duplicate defends against the boundary
    # shifting under us mid-request.
    combined = xr.concat(parts, dim="time")
    _, unique = np.unique(combined["time"].values, return_index=True)
    return combined.isel(time=np.sort(unique))
