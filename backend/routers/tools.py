"""REST surface for services that were previously reachable only from chat.

`services/pfz.py`, `geofencing.py`, `routing.py`, `cyclones.py` and
`severe_weather.py` already back chat tools (`services/chat/tools.py`) —
`services/chat/specialists.py` wires them into the agent's tool loop — but had
no HTTP route, and therefore no way for the map or any other page to render
their output directly. Thin routers, same convention as `routers/marine.py`:
validate here, call the service, map its own exception type to a real status
code, never leak a raw provider traceback.

Two of the five (`pfz`, `geofencing`) never raise at all — `find_zones` reads
two already-resident caches and reports `available: False` with a reason on a
cold one (the same `available`/`unavailable_reason` convention used
everywhere else in this codebase), and `geofencing.check` is pure local
geometry that touches no network. The other three (`routing`, `cyclones`,
`severe_weather`) depend on a live upstream fetch on every call — none of them
is a cache this server warms — so a failure there is mapped to 502, the same
split `routers/marine.py` already draws between `/biodiversity` (502, live
OBIS call) and `/eddies` (503, a cache this server warms).

`/search`, `/fetch-page` and `/literature` (sihtodo.md item 4) followed later
and are not chat-only tools becoming REST — they were built as REST and chat
tools together (`services/web_search.py`, `webpage.py`, `literature.py`), for
the same reason as everything above: a REST route makes a service directly
curl-able for testing and reuse without driving the whole chat loop.
`/fetch-page` is the one endpoint in this router whose failure can be a
caller error (a disallowed URL) rather than only an upstream one, so it alone
maps to 422 as well as 502 — see its own docstring.

`/tide` (sihtodo.md item 6) is the same "REST and chat tool together" shape,
over `services/tides.py` — see that module's docstring for the live-browser
investigation that found INCOIS's tide-gauge feed, the timestamp-decoding
quirk in its response, and the TLS workaround needed to reach it from Python.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from services import geofencing, pfz
from services.cyclones import CycloneError, get_active_cyclones
from services.cyclones import check_point as cyclone_check_point
from services.literature import LiteratureError
from services.literature import search_literature as run_literature_search
from services.marine_risk import assess as assess_marine_risk
from services.routing import RoutingError, plan_route
from services.severe_weather import SevereWeatherError
from services.severe_weather import check_point as severe_weather_check_point
from services.severe_weather import get_active_alerts as get_severe_weather_alerts
from services.tides import TideError
from services.tides import nearest_station as get_nearest_tide_station
from services.web_search import WebSearchError
from services.web_search import search as run_web_search
from services.webpage import WebpageError
from services.webpage import fetch as fetch_webpage_content

router = APIRouter(prefix="/api/ocean", tags=["ocean-tools"])


@router.get("/pfz")
async def get_pfz(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(100.0, ge=10, le=300),
):
    """Heuristic potential-fishing-zone screening near a point.

    Never raises: `find_zones` reads two already-resident, server-warmed
    caches (SST, chlorophyll) and reports `available: False` with a reason
    when either is cold, rather than raising — there is no exception type to
    catch here.
    """
    return pfz.find_zones(lat, lon, radius_km)


@router.get("/geofence")
async def get_geofence(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    """India EEZ / India-Sri Lanka IMBL / Marine Protected Area proximity for a point.

    Never raises: pure local geometry over an in-code registry, no network
    touched at all — see `services/geofencing.py`'s own docstring.
    """
    return geofencing.check(lat, lon)


@router.get("/route")
async def get_route(
    start_lat: float = Query(..., ge=-90, le=90),
    start_lon: float = Query(..., ge=-180, le=180),
    end_lat: float = Query(..., ge=-90, le=90),
    end_lon: float = Query(..., ge=-180, le=180),
):
    """Hazard-aware A* route between two points, over a live grid.

    502, not 503: every call fetches live GEBCO bathymetry and Open-Meteo
    wave/wind data — this is not a cache this server warms — so a failure
    (including "no path could be found within the search area") is the live
    fetch/search's to explain, the same split `/biodiversity` draws in
    `routers/marine.py`.
    """
    try:
        return await plan_route(start_lat, start_lon, end_lat, end_lon)
    except RoutingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/cyclones")
async def get_cyclones():
    """Every tropical cyclone GDACS currently reports as active, worldwide."""
    try:
        return await get_active_cyclones()
    except CycloneError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/cyclones/point")
async def get_cyclones_point(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(500.0, ge=50, le=2000),
):
    """Nearest currently-active cyclone to a point, and a coarse watch-radius flag."""
    try:
        return await cyclone_check_point(lat, lon, radius_km)
    except CycloneError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/severe-weather")
async def get_severe_weather():
    """Every IMD severe-weather alert currently within its validity window, nationwide."""
    try:
        return await get_severe_weather_alerts()
    except SevereWeatherError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/severe-weather/point")
async def get_severe_weather_point(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    """IMD severe-weather alerts whose warned area covers one point."""
    try:
        return await severe_weather_check_point(lat, lon)
    except SevereWeatherError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/risk")
async def get_marine_risk(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    """Deterministic 'is it safe to venture out' verdict for a point.

    Never raises: `assess_marine_risk` isolates each of its four live checks
    (sea conditions, severe weather, cyclones, geofencing) and degrades a
    failed one into `could_not_verify` rather than failing the whole call —
    see `services/marine_risk.py`.
    """
    return await assess_marine_risk(lat, lon)


@router.get("/search")
async def get_web_search(
    q: str = Query(..., min_length=1, description="Search query."),
    max_results: int = Query(5, ge=1, le=10),
):
    """General web search (sihtodo.md item 4), via Tavily.

    502 covers both a live-fetch failure and a missing `TAVILY_API_KEY` —
    see `services/web_search.py`'s own docstring on why no keyless general
    web search API exists to fall back to.
    """
    try:
        return await run_web_search(q, max_results)
    except WebSearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/fetch-page")
async def get_fetch_page(url: str = Query(..., min_length=1, description="A public http(s) URL.")):
    """Fetch one webpage and return its title and readable text.

    422, not 502, for a disallowed URL (bad scheme, unresolvable host, or one
    that resolves to a non-public address) — that is a caller error the same
    way a malformed bbox is elsewhere in this router, not an upstream
    failure. A genuine fetch failure (timeout, 4xx/5xx from the target site)
    is 502. See `services/webpage.py`'s docstring for the SSRF guard this
    endpoint depends on.
    """
    try:
        return await fetch_webpage_content(url)
    except WebpageError as exc:
        message = str(exc)
        if "Only http/https" in message or "non-public address" in message or "no host" in message:
            raise HTTPException(status_code=422, detail=message) from exc
        raise HTTPException(status_code=502, detail=message) from exc


@router.get("/tide")
async def get_tide(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(200.0, ge=10, le=500),
):
    """Current sea level at the nearest INCOIS tide-gauge station (sihtodo.md
    item 6), within `radius_km` of a point.

    502 for a genuine feed failure (the station list or a station's own
    reading feed could not be reached); a 200 with `available: false` for
    "nothing within radius" or "nearest station not reporting" — those are
    ordinary answers, not errors, the same split `/pfz` draws.
    """
    try:
        return await get_nearest_tide_station(lat, lon, radius_km)
    except TideError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/literature")
async def get_literature_search(
    q: str = Query(..., min_length=1, description="Topic, species, or research question."),
    max_results: int = Query(5, ge=1, le=10),
):
    """Published scientific literature search (sihtodo.md item 4), via CrossRef.

    502: CrossRef is a live upstream call on every request, the same class
    as `/cyclones` and `/severe-weather` above — no key required, but not a
    cache this server warms either.
    """
    try:
        return await run_literature_search(q, max_results)
    except LiteratureError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
