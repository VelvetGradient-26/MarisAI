"""NOAA Coral Reef Watch — bleaching heat stress and SST anomaly.

Three dashboard widgets need a *climatological baseline*, which no other
integration here carries: coral bleaching risk, marine-heatwave extent, and
"how far from normal is the ocean today". CRW publishes all of them on one
daily global 0.05deg grid, already differenced against a 1985-2012 baseline,
so the baseline is NOAA's rather than something estimated here.

Variables used:
  CRW_DHW         Degree Heating Weeks — accumulated heat stress (C-weeks).
  CRW_SSTANOMALY  SST minus the daily climatology (C).
  CRW_HOTSPOT     SST above the *maximum monthly mean* climatology (C).
  CRW_BAA         Bleaching Alert Area — NOAA's own 0-4 stress category.
  CRW_SEAICE      Sea-ice fraction, used to mask polar cells.

Two properties of this grid were established empirically and drive the
masking below; both quietly wreck any global statistic taken without them:

  * Ice-margin cells poleward of 60deg carry enormous apparent anomalies
    (a +17C cell in the Gulf of Ob) because the climatology there expects
    ice and the summer retreat leaves open water. They are real numbers
    about ice, not about ocean warming, so every aggregate here is taken
    over 60S-60N.
  * A handful of cells fall outside NOAA's own published valid range
    (|anomaly| <= 15C), so `valid_min`/`valid_max` are enforced rather than
    trusted.

Served through ERDDAP's griddap, subset server-side and strided down before
transfer: the native grid is 3600x7200 (~26M cells) and the dashboard needs
global structure, not 5km detail.

No credentials — the dataset is public. ERDDAP answers with a 302 first, so
redirects must be followed.
"""

from __future__ import annotations

import asyncio
import io
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
import numpy as np
import pandas as pd
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

ERDDAP_URL = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/NOAA_DHW.csv"

SOURCE_LABEL = "NOAA Coral Reef Watch (CoralTemp v3.1)"
SOURCE_URL = "https://coralreefwatch.noaa.gov/"
CITATION = (
    "NOAA Coral Reef Watch Daily Global 5km Satellite Coral Bleaching Heat Stress "
    "Monitoring Product Suite Version 3.1, NOAA/NESDIS/STAR."
)

# Native grid dimensions, needed to express the stride as index ranges.
_LAT_CELLS = 3600
_LON_CELLS = 7200

# Every 20th cell -> a 180x360 (1 degree) global field. Fine enough to resolve
# heatwave structure and coastal reef provinces, ~1.4MB and ~20s over the
# wire; the native grid is ~26M cells and would be neither.
_STRIDE = 20

_TIMEOUT = httpx.Timeout(180.0)

# CRW is a daily product published with roughly a one-to-two day lag, so
# anything more frequent than this re-fetches an identical grid.
REFRESH_INTERVAL_HOURS = 6

_VARIABLES = ("CRW_DHW", "CRW_SSTANOMALY", "CRW_HOTSPOT", "CRW_BAA", "CRW_SEAICE")

# NOAA's published valid range for the temperature fields. Enforced, not
# assumed: the live grid does carry a few cells outside it.
_ANOMALY_VALID_ABS = 15.0

# Aggregates are taken over this band only — see the module docstring on
# polar ice-margin artifacts.
ANALYSIS_LAT_LIMIT = 60.0

# Bleaching statistics are restricted harder still, to the latitudes where
# reef-building corals actually occur. CRW computes DHW on every water pixel
# it has, including enclosed brackish basins where the quantity is
# meaningless: the raw global maximum came from the St. Lawrence estuary, the
# Caspian and the Gulf of Finland at 40-53 C-weeks, which is both non-physical
# for reefs and nowhere near a coral. This is a latitude proxy for reef
# distribution, not a true reef-pixel mask, and is reported as such.
CORAL_LAT_LIMIT = 30.0

# NOAA's Bleaching Alert Area categories, as published.
BAA_LABELS = {
    0: "No Stress",
    1: "Bleaching Watch",
    2: "Bleaching Warning",
    3: "Alert Level 1",
    4: "Alert Level 2",
}

# DHW is the standard measure of accumulated stress: 4 C-weeks is where
# significant bleaching becomes likely and 8 is where mortality does. These
# are NOAA's published thresholds, not tuned here.
DHW_BLEACHING_LIKELY = 4.0
DHW_MORTALITY_LIKELY = 8.0

