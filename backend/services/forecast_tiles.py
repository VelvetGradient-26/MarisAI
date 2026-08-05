"""Forecast grids as map tiles.

Serves the **precomputed** output of `forecasting/grid_predictor.py`, and
deliberately runs no inference: a tile request reads a NetCDF grid and paints
it, exactly as `services/predictions.py` does for the offline ML products. The
reasoning is the same and worth restating, because the forecasting engine *is*
in the backend's import graph and so the shortcut is available here in a way it
is not there:

* A tile request cannot be slow, or fail, because a model was. Scoring a
  1-degree global grid costs ~25 minutes; it belongs on a schedule, not on the
  path of a map pan.
* What the map paints is exactly the artifact the parity test compared against
  the point API, rather than a third code path that has never been checked
  against either.

Two render modes, and the second is the one worth having. `absolute` paints the
forecast value. `change` paints forecast minus the latest observation — which
is what a forecast map is actually *for*, since the absolute field at +7 days
looks almost identical to today's and the difference is the entire signal.

Colour scales come out of the grid file's own attributes (`display_min`,
`display_max`, `change_scale`), written at build time. That keeps the renderer
and the frontend legend from disagreeing about what a colour means, which is a
class of bug no test catches and every user sees.
"""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr
from PIL import Image

from forecasting.grid_history import ungriddable_reason
from forecasting.grid_predictor import (
    GRID_DIR,
    build_forecast_grid,
    grid_path,
    save_grid,
)
from forecasting.model_store import list_trained
from services.colormaps import (
    DIVERGING_STOPS,
    SEQUENTIAL_STOPS,
    SST_COLORMAP_STOPS,
    ColorStop,
    build_colormap,
)

logger = logging.getLogger(__name__)

TILE_SIZE = 256

# A rebuild is ~50 minutes for the first variable at the 1-degree default (~35
# min of whole-globe Copernicus reads, ~15 min of feature building), so this is
# far longer than the other caches' intervals. It is also well inside the
# useful life of the answer: the underlying analysis publishes daily, so a grid
# rebuilt twice a day is never showing a stale ocean. Variables after the first
# are much cheaper — the global reads are cached and shared.
REFRESH_INTERVAL_HOURS = 12

# The grid the scheduled rebuild produces. Coarser than the finest the code
# supports, because the cell loop is linear in cell count and this is the point
# where a global grid still rebuilds inside its own refresh interval.
REFRESH_RESOLUTION_DEG = 1.0

MODE_ABSOLUTE = "absolute"
MODE_CHANGE = "change"
MODES = (MODE_ABSOLUTE, MODE_CHANGE)

# Variables whose absolute layer must match an existing observation layer's
# colours. Only sea surface temperature qualifies today: the map already draws
# observed SST with this exact ramp, and a forecast painted on a different
# scale would look like a different quantity when the two are compared, which
# is the single most likely thing a user will do with this layer.
#
# Everything else falls through to the sequential ramp. This table is
# presentation, not modelling — a variable missing from it renders correctly,
# just not colour-matched to anything.
#
# Note these stops are already in data units (degrees C), unlike the shared
# normalised ramps. `_colormap_for` is what reconciles the two.
_MATCHED_STOPS: dict[str, list[ColorStop]] = {
    "sea_surface_temperature": SST_COLORMAP_STOPS,
}


class ForecastTileError(RuntimeError):
    """A forecast grid is missing, malformed, or the request is out of range."""


# --------------------------------------------------------------------------
# Grid loading
# --------------------------------------------------------------------------


def _grid_dir(root: Path | None = None) -> Path:
    return root or GRID_DIR


@lru_cache(maxsize=16)
def _load_grid(variable: str, directory: str) -> xr.Dataset:
    path = Path(directory) / f"{variable}.nc"
    if not path.exists():
        raise ForecastTileError(
            f"no forecast grid for {variable!r}. Build it with: "
            f"python scripts/build_forecast_grid.py --variable {variable}"
        )
    try:
        # Read fully and close the handle, so a scheduled rebuild can replace
        # the file while the API is running — holding it open fails with EACCES
        # on macOS, which is a confusing way to discover a lock.
        with xr.open_dataset(path) as handle:
            return handle.load()
    except ForecastTileError:
        raise
    except Exception as exc:  # noqa: BLE001 - xarray raises backend-specific types
        raise ForecastTileError(f"could not read forecast grid {path.name}: {exc}") from exc


def clear_cache() -> None:
    """Drop cached grids — call after a scheduled rebuild writes new ones."""
    _load_grid.cache_clear()
    render_tile.cache_clear()


def available(root: Path | None = None) -> list[str]:
    """Which variables currently have a grid on disk."""
    directory = _grid_dir(root)
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob("*.nc"))


