from fastapi import APIRouter, HTTPException, Query

from services import (
    biodiversity,
    copernicus_currents,
    copernicus_sst,
    copernicus_wind,
    currents_depth,
    drift,
    eddies,
    eddy_tracking,
    edna,
    heatwaves,
    ocean_heat_content_field,
    upwelling,
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


@router.get("/eddies")
async def get_eddies(
    bbox: str | None = Query(
        None,
        description="Optional south,west,north,east. East < west crosses the antimeridian.",
    ),
    polarity: str | None = Query(None, description="cyclonic | anticyclonic"),
    min_radius_km: float | None = Query(None, gt=0),
    limit: int = Query(eddies.DEFAULT_LIMIT, ge=1, le=eddies.MAX_LIMIT),
):
    """Rotating features detected in the live surface-current field.

    503 rather than 502 on a cold detector: this reads a cache *this* server
    warms, so an unavailable answer is ours to explain, unlike the OBIS call
    above. A malformed bbox or polarity is the caller's, hence 422.
    """
    if polarity is not None and polarity not in ("cyclonic", "anticyclonic"):
        raise HTTPException(
            status_code=422,
            detail=f"unknown polarity {polarity!r}; expected 'cyclonic' or 'anticyclonic'",
        )

    parsed: tuple[float, float, float, float] | None = None
    if bbox is not None:
        try:
            south, west, north, east = (float(part) for part in bbox.split(","))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="bbox must be four comma-separated numbers: south,west,north,east",
            ) from exc
        if south > north:
            raise HTTPException(
                status_code=422, detail="bbox south must not be north of bbox north"
            )
        parsed = (south, west, north, east)

    try:
        return eddies.get_eddies(
            bbox=parsed,
            polarity=polarity,
            min_radius_km=min_radius_km,
            limit=limit,
        )
    except eddies.EddyError as exc:
        # Everything the caller could have got wrong was rejected above, so
        # anything reaching here is a cold or unusable currents cache.
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/eddies/tracks")
async def get_eddy_tracks(
    bbox: str | None = Query(
        None,
        description="Optional south,west,north,east. East < west crosses the antimeridian.",
    ),
    polarity: str | None = Query(None, description="cyclonic | anticyclonic"),
    min_age_hours: float | None = Query(None, ge=0),
    limit: int = Query(eddy_tracking.DEFAULT_LIMIT, ge=1, le=eddy_tracking.MAX_LIMIT),
):
    """Frame-to-frame identity over `/eddies`' own hourly detection passes.

    Unlike `/eddies`, this never 503s on its own: it reads state a scheduled
    job already computed rather than the live currents cache, so there is no
    per-request failure mode to report. `active_tracks: 0` is what a cold
    process (no scheduled refresh has run yet — state lives in this process
    and does not survive a restart) and a genuinely quiet ocean look like
    alike, and both are real, reportable answers rather than errors. 422 for
    a caller error (bad bbox/polarity), the same convention as `/eddies`.
    """
    if polarity is not None and polarity not in ("cyclonic", "anticyclonic"):
        raise HTTPException(
            status_code=422,
            detail=f"unknown polarity {polarity!r}; expected 'cyclonic' or 'anticyclonic'",
        )

    parsed: tuple[float, float, float, float] | None = None
    if bbox is not None:
        try:
            south, west, north, east = (float(part) for part in bbox.split(","))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="bbox must be four comma-separated numbers: south,west,north,east",
            ) from exc
        if south > north:
            raise HTTPException(
                status_code=422, detail="bbox south must not be north of bbox north"
            )
        parsed = (south, west, north, east)

    return eddy_tracking.get_tracks(
        bbox=parsed, polarity=polarity, min_age_hours=min_age_hours, limit=limit
    )


@router.get("/eddies/tracks/{track_id}")
async def get_eddy_track(track_id: str):
    """One track's full position history."""
    track = eddy_tracking.get_track(track_id)
    if track is None:
        raise HTTPException(status_code=404, detail=f"No such track: {track_id!r}")
    return track


@router.get("/heatwaves")
async def get_heatwaves():
    """Marine heatwaves in the current sea-surface temperature field.

    503, not 502: this reads a cache this server warms, over a climatology this
    project builds offline, so an unavailable answer is ours to explain — the
    same split as `/eddies` and the opposite of `/edna` below. The two reasons
    are different and the message says which: no climatology has been built
    (actionable — run the script), or the recent record is still loading.
    """
    try:
        return heatwaves.current_field().as_dict()
    except heatwaves.HeatwaveError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/heatwaves/cells")
