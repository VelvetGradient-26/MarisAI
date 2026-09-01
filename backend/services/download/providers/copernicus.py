"""Copernicus Marine providers for the Universal Ocean Data Downloader.

Deliberately separate from `services/copernicus_sst.py` / `copernicus_wind.py`
— those are single-"latest"-snapshot in-memory caches tuned for map rendering
(`arco-geo-series`: huge spatial chunks, one timestep each — fine for "whole
globe right now", wrong tool for "one region over many days"). This feature's
access pattern is the opposite shape: a bounded area over an arbitrary date
range. For that, `arco-time-series` (fine spatial chunks, huge time chunks)
combined with server-side bbox/date filtering is what's actually fast —
benchmarked at ~8-10s for a several-degree bbox over a full month of hourly
data, vs. what would be many minutes through arco-geo-series for the same
request (one whole-globe fetch per timestep).

Reuses the *dataset IDs* from those modules (single source of truth) but
implements its own fetch functions rather than touching their cache-shaped,
already-delicately-tuned code.

Every dataset here is reached through one generic `fetch` — the per-dataset
differences (which fields, how the depth axis is handled) are data, held in
`catalog.py`, not branches. Coverage windows, grid spacing and native cadence
live there too; this module only knows how to *fetch*.
"""

from __future__ import annotations

import asyncio
from datetime import date

import xarray as xr
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from services.copernicus_sst import DATASET_ID as PHYSICS_DATASET_ID
from services.copernicus_wind import DATASET_ID as WIND_DATASET_ID

# --- Dataset IDs -----------------------------------------------------------
#
# PHYSICS_DATASET_ID / WIND_DATASET_ID are imported above from the modules
# that already own them. The rest have no map-rendering counterpart to borrow
# from, so they are defined here. Every one was verified by opening it and
# reading its real variable list, dims and time axis rather than trusting the
# product documentation — two of them contradicted what the docs implied.

# Global wave analysis/forecast (GLOBAL_ANALYSISFORECAST_WAV_001_027).
WAVES_DATASET_ID = "cmems_mod_glo_wav_anfc_0.083deg_PT3H-i"

# Daily-mean physics from the same product family as PHYSICS_DATASET_ID, but
# a *different* dataset: this is the only one carrying `tob`/`sob` (bottom
# temperature and salinity). The hourly PHYSICS_DATASET_ID has neither — it
# carries only so/thetao/uo/vo/zos on a singleton surface depth level.
PHYSICS_DAILY_DATASET_ID = "cmems_mod_glo_phy_anfc_0.083deg_P1D-m"

# Depth-resolved daily temperature and salinity (50 levels, 0.494m -> 5727.9m),
# split one variable per dataset upstream. These back the depth selector; the
# surface-only variables keep using the cheaper hourly dataset above.
THETAO_DEPTH_DATASET_ID = "cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m"
SO_DEPTH_DATASET_ID = "cmems_mod_glo_phy-so_anfc_0.083deg_P1D-m"

# Sea level anomaly (SEALEVEL_GLO_PHY_L4_NRT_008_046). The 0.25deg variant of
# this product is stale — its time axis stops in Nov 2024 — so this is the
# 0.125deg one, which is current.
SEALEVEL_DATASET_ID = "cmems_obs-sl_glo_phy-ssh_nrt_allsat-l4-duacs-0.125deg_P1D"

# Biogeochemistry (GLOBAL_ANALYSISFORECAST_BGC_001_028) is published as five
# separate datasets on a shared 0.25deg daily grid, split by theme. A request
# only ever opens the ones its variables actually need.
BGC_BIO_DATASET_ID = "cmems_mod_glo_bgc-bio_anfc_0.25deg_P1D-m"
BGC_NUT_DATASET_ID = "cmems_mod_glo_bgc-nut_anfc_0.25deg_P1D-m"
BGC_CAR_DATASET_ID = "cmems_mod_glo_bgc-car_anfc_0.25deg_P1D-m"
BGC_PFT_DATASET_ID = "cmems_mod_glo_bgc-pft_anfc_0.25deg_P1D-m"
BGC_OPTICS_DATASET_ID = "cmems_mod_glo_bgc-optics_anfc_0.25deg_P1D-m"


# --- Depth handling --------------------------------------------------------
#
# Three genuinely different situations, so an explicit mode per dataset rather
# than sniffing dims at runtime:
#
#   "none"    - no depth dim at all (waves, wind, sea level, the daily
#               bottom-field dataset). Nothing to do.
#   "surface" - a depth dim exists but only the surface is wanted. The hourly
#               physics dataset has a singleton 0.494m level, the BGC ones
#               carry all 50. Bounding *server-side* is not an optimisation
#               here, it is the difference between ~7s and a request that does
#               not finish: without it the toolbox pulls all 50 levels.
#   "select"  - the caller picked a depth; bound the server-side request to a
#               window around it, then take the nearest real level.
DEPTH_NONE = "none"
DEPTH_SURFACE = "surface"
DEPTH_SELECT = "select"

