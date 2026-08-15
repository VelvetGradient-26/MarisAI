"""What has been *recorded* near a point, from OBIS.

OBIS has been in this repo since the habitat pipeline was built, but only inside
`machine_learning/` — the backend has never been able to answer "what lives
here", which is among the first questions anyone asks of a marine platform. Two
cheap calls answer it: `/v3/statistics` gives record, species, dataset and
year-range counts for a box in one request, and `/v3/checklist` gives the
species themselves with a record count each.

**The headline number is survey effort, not biodiversity, and this module says
so in every response.** OBIS record density tracks where people sampled — near
institutes, ports, shipping lanes and reef research sites — far more strongly
than it tracks where life is. A naive hotspot map built from these counts finds
marine laboratories. That is not a caveat bolted on: it is the *same* bias
`fish_habitat`'s target-group background exists to correct, and correcting it
inside the model while printing an uncorrected headline on a page would be
indefensible. So `bias_note` is a required part of the payload rather than
small print, and the counts are named "recorded" throughout — never "present",
never "found".

**Absence means nothing here.** OBIS is presence-only: a species missing from a
box means nobody logged it, not that it is not there. No response from this
module should be phrased, or read, as evidence of absence.

The search box is a square around the requested point rather than a true radius.
A degree of longitude shortens toward the poles, so a fixed-degree box is a
different area at 60 degrees than at the equator — the response reports the box
it actually used and its area, so a comparison between two latitudes is made
against a stated denominator rather than an assumed one.
"""

from __future__ import annotations

import asyncio
import math
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from loguru import logger

API_ROOT = "https://api.obis.org/v3"
SOURCE_LABEL = "Ocean Biodiversity Information System (OBIS)"
SOURCE_URL = "https://obis.org/"

# Ray-finned fishes. The same target group `fish_habitat` draws its background
# from, so "how many fish species" here means the same thing it means there.
_FISH_TAXON_ID = 10194

_TIMEOUT = httpx.Timeout(30.0)

# Half-width of the search box, in degrees. 0.5 gives a 1x1 degree box — about
# 111 km north-south, and roughly that east-west in the tropics. Large enough
# that a coastal point catches a real survey history, small enough that it is
# still "here" rather than "this sea".
DEFAULT_RADIUS_DEG = 0.5
_MAX_RADIUS_DEG = 5.0

# Species listed in the checklist section. The full list runs to hundreds and is
# an export, not a page.
_CHECKLIST_LIMIT = 25

# OBIS answers in a second or two and its holdings change on a release cadence
# of weeks, so this cache is about repeat views of the same place rather than
# about rate limits.
_CACHE_TTL = timedelta(hours=6)
_CACHE_MAX = 128
_KEY_DECIMALS = 2

BIAS_NOTE = (
    "OBIS record counts measure SURVEY EFFORT, not biodiversity. Records cluster around "
    "marine institutes, ports, shipping routes and reef research sites, so a place with "
    "more records is more often a place that was studied more. Absence of a species means "
    "nobody logged it here, never that it is not present."
)


class BiodiversityError(RuntimeError):
    """OBIS could not be queried, or answered with nothing usable."""


@dataclass
class _Entry:
    payload: dict[str, Any]
    stored_at: datetime


_cache: dict[tuple, _Entry] = {}
_lock = threading.Lock()


def _cached(key: tuple) -> dict[str, Any] | None:
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        if datetime.now(timezone.utc) - entry.stored_at > _CACHE_TTL:
            _cache.pop(key, None)
            return None
        return entry.payload


def _store(key: tuple, payload: dict[str, Any]) -> None:
    with _lock:
        _cache[key] = _Entry(payload=payload, stored_at=datetime.now(timezone.utc))
        if len(_cache) > _CACHE_MAX:
            oldest = min(_cache, key=lambda k: _cache[k].stored_at)
            _cache.pop(oldest, None)


def _box(latitude: float, longitude: float, radius_deg: float) -> tuple[float, float, float, float]:
    """The search box, clamped to valid coordinates.

    Latitude is clamped rather than wrapped: a box straddling the pole is not a
    box. Longitude is *not* wrapped either — a box crossing the antimeridian
    would need a multipolygon, and OBIS's WKT parser takes the naive one as a
    band the long way round the planet, which silently returns the whole ocean.
    """
    min_lat = max(latitude - radius_deg, -90.0)
    max_lat = min(latitude + radius_deg, 90.0)
    min_lon = max(longitude - radius_deg, -180.0)
    max_lon = min(longitude + radius_deg, 180.0)
    return min_lon, min_lat, max_lon, max_lat


