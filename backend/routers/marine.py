from fastapi import APIRouter, HTTPException, Query

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
