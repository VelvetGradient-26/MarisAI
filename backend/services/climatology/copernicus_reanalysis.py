"""Copernicus GLORYS reanalysis (`cmems_mod_glo_phy_my_0.083deg_P1D-m`), the
baseline `sst_anomaly.py` names as the fix for scoring the live Copernicus
physics field against a mismatched climatology.

**A third access pattern, matching neither existing Copernicus fetch shape in
this codebase.** `services/download/providers/copernicus.py` uses
`arco-time-series` for "one bounded area, many timesteps"; `copernicus_sst.py`/
`copernicus_wind.py` use `arco-geo-series` for "whole globe, one latest
timestep". This is "whole globe, many timesteps" — the same shape
`forecasting/grid_history.py` uses for the forecast map's grid builder, and for
the same reason: `arco-geo-series`'s huge per-timestep spatial chunks are the
right ones to touch once per year of daily fields, where `arco-time-series`
would touch every one of its fine spatial chunks for a whole-globe request.

**Depth is server-side bounded to the surface, same trap as everywhere else
in this codebase that touches this dataset family.** The reanalysis carries
50 geometrically spaced levels (0.494 m to 5727.9 m); `machine_learning/`,
the download providers and the forecast grid builder all document the same
finding independently — without `minimum_depth`/`maximum_depth`, a request
pulls all 50 levels and does not finish in any reasonable time.

**Coarsened while the array is still lazy**, the same rule
`marine_ml`/`fusion.py` states for the same reason: a global daily field at
native 1/12 deg is large enough that resolving it before reducing it costs
memory and time this has no use for. `sea_surface_temperature`'s existing
OISST climatology (`scripts/build_climatology.py`) ships at 1 degree by
default for the same reason (94.6 MB/year at 1 deg against ~1.5 GB/year
native) — this module defaults to the same resolution so the two
climatologies stay comparably sized, not because 1 degree is otherwise
special.
"""

from __future__ import annotations

import asyncio
from datetime import date

import xarray as xr

from app.core.config import settings

DATASET_ID = "cmems_mod_glo_phy_my_0.083deg_P1D-m"
VARIABLE = "thetao"

# The dataset's own native spacing (probed live 2026-08-24 via
# `copernicusmarine.describe`): 1/12 deg, i.e. the same GLO12 grid the live
# `copernicus_sst.py`/`copernicus_wind.py` caches use — expected, since this
# reanalysis and that NRT analysis-forecast product share the same modelling
# system, which is the whole reason scoring one against the other should
# agree better than either does against OISST.
NATIVE_SPACING_DEG = 1.0 / 12.0

# Read off the dataset's own time coordinate (probed live 2026-08-24), not
# copied from the product page — the two disagree by dataset in this
# codebase often enough (`crw.py`, `oisst.py`) that only the value read off
# the object being fetched is trusted.
COVERAGE_START = date(1993, 1, 1)

# Surface bound. The shallowest of the 50 levels is 0.494 m.
_SURFACE_MAX_DEPTH_M = 1.0


class CopernicusReanalysisError(RuntimeError):
    """A GLORYS reanalysis request failed."""


def _open_lazy(start: date, end: date, variables: list[str] | None = None):
    import copernicusmarine

    return copernicusmarine.open_dataset(
        dataset_id=DATASET_ID,
        variables=variables or [VARIABLE],
        username=settings.COPERNICUS_USERNAME,
        password=settings.COPERNICUS_PASSWORD,
        service="arco-geo-series",
        minimum_depth=0.0,
        maximum_depth=_SURFACE_MAX_DEPTH_M,
        start_datetime=f"{start.isoformat()}T00:00:00",
        end_datetime=f"{end.isoformat()}T23:59:59",
    )


def _resolve_depth(dataset: xr.Dataset) -> xr.Dataset:
    if "depth" in dataset.dims:
        dataset = dataset.isel(depth=0, drop=True)
    elif "depth" in dataset.coords:
        dataset = dataset.drop_vars("depth")
    return dataset


