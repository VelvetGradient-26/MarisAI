"""Copernicus Marine ingestion for the Marine Data Fusion Layer.

Fetches the physical and biogeochemical ocean state for a region/date range
and caches it as NetCDF in the raw zone, so re-running the pipeline does not
re-download. Both problem statements pull from these two functions.

Two things here are load-bearing and were established empirically, not
assumed (see the module's timings below):

1. **Service choice.** The access pattern is "one bounded area, many
   timesteps", so every call goes through ``arco-time-series``. Copernicus's
   other service, ``arco-geo-series``, stores one timestep per huge lat/lon
   chunk and would fetch the whole globe once per day of the range — the
   difference is seconds vs. hours. The backend's downloader made the same
   call for the same reason (``backend/services/download/providers/copernicus.py``).

2. **Depth selection must happen server-side.** These reanalysis products
   carry 50 depth levels. ``open_dataset`` without a depth range returns all
   of them, and the surface layer is the only one used here — an otherwise
   identical request took 63s with the depth bound and did not complete in
   15 minutes without it. This is *not* the singleton-depth situation the
   backend's NRT products have, where ``isel(depth=0)`` after the fact is
   harmless; here it is the difference between working and hanging.

Measured on a 8x14 degree box, surface layer only:

===============  =========================  =================
product          30 days daily              1 year monthly
===============  =========================  =================
physics 1/12deg  ~63 s                      ~13 s (full 40x30 region)
bgc 1/4deg       ~15 s                      ~9 s  (full 40x30 region)
===============  =========================  =================

Which is why wide-region work uses the monthly products and daily work stays
in a bounded box.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal, Sequence

import xarray as xr

from marine_ml import config

Cadence = Literal["daily", "monthly"]


class CopernicusError(RuntimeError):
    """Raised when a Copernicus Marine fetch cannot be completed."""


# Daily and monthly editions of the same reanalysis. The monthly products are
# the same grid and variables, temporally averaged — so a pipeline written
# against one runs unchanged against the other.
_DATASET_IDS: dict[tuple[str, Cadence], str] = {
    ("physics", "daily"): config.PHYSICS_DATASET_ID,
    ("physics", "monthly"): "cmems_mod_glo_phy_my_0.083deg_P1M-m",
    ("bgc", "daily"): config.BGC_DATASET_ID,
    ("bgc", "monthly"): "cmems_mod_glo_bgc_my_0.25deg_P1M-m",
}

# Shallowest model level is ~0.494m (physics) / ~0.506m (bgc); asking for
# [0, 1] pins the request to that single surface level. Copernicus logs a
# benign warning that 0.0 is above the shallowest coordinate.
_SURFACE_MIN_DEPTH = 0.0
_SURFACE_MAX_DEPTH = 1.0

# L4 reprocessed scatterometer wind, hourly. Chosen over ERA5-via-CDS purely
# because it needs no second account — the Copernicus credentials already in
# backend/.env reach it — and because it serves **wind stress directly**
# (`eastward_stress`/`northward_stress`) rather than 10m winds that would
# then need a bulk-formula conversion with its own drag-coefficient
# assumptions. The NRT edition the backend map uses only reaches back to
# 2024-06; this multi-year edition covers the training period.
WIND_DATASET_ID = "cmems_obs-wind_glo_phy_my_l4_0.125deg_PT1H"
WIND_VARIABLES = (
    "eastward_stress",
    "northward_stress",
    "stress_curl",
    "eastward_wind",
    "northward_wind",
)


def _cache_path(
    product: str, cadence: Cadence, region: config.Region, start: date, end: date
) -> Path:
    name = (
        f"{product}_{cadence}_{region.name}_"
        f"{start.isoformat()}_{end.isoformat()}.nc"
    )
    return config.COPERNICUS_RAW_DIR / name


def _open(
    dataset_id: str,
    variables: Sequence[str],
    region: config.Region,
    start: date,
    end: date,
) -> xr.Dataset:
    import copernicusmarine

    username, password = config.copernicus_credentials()
    try:
        return copernicusmarine.open_dataset(
            dataset_id=dataset_id,
            variables=list(variables),
            username=username,
            password=password,
            service=config.COPERNICUS_SERVICE,
            minimum_longitude=region.west,
            maximum_longitude=region.east,
            minimum_latitude=region.south,
            maximum_latitude=region.north,
            start_datetime=f"{start.isoformat()}T00:00:00",
            # Inclusive of the whole end day, not just its midnight instant.
            end_datetime=f"{end.isoformat()}T23:59:59",
            minimum_depth=_SURFACE_MIN_DEPTH,
            maximum_depth=_SURFACE_MAX_DEPTH,
        )
    except Exception as exc:  # copernicusmarine raises a wide variety of types
        raise CopernicusError(
            f"could not open Copernicus dataset {dataset_id!r} for "
            f"{region.name} {start}..{end}: {exc}"
        ) from exc


def _fetch(
    product: str,
    variables: Sequence[str],
    cadence: Cadence,
    region: config.Region,
    start: date,
    end: date,
    refresh: bool,
) -> xr.Dataset:
    try:
        dataset_id = _DATASET_IDS[(product, cadence)]
    except KeyError:
        raise CopernicusError(
            f"no {product!r} dataset registered for cadence {cadence!r}"
        ) from None

    config.ensure_directories()
    cached = _cache_path(product, cadence, region, start, end)
    if cached.exists() and not refresh:
        return xr.open_dataset(cached)

    ds = _open(dataset_id, variables, region, start, end)
    # Drop the now-singleton depth dimension so downstream code sees clean
    # (time, latitude, longitude) fields.
    if "depth" in ds.dims:
        ds = ds.isel(depth=0, drop=True)

    try:
        ds = ds.load()
    except Exception as exc:
        raise CopernicusError(
            f"failed downloading {product} ({cadence}) for {region.name} "
            f"{start}..{end}: {exc}"
        ) from exc

    if ds.sizes.get("time", 0) == 0:
        raise CopernicusError(
            f"{product} ({cadence}) returned no timesteps for {start}..{end} — "
            "the range is probably outside this product's coverage."
        )

    # Record what produced this file. Section 5 of the approach doc asks for
    # traceable lineage: these products are periodically reprocessed, so the
    # dataset id alone is not enough to reproduce a training run.
    ds.attrs.update(
        marine_ml_dataset_id=dataset_id,
        marine_ml_cadence=cadence,
        marine_ml_region=region.name,
        marine_ml_bbox=f"{region.west},{region.south},{region.east},{region.north}",
        marine_ml_start=start.isoformat(),
        marine_ml_end=end.isoformat(),
    )
    ds.to_netcdf(cached)
    return ds


def fetch_physics(
    region: config.Region = config.DEFAULT_REGION,
    start: date = config.DEFAULT_START,
    end: date = config.DEFAULT_END,
    cadence: Cadence = "daily",
    variables: Sequence[str] = config.PHYSICS_VARIABLES,
    refresh: bool = False,
) -> xr.Dataset:
    """Surface temperature, salinity, currents, sea surface height and mixed
    layer depth over ``region``. Cached as NetCDF in the raw zone."""
    return _fetch("physics", variables, cadence, region, start, end, refresh)


def _month_starts(start: date, end: date) -> list[tuple[date, date]]:
    """Split a date range into calendar-month (start, end) pairs."""
    import calendar

    chunks: list[tuple[date, date]] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        last_day = calendar.monthrange(cursor.year, cursor.month)[1]
        chunk_start = max(cursor, start)
        chunk_end = min(date(cursor.year, cursor.month, last_day), end)
        chunks.append((chunk_start, chunk_end))
        cursor = date(
            cursor.year + (cursor.month // 12), (cursor.month % 12) + 1, 1
        )
    return chunks


def fetch_wind(
    region: config.Region = config.DEFAULT_REGION,
    start: date = config.DEFAULT_START,
    end: date = config.DEFAULT_END,
    variables: Sequence[str] = WIND_VARIABLES,
    refresh: bool = False,
) -> xr.Dataset:
    """Daily-mean surface wind stress and wind over ``region``.

    The source product is **hourly**, and that is the whole reason this
    function does not go through ``_fetch``. One month of five variables over
    a 10x17 degree box is ~324 MB in memory and takes ~70 s; the full two-year
    training window would be ~7.8 GB held at once, to produce ~160 MB of daily
    means. So it is fetched a calendar month at a time and averaged to daily
    *before* the next month is requested — peak memory stays at one month.

    Daily averaging also repairs coverage. The stress fields are
    scatterometer-derived and only ~61% populated at any given hour because
    of satellite swath gaps; averaging the day's passes fills most of that in.
    """
    config.ensure_directories()
    cached = config.COPERNICUS_RAW_DIR / (
        f"wind_daily_{region.name}_{start.isoformat()}_{end.isoformat()}.nc"
    )
    if cached.exists() and not refresh:
        return xr.open_dataset(cached)

    chunks = _month_starts(start, end)
    daily_chunks: list[xr.Dataset] = []

    for index, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        print(
            f"    wind chunk {index}/{len(chunks)}: {chunk_start}..{chunk_end}",
            flush=True,
        )
        hourly = _open(WIND_DATASET_ID, variables, region, chunk_start, chunk_end)
        try:
            # Mean over each day, skipping the swath-gap NaNs rather than
            # letting one missing hour void the whole day.
            daily_chunks.append(hourly.resample(time="1D").mean(skipna=True).load())
        except Exception as exc:
            raise CopernicusError(
                f"failed downloading wind for {region.name} "
                f"{chunk_start}..{chunk_end}: {exc}"
            ) from exc
        finally:
            hourly.close()

    if not daily_chunks:
        raise CopernicusError(f"wind returned no data for {start}..{end}")

    ds = xr.concat(daily_chunks, dim="time")
    ds.attrs.update(
        marine_ml_dataset_id=WIND_DATASET_ID,
        marine_ml_cadence="daily (resampled from hourly)",
        marine_ml_region=region.name,
        marine_ml_bbox=f"{region.west},{region.south},{region.east},{region.north}",
        marine_ml_start=start.isoformat(),
        marine_ml_end=end.isoformat(),
    )
    ds.to_netcdf(cached)
    return ds


def fetch_bgc(
    region: config.Region = config.DEFAULT_REGION,
    start: date = config.DEFAULT_START,
    end: date = config.DEFAULT_END,
    cadence: Cadence = "daily",
    variables: Sequence[str] = config.BGC_VARIABLES,
    refresh: bool = False,
) -> xr.Dataset:
    """Chlorophyll, nutrients, dissolved oxygen and primary production over
    ``region``. Cached as NetCDF in the raw zone.

    This is model-based biogeochemistry, not ocean colour, and that is a
    deliberate choice for the HAB problem: it is not cloud-limited, so it
    gives continuous daily coverage where satellite chlorophyll has gaps
    (approach doc 3.3, "missingness / cloud-cover audit"). Satellite ocean
    colour remains the higher-fidelity source when it is available.
    """
    return _fetch("bgc", variables, cadence, region, start, end, refresh)
