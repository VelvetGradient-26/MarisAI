"""ML prediction grids — habitat suitability and harmful-algal-bloom risk.

Serves the **precomputed** output of the offline pipelines in
`machine_learning/`. This module deliberately does not import that package or
load any model: it reads NetCDF grids with the numpy/xarray already in the
backend's dependency set, and renders raster tiles the same way
`copernicus_sst` does.

Three consequences worth stating, because they were the reason for the design:

* `machine_learning` stays out of the backend's import graph — a documented
  boundary in this repo — and the backend gains no scikit-learn/LightGBM
  dependency (several hundred MB for code that would run once per request).
* A tile request cannot be slow, or fail, because a model was.
* What the API serves is exactly the artifact that was cross-validated,
  rather than a second inference path that has never been scored.

The tradeoff is real and worth naming: predictions exist only where and when
the export covered. There is no scoring of an arbitrary user-drawn area, and
adding one would mean live inference and the dependency weight that comes with
it. `manifest()` therefore reports coverage explicitly so the UI can say what
exists rather than silently rendering empty tiles.

Grids are memory-mapped on first use and cached for the process lifetime; they
are a few MB and change only when the export is re-run.
"""

from __future__ import annotations

import io
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr
from PIL import Image

from app.core.config import settings
from services.colormaps import ColorStop, build_colormap

logger = logging.getLogger(__name__)

TILE_SIZE = 256

HABITAT_GRID = "habitat_suitability.nc"
HAB_GRID = "hab_risk.nc"
MANIFEST = "manifest.json"


class PredictionError(RuntimeError):
    """Raised when a prediction grid is missing, malformed, or out of range."""


# --------------------------------------------------------------------------
# Colormaps
# --------------------------------------------------------------------------

# Suitability is a magnitude on 0-1, so it gets a single-hue sequential ramp
# light-to-dark. A rainbow here would invent category boundaries the model
# does not have. Kept in sync by hand with the CSS stops in the frontend's
# layerRegistry (same arrangement as SST — RGB tuples for numpy vs CSS hex for
# the legend bar, not derivable from one source without a build step).
SUITABILITY_STOPS: list[ColorStop] = [
    (0.00, (205, 226, 251)),
    (0.25, (134, 182, 239)),
    (0.50, (57, 135, 229)),
    (0.75, (37, 106, 191)),
    (1.00, (13, 54, 107)),
]
SUITABILITY_COLORMAP = build_colormap(SUITABILITY_STOPS)

# Bloom risk is also 0-1, but it is a hazard, so it runs cool-to-hot. This is
# a *semantic heat* ramp, one of the few defensible multi-hue sequential
# cases: the reader is meant to read "worse" toward red, and the legend states
# the scale.
BLOOM_RISK_STOPS: list[ColorStop] = [
    (0.00, (222, 235, 247)),
    (0.25, (161, 217, 155)),
    (0.50, (254, 217, 118)),
    (0.75, (253, 141, 60)),
    (1.00, (189, 0, 38)),
]
BLOOM_RISK_COLORMAP = build_colormap(BLOOM_RISK_STOPS)


# --------------------------------------------------------------------------
# Grid loading
# --------------------------------------------------------------------------


def _export_dir() -> Path:
    return Path(settings.PREDICTIONS_DIR).expanduser().resolve()


@lru_cache(maxsize=1)
def _load_manifest() -> dict[str, Any]:
    path = _export_dir() / MANIFEST
    if not path.exists():
        raise PredictionError(
            f"no prediction manifest at {path}. Run "
            "`PYTHONPATH=. python scripts/export_predictions.py` in machine_learning/."
        )
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise PredictionError(f"prediction manifest at {path} is not valid JSON: {exc}") from exc


@lru_cache(maxsize=4)
def _load_grid(filename: str) -> xr.Dataset:
    path = _export_dir() / filename
    if not path.exists():
        raise PredictionError(
            f"prediction grid {filename} is missing from {_export_dir()}. "
            "Re-run the export in machine_learning/."
        )
    try:
        # Read fully into memory and close the handle. Holding the file open
        # would block the offline exporter from overwriting it — on macOS the
        # re-export fails outright with EACCES while the API is running, which
        # is a genuinely confusing way to discover a lock. The grids are a few
        # MB, so there is nothing to gain from lazy access anyway.
        with xr.open_dataset(path) as handle:
            return handle.load()
    except Exception as exc:  # xarray raises a range of backend-specific types
        raise PredictionError(f"could not read prediction grid {filename}: {exc}") from exc


def manifest() -> dict[str, Any]:
    """Everything the UI needs to describe what exists and how good it is."""
    return _load_manifest()


def available() -> bool:
    """Whether any exports are present — lets the UI degrade honestly."""
    return (_export_dir() / MANIFEST).exists()


# --------------------------------------------------------------------------
# Slicing
# --------------------------------------------------------------------------


def habitat_slice(species: str, month: int) -> xr.DataArray:
    dataset = _load_grid(HABITAT_GRID)
    if species not in dataset.species.values:
        raise PredictionError(
            f"unknown species {species!r}; available: "
            f"{', '.join(map(str, dataset.species.values))}"
        )
    if month not in dataset.month.values:
        raise PredictionError(f"month {month} is not in the export (expected 1-12)")
    return dataset["suitability"].sel(species=species, month=month)