def catalog(root: Path | None = None) -> list[dict[str, Any]]:
    """Everything the map needs to build its layers and legends.

    Drives the frontend registry, so a newly built grid becomes a map layer
    with no frontend edit — the same contract the metric pages already have
    with `/api/v1/forecast/catalog`.
    """
    entries: list[dict[str, Any]] = []
    for variable in available(root):
        try:
            grid = _load_grid(variable, str(_grid_dir(root)))
        except ForecastTileError as exc:
            entries.append({"variable": variable, "error": str(exc)})
            continue

        attrs = grid.attrs
        missing = str(attrs.get("missing_covariates", "") or "")
        entries.append(
            {
                "variable": variable,
                "label": attrs.get("label", variable),
                "unit": attrs.get("unit", ""),
                "horizons": [int(h) for h in grid.horizon.values],
                "resolution_deg": float(attrs.get("resolution_deg", 0.0)),
                "generated_at": attrs.get("generated_at"),
                "observation_date": attrs.get("observation_date"),
                "trained_at": attrs.get("trained_at"),
                "model": attrs.get("model"),
                "sources": str(attrs.get("sources", "")).split("; ") if attrs.get("sources") else [],
                "display_min": float(attrs.get("display_min", 0.0)),
                "display_max": float(attrs.get("display_max", 1.0)),
                "change_scale": float(attrs.get("change_scale", 1.0)),
                "skill_scores": attrs.get("skill_scores"),
                "cells_scored": int(attrs.get("cells_scored", 0)),
                # Named, never omitted. These covariates were in the model at
                # training time and have no global field, so the grid was scored
                # without them — the legend says so rather than letting the map
                # look exactly as confident as a complete one would.
                "missing_covariates": [item for item in missing.split(", ") if item],
            }
        )
    return entries


# --------------------------------------------------------------------------
# Field selection
# --------------------------------------------------------------------------


@lru_cache(maxsize=64)
def _rescaled(stops_key: str, low: float, high: float) -> Any:
    """A colormap whose control points sit in the data's own units.

    The shared ramps in `colormaps.py` are defined on a unit domain — [0, 1]
    for sequential, [-1, 1] for diverging — so that one ramp serves every
    variable. Stretching them onto the real domain here, rather than squeezing
    the *values* into the unit domain at render time, is what lets every
    colormap in this module take raw values. Mixing the two conventions is a
    genuine hazard: `SST_COLORMAP_STOPS` is already in degrees Celsius, so
    handing it a normalised 0-1 array paints the entire ocean the colour of
    -2 degC.
    """
    source = {"sequential": SEQUENTIAL_STOPS, "diverging": DIVERGING_STOPS}[stops_key]
    lowest = source[0][0]
    span = source[-1][0] - lowest
    return build_colormap(
        [(low + (offset - lowest) / span * (high - low), rgb) for offset, rgb in source]
    )


def _field(grid: xr.Dataset, horizon: int, mode: str) -> tuple[xr.DataArray, Any]:
    """The DataArray to paint, and a colormap that takes its raw values."""
    if mode not in MODES:
        raise ForecastTileError(f"unknown mode {mode!r}; expected one of {', '.join(MODES)}")

    horizons = [int(h) for h in grid.horizon.values]
    if horizon not in horizons:
        raise ForecastTileError(
            f"horizon {horizon} is not in this grid (has: {', '.join(map(str, horizons))})"
        )

    forecast = grid["forecast"].sel(horizon=horizon)

    if mode == MODE_CHANGE:
        # Symmetric by construction, so zero lands on the ramp's neutral centre.
        scale = abs(float(grid.attrs.get("change_scale", 1.0))) or 1.0
        return forecast - grid["anchor"], _rescaled("diverging", -scale, scale)

    matched = _MATCHED_STOPS.get(str(grid.attrs.get("variable", "")))
    if matched is not None:
        return forecast, build_colormap(matched)

    return forecast, _rescaled(
        "sequential",
        float(grid.attrs.get("display_min", 0.0)),
        float(grid.attrs.get("display_max", 1.0)),
    )


# --------------------------------------------------------------------------
# Point query
# --------------------------------------------------------------------------


def point(
    variable: str, horizon: int, latitude: float, longitude: float, root: Path | None = None
) -> dict[str, Any]:
    """The forecast at one coordinate, read straight off the grid.

    Nearest-cell, not interpolated: this answers "what does the layer say
    here", and it must agree with the pixel under the cursor rather than with a
    more precise number the grid does not carry.
    """
    grid = _load_grid(variable, str(_grid_dir(root)))
    forecast, _colormap = _field(grid, horizon, MODE_ABSOLUTE)

    selected = forecast.sel(latitude=latitude, longitude=longitude, method="nearest")
    anchor = grid["anchor"].sel(latitude=latitude, longitude=longitude, method="nearest")

    value = float(selected)
    observed = float(anchor)
    finite = np.isfinite(value)

    return {
        "variable": variable,
        "label": grid.attrs.get("label", variable),
        "unit": grid.attrs.get("unit", ""),
        "horizon_days": horizon,
        "forecast": round(value, 3) if finite else None,
        "last_observed": round(observed, 3) if np.isfinite(observed) else None,
        "change": round(value - observed, 3) if finite and np.isfinite(observed) else None,
        "observation_date": grid.attrs.get("observation_date"),
        "generated_at": grid.attrs.get("generated_at"),
        "resolution_deg": float(grid.attrs.get("resolution_deg", 0.0)),
    }


