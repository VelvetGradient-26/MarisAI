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
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from services import geofencing, pfz
from services.cyclones import CycloneError
from services.cyclones import check_point as cyclone_check_point
from services.cyclones import get_active_cyclones
from services.routing import RoutingError, plan_route
from services.severe_weather import SevereWeatherError
from services.severe_weather import check_point as severe_weather_check_point
from services.severe_weather import get_active_alerts as get_severe_weather_alerts

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