def hab_slice(horizon: int, day: str | None = None) -> xr.DataArray:
    dataset = _load_grid(HAB_GRID)
    if horizon not in dataset.horizon.values:
        raise PredictionError(
            f"unknown horizon {horizon}; available: "
            f"{', '.join(map(str, dataset.horizon.values))}"
        )
    dates = [str(d) for d in dataset.date.values]
    # Default to the most recent exported day rather than erroring, so the
    # common "just show me the latest" request needs no date handling client-side.
    selected = day or dates[-1]
    if selected not in dates:
        raise PredictionError(
            f"date {selected!r} is not in the export (covers {dates[0]} to {dates[-1]})"
        )
    return dataset["risk"].sel(horizon=horizon, date=selected)


# --------------------------------------------------------------------------
# Point queries
# --------------------------------------------------------------------------


def _nearest_value(field: xr.DataArray, latitude: float, longitude: float) -> float | None:
    lat_range = (float(field.latitude.min()), float(field.latitude.max()))
    lon_range = (float(field.longitude.min()), float(field.longitude.max()))
    if not (lat_range[0] <= latitude <= lat_range[1]
            and lon_range[0] <= longitude <= lon_range[1]):
        return None
    value = float(field.sel(latitude=latitude, longitude=longitude, method="nearest"))
    return None if np.isnan(value) else round(value, 4)


def habitat_point(species: str, month: int, latitude: float, longitude: float) -> dict[str, Any]:
    value = _nearest_value(habitat_slice(species, month), latitude, longitude)
    return {
        "species": species,
        "month": month,
        "suitability": value,
        # Distinguishing "outside the model's domain" from "land or no data"
        # matters: one means we never modelled here, the other means we did
        # and there is nothing there.
        "outside_coverage": value is None and not _within_habitat_domain(latitude, longitude),
        "value_label": "relative habitat suitability",
    }


def hab_point(horizon: int, latitude: float, longitude: float,
              day: str | None = None) -> dict[str, Any]:
    field = hab_slice(horizon, day)
    value = _nearest_value(field, latitude, longitude)
    return {
        "horizon_days": horizon,
        "date": str(field.date.values),
        "risk": value,
        "outside_coverage": value is None and not _within_hab_domain(latitude, longitude),
        "value_label": "probability of bloom",
    }


def _within(dataset_name: str, latitude: float, longitude: float) -> bool:
    region = _load_manifest()["products"][dataset_name]["region"]
    return (region["south"] <= latitude <= region["north"]
            and region["west"] <= longitude <= region["east"])


def _within_habitat_domain(latitude: float, longitude: float) -> bool:
    return _within("habitat", latitude, longitude)


def _within_hab_domain(latitude: float, longitude: float) -> bool:
    return _within("hab", latitude, longitude)


# --------------------------------------------------------------------------
# Tile rendering
# --------------------------------------------------------------------------


def _tile_lonlat(z: int, x: int, y: int) -> tuple[np.ndarray, np.ndarray]:
    """Web-Mercator tile pixel centres as lon/lat vectors. Mirrors
    `copernicus_sst._tile_lonlat` — same maths, same tiling scheme."""
    n = 2**z
    px = np.arange(TILE_SIZE, dtype=np.float64)
    lon = (x + (px + 0.5) / TILE_SIZE) / n * 360.0 - 180.0
    y_frac = (y + (px + 0.5) / TILE_SIZE) / n
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * y_frac))))
    return lon, lat


def _render(field: xr.DataArray, colormap, z: int, x: int, y: int) -> bytes:
    lon, lat = _tile_lonlat(z, x, y)

    # Nearest-neighbour rather than interpolation: these are model outputs on
    # a 0.25° grid, and smoothing them across cells would imply a spatial
    # precision the model does not have. Blocky is honest here.
    values = field.interp(
        latitude=xr.DataArray(lat, dims="y"),
        longitude=xr.DataArray(lon, dims="x"),
        method="nearest",
        kwargs={"bounds_error": False, "fill_value": np.nan},
    ).values

    rgb = np.nan_to_num(colormap(values), nan=0.0).astype(np.uint8)
    alpha = np.where(np.isnan(values), 0, 220).astype(np.uint8)
    rgba = np.dstack([rgb, alpha])

    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG")
    return buf.getvalue()


_EMPTY_TILE = io.BytesIO()
Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(_EMPTY_TILE, format="PNG")
_EMPTY_TILE_BYTES = _EMPTY_TILE.getvalue()


@lru_cache(maxsize=4096)
def render_habitat_tile(species: str, month: int, z: int, x: int, y: int) -> bytes:
    return _render(habitat_slice(species, month), SUITABILITY_COLORMAP, z, x, y)


@lru_cache(maxsize=4096)
def render_hab_tile(horizon: int, day: str, z: int, x: int, y: int) -> bytes:
    return _render(hab_slice(horizon, day), BLOOM_RISK_COLORMAP, z, x, y)


def habitat_tile_or_placeholder(species: str, month: int, z: int, x: int, y: int) -> bytes:
    """Router-facing: never raises, so a missing export or render error shows
    as an empty tile rather than a broken map (same contract as the SST tiles)."""
    try:
        return render_habitat_tile(species, month, z, x, y)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"habitat tile {species}/{month} {z}/{x}/{y} failed: {exc}")
        return _EMPTY_TILE_BYTES


def hab_tile_or_placeholder(horizon: int, day: str | None, z: int, x: int, y: int) -> bytes:
    try:
        resolved = day or str(hab_slice(horizon).date.values)
        return render_hab_tile(horizon, resolved, z, x, y)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"bloom tile t+{horizon} {z}/{x}/{y} failed: {exc}")
        return _EMPTY_TILE_BYTES
