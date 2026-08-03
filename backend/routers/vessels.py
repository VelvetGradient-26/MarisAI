from fastapi import APIRouter, Query

from services import ais

router = APIRouter(prefix="/api/vessels", tags=["vessels"])

# Enough to fill a viewport densely without shipping a payload the browser
# has to thin out itself; `total_in_view` in the response says how many were
# actually there.
DEFAULT_LIMIT = 1500
MAX_LIMIT = 5000


@router.get("")
async def get_vessels(
    west: float = Query(..., ge=-180, le=180),
    south: float = Query(..., ge=-90, le=90),
    east: float = Query(..., ge=-180, le=180),
    north: float = Query(..., ge=-90, le=90),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
):
    """Vessels currently known inside the viewport, as GeoJSON.

    Reads an in-memory store fed by a background websocket, so there is no
    upstream call to fail here — an unconfigured or disconnected feed is an
    empty collection with `connected: false`, not an error. The client shows
    that state rather than an error toast.
    """
    return ais.vessels_in_bbox(west, south, east, north, limit)


@router.get("/status")
async def get_vessel_feed_status():
    return ais.status()