# Surface bound. The shallowest level across every depth-resolved dataset here
# is 0.494m, so a 0..1m window always contains exactly one level.
_SURFACE_MAX_DEPTH = 1.0


def _select_window(depth_m: float) -> tuple[float, float]:
    """Server-side depth bounds around a requested depth.

    The 50 levels are geometrically spaced (0.49, 1.54, 2.65 ... 5727.9), so a
    fixed-width window would be far too coarse near the surface and far too
    tight at depth. A proportional window with a small absolute floor tracks
    the spacing at every scale, and the `.sel(method="nearest")` afterwards is
    what actually picks the level — this only has to be wide enough to contain
    it.
    """
    return max(0.0, depth_m * 0.5 - 2.0), depth_m * 1.5 + 2.0


def _open(
    dataset_id: str,
    variables: list[str],
    west: float,
    south: float,
    east: float,
    north: float,
    start_date: date,
    end_date: date,
    depth_mode: str,
    depth_m: float | None,
) -> xr.Dataset:
    import copernicusmarine

    kwargs: dict[str, object] = {}
    if depth_mode == DEPTH_SURFACE:
        kwargs["minimum_depth"] = 0.0
        kwargs["maximum_depth"] = _SURFACE_MAX_DEPTH
    elif depth_mode == DEPTH_SELECT:
        minimum, maximum = _select_window(depth_m or 0.0)
        kwargs["minimum_depth"] = minimum
        kwargs["maximum_depth"] = maximum

    return copernicusmarine.open_dataset(
        dataset_id=dataset_id,
        variables=variables,
        username=settings.COPERNICUS_USERNAME,
        password=settings.COPERNICUS_PASSWORD,
        # Server-side bbox+date filtering via arco-time-series — see module
        # docstring for why this (not arco-geo-series) is the right service
        # for this feature's "bounded area, many timesteps" access pattern.
        service="arco-time-series",
        minimum_longitude=west,
        maximum_longitude=east,
        minimum_latitude=south,
        maximum_latitude=north,
        # Inclusive of the entire end_date, not just its midnight instant.
        start_datetime=f"{start_date.isoformat()}T00:00:00",
        end_datetime=f"{end_date.isoformat()}T23:59:59",
        **kwargs,
    )


def _resolve_depth(subset: xr.Dataset, depth_mode: str, depth_m: float | None) -> xr.Dataset:
    if "depth" not in subset.dims and "depth" not in subset.coords:
        return subset
    if depth_mode == DEPTH_SELECT and depth_m is not None:
        # The scalar `depth` coord is kept here — service.py reports the level
        # actually chosen, which is not the level asked for.
        return subset.sel(depth=depth_m, method="nearest")
    # Surface: the server-side bound already narrowed this to one level, so
    # index 0 is the surface. Kept as isel rather than a second sel so a
    # singleton depth dim (the hourly physics dataset) behaves identically.
    surface = subset.isel(depth=0) if "depth" in subset.dims else subset
    # Then drop the leftover scalar coord. Nominally the same surface level
    # everywhere, it is stored at slightly different precision per product
    # (0.494025 vs 0.49402538), and xr.merge treats a coord that disagrees in
    # the last decimal as a conflict — which made any physics + BGC request
    # fail outright. Nothing downstream wants a surface depth column anyway.
    return surface.drop_vars("depth", errors="ignore")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _fetch_sync(
    dataset_id: str,
    fields: list[str],
    west: float,
    south: float,
    east: float,
    north: float,
    start_date: date,
    end_date: date,
    depth_mode: str,
    depth_m: float | None,
) -> xr.Dataset:
    ds = _open(
        dataset_id, fields, west, south, east, north, start_date, end_date, depth_mode, depth_m
    )
    try:
        return _resolve_depth(ds[fields], depth_mode, depth_m).load()
    finally:
        # See the matching comment in services/copernicus_sst.py — never left
        # open by copernicusmarine.open_dataset() (called inside `_open`).
        ds.close()


async def fetch(
    *,
    dataset_id: str,
    fields: list[str],
    west: float,
    south: float,
    east: float,
    north: float,
    start_date: date,
    end_date: date,
    depth_mode: str = DEPTH_NONE,
    depth_m: float | None = None,
) -> xr.Dataset:
    """Fetch one Copernicus dataset over a bbox and date range.

    `copernicusmarine`/`xarray` are synchronous and release the GIL inside
    their network and decompression work, so this runs in a worker thread —
    which is also what lets service.py fetch every provider concurrently.
    """
    return await asyncio.to_thread(
        _fetch_sync,
        dataset_id,
        fields,
        west,
        south,
        east,
        north,
        start_date,
        end_date,
        depth_mode,
        depth_m,
    )


