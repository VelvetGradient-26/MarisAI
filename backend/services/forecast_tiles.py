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
from forecasting import ForecastingError, derived
from forecasting.model_store import list_trained
from services.colormaps import (
    CYCLIC_STOPS,
    DIVERGING_STOPS,
    SEQUENTIAL_STOPS,
    SST_COLORMAP_STOPS,
    ColorStop,
    build_colormap,
)
from services.download.registry import VARIABLE_REGISTRY
from services.field_sampling import Sampler, angular_difference, build_sampler

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

# Unforecastable ocean, drawn as a 45-degree hatch rather than left blank.
#
# This exists because of a measured collision, not a style preference. Every
# ramp here bottoms out near black, and the map's default basemap is a near-
# black ocean (`abyss.ts`'s #030f1e), so at the layer's 0.7 opacity the darkest
# step of each ramp sits at 1.13-1.27:1 contrast against bare basemap — against
# a 2:1 floor. The consequence is that a cell showing *strong cooling* and a
# cell showing *nothing at all* were the same pixel to a reader.
#
# Lightening the ramps was the obvious fix and does not work: reaching 2:1
# needs the diverging ends brightened ~1.9x (colliding with their own next
# stop) and viridis's end 2.4x, which turns it magenta. Raising the layer's
# opacity does not work either — none of the four ends clears 2:1 even at
# opacity 1.0. The distinguishing mark has to be *texture*, not colour.
#
# `anchor` is what separates the two cases, and it is already in the grid file:
# it is finite exactly where a latest observation existed, so anchor-finite +
# forecast-NaN means "we can see this water, the model could not score it",
# while anchor-NaN is land or outside coverage and stays transparent. Marking
# the second would hatch every continent.
_HATCH_RGB = (122, 133, 144)
_HATCH_PERIOD = 8
_HATCH_WIDTH = 3


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
    _samplers.cache_clear()
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
                # A bearing's scale comes from geometry, not from the grid's own
                # percentiles, and the renderer already ignores the stored
                # values for one. Reporting the geometric bounds here is what
                # keeps the frontend legend showing the same thing the tiles
                # were painted with — including on grids built before circular
                # variables were handled, whose stored `display_max` is 400.
                "circular": is_circular(variable),
                "display_min": 0.0 if is_circular(variable) else float(attrs.get("display_min", 0.0)),
                "display_max": (
                    360.0 if is_circular(variable) else float(attrs.get("display_max", 1.0))
                ),
                "change_scale": (
                    _CIRCULAR_CHANGE_SCALE
                    if is_circular(variable)
                    else float(attrs.get("change_scale", 1.0))
                ),
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


def is_circular(variable: str) -> bool:
    """Whether this variable is a compass bearing rather than a magnitude.

    Read from the download registry, which is the one place that fact is
    recorded — every consumer of a direction field needs it, and a second list
    here would drift the first time a fourth direction variable is added.
    """
    info = VARIABLE_REGISTRY.get(variable)
    return bool(info and info.circular)


