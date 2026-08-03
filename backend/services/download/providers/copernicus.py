"""Copernicus Marine provider for the Universal Ocean Data Downloader.

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
"""

from __future__ import annotations

import asyncio
from datetime import date

import xarray as xr

# Real coverage confirmed empirically while planning this feature (see the
# Phase 1 plan) — used only for a fast, friendly preflight error message
# before ever calling Copernicus; the fetch itself remains the source of
# truth, so this drifting slightly stale over time just means a slower error
# (from the actual fetch returning no data) rather than a wrong one.
PHYSICS_COVERAGE_START = date(2022, 6, 1)
WIND_COVERAGE_START = date(2024, 6, 13)
# Confirmed the same way, by opening the dataset unfiltered and reading its
# actual time axis: it starts 2022-11-01T03:00 and runs ~10 days into the
# future (it is an analysis+forecast product).
WAVES_COVERAGE_START = date(2022, 11, 1)
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from services.copernicus_sst import DATASET_ID as PHYSICS_DATASET_ID
from services.copernicus_wind import DATASET_ID as WIND_DATASET_ID

# Global wave analysis/forecast (GLOBAL_ANALYSISFORECAST_WAV_001_027). Unlike
# the physics and wind dataset IDs there is no map-rendering module to borrow
# this from — no wave layer exists on the map — so it is defined here.
WAVES_DATASET_ID = "cmems_mod_glo_wav_anfc_0.083deg_PT3H-i"

# All variables the physics dataset carries (see the Phase 1 plan — the same
# dataset copernicus_sst.py uses for `thetao` also carries salinity, currents,
# and sea surface height). Only the subset actually requested gets fetched.
PHYSICS_FIELDS = ("so", "thetao", "uo", "vo", "zos")
WIND_FIELDS = ("eastward_wind", "northward_wind")

# The five wave fields the registry exposes, verified against the live
# dataset rather than assumed from the product docs. Two names are easy to
# get wrong: VCMX is crest-to-trough maximum wave height (what "maximum wave
# height" means), while the similarly-named VMXL is only the highest crest,
# roughly half the wave; and VMDR is a "from" direction, matching the wind
# convention rather than the currents' "toward" one.
WAVES_FIELDS = ("VHM0", "VCMX", "VTM02", "VTPK", "VMDR")


def _open_bbox_range(
    dataset_id: str,
    variables: list[str],
    west: float,
    south: float,
    east: float,
    north: float,
    start_date: date,
    end_date: date,
) -> xr.Dataset:
    import copernicusmarine

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
    )


def _drop_singleton_depth(subset: xr.Dataset) -> xr.Dataset:
    # thetao/so/uo/vo carry a singleton surface depth dim (~0.494m, same
    # dataset copernicus_sst.py already works around); zos has no depth dim
    # at all. isel is a no-op for variables that lack the dim.
    return subset.isel(depth=0) if "depth" in subset.dims else subset


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _fetch_physics_sync(
    west: float,
    south: float,
    east: float,
    north: float,
    start_date: date,
    end_date: date,
    fields: list[str],
) -> xr.Dataset:
    ds = _open_bbox_range(PHYSICS_DATASET_ID, fields, west, south, east, north, start_date, end_date)
    return _drop_singleton_depth(ds[fields]).load()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _fetch_wind_sync(
    west: float,
    south: float,
    east: float,
    north: float,
    start_date: date,
    end_date: date,
) -> xr.Dataset:
    fields = list(WIND_FIELDS)
    ds = _open_bbox_range(WIND_DATASET_ID, fields, west, south, east, north, start_date, end_date)
    return _drop_singleton_depth(ds[fields]).load()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _fetch_waves_sync(
    west: float,
    south: float,
    east: float,
    north: float,
    start_date: date,
    end_date: date,
    fields: list[str],
) -> xr.Dataset:
    ds = _open_bbox_range(WAVES_DATASET_ID, fields, west, south, east, north, start_date, end_date)
    # No depth dim on this product at all (confirmed against the live
    # dataset); _drop_singleton_depth is a no-op here, kept for symmetry with
    # the other two fetchers.
    return _drop_singleton_depth(ds[fields]).load()


async def fetch_physics(
    west: float,
    south: float,
    east: float,
    north: float,
    start_date: date,
    end_date: date,
    fields: list[str],
) -> xr.Dataset:
    return await asyncio.to_thread(
        _fetch_physics_sync, west, south, east, north, start_date, end_date, fields
    )


async def fetch_wind(
    west: float,
    south: float,
    east: float,
    north: float,
    start_date: date,
    end_date: date,
) -> xr.Dataset:
    return await asyncio.to_thread(_fetch_wind_sync, west, south, east, north, start_date, end_date)


async def fetch_waves(
    west: float,
    south: float,
    east: float,
    north: float,
    start_date: date,
    end_date: date,
    fields: list[str],
) -> xr.Dataset:
    return await asyncio.to_thread(
        _fetch_waves_sync, west, south, east, north, start_date, end_date, fields
    )
