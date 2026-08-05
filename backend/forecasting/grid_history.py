"""Global gridded history — the forecast map's input.

`history.py` fetches one point at a time, which is right for a forecast
request and impossible for a map: a 1-degree global ocean grid is ~42,000
points, and 42,000 Copernicus point-series reads is not a slow version of this
feature, it is a different feature that never finishes.

So the fetch is inverted. Pull each dataset **once, globally**, hold it as
`(time, latitude, longitude)`, and slice per cell in memory. The network cost
stops scaling with the number of cells and starts scaling with the number of
*datasets*, which is a handful and shared across every variable that reads
them.

Three things about this module are load-bearing:

* **`arco-geo-series`, not `arco-time-series`.** The repo's rule is that the
  service must match the access pattern, and this is a third pattern the
  downloader never had: whole globe, many timesteps. geo-series chunks are one
  global timestep each, so N timesteps is N chunk reads. time-series chunks are
  fine in lat/lon, so a global request would touch every spatial chunk on the
  planet.

* **Providers are taken from the registry unchanged, and that is expensive on
  purpose.** Sea surface temperature resolves to `copernicus_physics`, the
  *hourly* product, so a 45-day window is ~1080 whole-globe timestep reads
  rather than 45 — measured at 35+ minutes, and independent of the output
  resolution, since geo-series chunks come off the wire at full resolution
  whatever stride is applied afterwards.

  The cheap alternative was measured and rejected *for now*: the daily
  depth-resolved datasets (`cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m`,
  1.05s/timestep, and its salinity twin at 0.60s) serve the same surface fields
  at 45 timesteps instead of 1080 — a ~40x reduction. Substituting them would
  change two things at once, though: the daily product's own mean replaces a
  mean of hourly steps (near-identical), *and* the merge in `build_dataframe`
  would inner-join hourly wind against a daily axis, collapsing wind speed from
  a 24-hour mean to a single instantaneous value (not near-identical, and in a
  direction Jensen's inequality guarantees is biased). Correctness first: the
  grid uses exactly what the point path uses, so there is no divergence to
  argue about. The substitution is worth revisiting with a measured comparison
  against the point API behind it.

* **Striding happens while the array is still lazy.** A global 0.083deg float64
  field is ~70MB per timestep per variable; 45 timesteps of two variables at
  full resolution is over 6GB. `providers/copernicus.fetch_global` coarsens
  before `.load()`, so the peak stays around one chunk.

* **The slice this module hands out is shaped exactly like what
  `history._fetch_frame` hands `build_dataframe`** — a
  `{provider_key: (ProviderSpec, Dataset)}` with scalar lat/lon. That is not a
  coincidence, it is the whole design: the grid path is the point path with the
  network replaced by an in-memory slice, so there is no second history
  assembly to drift out of step with the first. See `grid_predictor`.

What cannot be gridded is reported, never guessed. Open-Meteo is a point API
capped at 900 points, so `air_temperature` and its meteorological siblings have
no global field here. Those codes come back in `ungriddable` and the predictor
states the degradation rather than letting LightGBM's missing-value branch
absorb it silently.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import xarray as xr

from forecasting import ForecastingError
from services.download import catalog
from services.download.catalog import ProviderSpec
from services.download.providers import copernicus, gebco
from services.download.registry import VariableInfo, resolve_variables

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "grid"

# Time-varying fields go stale; bathymetry does not. Splitting the TTL keeps a
# refresh from re-downloading a global GEBCO grid that cannot have changed.
_FIELD_TTL = timedelta(hours=6)
_STATIC_TTL = timedelta(days=90)

# Providers with no global gridded form. Open-Meteo is a point API billed per
# grid point (`ProviderSpec.max_points = 900`), so a global field would be tens
# of thousands of HTTP requests for one covariate.
_UNGRIDDABLE_PROVIDERS = frozenset({catalog.PROVIDER_OPENMETEO})


class GridHistoryError(ForecastingError):
    """A global grid could not be assembled."""


@dataclass(frozen=True)
class GridRequest:
    """What to fetch, and onto what grid."""

    codes: tuple[str, ...]
    start_date: date
    end_date: date
    # The canonical output grid. Each provider is strided towards this from its
    # own native spacing, then nearest-sampled onto it at slice time.
    resolution_deg: float = 1.0

    def __post_init__(self) -> None:
        if self.resolution_deg <= 0:
            raise GridHistoryError("resolution_deg must be positive")
        if self.end_date < self.start_date:
            raise GridHistoryError(
                f"end_date {self.end_date} precedes start_date {self.start_date}"
            )


def output_grid(resolution_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """Cell centres of the canonical global grid.

    Centres rather than edges, so a nearest-sample from a provider grid lands
    in the middle of an output cell instead of on a boundary where the choice
    between two source cells is a rounding accident.
    """
    half = resolution_deg / 2.0
    latitudes = np.arange(-90.0 + half, 90.0, resolution_deg)
    longitudes = np.arange(-180.0 + half, 180.0, resolution_deg)
    return latitudes, longitudes


def ungriddable_reason(code: str) -> str | None:
    """Why `code` cannot be a global field, or None if it can.

    Answered from the registry alone, with no network, so a planner can skip a
    variable before paying for a fetch. The target variable is what matters:
    a *covariate* with no global field degrades the forecast and is reported,
    but a *target* with no global field has nothing to paint at all.
    """
    try:
        info = resolve_variables([code])[code]
    except ValueError as exc:
        return str(exc)
    if info.provider is None:
        return f"{code} has no provider"
    if info.provider in _UNGRIDDABLE_PROVIDERS:
        return (
            f"{code} comes from {info.provider}, a point API with no global "
            f"gridded form (capped at {catalog.get(info.provider).max_points} points)"
        )
    return None


@dataclass
class GridStack:
    """Global fields for one variable's codes, plus what could not be fetched."""

    providers: dict[str, tuple[ProviderSpec, xr.Dataset]]
    # Only the codes whose provider is actually present. `build_dataframe`
    # indexes the merged dataset by `source_field`, so passing it a variable
    # whose provider was skipped is a KeyError, not a missing column.
    variables: dict[str, VariableInfo]
    ungriddable: tuple[str, ...]
    latitudes: np.ndarray
    longitudes: np.ndarray
    start_date: date
    sources: list[str] = field(default_factory=list)

    def slice_point(self, latitude: float, longitude: float) -> dict[str, tuple[ProviderSpec, xr.Dataset]]:
        """One cell, shaped like `history._fetch_frame`'s fetch result.

        Nearest-selection per provider, matching what the point path does after
        its widened-bbox fetch — each provider keeps its own native grid and
        resolves the coordinate itself.
        """
        return {
            key: (
                spec,
                dataset.sel(latitude=latitude, longitude=longitude, method="nearest"),
            )
            for key, (spec, dataset) in self.providers.items()
        }

    def ocean_mask(self, target_code: str) -> np.ndarray:
        """Which output cells the target variable actually has data in.

        Taken from the **last** timestep, because that is the delta anchor: a
        cell whose most recent observation is missing cannot be forecast by a
        delta model at all (`predictor.predict` raises rather than inventing an
        anchor), so masking here and refusing there agree by construction.
        """
        info = self.variables.get(target_code)
        if info is None or info.provider is None:
            raise GridHistoryError(
                f"{target_code!r} has no gridded provider in this stack; "
                f"ungriddable codes were: {', '.join(self.ungriddable) or 'none'}"
            )
        _spec, dataset = self.providers[info.provider]

        fields = [f for f in (info.source_field, *(info.derived_from or ())) if f]
        present = [f for f in fields if f in dataset.data_vars]
        if not present:
            raise GridHistoryError(
                f"no source field for {target_code!r} in provider {info.provider!r}"
            )

        latest = dataset[present[0]]
        if "time" in latest.dims:
            latest = latest.isel(time=-1)

        sampled = latest.sel(
            latitude=xr.DataArray(self.latitudes, dims="y"),
            longitude=xr.DataArray(self.longitudes, dims="x"),
            method="nearest",
        )
        return np.isfinite(np.asarray(sampled.values, dtype="float64"))


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------


