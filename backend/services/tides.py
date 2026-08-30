"""Real-time tide-gauge sea level, from INCOIS's Indian Tsunami Early Warning
System (TEWS) network.

sihtodo.md item 6 ("tide data — a hard gap, and the PS names it explicitly")
recorded that no live, keyless, machine-readable INCOIS tide feed had been
found in a static-probe pass, and that a real browser session watching the
TEWS map's own network traffic was the next thing worth trying. That session
(2026-08-27, `https://tsunami.incois.gov.in/TEWS/`) found it: the map's own
"TideGauge" layer is built from `/itews/homexmls/TideStations.xml` (a list of
~50 Indian stations with position and `Reporting`/`Not Reporting` status,
served with no key), and clicking a station marker fetches
`/itews/JSONS/{STATION_REAL_NAME_UPPERCASE}_{days}.json` — a genuine,
1-minute-cadence sea-level series for `days` in {1, 7, 30}. Both are read by
`main.js`/`TGChartNat.js` client-side with no auth of any kind.

**This is measured real-time sea level from a tide gauge (radar/pressure
sensor), not a predicted astronomical tide table.** INCOIS's actual tide
*prediction* page (`ITCOocean/tides.jsp`, per sihtodo.md's original probe)
still 404s — that gap is real and unclosed. What this module answers instead
is "what is the water doing at this coastal station right now", which folds
in the astronomical tide plus storm surge and local wave setup — the PS's own
example question ("tide, weather, and sea conditions") is arguably better
served by the measured value anyway, but every response says which one this
is rather than letting "tide" imply a forecast it is not.

**The series JSON's timestamp field is not a real epoch, and this was found
by cross-checking it against the station page's own displayed values.**
`GARDENREACH_1.json`'s last point decodes (naively, as epoch-milliseconds) to
the year 126, not 2026 — every other field (month/day/hour/minute, and the
water-level value) matched the page's own "Last Reported Date&Time(UTC)" and
"Last Reported Value(m)" exactly. The gap is exactly 1900 years on every
point in every station and every window (1/7/30 day) checked — the classic
signature of legacy `java.util.Date(year, month, day)` construction (which
takes `year - 1900`) being round-tripped through epoch-millis arithmetic
without the 1900 ever being added back server-side. `_decode_timestamp`
corrects only the year field rather than adding a fixed millisecond offset,
because 1900 years is not a fixed number of milliseconds across that many
leap years — replacing the year reproduces the displayed value exactly,
verified against multiple stations.

**A "Not Reporting" station's series JSON is `[{"data": []}]` — a clean empty
signal, not a 404 or stale frozen values** (verified live against
`VISAKHAPATNAM_1.json` while `VISAKHAPATNAM` shows `Not Reporting` in the
station list). `nearest_station` therefore still prefers a `Reporting`
station over a closer `Not Reporting` one, but falls back to the nearest
`Not Reporting` one with a plain "not currently reporting" answer rather than
claiming no station exists nearby at all.

**Scoped to the ~50 India stations in `TideStations.xml` only** — the same
feed's `TideIntStations.xml` lists 832 more, worldwide, feeding the same
global tsunami-warning network, but MarisAI's own coastal-fisherman use case
is India-scoped everywhere else in this codebase (habitat/bloom
models, PFZ, geofencing), and extending this to the whole planet would need
verifying the JSON naming convention holds for names this file has not seen
(accents, multi-word ports) — left for a later pass if a non-India query
ever needs it.

**`tsunami.incois.gov.in` fails Python's default TLS verification, and this
was found the hard way — `curl` and a browser reach it fine, `httpx` does
not.** `openssl s_client -connect tsunami.incois.gov.in:443 -showcerts`
shows the handshake carries exactly one certificate: the leaf, issued by
"GlobalSign RSA OV SSL CA 2018". The server never sends that intermediate,
so a client verifying strictly against `certifi`'s bundle (which holds
GlobalSign's *root* but not this intermediate) fails with "unable to get
local issuer certificate" — while curl and browsers tolerate it, either via
OS-level Authority Information Access fetching or an already-cached
intermediate. `_SSL_CONTEXT` below loads `certifi`'s normal trust roots
*plus* this one intermediate (fetched once from GlobalSign's own AIA URL,
`http://secure.globalsign.com/cacert/gsrsaovsslca2018.crt`, and embedded
here rather than fetched at request time, which would just be a second
network call that could itself fail) so the chain completes locally without
weakening verification of anything else. Valid until 2028-11-21 per the
certificate's own `notAfter`; re-fetch and replace if this ever expires or
INCOIS starts sending a complete chain itself (harmless either way — an
extra trusted intermediate that chain-building never needs to use).
"""