# What this module calls a heat-stress cell: HotSpot >= 1C, i.e. water at
# least a degree above the warmest month it normally reaches. This is NOAA's
# own criterion for accumulating DHW, so it is a published threshold rather
# than one invented here.
#
# It replaced a raw "anomaly >= 1C" test that flagged 42% of the ocean and
# said nothing; HotSpot >= 1C flags ~13% of 60S-60N and correctly reports
# zero across the winter Southern Ocean.
#
# This is still NOT the formal Hobday et al. marine-heatwave definition
# (90th-percentile climatology sustained five days), which needs a full
# distribution CRW does not publish. Responses state the criterion they used.
HOTSPOT_STRESS_C = 1.0

# A heat-stress patch must cover at least this many grid cells to be counted
# as a region. On the 1deg working grid that is roughly 100,000 km2 — enough
# to exclude single-cell speckle without discarding real features.
_MIN_REGION_CELLS = 8

# Ice-covered cells have an SST anomaly that is real but not meaningful as
# "ocean warming" for a dashboard headline, so they are excluded.
_SEAICE_MASK_FRACTION = 0.15


class CrwError(RuntimeError):
    """Coral Reef Watch fetch or parse failed."""


@dataclass
class _CrwCache:
    latitudes: np.ndarray          # (nlat,)
    longitudes: np.ndarray         # (nlon,)
    dhw: np.ndarray                # (nlat, nlon)
    anomaly: np.ndarray            # (nlat, nlon)
    hotspot: np.ndarray            # (nlat, nlon)
    baa: np.ndarray                # (nlat, nlon)
    seaice: np.ndarray             # (nlat, nlon)
    timestamp: datetime
    fetched_at: datetime
    latency_ms: float


_cache: _CrwCache | None = None
_refresh_lock = asyncio.Lock()


def _build_query() -> str:
    span = f"[last][0:{_STRIDE}:{_LAT_CELLS - 1}][0:{_STRIDE}:{_LON_CELLS - 1}]"
    return ",".join(f"{variable}{span}" for variable in _VARIABLES)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
def _request_csv() -> tuple[str, float]:
    started = datetime.now(timezone.utc)
    # griddap's selector is not a normal query parameter (it carries no `=`),
    # so it is appended to the URL rather than passed via `params`.
    url = f"{ERDDAP_URL}?{_build_query()}"
    # follow_redirects is required: ERDDAP answers griddap requests with a 302
    # to the generated file, and without it the body comes back empty.
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        text = response.text
    latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
    return text, latency_ms


def _parse(text: str, latency_ms: float) -> _CrwCache:
    # Row 0 is the column names, row 1 the units — skip the units row only.
    frame = pd.read_csv(io.StringIO(text), skiprows=[1])
    if frame.empty:
        raise CrwError("Coral Reef Watch returned an empty grid")

    for column in ("time", "latitude", "longitude", *_VARIABLES):
        if column not in frame.columns:
            raise CrwError(f"Coral Reef Watch response missing column {column!r}")

    timestamp = datetime.fromisoformat(str(frame["time"].iloc[0]).replace("Z", "+00:00"))

    latitudes = np.sort(frame["latitude"].unique().astype(np.float64))
    longitudes = np.sort(frame["longitude"].unique().astype(np.float64))

    pivoted = {}
    for variable in _VARIABLES:
        table = frame.pivot_table(
            index="latitude", columns="longitude", values=variable, dropna=False
        )
        # .copy() because a reindexed pivot hands back a read-only view, and
        # the valid-range masking below writes into these arrays.
        pivoted[variable] = (
            table.reindex(index=latitudes, columns=longitudes)
            .to_numpy(dtype=np.float64)
            .copy()
        )

    # Enforce NOAA's own valid range rather than trusting it — out-of-range
    # cells do occur and would otherwise dominate every extreme statistic.
    anomaly = pivoted["CRW_SSTANOMALY"]
    hotspot = pivoted["CRW_HOTSPOT"]
    anomaly[np.abs(anomaly) > _ANOMALY_VALID_ABS] = np.nan
    hotspot[np.abs(hotspot) > _ANOMALY_VALID_ABS] = np.nan

    return _CrwCache(
        latitudes=latitudes,
        longitudes=longitudes,
        dhw=pivoted["CRW_DHW"],
        anomaly=anomaly,
        hotspot=hotspot,
        baa=pivoted["CRW_BAA"],
        seaice=pivoted["CRW_SEAICE"],
        timestamp=timestamp,
        fetched_at=datetime.now(timezone.utc),
        latency_ms=latency_ms,
    )