# --- Whole-globe, many-timesteps ------------------------------------------
#
# The third access pattern, and the one the module docstring above did not
# anticipate. `fetch` serves "bounded area, many timesteps" through
# arco-time-series; `services/copernicus_sst.py` serves "whole globe, one
# timestep" through arco-geo-series. The forecast grid needs "whole globe,
# ~45 timesteps", and arco-geo-series is the right service for it: one chunk
# read per timestep, versus arco-time-series' fine spatial chunks which would
# mean touching every spatial chunk on the planet.


def _coarsen(dataset: xr.Dataset, stride: int) -> xr.Dataset:
    """Thin the lat/lon axes *before* the data is materialised.

    This is a memory bound, not a speed one. arco-geo-series chunks are one
    whole-globe timestep each, so the bytes come off the wire either way — but
    a global 0.083deg float64 field is ~70MB per timestep per variable, and 45
    timesteps of two variables held at full resolution is over 6GB. Striding
    while the array is still lazy keeps the peak at roughly one chunk *per
    concurrent task* — see `_bounded_load` for why that qualifier matters.
    """
    if stride <= 1:
        return dataset
    return dataset.isel(
        latitude=slice(None, None, stride), longitude=slice(None, None, stride)
    )


# How many chunks may be in flight inside one `.load()`. Dask's threaded
# scheduler defaults to one worker per core, which on an 8-core machine means
# eight whole-globe timesteps decompressing at once — and `_fetch_global` is
# itself called concurrently for every provider a variable needs, so the true
# peak was 8 x chunk x providers, not the "roughly one chunk" `_coarsen`
# promises. Measured on an 8 GB machine: a single-variable grid build peaked at
# ~3.0 GB.
#
# Four is not a compromise between memory and speed, because this fetch is not
# CPU-bound: it is one HTTPS stream per chunk out of S3. The same build logged
# 18 "Connection pool is full, discarding connection" warnings against a pool of
# 10 — the extra threads were re-handshaking TLS on connections they had just
# discarded, so the parallelism past the pool size was costing time as well as
# memory.
#
# That pool size is botocore's default, and `copernicusmarine` builds its
# `botocore.config.Config` without `max_pool_connections`, so there is no
# env var or setting that raises it — only monkeypatching a vendored client
# would. Bounding the demand instead reaches the same place: four threads per
# provider stays under ten even with two providers in flight.
_GLOBAL_LOAD_THREADS = 4


def _bounded_load(dataset: xr.Dataset) -> xr.Dataset:
    """`.load()` with a bounded number of chunks in flight.

    Scoped with a context manager rather than set globally: dask's thread pool
    is process-wide, and the downloader's bbox fetches are small enough that
    throttling them too would be a pointless slowdown. Only whole-globe reads
    need the bound.
    """
    import dask

    with dask.config.set(
        scheduler="threads", num_workers=_GLOBAL_LOAD_THREADS, pool=None
    ):
        return dataset.load()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _fetch_global_sync(
    dataset_id: str,
    fields: list[str],
    start_date: date,
    end_date: date,
    depth_mode: str,
    stride: int,
) -> xr.Dataset:
    import copernicusmarine

    kwargs: dict[str, object] = {}
    if depth_mode in (DEPTH_SURFACE, DEPTH_SELECT):
        # Always the surface here. A depth-resolved forecast grid would be a
        # different product with a depth axis; nothing asks for one yet, and
        # bounding server-side is what keeps the 50-level datasets from
        # pulling every level (see the docstring on DEPTH_SURFACE).
        kwargs["minimum_depth"] = 0.0
        kwargs["maximum_depth"] = _SURFACE_MAX_DEPTH

    dataset = copernicusmarine.open_dataset(
        dataset_id=dataset_id,
        variables=fields,
        username=settings.COPERNICUS_USERNAME,
        password=settings.COPERNICUS_PASSWORD,
        service="arco-geo-series",
        start_datetime=f"{start_date.isoformat()}T00:00:00",
        end_datetime=f"{end_date.isoformat()}T23:59:59",
        **kwargs,
    )
    try:
        subset = _resolve_depth(dataset[fields], DEPTH_SURFACE, None)
        return _bounded_load(_coarsen(subset, stride))
    finally:
        # See the matching comment in services/copernicus_sst.py — never left open.
        dataset.close()


async def fetch_global(
    *,
    dataset_id: str,
    fields: list[str],
    start_date: date,
    end_date: date,
    depth_mode: str = DEPTH_NONE,
    stride: int = 1,
) -> xr.Dataset:
    """One Copernicus dataset over the whole globe for a date range.

    Deliberately not part of the `FetchFn` protocol: it takes no bbox, and
    `catalog.py`'s providers are all bbox-shaped because that is what the
    downloader needs. This is the forecast grid's entry point, reached through
    `catalog.copernicus_dataset()` so the dataset id still has one home.
    """
    return await asyncio.to_thread(
        _fetch_global_sync,
        dataset_id,
        fields,
        start_date,
        end_date,
        depth_mode,
        stride,
    )
