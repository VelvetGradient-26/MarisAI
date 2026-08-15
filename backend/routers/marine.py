from fastapi import APIRouter, HTTPException, Query

from services import (
    biodiversity,
    copernicus_currents,
    copernicus_sst,
    copernicus_wind,
    currents_depth,
    drift,
    stokes_drift,
)
from services.bathymetry import BathymetryError, get_elevation
from services.copernicus_currents import CopernicusCurrentsError
from services.currents_depth import CurrentsDepthError
from services.drift import DriftError
from services.stokes_drift import StokesDriftError
from services.copernicus_sst import CopernicusSstError
from services.copernicus_wind import CopernicusWindError
from services.openmeteo import OpenMeteoError, get_realtime_ocean_conditions

router = APIRouter(prefix="/api/ocean", tags=["ocean"])


@router.get("/realtime")
async def get_ocean_realtime(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    try:
        return await get_realtime_ocean_conditions(latitude=lat, longitude=lon)
    except OpenMeteoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/depth")
async def get_ocean_depth(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    try:
        return await get_elevation(latitude=lat, longitude=lon)
    except BathymetryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/sst/point")
async def get_sst_point(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    try:
        return copernicus_sst.get_point(lat, lon)
    except CopernicusSstError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/sst/meta")
async def get_sst_meta():
    try:
        return copernicus_sst.get_meta()
    except CopernicusSstError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/wind/point")
async def get_wind_point(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    try:
        return copernicus_wind.get_point(lat, lon)
    except CopernicusWindError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/wind/meta")
async def get_wind_meta():
    try:
        return copernicus_wind.get_meta()
    except CopernicusWindError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/currents/point")
async def get_currents_point(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    try:
        return copernicus_currents.get_point(lat, lon)
    except CopernicusCurrentsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/currents/meta")
async def get_currents_meta():
    try:
        return copernicus_currents.get_meta()
    except CopernicusCurrentsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/stokes/point")
async def get_stokes_point(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    try:
        return stokes_drift.get_point(lat, lon)
    except StokesDriftError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/stokes/meta")
async def get_stokes_meta():
    try:
        return stokes_drift.get_meta()
    except StokesDriftError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/biodiversity")
async def get_biodiversity(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_deg: float = Query(biodiversity.DEFAULT_RADIUS_DEG, gt=0, le=5),
    limit: int = Query(25, ge=1, le=100),
):
    """What OBIS has *recorded* near a point — survey effort, not abundance.

    502 rather than 503 on failure: this is a live upstream call, not a cache
    this server warms, so an outage is the provider's rather than ours.
    """
    try:
        return await biodiversity.at_point(lat, lon, radius_deg=radius_deg, limit=limit)
    except biodiversity.BiodiversityError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/drift/presets")
async def get_drift_presets():
    """The named drifting objects and their leeway coefficients.

    A separate endpoint rather than a constant in the client, because the
    coefficient is a modelling choice this codebase owns — a UI that hardcoded
    0.035 for a person in the water would keep asserting it after the value was
    revised here.
    """
    return {"presets": drift.presets(), "unit": drift.UNIT}


@router.get("/drift/point")
async def get_drift_point(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    alpha: float | None = Query(
        None, description="Leeway coefficient, 0-0.15. Ignored when `preset` is given."
    ),
    preset: str | None = Query(None, description="Leeway preset key from /drift/presets"),
):
    """Combined drift velocity — current + Stokes + leeway — with its terms."""
    try:
        resolved = drift.resolve_alpha(alpha, preset)
    except DriftError as exc:
        # A bad preset name or an out-of-range coefficient is the caller's to
        # fix, unlike a cold cache below.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        return drift.get_point(lat, lon, resolved)
    except DriftError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/drift/meta")
async def get_drift_meta(
    alpha: float | None = Query(None),
    preset: str | None = Query(None),
):
    try:
        resolved = drift.resolve_alpha(alpha, preset)
    except DriftError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        return drift.get_meta(resolved)
    except DriftError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/currents/depth/point")
async def get_currents_depth_point(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    depth_m: float = Query(..., ge=0.0, le=6000.0),
):
    try:
        return currents_depth.get_point(lat, lon, depth_m)
    except CurrentsDepthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/currents/depth/meta")
async def get_currents_depth_meta(depth_m: float = Query(..., ge=0.0, le=6000.0)):
    try:
        return currents_depth.get_meta(depth_m)
    except CurrentsDepthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
