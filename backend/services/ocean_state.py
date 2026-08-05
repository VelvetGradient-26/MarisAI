"""Global ocean-state snapshot — the numbers behind the dashboard's KPI row.

`copernicus_sst.py` and `copernicus_wind.py` already hold global grids, but
only for the two fields the map animates. This module covers the rest of what
the dashboard reports globally — surface currents, chlorophyll, salinity,
dissolved oxygen and wave height — on the same cached/scheduled pattern.

Two things shape the design:

  * **Statistics are computed in the fetch thread and the grid is thrown
    away.** A global 0.083deg field is 2041x4320 float64 (~70MB); holding
    several of them to re-derive a mean on request would cost hundreds of
    megabytes to serve a handful of numbers.
  * **Every mean is area-weighted by cos(latitude).** These are equal-angle
    grids, so an unweighted mean counts a polar cell as heavily as an
    equatorial one that covers eleven times the area.

Service choice and depth bounds follow the rules in CLAUDE.md: whole-globe
single-timestep access means `arco-geo-series`, and every request carries a
server-side depth bound so the 50-level products do not ship 49 unwanted
levels.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from services.download.providers.copernicus import (
    BGC_BIO_DATASET_ID,
    BGC_PFT_DATASET_ID,
    PHYSICS_DATASET_ID,
    WAVES_DATASET_ID,
)

SOURCE_LABEL = "Copernicus Marine Service"

# Surface-only. Without a server-side depth bound the 50-level products pull
# every level and effectively never finish (see CLAUDE.md).
#
# Only an upper bound is set, matching the downloader's DEPTH_SURFACE. A tight
# two-sided window around 0.494m makes the toolbox warn that the selection
# exceeds the dataset's depth coordinate, since surface-only products carry a
# single depth whose exact value differs between them.
_SURFACE_MAX = 1.0

# Matches the SST cache's cadence — these are the same analysis products and
# there is nothing newer to collect in between.
REFRESH_INTERVAL_HOURS = 3


class OceanStateError(RuntimeError):
    """Global ocean-state snapshot unavailable."""


@dataclass(frozen=True)
class FieldSpec:
    """One global field to summarise.

    `dataset_id` plus `variables` is what gets fetched; `reduce` turns the
    loaded arrays into the single field the dashboard shows, which is how
    current *speed* comes from the uo/vo pair without a separate dataset.
    """

    key: str
    dataset_id: str
    variables: tuple[str, ...]
    unit: str
    label: str
    reduce: Callable[[dict[str, np.ndarray]], np.ndarray]
    depth_bounded: bool = True
    # Fields where the extreme tail is itself the story (waves) report
    # percentiles; a mean wave height alone hides every dangerous sea.
    report_percentiles: bool = False


def _speed(arrays: dict[str, np.ndarray]) -> np.ndarray:
    return np.hypot(arrays["uo"], arrays["vo"])


def _single(name: str) -> Callable[[dict[str, np.ndarray]], np.ndarray]:
    return lambda arrays: arrays[name]


FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        key="current_speed",
        dataset_id=PHYSICS_DATASET_ID,
        variables=("uo", "vo"),
        unit="m/s",
        label="Surface Current Speed",
        reduce=_speed,
        report_percentiles=True,
    ),
    FieldSpec(
        key="sea_surface_salinity",
        dataset_id=PHYSICS_DATASET_ID,
        variables=("so",),
        unit="PSU",
        label="Sea Surface Salinity",
        reduce=_single("so"),
    ),
    FieldSpec(
        key="chlorophyll_a",
        dataset_id=BGC_PFT_DATASET_ID,
        variables=("chl",),
        unit="mg/m3",
        label="Chlorophyll-a",
        reduce=_single("chl"),
    ),
    FieldSpec(
        key="dissolved_oxygen",
        dataset_id=BGC_BIO_DATASET_ID,
        variables=("o2",),
        unit="mmol/m3",
        label="Dissolved Oxygen",
        reduce=_single("o2"),
    ),
    FieldSpec(
        key="wave_height",
        dataset_id=WAVES_DATASET_ID,
        variables=("VHM0",),
        unit="m",
        label="Significant Wave Height",
        reduce=_single("VHM0"),
        # The wave product has no depth dimension at all — passing a depth
        # bound to it is an error, not a no-op.
        depth_bounded=False,
        report_percentiles=True,
    ),
)


@dataclass
class _Snapshot:
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    fetched_at: datetime | None = None
    latency_ms: float = 0.0


_cache: _Snapshot | None = None
_refresh_lock = asyncio.Lock()


def _area_weighted_stats(
    values: np.ndarray, latitudes: np.ndarray, spec: FieldSpec
) -> dict[str, Any]:
    """Reduce a global grid to the handful of numbers the dashboard shows."""
    valid = np.isfinite(values)
    if not valid.any():
        raise OceanStateError(f"{spec.key}: grid holds no valid cells")

    weights = np.broadcast_to(
        np.cos(np.radians(latitudes))[:, None], values.shape
    )
    selected = values[valid]
    stats: dict[str, Any] = {
        "key": spec.key,
        "label": spec.label,
        "unit": spec.unit,
        "mean": round(float(np.average(selected, weights=weights[valid])), 4),
        "min": round(float(selected.min()), 4),
        "max": round(float(selected.max()), 4),
        "valid_cells": int(valid.sum()),
    }
    if spec.report_percentiles:
        p90, p99 = np.percentile(selected, [90, 99])
        stats["p90"] = round(float(p90), 4)
        stats["p99"] = round(float(p99), 4)
    return stats


def _load_field(spec: FieldSpec) -> dict[str, Any]:
    import copernicusmarine

    now = datetime.now(timezone.utc)
    kwargs: dict[str, Any] = {
        "dataset_id": spec.dataset_id,
        "variables": list(spec.variables),
        "username": settings.COPERNICUS_USERNAME,
        "password": settings.COPERNICUS_PASSWORD,
        # Whole globe at one instant — the geo-series chunking. Picking the
        # time-series service here turns ~15s into many minutes.
        "service": "arco-geo-series",
    }
    if spec.depth_bounded:
        kwargs["maximum_depth"] = _SURFACE_MAX

    dataset = copernicusmarine.open_dataset(**kwargs)

    # Never label a forecast step as "current" — same rule as copernicus_sst.
    past = dataset.sel(time=slice(None, now.replace(tzinfo=None)))
    if past.sizes.get("time", 0) == 0:
        raise OceanStateError(f"{spec.key}: no timestep at or before now")

    arrays: dict[str, np.ndarray] = {}
    timestamp: datetime | None = None
    for name in spec.variables:
        selected = past[name].isel(time=-1)
        if "depth" in selected.dims:
            selected = selected.isel(depth=0)
        loaded = selected.load()
        if timestamp is None:
            timestamp = datetime.fromisoformat(
                str(loaded.time.values)[:19]
            ).replace(tzinfo=timezone.utc)
        arrays[name] = loaded.values.astype(np.float64)
        latitudes = loaded.latitude.values.astype(np.float64)

    values = spec.reduce(arrays)
    stats = _area_weighted_stats(values, latitudes, spec)
    stats["timestamp"] = timestamp.isoformat() if timestamp else None
    stats["dataset_id"] = spec.dataset_id
    return stats


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=2, min=4, max=20))
def _load_field_with_retry(spec: FieldSpec) -> dict[str, Any]:
    return _load_field(spec)


def _load_all() -> _Snapshot:
    started = datetime.now(timezone.utc)
    snapshot = _Snapshot()

    for spec in FIELDS:
        try:
            snapshot.fields[spec.key] = _load_field_with_retry(spec)
        except Exception:  # noqa: BLE001 - one bad field must not lose the rest
            logger.opt(exception=True).warning(
                f"Ocean-state field {spec.key} failed to load; continuing"
            )

    if not snapshot.fields:
        raise OceanStateError("No ocean-state fields could be loaded")

    snapshot.fetched_at = datetime.now(timezone.utc)
    snapshot.latency_ms = (snapshot.fetched_at - started).total_seconds() * 1000
    return snapshot


async def refresh_cache() -> None:
    """Rebuild the snapshot, keeping the previous one on total failure.

    Partial success is kept: a snapshot missing chlorophyll is still worth
    serving, and the missing field simply reports as unavailable.
    """
    global _cache
    async with _refresh_lock:
        try:
            fresh = await asyncio.to_thread(_load_all)
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning(
                "Ocean-state refresh failed, keeping previous snapshot if any"
            )
            return

        _cache = fresh
        logger.info(f"Ocean-state snapshot refreshed: {len(fresh.fields)} fields")


def _require_cache() -> _Snapshot:
    if _cache is None:
        raise OceanStateError(
            "Global ocean state not yet available — initial fetch in progress or failed"
        )
    return _cache


def is_refreshing() -> bool:
    """Whether a refresh is in flight right now.

    Reuses the existing refresh lock rather than tracking a second flag: the
    lock is held for exactly the duration of a fetch, so it already is the
    answer. Lets the dashboard tell "still warming up" apart from "failed",
    which are very different things to show a user.
    """
    return _refresh_lock.locked()


def is_available() -> bool:
    return _cache is not None


def health() -> dict[str, Any]:
    if _cache is None or _cache.fetched_at is None:
        return {"connected": False, "latency_ms": None, "last_sync": None, "records": 0}
    return {
        "connected": True,
        "latency_ms": round(_cache.latency_ms),
        "last_sync": _cache.fetched_at.isoformat(),
        "records": len(_cache.fields),
    }


def get_field(key: str) -> dict[str, Any] | None:
    """One field's statistics, or None if that field failed to load."""
    if _cache is None:
        return None
    return _cache.fields.get(key)


def summary() -> dict[str, Any]:
    cache = _require_cache()
    return {
        "fields": cache.fields,
        "fetched_at": cache.fetched_at.isoformat() if cache.fetched_at else None,
        "source": SOURCE_LABEL,
    }