# A veer of half a turn is the largest one there is, so the change ramp for a
# direction spans the whole of it. Unlike the per-variable `change_scale` in the
# grid file, this is not fitted to observed spread: the domain is fixed by
# geometry, and a ramp whose ends were percentiles could paint two genuinely
# opposite headings the same colour.
_CIRCULAR_CHANGE_SCALE = 180.0


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
    source = {
        "sequential": SEQUENTIAL_STOPS,
        "diverging": DIVERGING_STOPS,
        "cyclic": CYCLIC_STOPS,
    }[stops_key]
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

    variable_key = str(grid.attrs.get("variable", ""))
    circular = is_circular(variable_key)
    forecast = grid["forecast"].sel(horizon=horizon)

    if mode == MODE_CHANGE:
        if circular:
            # A signed veer wrapped to (-180, 180], not a subtraction. Plain
            # arithmetic reads a 5-degree veer across north as -355, which on a
            # ramp reaching +/-180 clamps hard to the cold end — a small
            # clockwise turn painted as the largest possible anticlockwise one.
            change = xr.apply_ufunc(angular_difference, forecast, grid["anchor"])
            return change, _rescaled("diverging", -_CIRCULAR_CHANGE_SCALE, _CIRCULAR_CHANGE_SCALE)

        # Symmetric by construction, so zero lands on the ramp's neutral centre.
        scale = abs(float(grid.attrs.get("change_scale", 1.0))) or 1.0
        return forecast - grid["anchor"], _rescaled("diverging", -scale, scale)

    if circular:
        # A cyclic ramp, on the variable's true domain rather than the grid's
        # observed percentiles: 0 and 360 are the same heading and must be the
        # same colour, which a scale fitted to the data cannot guarantee.
        return forecast, _rescaled("cyclic", 0.0, 360.0)

    matched = _MATCHED_STOPS.get(variable_key)
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

    # The same wrap the change layer uses, so the number in the panel and the
    # colour under the cursor agree about which way the current turned.
    change: float | None = None
    if finite and np.isfinite(observed):
        difference = (
            float(angular_difference(value, observed))
            if is_circular(variable)
            else value - observed
        )
        change = round(difference, 3)

    return {
        "variable": variable,
        "label": grid.attrs.get("label", variable),
        "unit": grid.attrs.get("unit", ""),
        "horizon_days": horizon,
        "forecast": round(value, 3) if finite else None,
        "last_observed": round(observed, 3) if np.isfinite(observed) else None,
        "change": change,
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


@lru_cache(maxsize=64)
def _samplers(
    variable: str, horizon: int, mode: str, directory: str, version: str
) -> tuple[Sampler, Sampler]:
    """The field's sampler and its anchor's, built once per grid rather than per
    tile. Building them costs a nearest-fill over the whole globe, which is
    trivial once and wasteful 4,096 times."""
    grid = _load_grid(variable, directory)
    field, _colormap = _field(grid, horizon, mode)

    # Only the *absolute* field of a circular variable is still an angle. In
    # `change` mode `_field` has already differenced it into a signed veer on
    # (-180, 180], which is an ordinary linear quantity — resampling that as an
    # angle would fold negative veers back onto positive ones.
    angular = is_circular(variable) and mode != MODE_CHANGE
    return (
        build_sampler(field, angular=angular),
        build_sampler(grid["anchor"], angular=is_circular(variable)),
    )


@lru_cache(maxsize=8)
def _hatch(size: int) -> np.ndarray:
    """A 45-degree stripe mask, True on the stripe. Cached — it is the same
    array for every tile, and rebuilding it per tile is pure waste."""
    ys, xs = np.mgrid[0:size, 0:size]
    return ((xs + ys) % _HATCH_PERIOD) < _HATCH_WIDTH


@lru_cache(maxsize=4096)
def render_tile(
    variable: str, horizon: int, mode: str, z: int, x: int, y: int, directory: str, version: str
) -> bytes:
    """One tile. `version` is part of the key only so a rebuild invalidates it."""
    grid = _load_grid(variable, directory)
    _, colormap = _field(grid, horizon, mode)
    sample_field, sample_anchor = _samplers(variable, horizon, mode, directory, version)

    lon, lat = _tile_lonlat(z, x, y)
    values = sample_field(lon, lat)

    # Raw values: every colormap `_field` hands back is already in data units,
    # and `build_colormap` clamps beyond its endpoints rather than extrapolating.
    rgb = np.nan_to_num(colormap(values), nan=0.0).astype(np.uint8)
    alpha = np.where(np.isnan(values), 0, 220).astype(np.uint8)

    # Observable water the model could not score: hatched, so "no forecast" can
    # never be read as an extreme value. See the _HATCH_* constants.
    stripe = np.isnan(values) & np.isfinite(sample_anchor(lon, lat)) & _hatch(TILE_SIZE)
    rgb[stripe] = _HATCH_RGB
    alpha[stripe] = 220

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
    trained = list_trained()
    buildable_grids = {
        variable: horizons
        for variable, horizons in trained.items()
        if ungriddable_reason(variable) is None
    }
    # Derived bearings have no model, so `list_trained` never sees them — but
    # their grids are assembled from the component grids in seconds, so the
    # scheduler should refresh them alongside. Added after the components so a
    # single pass builds the components first and derives from what it just
    # wrote, rather than from the previous cycle's grids.
    for name, spec in derived.DERIVED.items():
        if spec.east in buildable_grids and spec.north in buildable_grids:
            buildable_grids[name] = sorted(
                set(buildable_grids[spec.east]) & set(buildable_grids[spec.north])
            )
    return buildable_grids


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
                if derived.is_derived(variable):
                    # Assembled from the component grids this same pass just
                    # wrote — seconds, no fetch, no inference. Threaded because
                    # opening two global NetCDFs is still a blocking read on
                    # the server's event loop.
                    grid = await asyncio.to_thread(_derive_grid_from_components, variable)
                else:
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


def _derive_grid_from_components(variable: str):
    """Open a derived bearing's two component grids and combine them.

    Kept beside the refresh rather than in `derived.py` because it is the only
    part that touches this module's grid *paths*; the arithmetic itself lives in
    one place, shared with the offline builder and the point forecast.
    """
    import xarray as xr

    spec = derived.spec_for(variable)
    assert spec is not None
    east_path = _grid_dir() / f"{spec.east}.nc"
    north_path = _grid_dir() / f"{spec.north}.nc"
    if not east_path.exists() or not north_path.exists():
        raise ForecastingError(
            f"{variable} needs the {spec.east} and {spec.north} grids, and at "
            "least one is missing"
        )
    with xr.open_dataset(east_path) as east, xr.open_dataset(north_path) as north:
        return derived.derive_grid(east, north, variable)


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