def _cache_key(provider_key: str, fields: list[str], request: GridRequest, stride: int) -> str:
    """Identify a cached global field by exactly what varies its contents.

    Two things are deliberately conditional. A time-invariant provider drops
    the date window, because bathymetry for one week is bathymetry for any
    other. And GEBCO drops the stride, because it does its own server-side
    thinning (`gebco.choose_stride`) and ignores the value passed here — keying
    on it would refetch an identical global grid once per output resolution.
    """
    payload: dict[str, object] = {"provider": provider_key, "fields": sorted(fields)}
    if catalog.get(provider_key).time_varying:
        payload["start"] = request.start_date.isoformat()
        payload["end"] = request.end_date.isoformat()
    if provider_key != catalog.PROVIDER_GEBCO:
        payload["stride"] = stride
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]


def _cache_get(key: str, ttl: timedelta) -> xr.Dataset | None:
    path = CACHE_DIR / f"{key}.nc"
    if not path.exists():
        return None
    age = datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    if age > ttl:
        return None
    try:
        with xr.open_dataset(path) as handle:
            # Read fully and close, exactly as `services/predictions.py` does:
            # holding the handle open blocks the next refresh from replacing the
            # file, which on macOS fails with EACCES.
            return handle.load()
    except Exception as exc:  # noqa: BLE001 - a corrupt cache entry is not fatal
        logger.warning(f"discarding unreadable grid cache entry {path.name}: {exc}")
        path.unlink(missing_ok=True)
        return None


def _cache_put(key: str, dataset: xr.Dataset) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.nc"
    try:
        temporary = path.with_suffix(".nc.tmp")
        dataset.to_netcdf(temporary)
        temporary.replace(path)
    except Exception as exc:  # noqa: BLE001 - caching is an optimisation
        logger.warning(f"could not cache grid to {path.name}: {exc}")