def _load() -> _CrwCache:
    text, latency_ms = _request_csv()
    return _parse(text, latency_ms)


async def refresh_cache() -> None:
    """Replace the cache, keeping the previous grid on any failure."""
    global _cache
    async with _refresh_lock:
        try:
            fresh = await asyncio.to_thread(_load)
        except Exception:  # noqa: BLE001 - stale heat-stress data beats none
            logger.opt(exception=True).warning("CRW refresh failed, keeping previous cache if any")
            return

        _cache = fresh
        logger.info(f"CRW cache refreshed: timestep {fresh.timestamp.isoformat()}")


def _require_cache() -> _CrwCache:
    if _cache is None:
        raise CrwError(
            "Coral Reef Watch data not yet available — initial fetch in progress or failed"
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
    if _cache is None:
        return {"connected": False, "latency_ms": None, "last_sync": None, "records": 0}
    return {
        "connected": True,
        "latency_ms": round(_cache.latency_ms),
        "last_sync": _cache.fetched_at.isoformat(),
        "records": int(np.isfinite(_cache.anomaly).sum()),
    }


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _area_weights(latitudes: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """cos(lat) weights — equal-angle cells shrink toward the poles, so an
    unweighted mean would over-count polar water several-fold."""
    weights = np.cos(np.radians(latitudes))
    return np.broadcast_to(weights[:, None], shape)


def _ocean_mask(cache: _CrwCache) -> np.ndarray:
    """Finite, ice-free, non-polar cells. Land is NaN in every CRW variable.

    The latitude bound is the important part: without it the polar
    ice-margin cells described in the module docstring set every extreme
    and roughly triple the global mean anomaly.
    """
    mask = np.isfinite(cache.anomaly)
    # SEAICE is NaN wherever ice is absent, so NaN means "no ice", not
    # "unknown" — filling with 0 is correct here.
    ice = np.nan_to_num(cache.seaice, nan=0.0)
    latitudes = np.broadcast_to(cache.latitudes[:, None], cache.anomaly.shape)
    within_band = np.abs(latitudes) <= ANALYSIS_LAT_LIMIT
    return mask & (ice < _SEAICE_MASK_FRACTION) & within_band


def _reef_mask(cache: _CrwCache) -> np.ndarray:
    """Ocean cells at reef-building latitudes, where DHW means something."""
    latitudes = np.broadcast_to(cache.latitudes[:, None], cache.dhw.shape)
    return (
        _ocean_mask(cache)
        & np.isfinite(cache.dhw)
        & (np.abs(latitudes) <= CORAL_LAT_LIMIT)
    )


def sst_anomaly_summary() -> dict[str, Any]:
    """Area-weighted global mean SST anomaly against NOAA's climatology."""
    cache = _require_cache()
    mask = _ocean_mask(cache)
    if not mask.any():
        raise CrwError("No valid ocean cells in the Coral Reef Watch grid")

    weights = _area_weights(cache.latitudes, cache.anomaly.shape)[mask]
    values = cache.anomaly[mask]
    mean = float(np.average(values, weights=weights))

    return {
        "mean_anomaly_c": round(mean, 3),
        "baseline": "1985-2012 daily climatology (NOAA CoralTemp)",
        "coverage": f"{ANALYSIS_LAT_LIMIT:.0f}S-{ANALYSIS_LAT_LIMIT:.0f}N, ice-free ocean",
        "observed_at": cache.timestamp.isoformat(),
        "source": SOURCE_LABEL,
    }


def marine_heatwave_summary() -> dict[str, Any]:
    """Contiguous regions of coral-relevant heat stress (HotSpot >= 1C).

    Regions are 8-connected components on the working grid, merged across the
    antimeridian so a patch straddling 180deg counts once rather than twice,
    and filtered to `_MIN_REGION_CELLS` so speckle does not inflate the count.

    Each region reports its *peak cell*, not its centroid: these patches are
    long and curved, and the centroid of a horseshoe-shaped region routinely
    lands on land, which reads as a bug even when the region is correct.
    """
    from scipy import ndimage

    cache = _require_cache()
    mask = _ocean_mask(cache) & np.isfinite(cache.hotspot)
    hot = mask & (cache.hotspot >= HOTSPOT_STRESS_C)

    labels, count = ndimage.label(hot, structure=np.ones((3, 3), dtype=int))

    # The grid is periodic in longitude but `label` is not, so a region
    # crossing the antimeridian arrives as two components. Merge any pair
    # touching across the seam before counting.
    if count > 0:
        for row in range(labels.shape[0]):
            east, west = labels[row, -1], labels[row, 0]
            if east and west and east != west:
                labels[labels == west] = east
        remaining = np.unique(labels[labels > 0])
    else:
        remaining = np.array([], dtype=int)

    weights = _area_weights(cache.latitudes, cache.hotspot.shape)
    # A 1deg cell is ~12,364 km^2 at the equator; the cos(lat) weight above
    # scales that to each cell's true area.
    cell_area_km2 = 12364.0
    latitudes = np.broadcast_to(cache.latitudes[:, None], hot.shape)
    longitudes = np.broadcast_to(cache.longitudes[None, :], hot.shape)

    regions = []
    for label_id in remaining:
        selected = labels == label_id
        cells = int(selected.sum())
        if cells < _MIN_REGION_CELLS:
            continue

        values = np.where(selected, cache.hotspot, np.nan)
        peak_index = np.unravel_index(np.nanargmax(values), values.shape)
        regions.append(
            {
                "area_km2": round(float(weights[selected].sum() * cell_area_km2)),
                "cells": cells,
                "peak_hotspot_c": round(float(cache.hotspot[peak_index]), 2),
                "peak_anomaly_c": round(float(cache.anomaly[peak_index]), 2)
                if np.isfinite(cache.anomaly[peak_index])
                else None,
                "peak_dhw_c_weeks": round(float(cache.dhw[peak_index]), 2)
                if np.isfinite(cache.dhw[peak_index])
                else None,
                "peak_location": {
                    "latitude": round(float(latitudes[peak_index]), 2),
                    "longitude": round(float(longitudes[peak_index]), 2),
                },
            }
        )

    regions.sort(key=lambda region: region["area_km2"], reverse=True)

    total_weight = float(weights[mask].sum())
    hot_fraction = float(weights[hot].sum() / total_weight) if total_weight else 0.0

    return {
        "region_count": len(regions),
        "ocean_fraction": round(hot_fraction, 4),
        "largest_regions": regions[:5],
        "threshold_c": HOTSPOT_STRESS_C,
        # Stated explicitly so nobody reads this as the Hobday definition.
        "definition": (
            f"Contiguous areas ({_MIN_REGION_CELLS}+ cells) where SST is at least "
            f"{HOTSPOT_STRESS_C}C above the maximum monthly mean climatology "
            f"(NOAA CoralTemp HotSpot), over {ANALYSIS_LAT_LIMIT:.0f}S-"
            f"{ANALYSIS_LAT_LIMIT:.0f}N ice-free ocean. This is NOAA's heat-stress "
            f"criterion, not the 90th-percentile 5-day formal marine-heatwave "
            f"definition."
        ),
        "observed_at": cache.timestamp.isoformat(),
        "source": SOURCE_LABEL,
    }


def bleaching_summary() -> dict[str, Any]:
    """Global coral heat-stress state from DHW and NOAA's alert categories.

    Reported over cells actually carrying heat stress rather than the whole
    ocean: DHW is defined on reef-bearing water, and averaging it across the
    Southern Ocean would dilute every reading to zero.
    """
    cache = _require_cache()
    mask = _reef_mask(cache)
    if not mask.any():
        raise CrwError("No valid cells in the Coral Reef Watch DHW grid")

    dhw = cache.dhw[mask]
    weights = _area_weights(cache.latitudes, cache.dhw.shape)[mask]

    stressed = dhw > 0
    bleaching_likely = dhw >= DHW_BLEACHING_LIKELY
    mortality_likely = dhw >= DHW_MORTALITY_LIKELY

    total_weight = float(weights.sum())
    likely_fraction = float(weights[bleaching_likely].sum() / total_weight) if total_weight else 0.0

    baa = cache.baa[mask]
    categories = {}
    for level, label in BAA_LABELS.items():
        selected = baa == level
        categories[label] = {
            "level": level,
            "cells": int(selected.sum()),
            "fraction": round(float(weights[selected].sum() / total_weight), 4)
            if total_weight
            else 0.0,
        }

    # Headline category driven by how much reef water sits at Alert Level 1+,
    # which is where NOAA expects bleaching rather than merely elevated heat.
    if likely_fraction >= 0.05:
        risk = "High"
    elif likely_fraction >= 0.01:
        risk = "Moderate"
    else:
        risk = "Low"

    return {
        "risk": risk,
        "max_dhw_c_weeks": round(float(np.nanmax(dhw)), 2),
        "mean_dhw_c_weeks": round(float(np.average(dhw, weights=weights)), 3),
        "stressed_fraction": round(float(weights[stressed].sum() / total_weight), 4)
        if total_weight
        else 0.0,
        "bleaching_likely_fraction": round(likely_fraction, 4),
        "mortality_likely_cells": int(mortality_likely.sum()),
        "alert_categories": categories,
        "thresholds": {
            "bleaching_likely_dhw": DHW_BLEACHING_LIKELY,
            "mortality_likely_dhw": DHW_MORTALITY_LIKELY,
        },
        "coverage": (
            f"{CORAL_LAT_LIMIT:.0f}S-{CORAL_LAT_LIMIT:.0f}N ice-free ocean "
            f"(latitude proxy for reef distribution)"
        ),
        "observed_at": cache.timestamp.isoformat(),
        "source": SOURCE_LABEL,
    }


def sea_ice_summary() -> dict[str, Any]:
    """Area-weighted ice-covered fraction, split by hemisphere."""
    cache = _require_cache()
    ice = cache.seaice
    valid = np.isfinite(ice)
    if not valid.any():
        raise CrwError("No valid cells in the Coral Reef Watch sea-ice grid")

    weights = _area_weights(cache.latitudes, ice.shape)
    covered = valid & (ice >= _SEAICE_MASK_FRACTION)
    latitudes = np.broadcast_to(cache.latitudes[:, None], ice.shape)

    cell_area_km2 = 12364.0
    north = covered & (latitudes > 0)
    south = covered & (latitudes < 0)

    return {
        "northern_area_km2": round(float(weights[north].sum() * cell_area_km2)),
        "southern_area_km2": round(float(weights[south].sum() * cell_area_km2)),
        "observed_at": cache.timestamp.isoformat(),
        "source": SOURCE_LABEL,
    }


# Two reported hotspots must be at least this far apart. Without it the top
# of the list is simply the handful of adjacent cells forming the single
# worst patch — five alerts describing one event.
_HOTSPOT_MIN_SEPARATION_KM = 800.0


def hotspots(limit: int = 6) -> list[dict[str, Any]]:
    """The most heat-stressed reef locations, spatially declustered.

    Each entry is a distinct event rather than a neighbouring cell of one
    already reported, so the alerts panel shows six places rather than six
    views of the same warm pool.
    """
    cache = _require_cache()
    mask = _reef_mask(cache)
    if not mask.any():
        return []

    dhw = np.where(mask, cache.dhw, np.nan)
    ranked = np.argsort(np.nan_to_num(dhw, nan=-np.inf), axis=None)[::-1]

    results: list[dict[str, Any]] = []
    for index in ranked:
        row, column = np.unravel_index(index, dhw.shape)
        value = dhw[row, column]
        # Sorted descending, so the first sub-threshold cell ends the search.
        if not np.isfinite(value) or value < DHW_BLEACHING_LIKELY:
            break

        latitude = float(cache.latitudes[row])
        longitude = float(cache.longitudes[column])
        if any(
            _haversine_km(latitude, longitude, other["latitude"], other["longitude"])
            < _HOTSPOT_MIN_SEPARATION_KM
            for other in results
        ):
            continue

        results.append(
            {
                "latitude": round(latitude, 3),
                "longitude": round(longitude, 3),
                "dhw_c_weeks": round(float(value), 2),
                "anomaly_c": round(float(cache.anomaly[row, column]), 2)
                if np.isfinite(cache.anomaly[row, column])
                else None,
                "alert_level": int(cache.baa[row, column])
                if np.isfinite(cache.baa[row, column])
                else 0,
                "alert_label": BAA_LABELS.get(
                    int(cache.baa[row, column]) if np.isfinite(cache.baa[row, column]) else 0,
                    "Unknown",
                ),
            }
        )
        if len(results) >= limit:
            break
    return results


def meta() -> dict[str, Any]:
    cache = _require_cache()
    return {
        "source": SOURCE_LABEL,
        "source_url": SOURCE_URL,
        "citation": CITATION,
        "observed_at": cache.timestamp.isoformat(),
        "fetched_at": cache.fetched_at.isoformat(),
        "grid_spacing_deg": round(0.05 * _STRIDE, 3),
    }