from __future__ import annotations

import logging
import ssl
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Any
from xml.etree import ElementTree

import certifi
import httpx

logger = logging.getLogger(__name__)

_STATIONS_URL = "https://tsunami.incois.gov.in/itews/homexmls/TideStations.xml"
_SERIES_URL = "https://tsunami.incois.gov.in/itews/JSONS/{station}_1.json"
_TIMEOUT = httpx.Timeout(20.0)

# GlobalSign's "GlobalSign RSA OV SSL CA 2018" intermediate — see the module
# docstring. Issued by GlobalSign Root CA - R3, which is in certifi already.
_GLOBALSIGN_RSA_OV_SSL_CA_2018 = """\
-----BEGIN CERTIFICATE-----
MIIETjCCAzagAwIBAgINAe5fIh38YjvUMzqFVzANBgkqhkiG9w0BAQsFADBMMSAw
HgYDVQQLExdHbG9iYWxTaWduIFJvb3QgQ0EgLSBSMzETMBEGA1UEChMKR2xvYmFs
U2lnbjETMBEGA1UEAxMKR2xvYmFsU2lnbjAeFw0xODExMjEwMDAwMDBaFw0yODEx
MjEwMDAwMDBaMFAxCzAJBgNVBAYTAkJFMRkwFwYDVQQKExBHbG9iYWxTaWduIG52
LXNhMSYwJAYDVQQDEx1HbG9iYWxTaWduIFJTQSBPViBTU0wgQ0EgMjAxODCCASIw
DQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAKdaydUMGCEAI9WXD+uu3Vxoa2uP
UGATeoHLl+6OimGUSyZ59gSnKvuk2la77qCk8HuKf1UfR5NhDW5xUTolJAgvjOH3
idaSz6+zpz8w7bXfIa7+9UQX/dhj2S/TgVprX9NHsKzyqzskeU8fxy7quRU6fBhM
abO1IFkJXinDY+YuRluqlJBJDrnw9UqhCS98NE3QvADFBlV5Bs6i0BDxSEPouVq1
lVW9MdIbPYa+oewNEtssmSStR8JvA+Z6cLVwzM0nLKWMjsIYPJLJLnNvBhBWk0Cq
o8VS++XFBdZpaFwGue5RieGKDkFNm5KQConpFmvv73W+eka440eKHRwup08CAwEA
AaOCASkwggElMA4GA1UdDwEB/wQEAwIBhjASBgNVHRMBAf8ECDAGAQH/AgEAMB0G
A1UdDgQWBBT473/yzXhnqN5vjySNiPGHAwKz6zAfBgNVHSMEGDAWgBSP8Et/qC5F
JK5NUPpjmove4t0bvDA+BggrBgEFBQcBAQQyMDAwLgYIKwYBBQUHMAGGImh0dHA6
Ly9vY3NwMi5nbG9iYWxzaWduLmNvbS9yb290cjMwNgYDVR0fBC8wLTAroCmgJ4Yl
aHR0cDovL2NybC5nbG9iYWxzaWduLmNvbS9yb290LXIzLmNybDBHBgNVHSAEQDA+
MDwGBFUdIAAwNDAyBggrBgEFBQcCARYmaHR0cHM6Ly93d3cuZ2xvYmFsc2lnbi5j
b20vcmVwb3NpdG9yeS8wDQYJKoZIhvcNAQELBQADggEBAJmQyC1fQorUC2bbmANz
EdSIhlIoU4r7rd/9c446ZwTbw1MUcBQJfMPg+NccmBqixD7b6QDjynCy8SIwIVbb
0615XoFYC20UgDX1b10d65pHBf9ZjQCxQNqQmJYaumxtf4z1s4DfjGRzNpZ5eWl0
6r/4ngGPoJVpjemEuunl1Ig423g7mNA2eymw0lIYkN5SQwCuaifIFJ6GlazhgDEw
fpolu4usBCOmmQDo8dIm7A9+O4orkjgTHY+GzYZSR+Y0fFukAj6KYXwidlNalFMz
hriSqHKvoflShx8xpfywgVcvzfTO3PYkz6fiNJBonf6q8amaEsybwMbDqKWwIX7e
SPY=
-----END CERTIFICATE-----
"""


