"""Forecast vector fields as particle textures.

`forecast_tiles` paints a forecast *scalar* grid as raster tiles. This does the
other thing a forecast grid can be: where two grids hold the components of one
vector, they compose into the same RGBA U/V texture the live wind and currents
layers already feed to the GPU particle engine — so a user can watch the
predicted flow move, at +1/+3/+7/+30 days, in exactly the idiom they already
read the live map in.

**Nothing here runs a model.** Same contract as `forecast_tiles`: grids are
built offline by `scripts/build_forecast_grid.py` and this reads them. A field
request cannot be slow, or fail, because inference was.

**A pair is only a pair if both halves exist.** `PAIRS` names the component
variables, and `available()` reports a pair only when both grids are on disk
*and* share a horizon — a texture built from a stale `current_u` and a fresh
`current_v` would animate confidently in the wrong direction, which is worse
than an absent layer.

**A pair is always two forecast *components*, never a forecast bearing.** Ocean
currents were the first pair because `current_u`/`current_v` are directly
forecast, which is exactly what a particle field needs. Wind was configured as
`wind_speed` + `wind_direction` — both griddable, but direction is a *circular*
quantity, and every operation between here and the screen (the model's own
regression on the level, the grid's bilinear resample, the particle engine's
texture interpolation) is linear. Averaging 359deg and 1deg gives 180deg, the
exact opposite heading, so a wind field composed from those two grids would have
flowed backwards along every wrap. So `wind_u`/`wind_v` were configured as
forecast variables in their own right over the downloader's Copernicus
`eastward_wind`/`northward_wind` — two registry entries, two YAML blocks and two
training runs, not a new integration. Any future pair goes the same way.

**The visual identity belongs to the pair, and lives on the frontend.** Each
forecast field is drawn exactly like its *live* counterpart, because comparison
is the only thing anyone wants from it — see `PAIR_VISUALS` in
`layers/forecastVectorLayers.ts`. `direction_convention` below is served for the
same reason: the two conventions are 180deg apart and a layer that picks the
wrong one looks entirely plausible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from services import vector_field
from services.forecast_tiles import (
    ForecastTileError,
    _grid_dir,
    _load_grid,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VectorPair:
    """Two scalar forecast variables that together make one vector field."""

    key: str
    label: str
    unit: str
    u_variable: str
    v_variable: str
    # Legend top, in the field's own units. Not derived from the grid's
    # `display_max`, which is a robust percentile of the *component* — a
    # percentile of `uo` alone says nothing about how fast the water moves.
    speed_max_legend: float
    # Oceanographic ("toward") or meteorological ("from"). Stated rather than
    # inferred, because the two conventions are 180deg apart and a vector layer
    # that picks the wrong one looks entirely plausible.
    direction_convention: str


PAIRS: dict[str, VectorPair] = {
    "currents": VectorPair(
        key="currents",
        label="Ocean Currents",
        unit="m/s",
        u_variable="current_u",
        v_variable="current_v",
        speed_max_legend=2.0,
        direction_convention="toward",
    ),
    # Registered here before its grids existed, deliberately — and it became a
    # live layer the moment `wind_u`/`wind_v` were trained and built, with no
    # frontend edit. `catalog()` reports a pair with an explicit reason while a
    # component is missing, which is a better answer than a layer that silently
    # does not exist while two trained models sit on disk. Register the next
    # pair the same way round.
    #
    # 25 m/s is a strong gale, chosen as a legend top the same way currents'
    # 2.0 m/s was: high enough that a storm is not clipped flat, low enough that
    # ordinary weather uses most of the ramp.
    "wind": VectorPair(
        key="wind",
        label="Forecast Wind",
        unit="m/s",
        u_variable="wind_u",
        v_variable="wind_v",
        speed_max_legend=25.0,
        direction_convention="from",
    ),
}


class ForecastVectorError(RuntimeError):
    """A forecast vector pair is missing, malformed, or out of range."""


def _pair(key: str) -> VectorPair:
    pair = PAIRS.get(key)
    if pair is None:
        raise ForecastVectorError(
            f"unknown forecast vector field {key!r}; expected one of {', '.join(PAIRS)}"
        )
    return pair


def _shared_horizons(u_grid: xr.Dataset, v_grid: xr.Dataset) -> list[int]:
    """Horizons both components carry.

    Intersected rather than taken from either side: the two grids are built by
    separate runs and can legitimately disagree — one rebuilt after a config
    change, one not — and a horizon present in only one would compose a vector
    out of a component that does not exist.
    """
    u_horizons = {int(h) for h in u_grid.horizon.values}
    v_horizons = {int(h) for h in v_grid.horizon.values}
    return sorted(u_horizons & v_horizons)


def available(root: Path | None = None) -> list[str]:
    """Which vector pairs currently have both grids on disk."""
    directory = _grid_dir(root)
    ready = []
    for key, pair in PAIRS.items():
        u_path = directory / f"{pair.u_variable}.nc"
        v_path = directory / f"{pair.v_variable}.nc"
        if u_path.exists() and v_path.exists():
            ready.append(key)
    return ready


def catalog(root: Path | None = None) -> list[dict[str, Any]]:
    """What the frontend needs to register a particle layer per horizon.

    Mirrors `forecast_tiles.catalog`: an entry that cannot be served reports
    its own reason rather than being dropped, so the map can say why a layer a
    user expects is absent instead of silently not having it.
    """
    directory = _grid_dir(root)
    entries: list[dict[str, Any]] = []

    for key, pair in PAIRS.items():
        entry: dict[str, Any] = {
            "key": key,
            "label": pair.label,
            "unit": pair.unit,
            "u_variable": pair.u_variable,
            "v_variable": pair.v_variable,
            "speed_max_legend": pair.speed_max_legend,
            "direction_convention": pair.direction_convention,
            "horizons": [],
        }
        try:
            u_grid = _load_grid(pair.u_variable, str(directory))
            v_grid = _load_grid(pair.v_variable, str(directory))
        except ForecastTileError as exc:
            entry["error"] = str(exc)
            entries.append(entry)
            continue

        horizons = _shared_horizons(u_grid, v_grid)
        if not horizons:
            entry["error"] = (
                f"{pair.u_variable} and {pair.v_variable} share no horizon "
                f"({sorted(int(h) for h in u_grid.horizon.values)} vs "
                f"{sorted(int(h) for h in v_grid.horizon.values)}) — rebuild both"
            )
            entries.append(entry)
            continue

        entry.update(
            {
                "horizons": horizons,
                "resolution_deg": float(u_grid.attrs.get("resolution_deg", 0.0)),
                "observation_date": u_grid.attrs.get("observation_date"),
                "generated_at": u_grid.attrs.get("generated_at"),
                "model": u_grid.attrs.get("model", "LightGBM"),
                "sources": [
                    source
                    for source in str(u_grid.attrs.get("sources", "")).split("; ")
                    if source
                ],
                "skill_scores": u_grid.attrs.get("skill_scores", ""),
                "missing_covariates": [
                    name
                    for name in str(u_grid.attrs.get("missing_covariates", "")).split(", ")
                    if name
                ],
            }
        )
        entries.append(entry)

    return entries


@lru_cache(maxsize=32)
def _texture(
    key: str, horizon: int, mode: str, directory: str, version: str
) -> vector_field.FieldTexture:
    """The encoded field for one pair/horizon. `version` keys the cache only so
    a rebuild invalidates it."""
    pair = _pair(key)
    u_grid = _load_grid(pair.u_variable, directory)
    v_grid = _load_grid(pair.v_variable, directory)

    horizons = _shared_horizons(u_grid, v_grid)
    if horizon not in horizons:
        raise ForecastVectorError(
            f"horizon {horizon} is not carried by both components of {key!r} "
            f"(shared: {', '.join(map(str, horizons)) or 'none'})"
        )

    if mode == "forecast":
        u = u_grid["forecast"].sel(horizon=horizon)
        v = v_grid["forecast"].sel(horizon=horizon)
    elif mode == "anchor":
        # The observations the forecast was anchored on, as a field in its own
        # right. This is what makes the layer readable: watching the predicted
        # flow next to the flow it was launched from is the comparison, and
        # rebuilding it client-side from two more requests would be the same
        # data twice.
        u = u_grid["anchor"]
        v = v_grid["anchor"]
    else:
        raise ForecastVectorError(f"unknown mode {mode!r}; expected 'forecast' or 'anchor'")

    if not u.shape == v.shape:
        raise ForecastVectorError(
            f"{pair.u_variable} and {pair.v_variable} grids disagree in shape "
            f"({u.shape} vs {v.shape}) — rebuild both"
        )

    return vector_field.encode(
        u.values,
        v.values,
        u_grid["latitude"].values,
        u_grid["longitude"].values,
    )


def _version(directory: str, pair: VectorPair) -> str:
    """A cache key that changes when either component is rebuilt."""
    u_grid = _load_grid(pair.u_variable, directory)
    v_grid = _load_grid(pair.v_variable, directory)
    return f"{u_grid.attrs.get('generated_at', '')}|{v_grid.attrs.get('generated_at', '')}"


def field_png(key: str, horizon: int, mode: str, root: Path | None = None) -> bytes:
    pair = _pair(key)
    directory = str(_grid_dir(root))
    try:
        return _texture(key, horizon, mode, directory, _version(directory, pair)).png
    except ForecastTileError as exc:
        raise ForecastVectorError(str(exc)) from exc


def meta(key: str, horizon: int, mode: str, root: Path | None = None) -> dict[str, Any]:
    """Everything the particle layer needs to sample the texture and label it.

    Same shape as `copernicus_wind.get_meta` / `copernicus_currents.get_meta`,
    so the frontend's `fetchMeta` contract is one interface across live and
    forecast fields rather than three lookalikes.
    """
    pair = _pair(key)
    directory = str(_grid_dir(root))
    try:
        u_grid = _load_grid(pair.u_variable, directory)
        texture = _texture(key, horizon, mode, directory, _version(directory, pair))
    except ForecastTileError as exc:
        raise ForecastVectorError(str(exc)) from exc

    return {
        "key": key,
        "label": pair.label,
        "unit": pair.unit,
        "horizon_days": horizon,
        "mode": mode,
        "speed_max_legend": pair.speed_max_legend,
        "direction_convention": pair.direction_convention,
        "u_min": texture.u_min,
        "u_max": texture.u_max,
        "v_min": texture.v_min,
        "v_max": texture.v_max,
        **texture.bounds(),
        "timestamp": u_grid.attrs.get("observation_date"),
        "generated_at": u_grid.attrs.get("generated_at"),
        "resolution_deg": float(u_grid.attrs.get("resolution_deg", 0.0)),
        "model": u_grid.attrs.get("model", "LightGBM"),
        "source": "; ".join(
            source for source in str(u_grid.attrs.get("sources", "")).split("; ") if source
        ),
    }


def clear_cache() -> None:
    """Drop encoded textures — call after a rebuild writes new grids."""
    _texture.cache_clear()


def point(key: str, horizon: int, latitude: float, longitude: float, root: Path | None = None):
    """The forecast vector at one coordinate, read nearest-cell off both grids.

    Nearest-cell for the same reason `forecast_tiles.point` is: this answers
    "what does the layer say here", so it must agree with what is on screen
    rather than with a more precise number the grid does not carry.
    """
    import math

    pair = _pair(key)
    directory = str(_grid_dir(root))
    try:
        u_grid = _load_grid(pair.u_variable, directory)
        v_grid = _load_grid(pair.v_variable, directory)
    except ForecastTileError as exc:
        raise ForecastVectorError(str(exc)) from exc

    if horizon not in _shared_horizons(u_grid, v_grid):
        raise ForecastVectorError(f"horizon {horizon} is not carried by both components of {key!r}")

    selector = {"latitude": latitude, "longitude": longitude, "method": "nearest"}
    u = float(u_grid["forecast"].sel(horizon=horizon).sel(**selector))
    v = float(v_grid["forecast"].sel(horizon=horizon).sel(**selector))
    u_now = float(u_grid["anchor"].sel(**selector))
    v_now = float(v_grid["anchor"].sel(**selector))

    def described(east: float, north: float) -> dict[str, Any]:
        if not (np.isfinite(east) and np.isfinite(north)):
            return {"speed_ms": None, "direction_toward_deg": None}
        return {
            "speed_ms": round(math.hypot(east, north), 3),
            "direction_toward_deg": round((90.0 - math.degrees(math.atan2(north, east))) % 360.0, 1),
        }

    return {
        "key": key,
        "label": pair.label,
        "unit": pair.unit,
        "horizon_days": horizon,
        "forecast": described(u, v),
        "last_observed": described(u_now, v_now),
        "observation_date": u_grid.attrs.get("observation_date"),
        "generated_at": u_grid.attrs.get("generated_at"),
    }
