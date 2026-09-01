"""Live ARGO float profiles — the subsurface counterpart to `services/ndbc.py`.

`services/ndbc.py` gives the platform a real instrument reading at the
surface; nothing here gave one below it, even though `water_temperature`,
`water_salinity` and `currents_depth` are all served/forecast depth-resolved
variables with no independent check against an instrument (see TODO.md).
ARGO — ~4,000 autonomous floats that profile temperature and salinity from
~2000 m to the surface on a ~10-day cycle — is the standard in-situ source
for exactly this, and it needed a live source found before anything could be
scoped: probed live 2026-08-28 against Argovis
(`argovis-api.colorado.edu/argo`), a free, keyless, purpose-built REST API
over the underlying Ifremer/Coriolis ARGO GDAC (Global Data Assembly
Centre). A polygon query over the Arabian Sea (60-70E, 10-20N) returned in
~1-2s and included a real INCOIS-operated float (`dac/incois/7901136`) —
this platform's own region is directly covered.

**Two calls, not one.** Argovis's list endpoint (a bbox/date query) returns
each matching profile's *metadata* — position, timestamp, which variables
it carries — but not the depth-resolved values themselves; a profile's
values are a second call by its own `_id`. Fetching values for every
candidate in a search box would be wasteful when only the nearest one is
ever wanted, so `nearest_profile` ranks candidates from the cheap metadata
call and fetches full data for the winner alone.

**Pressure, not depth, and the two are only approximately equal.** ARGO
(and oceanography generally) records pressure in decibars; 1 dbar of
seawater pressure corresponds to very close to 1 m of depth in the upper
ocean (the discrepancy is under 2% even at 2000 m), which is why this is
usually treated as a depth axis without further correction — done the same
way here, and named as an approximation rather than presented as exact.

**Validation first, bias correction second — see
`scripts/compare_against_argo.py`.** This module only fetches and parses;
it does not compare a profile against anything this platform serves. That
comparison is deliberately a separate, explicit script rather than folded
in here, the same reason `scripts/compare_against_eddy_atlas.py` is not
inside `services/eddies.py`: measuring whether a correction is even needed
is a different kind of operation from serving live data, and one that
should stay easy to re-run on its own.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

ARGOVIS_BASE_URL = "https://argovis-api.colorado.edu/argo"
SOURCE_LABEL = "Argovis, over the Ifremer/Coriolis ARGO Global Data Assembly Centre"
SOURCE_URL = "https://argovis.colorado.edu/"

_TIMEOUT = httpx.Timeout(30.0)
EARTH_RADIUS_KM = 6371.0088

# How far a profile may be from the requested point and still count as
# "nearby". ARGO's float density is coarse by design (~1 float per 3
# degrees globally, the whole point of the network being basin-scale
# coverage rather than dense sampling) — a tight radius would report "no
# float here" for most points on Earth, which is a true but useless answer
# for a screening tool. Wide enough to usually find one in the North Indian
# Ocean, still a real bound.
DEFAULT_RADIUS_KM = 300.0
MAX_RADIUS_KM = 1000.0

# A float profiles roughly every 10 days; this is generous enough to find
# the most recent cycle from a float that reported just before the window
# opened, without reaching back to a profile so old it no longer describes
# current conditions.
DEFAULT_LOOKBACK_DAYS = 30
MAX_LOOKBACK_DAYS = 120

_PROFILE_VARIABLES = ("temperature", "salinity", "pressure")


class ArgoError(RuntimeError):
    """The Argovis feed could not be reached or answered with something unusable."""


@dataclass(frozen=True)
class ArgoLevel:
    pressure_dbar: float
    depth_m: float  # `pressure_dbar`, treated as depth — see module docstring.
    temperature_c: float | None
    salinity_psu: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "pressure_dbar": round(self.pressure_dbar, 1),
            "depth_m": round(self.depth_m, 1),
            "temperature_c": round(self.temperature_c, 3) if self.temperature_c is not None else None,
            "salinity_psu": round(self.salinity_psu, 3) if self.salinity_psu is not None else None,
        }


@dataclass(frozen=True)
class ArgoProfile:
    profile_id: str
    float_id: str
    latitude: float
    longitude: float
    timestamp: datetime
    distance_km: float
    levels: list[ArgoLevel]

    def shallowest(self) -> ArgoLevel | None:
        """The level nearest the surface with a usable temperature — for
        comparing against a surface product like `services/copernicus_sst.py`
        or OISST, neither of which measures at exactly 0 dbar either."""
        candidates = [level for level in self.levels if level.temperature_c is not None]
        return min(candidates, key=lambda level: level.pressure_dbar) if candidates else None

    def as_dict(self, *, include_levels: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "profile_id": self.profile_id,
            "float_id": self.float_id,
            "latitude": round(self.latitude, 4),
            "longitude": round(self.longitude, 4),
            "timestamp": self.timestamp.isoformat(),
            "distance_km": round(self.distance_km, 1),
            "level_count": len(self.levels),
        }
        if include_levels:
            payload["levels"] = [level.as_dict() for level in self.levels]
        return payload


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _bbox_polygon(latitude: float, longitude: float, radius_km: float) -> list[list[float]]:
    """A closed lon/lat box around a point, generous enough at high latitude.

    A plain degree box narrows in longitude toward the poles (`cos(lat)`),
    so it is widened here rather than left to under-cover a high-latitude
    query — this platform's own use is tropical/subtropical, but the
    function is not.
    """
    lat_margin = radius_km / 111.32
    lon_margin = radius_km / (111.32 * max(math.cos(math.radians(latitude)), 0.1))
    south, north = latitude - lat_margin, latitude + lat_margin
    west, east = longitude - lon_margin, longitude + lon_margin
    return [[west, south], [east, south], [east, north], [west, north], [west, south]]


@retry(
    retry=retry_if_not_exception_type(ArgoError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=15),
)
async def _get(client: httpx.AsyncClient, params: dict[str, Any], *, not_found_is_empty: bool = False) -> Any:
    """`not_found_is_empty` covers a real Argovis behaviour, found live: the
    *search* endpoint returns HTTP 404 — not `200` with `[]` — for a
    polygon/date query that simply matches no profiles, which is the common
    case for a narrow, recent window given ARGO's sparse ~10-day-cycle
    coverage. Confirmed by re-running an identical query with a wider date
    range, which returned real profiles with `200`. Without this, a
    genuinely empty search was indistinguishable from a real failure: it
    retried three times against a query that could never succeed (the
    result does not change on retry) and then raised `ArgoError`, so
    `nearest_profile`'s own "no float nearby" response — the whole reason
    it never raises for that case — was never reached. The *detail* fetch
    by a known `_id` does not set this: a 404 there means a real profile
    vanished between calls, which is worth surfacing as an error.
    """
    response = await client.get(ARGOVIS_BASE_URL, params=params)
    if not_found_is_empty and response.status_code == 404:
        return []
    response.raise_for_status()
    return response.json()


async def nearest_profile(
    latitude: float,
    longitude: float,
    radius_km: float = DEFAULT_RADIUS_KM,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """The nearest ARGO profile to a point within `radius_km` and
    `lookback_days`, with its full temperature/salinity-by-depth data.

    Never raises for "no float nearby" — ARGO's coverage is real but coarse
    (see `DEFAULT_RADIUS_KM`'s own reasoning), and that is a true, useful
    answer rather than a failure. Only a genuine Argovis fetch failure
    raises `ArgoError`.
    """
    radius_km = min(radius_km, MAX_RADIUS_KM)
    lookback_days = min(lookback_days, MAX_LOOKBACK_DAYS)
    now = datetime.now(UTC)
    start = now - timedelta(days=lookback_days)
    polygon = _bbox_polygon(latitude, longitude, radius_km)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            candidates = await _get(
                client,
                {
                    "startDate": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "endDate": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "polygon": str(polygon).replace(" ", ""),
                },
                not_found_is_empty=True,
            )
    except httpx.HTTPStatusError as exc:
        raise ArgoError(f"Argovis returned {exc.response.status_code} for the profile search") from exc
    except httpx.HTTPError as exc:
        logger.warning(f"Argovis search request failed: {exc}")
        raise ArgoError(f"Argovis could not be reached: {exc}") from exc

    if not candidates:
        return {
            "available": False,
            "unavailable_reason": (
                f"no ARGO float profiled within {radius_km:.0f} km of this point in "
                f"the last {lookback_days} days — real coverage, not a fetch failure "
                "(the network averages roughly one float per 3 degrees globally)"
            ),
            "radius_km": radius_km,
            "lookback_days": lookback_days,
        }

    ranked = sorted(
        (
            (
                _haversine_km(latitude, longitude, entry["geolocation"]["coordinates"][1], entry["geolocation"]["coordinates"][0]),
                entry,
            )
            for entry in candidates
            if entry.get("geolocation", {}).get("coordinates")
        ),
        key=lambda pair: pair[0],
    )
    if not ranked:
        return {
            "available": False,
            "unavailable_reason": "Argovis returned candidates with no usable position",
            "radius_km": radius_km,
            "lookback_days": lookback_days,
        }

    distance_km, nearest = ranked[0]

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            detail = await _get(
                client,
                {"id": nearest["_id"], "data": ",".join(_PROFILE_VARIABLES)},
            )
    except httpx.HTTPStatusError as exc:
        raise ArgoError(f"Argovis returned {exc.response.status_code} fetching profile {nearest['_id']!r}") from exc
    except httpx.HTTPError as exc:
        logger.warning(f"Argovis profile fetch failed: {exc}")
        raise ArgoError(f"Argovis could not be reached: {exc}") from exc

    if not detail:
        raise ArgoError(f"Argovis returned no data for profile {nearest['_id']!r}")

    profile = _parse_profile(detail[0], distance_km)
    return {"available": True, "radius_km": radius_km, "lookback_days": lookback_days, "profile": profile.as_dict()}


def _parse_profile(entry: dict[str, Any], distance_km: float) -> ArgoProfile:
    data = entry.get("data") or []
    data_info = entry.get("data_info") or []
    variable_names = data_info[0] if data_info else []

    columns = dict(zip(variable_names, data, strict=False))
    pressures = columns.get("pressure") or []
    temperatures = columns.get("temperature") or [None] * len(pressures)
    salinities = columns.get("salinity") or [None] * len(pressures)

    levels = [
        ArgoLevel(pressure_dbar=float(pressure), depth_m=float(pressure), temperature_c=temp, salinity_psu=salinity)
        for pressure, temp, salinity in zip(pressures, temperatures, salinities, strict=True)
        if pressure is not None
    ]
    levels.sort(key=lambda level: level.pressure_dbar)

    coordinates = entry["geolocation"]["coordinates"]  # [lon, lat]
    return ArgoProfile(
        profile_id=str(entry["_id"]),
        float_id=str(entry["_id"]).split("_")[0],
        latitude=float(coordinates[1]),
        longitude=float(coordinates[0]),
        timestamp=datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")),
        distance_km=distance_km,
        levels=levels,
    )