def _coarsen(dataset: xr.Dataset, resolution_deg: float) -> xr.Dataset:
    """Block-average onto a coarser grid while the array is still lazy.

    `factor` rounds rather than requiring exact divisibility — the native
    spacing is 1/12 deg, so a 1 degree request is `factor=12` exactly, but a
    caller asking for, say, 0.9 deg should not hard-fail over a rounding
    artefact `MIN_RADIUS_KM`-style code elsewhere in this codebase treats as
    a real constraint, not a formatting nuisance.
    """
    factor = round(resolution_deg / NATIVE_SPACING_DEG)
    if factor <= 1:
        return dataset
    return dataset.coarsen(latitude=factor, longitude=factor, boundary="trim").mean()


def stride_for(resolution_deg: float) -> int:
    """Exposed for callers sizing a fetch (mirrors `oisst.stride_for`)."""
    factor = round(resolution_deg / NATIVE_SPACING_DEG)
    if factor < 1:
        raise CopernicusReanalysisError(
            f"resolution {resolution_deg} deg is finer than this dataset's "
            f"native {NATIVE_SPACING_DEG:.4f} deg grid"
        )
    return factor


def _fetch_sync(start: date, end: date, resolution_deg: float) -> xr.Dataset:
    try:
        opened = _open_lazy(start, end)
    except Exception as exc:  # noqa: BLE001 - copernicusmarine raises widely
        raise CopernicusReanalysisError(f"GLORYS reanalysis request failed: {exc}") from exc

    try:
        dataset = _resolve_depth(opened[[VARIABLE]])
        dataset = _coarsen(dataset, resolution_deg)
        loaded = dataset.load()
        if "time" not in loaded.sizes or int(loaded.sizes["time"]) == 0:
            raise CopernicusReanalysisError(
                f"GLORYS reanalysis returned no daily fields for "
                f"{start.isoformat()}..{end.isoformat()}"
            )
        return loaded
    finally:
        # See the matching comment in copernicus_sst.py — never left open.
        opened.close()


async def fetch_range(start: date, end: date, *, resolution_deg: float = 1.0) -> xr.Dataset:
    """One inclusive date range of global surface temperature, coarsened to
    `resolution_deg`.

    `copernicusmarine`/`xarray` are synchronous and release the GIL inside
    their network and decompression work, so this runs in a worker thread —
    the same reason `services/download/providers/copernicus.py::fetch` does.
    """
    return await asyncio.to_thread(_fetch_sync, start, end, resolution_deg)


CURRENT_VARIABLES = ["uo", "vo"]


def _fetch_currents_sync(day: date, resolution_deg: float) -> xr.Dataset:
    """`eastward_sea_water_velocity`/`northward_sea_water_velocity` for one
    day — for `scripts/compare_against_eddy_atlas.py`, which needs a
    historical current field `services/copernicus_currents.py`'s live-only
    cache cannot supply (the atlas's own coverage runs 1993-2023, long before
    that cache's NRT product starts). Same dataset as `fetch_range`, since
    the reanalysis carries `uo`/`vo` on the same grid as `thetao` — a second
    fetch of the same product, not a second integration.
    """
    try:
        opened = _open_lazy(day, day, CURRENT_VARIABLES)
    except Exception as exc:  # noqa: BLE001 - copernicusmarine raises widely
        raise CopernicusReanalysisError(f"GLORYS reanalysis request failed: {exc}") from exc

    try:
        dataset = _resolve_depth(opened[CURRENT_VARIABLES])
        dataset = _coarsen(dataset, resolution_deg)
        loaded = dataset.load()
        if "time" not in loaded.sizes or int(loaded.sizes["time"]) == 0:
            raise CopernicusReanalysisError(f"GLORYS reanalysis returned no currents for {day.isoformat()}")
        return loaded
    finally:
        # See the matching comment in copernicus_sst.py — never left open.
        opened.close()


async def fetch_currents_day(day: date, *, resolution_deg: float = 0.25) -> xr.Dataset:
    """One day's global surface currents, coarsened to `resolution_deg`.

    Defaults to 0.25 deg, not `fetch_range`'s 1 deg — `services/eddies.py`'s
    detector is tuned to the live currents cache's own resolution
    (`MIN_RADIUS_KM` etc.), and a coarser grid than that would make it
    resolve fewer, larger features than the same code sees in production,
    confounding a comparison meant to test the detector, not a deliberately
    degraded copy of it.
    """
    return await asyncio.to_thread(_fetch_currents_sync, day, resolution_deg)