def _build_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=certifi.where())
    context.load_verify_locations(cadata=_GLOBALSIGN_RSA_OV_SSL_CA_2018)
    return context


_SSL_CONTEXT = _build_ssl_context()

# Station status/position changes rarely; the reading itself is fetched fresh
# on every call, since that is the actual "current condition" being asked
# for. Same shape as services/severe_weather.py's alert-feed cache.
_CACHE_TTL = timedelta(minutes=15)

# A rise/fall smaller than this over the trend window is noise (sensor
# jitter), not a real tide movement — verified against Gardenreach's own
# series, whose consecutive 1-minute readings jitter by up to ~0.02m.
_TREND_THRESHOLD_M = 0.03
_TREND_WINDOW_MINUTES = 30


class TideError(RuntimeError):
    """The INCOIS TEWS station list or reading feed could not be reached."""


@dataclass(frozen=True)
class _Station:
    code: str
    name: str
    latitude: float
    longitude: float
    reporting: bool


@dataclass
class _Entry:
    stations: list[_Station]
    stored_at: datetime


_cache: _Entry | None = None
_lock = threading.Lock()


def _cached() -> list[_Station] | None:
    with _lock:
        if _cache is None:
            return None
        if datetime.now(timezone.utc) - _cache.stored_at > _CACHE_TTL:
            return None
        return _cache.stations


def _store(stations: list[_Station]) -> None:
    global _cache
    with _lock:
        _cache = _Entry(stations=stations, stored_at=datetime.now(timezone.utc))


def _text(element: ElementTree.Element, tag: str) -> str | None:
    child = element.find(tag)
    return child.text.strip() if child is not None and child.text else None


async def _fetch_stations() -> list[_Station]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=_SSL_CONTEXT) as client:
            response = await client.get(_STATIONS_URL)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise TideError(f"The INCOIS tide-station list could not be reached: {exc}") from exc

    try:
        root = ElementTree.fromstring(response.text)
    except ElementTree.ParseError as exc:
        raise TideError("The INCOIS tide-station list was not valid XML") from exc

    stations: list[_Station] = []
    for element in root.findall("station"):
        try:
            stations.append(
                _Station(
                    code=_text(element, "statname") or "",
                    name=_text(element, "statrealName") or _text(element, "statname") or "",
                    latitude=float(_text(element, "latitude")),
                    longitude=float(_text(element, "longitude")),
                    reporting=element.get("status") == "Reporting",
                )
            )
        except (TypeError, ValueError):
            continue  # a malformed entry costs one station, not the whole feed
    if not stations:
        raise TideError("The INCOIS tide-station list returned no stations")
    return stations


async def _stations() -> list[_Station]:
    cached = _cached()
    if cached is not None:
        return cached
    stations = await _fetch_stations()
    _store(stations)
    return stations


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * 6371.0088 * asin(sqrt(a))


def _decode_timestamp(raw_ms: float) -> datetime:
    """See the module docstring: the series JSON's `x` field decodes (as a
    plain epoch-millisecond value) to a year exactly 1900 short of the real
    one, on every point checked. Replacing only the year field is the
    correct fix — adding a fixed millisecond offset would drift across the
    1900 years' worth of leap-year differences."""
    naive = datetime.fromtimestamp(raw_ms / 1000, tz=timezone.utc)
    return naive.replace(year=naive.year + 1900)