# --------------------------------------------------------------------------
# Tile rendering
# --------------------------------------------------------------------------


def _tile_lonlat(z: int, x: int, y: int) -> tuple[np.ndarray, np.ndarray]:
    """Web-Mercator tile pixel centres. Mirrors `copernicus_sst._tile_lonlat` —
    same maths, same tiling scheme."""
    n = 2**z
    px = np.arange(TILE_SIZE, dtype=np.float64)
    lon = (x + (px + 0.5) / TILE_SIZE) / n * 360.0 - 180.0
    y_frac = (y + (px + 0.5) / TILE_SIZE) / n
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * y_frac))))
    return lon, lat


@lru_cache(maxsize=4096)
def render_tile(
    variable: str, horizon: int, mode: str, z: int, x: int, y: int, directory: str, version: str
) -> bytes:
    """One tile. `version` is part of the key only so a rebuild invalidates it."""
    grid = _load_grid(variable, directory)
    field, colormap = _field(grid, horizon, mode)

    lon, lat = _tile_lonlat(z, x, y)
    values = field.interp(
        latitude=xr.DataArray(lat, dims="y"),
        longitude=xr.DataArray(lon, dims="x"),
        method="linear",
        kwargs={"bounds_error": False, "fill_value": np.nan},
    ).values

    # Raw values: every colormap `_field` hands back is already in data units,
    # and `build_colormap` clamps beyond its endpoints rather than extrapolating.
    rgb = np.nan_to_num(colormap(values), nan=0.0).astype(np.uint8)
    alpha = np.where(np.isnan(values), 0, 220).astype(np.uint8)
    rgba = np.dstack([rgb, alpha])

    buffer = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buffer, format="PNG")
    return buffer.getvalue()


_EMPTY_TILE = io.BytesIO()
Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(_EMPTY_TILE, format="PNG")
_EMPTY_TILE_BYTES = _EMPTY_TILE.getvalue()


# --------------------------------------------------------------------------
# Scheduled rebuild
# --------------------------------------------------------------------------

_refresh_lock = asyncio.Lock()


def is_refreshing() -> bool:
    """Whether a rebuild is in flight. Derived from the existing lock rather
    than a second flag, matching `copernicus_sst.is_refreshing`."""
    return _refresh_lock.locked()


def _is_fresh(variable: str, root: Path | None = None) -> bool:
    path = grid_path(variable, root)
    if not path.exists():
        return False
    age = datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return age < timedelta(hours=REFRESH_INTERVAL_HOURS)


def buildable() -> dict[str, list[int]]:
    """Trained variables that can actually have a global grid.

    A variable whose *target* comes from a point API is excluded here rather
    than attempted and failed — `air_temperature` is trained and will never be
    griddable, and a scheduled job should not log an error about that twice a
    day forever.
    """
    return {
        variable: horizons
        for variable, horizons in list_trained().items()
        if ungriddable_reason(variable) is None
    }


async def refresh_grids(*, force: bool = False) -> None:
    """Rebuild every buildable variable's grid.

    Wired into the scheduler. Follows the same contract as the other cached
    services: a failure keeps the previous grid in place — `save_grid` only
    writes after a successful build, so a failed rebuild cannot leave a partial
    or empty layer on the map.

    Skips grids that are already fresh, so a restart does not pay 25 minutes of
    CPU to reproduce a file written twenty minutes ago.
    """
    if _refresh_lock.locked():
        logger.info("forecast grid rebuild already in flight, skipping")
        return

    async with _refresh_lock:
        targets = buildable()
        if not targets:
            logger.info("no trained, griddable variables — no forecast grids to build")
            return

        for variable, horizons in targets.items():
            if not force and _is_fresh(variable):
                logger.info(f"forecast grid for {variable} is fresh, skipping rebuild")
                continue
            try:
                grid = await build_forecast_grid(
                    variable, horizons, resolution_deg=REFRESH_RESOLUTION_DEG
                )
                # Threaded for the same reason the build itself is: serialising
                # a global grid to netCDF is a blocking write, and this runs on
                # the server's event loop.
                await asyncio.to_thread(save_grid, grid, variable)
                clear_cache()
                logger.info(
                    f"forecast grid refreshed for {variable}: "
                    f"{grid.attrs.get('cells_scored')} cells, "
                    f"horizons {list(grid.horizon.values)}"
                )
            except Exception:  # noqa: BLE001 - keep the previous grid on any failure
                logger.exception(
                    f"forecast grid rebuild failed for {variable}, keeping previous grid"
                )


def tile_or_placeholder(
    variable: str, horizon: int, mode: str, z: int, x: int, y: int, root: Path | None = None
) -> bytes:
    """Router-facing: never raises, so a missing grid or a render error shows as
    an empty tile rather than a broken map — the same contract as the SST and
    prediction tiles."""
    directory = str(_grid_dir(root))
    try:
        grid = _load_grid(variable, directory)
        version = str(grid.attrs.get("generated_at", ""))
        return render_tile(variable, horizon, mode, z, x, y, directory, version)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"forecast tile {variable}/h{horizon}/{mode} {z}/{x}/{y} failed: {exc}")
        return _EMPTY_TILE_BYTES
