import asyncio

from fastapi import APIRouter, HTTPException, Response

from fastapi import Query

from services import (
    copernicus_currents,
    copernicus_sst,
    copernicus_wind,
    currents_depth,
    drift,
    stokes_drift,
)
from services.copernicus_currents import CopernicusCurrentsError
from services.currents_depth import CurrentsDepthError
from services.drift import DriftError
from services.stokes_drift import StokesDriftError
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


@router.get("/currents/field.png")
async def get_currents_field():
    # Same shape as the wind field above, and for the same reasons: one
    # whole-globe texture the particle shader samples client-side, rendered
    # once per cache refresh, with an honest 503 rather than a faked
    # placeholder when no cache has been populated yet.
    try:
        png_bytes = await asyncio.to_thread(copernicus_currents.get_field_png)
    except CopernicusCurrentsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=png_bytes, media_type="image/png")


@router.get("/stokes/field.png")
async def get_stokes_field():
    """Wave-induced transport, as a texture for the same particle engine.

    Separate from the currents field rather than summed into it: what carries a
    drifting object is the sum, but a layer that only ever showed the sum could
    not answer which of the two put it there — and in the trade-wind belts they
    routinely disagree in direction.
    """
    try:
        png_bytes = await asyncio.to_thread(stokes_drift.get_field_png)
    except StokesDriftError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=png_bytes, media_type="image/png")


@router.get("/drift/field.png")
async def get_drift_field(
    alpha: float | None = Query(None, ge=0.0, le=0.15),
    preset: str | None = Query(None),
):
    """The combined drift field — current + Stokes + leeway — as one texture.

    Parameterised on the leeway coefficient because that coefficient is a
    property of the drifting object rather than of the ocean, so there is no
    single correct field to serve. Encoding is per-alpha and cached; the two
    water terms are composed once per refresh and reused across every alpha.
    """
    try:
        resolved = drift.resolve_alpha(alpha, preset)
    except DriftError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        png_bytes = await asyncio.to_thread(drift.get_field_png, resolved)
    except DriftError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=png_bytes, media_type="image/png")


@router.get("/currents/depth/catalog")
async def get_currents_depth_catalog():
    """Which depth levels can be drawn right now, and why not where they cannot."""
    return {"levels": currents_depth.catalog()}


@router.get("/currents/depth/field.png")
async def get_currents_depth_field(depth_m: float = Query(..., ge=0.0, le=6000.0)):
    """One depth level of the daily currents product.

    A 503 rather than a placeholder when the level is still warming: each depth
    is an independent whole-globe fetch, and an empty texture animates nothing
    while looking exactly like one that is still loading.
    """
    try:
        png_bytes = await asyncio.to_thread(currents_depth.get_field_png, depth_m)
    except CurrentsDepthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=png_bytes, media_type="image/png")
