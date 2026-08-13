from fastapi import APIRouter, HTTPException, Query

from services import copernicus_currents, copernicus_sst, copernicus_wind
from services.bathymetry import BathymetryError, get_elevation
from services.copernicus_currents import CopernicusCurrentsError
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