def _wkt(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> str:
    corners = [
        (min_lon, min_lat),
        (max_lon, min_lat),
        (max_lon, max_lat),
        (min_lon, max_lat),
        (min_lon, min_lat),
    ]
    return "POLYGON((" + ", ".join(f"{lon:.4f} {lat:.4f}" for lon, lat in corners) + "))"


def _box_area_km2(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> float:
    """Approximate area, so a count can be quoted against a denominator.

    Spherical, using the mean latitude for the east-west extent. Exact enough
    for "records per 1000 km²" and stated as approximate.
    """
    mean_lat = math.radians((min_lat + max_lat) / 2.0)
    km_per_deg_lat = 110.574
    km_per_deg_lon = 111.320 * math.cos(mean_lat)
    return abs(max_lat - min_lat) * km_per_deg_lat * abs(max_lon - min_lon) * km_per_deg_lon


async def _get(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> Any:
    response = await client.get(f"{API_ROOT}{path}", params=params)
    response.raise_for_status()
    return response.json()


def _species_row(record: dict[str, Any]) -> dict[str, Any]:
    """One checklist entry, reduced to what a page shows.

    OBIS returns ~40 fields per taxon including a full parallel set of rank ids.
    The `records` count comes along because it is what makes the list orderable
    — and because a species with one record and a species with four hundred are
    very different claims about a place.
    """
    return {
        "scientific_name": record.get("scientificName"),
        "rank": record.get("taxonRank"),
        "records": record.get("records"),
        "kingdom": record.get("kingdom"),
        "phylum": record.get("phylum"),
        "class": record.get("class"),
        "order": record.get("order"),
        "family": record.get("family"),
        "is_marine": record.get("is_marine"),
        # Present on introduced/invasive taxa in the WRiMS register. Carried
        # because it is the one flag on this record that changes what a reader
        # should do about the row.
        "introduced_register": bool(record.get("wrims")),
    }


async def at_point(
    latitude: float,
    longitude: float,
    radius_deg: float = DEFAULT_RADIUS_DEG,
    limit: int = _CHECKLIST_LIMIT,
) -> dict[str, Any]:
    """Recorded biodiversity in a box around one point.

    Three OBIS calls, issued together: overall statistics, statistics restricted
    to ray-finned fishes, and the species checklist. The fish subset is a
    separate call rather than being counted out of the checklist because the
    checklist is truncated and the statistic must not be.
    """
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        raise BiodiversityError(f"coordinate out of range: {latitude}, {longitude}")
    if not 0.0 < radius_deg <= _MAX_RADIUS_DEG:
        raise BiodiversityError(
            f"radius must be between 0 and {_MAX_RADIUS_DEG} degrees; got {radius_deg}"
        )

    key = (
        round(latitude, _KEY_DECIMALS),
        round(longitude, _KEY_DECIMALS),
        round(radius_deg, 3),
        limit,
    )
    hit = _cached(key)
    if hit is not None:
        return hit

    min_lon, min_lat, max_lon, max_lat = _box(latitude, longitude, radius_deg)
    geometry = _wkt(min_lon, min_lat, max_lon, max_lat)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            overall, fishes, checklist = await asyncio.gather(
                _get(client, "/statistics", {"geometry": geometry}),
                _get(client, "/statistics", {"geometry": geometry, "taxonid": _FISH_TAXON_ID}),
                _get(client, "/checklist", {"geometry": geometry, "size": limit}),
            )
    except httpx.HTTPStatusError as exc:
        raise BiodiversityError(
            f"OBIS returned {exc.response.status_code} for this area"
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning(f"OBIS request failed: {exc}")
        raise BiodiversityError(f"OBIS could not be reached: {exc}") from exc

    records = int(overall.get("records") or 0)
    area_km2 = _box_area_km2(min_lon, min_lat, max_lon, max_lat)
    year_range = overall.get("yearrange") or []

    results = (checklist or {}).get("results") or []
    species = [_species_row(entry) for entry in results[:limit]]

    payload: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "search_box": {
            "min_longitude": round(min_lon, 4),
            "min_latitude": round(min_lat, 4),
            "max_longitude": round(max_lon, 4),
            "max_latitude": round(max_lat, 4),
            "radius_deg": radius_deg,
            "approx_area_km2": round(area_km2),
        },
        "totals": {
            "records": records,
            "species": int(overall.get("species") or 0),
            "taxa": int(overall.get("taxa") or 0),
            "datasets": int(overall.get("datasets") or 0),
            "fish_records": int(fishes.get("records") or 0),
            "fish_species": int(fishes.get("species") or 0),
            "first_year": year_range[0] if len(year_range) == 2 else None,
            "last_year": year_range[1] if len(year_range) == 2 else None,
            # Quoted per unit area rather than raw, because the box is a
            # different size at different latitudes and two raw counts are not
            # comparable. Still an effort density, not an abundance.
            "records_per_1000_km2": round(records / area_km2 * 1000, 1) if area_km2 else None,
        },
        "species": species,
        "species_truncated": len(results) > len(species)
        or int((checklist or {}).get("total") or 0) > len(species),
        "checklist_total": int((checklist or {}).get("total") or 0),
        "bias_note": BIAS_NOTE,
        "source": SOURCE_LABEL,
        "source_url": SOURCE_URL,
    }

    if records == 0:
        # An honest empty, distinguished from a failure. A box with no records
        # is a completely normal answer over most of the open ocean, and saying
        # "no records" where the data says "nobody has been here" would be the
        # exact inversion this module is about.
        payload["empty_reason"] = (
            "No OBIS records in this box. Most of the open ocean has never been "
            "sampled — this says nothing about what lives here."
        )

    _store(key, payload)
    return payload