async def _fetch_series(station_name: str) -> list[tuple[datetime, float]]:
    url = _SERIES_URL.format(station=station_name.upper())
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, verify=_SSL_CONTEXT) as client:
            response = await client.get(url)
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as exc:
        raise TideError(f"The tide reading for {station_name} could not be reached: {exc}") from exc
    except ValueError as exc:
        raise TideError(f"The tide reading for {station_name} was not valid JSON") from exc

    if not body or not body[0].get("data"):
        return []
    return [(_decode_timestamp(x), float(v)) for x, v in body[0]["data"]]


def _trend(series: list[tuple[datetime, float]]) -> str:
    if len(series) < 2:
        return "unknown"
    latest_time, latest_value = series[-1]
    cutoff = latest_time - timedelta(minutes=_TREND_WINDOW_MINUTES)
    reference_value = next((v for t, v in reversed(series) if t <= cutoff), series[0][1])
    delta = latest_value - reference_value
    if abs(delta) < _TREND_THRESHOLD_M:
        return "steady"
    return "rising" if delta > 0 else "falling"


async def nearest_station(latitude: float, longitude: float, radius_km: float) -> dict[str, Any]:
    """The nearest INCOIS tide-gauge station's current sea level, within
    `radius_km` of a point.

    Prefers a `Reporting` station over a closer `Not Reporting` one; falls
    back to the nearest `Not Reporting` one (a real, useful answer — "the
    closest gauge exists but is currently down") rather than claiming no
    station exists at all. Only raises `TideError` for a genuine fetch
    failure — "nothing within radius" and "nearest station not reporting"
    are both ordinary `available: False` answers, not errors.
    """
    stations = await _stations()

    def within_radius(candidates: list[_Station]) -> tuple[_Station, float] | None:
        best: tuple[_Station, float] | None = None
        for station in candidates:
            distance = _haversine_km(latitude, longitude, station.latitude, station.longitude)
            if distance <= radius_km and (best is None or distance < best[1]):
                best = (station, distance)
        return best

    reporting = within_radius([s for s in stations if s.reporting])
    fallback = reporting or within_radius([s for s in stations if not s.reporting])

    if fallback is None:
        return {
            "available": False,
            "reason": f"No INCOIS tide-gauge station is within {radius_km:.0f} km of this point.",
        }

    station, distance_km = fallback
    if not station.reporting:
        return {
            "available": False,
            "reason": (
                f"The nearest tide-gauge station ({station.name}, "
                f"{distance_km:.0f} km away) is not currently reporting."
            ),
            "station": station.name,
            "distance_km": round(distance_km, 1),
        }

    series = await _fetch_series(station.name)
    if not series:
        return {
            "available": False,
            "reason": (
                f"{station.name} is listed as reporting but returned no readings "
                "just now — likely a feed gap rather than a station outage."
            ),
            "station": station.name,
            "distance_km": round(distance_km, 1),
        }

    last_time, last_value = series[-1]
    age_minutes = (datetime.now(timezone.utc) - last_time).total_seconds() / 60
    # A "Reporting" station is INCOIS's own status flag and lags reality —
    # Chennai measured live 2026-08-27 read "Reporting" while its own last
    # point was ~3.8 hours old. Flag staleness ourselves rather than trusting
    # the station list's word for it.
    stale = age_minutes > 60
    note = (
        "Measured real-time sea level from a coastal tide gauge (includes "
        "the astronomical tide plus storm surge and local wave setup), not "
        "a predicted tide table — INCOIS does not publish a keyless "
        "astronomical tide-prediction feed."
    )
    if stale:
        note += (
            f" This station is marked 'Reporting' but its latest reading is "
            f"{age_minutes / 60:.1f} hours old — likely a feed gap, treat "
            "with caution."
        )
    return {
        "available": True,
        "station": station.name,
        "station_code": station.code,
        "station_latitude": station.latitude,
        "station_longitude": station.longitude,
        "distance_km": round(distance_km, 1),
        "water_level_m": last_value,
        "trend": _trend(series),
        "last_reported": last_time.isoformat(),
        "minutes_since_last_reading": round(age_minutes, 1),
        "stale": stale,
        "source": "INCOIS Indian Tsunami Early Warning System, tide-gauge network",
        "note": note,
    }