def clear_cache() -> int:
    """Drop every cached global field. Returns how many files were removed."""
    if not CACHE_DIR.exists():
        return 0
    removed = 0
    for path in CACHE_DIR.glob("*.nc"):
        path.unlink(missing_ok=True)
        removed += 1
    return removed


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------


def _needed_fields(variables: dict[str, VariableInfo], provider_key: str) -> list[str]:
    """Every upstream field this provider must supply. Mirrors
    `history._needed_fields` — derived variables need their components, not
    their own name."""
    fields: set[str] = set()
    for info in variables.values():
        if info.provider != provider_key:
            continue
        if info.source_field:
            fields.add(info.source_field)
        if info.derived_from:
            fields.update(info.derived_from)
    return sorted(fields)


def _stride_for(spec: ProviderSpec, resolution_deg: float) -> int:
    """How much to thin a provider's native grid to approach the output grid.

    Deliberately never below 1 and never *finer* than the output: sampling a
    0.083deg field onto a 1deg grid keeps one cell in twelve, and carrying the
    other eleven costs memory to deliver detail that is discarded at slice time.
    """
    if spec.grid_spacing_deg <= 0:
        return 1
    return max(1, int(round(resolution_deg / spec.grid_spacing_deg)))


async def _fetch_provider(
    provider_key: str,
    spec: ProviderSpec,
    fields: list[str],
    request: GridRequest,
) -> xr.Dataset:
    """One provider's global field, cached."""
    stride = _stride_for(spec, request.resolution_deg)
    key = _cache_key(provider_key, fields, request, stride)
    ttl = _FIELD_TTL if spec.time_varying else _STATIC_TTL

    cached = _cache_get(key, ttl)
    if cached is not None:
        logger.info(f"grid cache hit for {provider_key} ({', '.join(fields)})")
        return cached

    if provider_key == catalog.PROVIDER_GEBCO:
        # Time-invariant, and ERDDAP subsets server-side: `choose_stride` thins
        # a whole-globe request to ~40,000 cells on its own, which is close to
        # the 1deg output grid and one CSV response.
        dataset = await gebco.fetch(west=-180.0, south=-90.0, east=180.0, north=90.0)
    else:
        resolved = catalog.copernicus_dataset(provider_key)
        if resolved is None:
            raise GridHistoryError(
                f"provider {provider_key!r} has no global gridded fetch path"
            )
        dataset_id, depth_mode = resolved
        logger.info(
            f"fetching global {provider_key} ({', '.join(fields)}) "
            f"{request.start_date}..{request.end_date} at stride {stride}"
        )
        dataset = await copernicus.fetch_global(
            dataset_id=dataset_id,
            fields=fields,
            start_date=request.start_date,
            end_date=request.end_date,
            depth_mode=depth_mode,
            stride=stride,
        )

    _cache_put(key, dataset)
    return dataset


async def fetch_stack(request: GridRequest) -> GridStack:
    """Global fields for every griddable code in `request`.

    Providers are fetched concurrently. A provider that fails is fatal rather
    than degraded — unlike the point path, which can afford to drop bathymetry
    for one forecast, a missing field here would silently blank a covariate
    across the entire planet for every cell, and the resulting map would look
    exactly as confident as a correct one.
    """
    try:
        variables = resolve_variables(list(request.codes))
    except ValueError as exc:
        raise GridHistoryError(str(exc)) from exc

    griddable: dict[str, VariableInfo] = {}
    ungriddable: list[str] = []
    for code, info in variables.items():
        if info.provider is None or info.provider in _UNGRIDDABLE_PROVIDERS:
            ungriddable.append(code)
        else:
            griddable[code] = info

    if not griddable:
        raise GridHistoryError(
            f"none of {', '.join(request.codes)} can be fetched as a global grid"
        )

    provider_keys = sorted({info.provider for info in griddable.values() if info.provider})
    specs = {key: catalog.get(key) for key in provider_keys}

    try:
        datasets = await asyncio.gather(
            *(
                _fetch_provider(key, specs[key], _needed_fields(griddable, key), request)
                for key in provider_keys
            )
        )
    except GridHistoryError:
        raise
    except Exception as exc:  # noqa: BLE001 - never leak a provider traceback
        raise GridHistoryError(f"global grid fetch failed: {exc}") from exc

    latitudes, longitudes = output_grid(request.resolution_deg)

    if ungriddable:
        logger.warning(
            f"no global field for {', '.join(sorted(ungriddable))} — these covariates "
            f"will be absent from every cell of the forecast grid"
        )

    return GridStack(
        providers={
            key: (specs[key], dataset)
            for key, dataset in zip(provider_keys, datasets, strict=True)
        },
        variables=griddable,
        ungriddable=tuple(sorted(ungriddable)),
        latitudes=latitudes,
        longitudes=longitudes,
        start_date=request.start_date,
        sources=catalog.source_labels(set(provider_keys)),
    )
