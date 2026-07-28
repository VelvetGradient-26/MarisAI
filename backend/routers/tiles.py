import asyncio

from fastapi import APIRouter, HTTPException, Response

from services import copernicus_sst, copernicus_wind
from services.copernicus_wind import CopernicusWindError
from services.gfw import GfwError, fetch_tile

router = APIRouter(prefix="/api/tiles", tags=["tiles"])


@router.get("/gfw/{dataset}/{z}/{x}/{y}.png")
async def get_gfw_tile(dataset: str, z: int, x: int, y: int):
    try:
        png_bytes = await fetch_tile(dataset, z, x, y)
    except GfwError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return Response(content=png_bytes, media_type="image/png")


@router.get("/sst/{z}/{x}/{y}.png")
async def get_sst_tile(z: int, x: int, y: int):
    # Never raises — an empty/transparent tile is returned if the cache isn't
    # populated yet or a render fails, so the map shows nothing there instead
    # of a broken-image icon (same approach as the GFW proxy above). Run in a
    # thread since rendering is CPU-bound numpy/scipy/Pillow work, not I/O.
    png_bytes = await asyncio.to_thread(copernicus_sst.render_tile_or_placeholder, z, x, y)
    return Response(content=png_bytes, media_type="image/png")


@router.get("/wind/field.png")
async def get_wind_field():
    # Unlike SST's tiles, there's no z/x/y here — the whole globe is one
    # texture the particle shader samples client-side, pre-rendered once per
    # cache refresh (see copernicus_wind.render_field_png / get_field_png).
    # No natural transparent-placeholder fallback for a single full-globe
    # texture, so an honest 503 beats faking one.
    try:
        png_bytes = await asyncio.to_thread(copernicus_wind.get_field_png)
    except CopernicusWindError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=png_bytes, media_type="image/png")