async def get_heatwave_cells():
    """Cells currently in a marine heatwave, as drawable rectangles.

    Only cells with a category are sent: the output is sparse, and 40,000
    mostly-zero cells would be most of the payload for none of the picture. The
    coverage block rides along so the map can say how much ocean was examined —
    a blank layer here must not read as a failed load.
    """
    try:
        return heatwaves.cells()
    except heatwaves.HeatwaveError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/upwelling/cells")
async def get_upwelling_cells():
    """Coastal cells with a defined upwelling index, as drawable rectangles.

    Both signs are sent, not only the favourable ones: the sign is the
    measurement, and dropping the negatives would make "downwelling" and "not
    coastal" the same blank cell.
    """
    try:
        return upwelling.cells()
    except upwelling.UpwellingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/heatwaves/point")
async def get_heatwave_point(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    """Marine heatwave state at one coordinate.

    Answers for a point with no heatwave as readily as for one with — an absence
    is a result here, the same reason `/eddies` reports the distance to the
    nearest feature rather than omitting the row.
    """
    try:
        return heatwaves.at_point(lat, lon)
    except heatwaves.HeatwaveError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/upwelling")
async def get_upwelling():
    """Coastal upwelling favourability from Ekman transport.

    503 on a cold cache, like `/eddies` and `/heatwaves`: this reads the live
    wind and surface-current caches this server warms rather than fetching.
    """
    try:
        return upwelling.get_upwelling()
    except upwelling.UpwellingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/upwelling/point")
async def get_upwelling_point(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    """Upwelling favourability at one coordinate.

    Answers for open ocean too — "not coastal" is a result, and an omitted row
    reads as "no upwelling anywhere".
    """
    try:
        return upwelling.at_point(lat, lon)
    except upwelling.UpwellingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/ocean-heat-content/cells")
async def get_ocean_heat_content_cells(
    depth_m: float = Query(
        ocean_heat_content_field.OHC_LAYERS_M[-1],
        description="Which layer (50/100/200/700 m) to draw.",
    ),
):
    """One ocean-heat-content layer as drawable rectangles, over a regional
    grid built offline (`scripts/build_ocean_heat_content_grid.py`) — see
    `services/ocean_heat_content_field.py`'s own docstring for why this is
    regional rather than global and rebuilt on a schedule rather than fetched
    live.

    503 on a missing or unreadable grid file, the same class as `/eddies` and
    `/heatwaves`: this reads a build this project produces, not a live feed.
    """
    try:
        return ocean_heat_content_field.cells(depth_m)
    except ocean_heat_content_field.OceanHeatContentFieldError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/ocean-heat-content/point")
async def get_ocean_heat_content_point(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    """Every ocean-heat-content layer at one coordinate.

    Answers "outside this field's region" as a 200 with `available: false`,
    not an error — the region is a real, stated bound, not a failure.
    """
    try:
        return ocean_heat_content_field.at_point(lat, lon)
    except ocean_heat_content_field.OceanHeatContentFieldError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/edna/coverage")
async def get_edna_coverage(
    precision: int = Query(
        edna.DEFAULT_PRECISION,
        ge=edna.MIN_PRECISION,
        le=edna.MAX_PRECISION,
        description="OBIS grid precision; cell size is 360/2^(precision+5) degrees.",
    ),
    bbox: str | None = Query(None, description="Optional south,west,north,east."),
):
    """Where the ocean has been sampled for environmental DNA.

    502, not 503: this is a live OBIS call rather than a cache this server warms,
    so an outage belongs to the provider — the same split as `/biodiversity`
    above and the opposite of `/eddies`. A malformed bbox is the caller's, hence
    422, and it is rejected before the service is called.
    """
    parsed: tuple[float, float, float, float] | None = None
    if bbox is not None:
        try:
            south, west, north, east = (float(part) for part in bbox.split(","))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="bbox must be four comma-separated numbers: south,west,north,east",
            ) from exc
        if south > north:
            raise HTTPException(
                status_code=422, detail="bbox south must not be north of bbox north"
            )
        parsed = (south, west, north, east)

    try:
        return await edna.coverage(precision=precision, bbox=parsed)
    except edna.EdnaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/edna/point")
async def get_edna_point(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_deg: float = Query(0.5, gt=0, le=5.0),
    limit: int = Query(25, ge=1, le=100),
):
    """Molecular sampling near a point, beside the conventional record total."""
    try:
        return await edna.at_point(lat, lon, radius_deg=radius_deg, limit=limit)
    except edna.EdnaError as exc:
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
