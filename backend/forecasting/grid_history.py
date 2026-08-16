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

  The cheap alternative — the daily depth-resolved datasets
  (`cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m` and its salinity/current
  twins) at 45 timesteps instead of 1080 — was measured through this path on
  2026-08-15 and **rejected**, on grounds other than cost:

  * **Both halves of the old case were wrong.** The correctness objection (a
    daily axis collapsing hourly wind to an instantaneous value) is gone —
    `cleaning.py` now aggregates per provider *before* the merge. And the cost
    numbers reversed under a proper measurement: hourly is **0.89s/timestep**
    (not 34-46s), so a 45-day window is ~16 min rather than ~35; daily,
    depth-bounded, is **1.16s/timestep** (not 84-104s), so ~0.9 min. Daily is
    ~18x cheaper here, not ~40x, and hourly is affordable. A 2-day probe of the
    same daily read gives 3.89s/timestep — per-request overhead dominates a
    short window, which is how the earlier probe inverted the ranking.
  * **The depth bound is worth 2.2x** on the 50-level datasets (8.63s/timestep
    without it against 3.89 with, same window). Same trap `machine_learning/`
    documents.
  * **It is rejected anyway**, because the swap would cost `Resolution.hourly`
    for the seven variables on `copernicus_physics` — a shipped downloader
    capability — turn one provider into three, and force a retrain of every
    variable carrying SST/salinity/currents as a covariate. See TODO.md §2.

  Note also that the *merged* daily product `cmems_mod_glo_phy_anfc_0.083deg
  _P1D-m` is not the substitute: it carries `zos`/`tob`/`sob`/`mlotst` and sea
  ice, but **not** `thetao`/`so`/`uo`/`vo`. The per-variable daily datasets are.

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
import gc
import hashlib
import itertools
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import xarray as xr

from forecasting import ForecastingError, progress
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

# Hard ceiling on one provider fetch, and the retry around it. The same guard
# `history._fetch_with_retry` has carried since a point fetch hung for 98
# minutes — and the same failure, observed here on 2026-08-14: a whole-grid
# `--all` build sat for **11 hours** having completed 9 of 13 providers, with
# 41 sockets to Copernicus in CLOSE_WAIT. The remote had closed them; the client
# was waiting on dead sockets and would have waited forever. Nothing raised,
# nothing logged, the process was alive at 13 GB RSS, and the progress bar last
# repainted four minutes into the run.
#
# That is the entire point of a timeout as distinct from a retry: an error can
# be retried, but silence cannot be noticed. This module having grown from the
# point path without inheriting its guard is exactly how the same bug gets paid
# for twice.
#
# Much larger than the point path's 300s, because these are legitimately long:
# a whole-globe hourly product over a 45-day window is ~1080 timestep reads and
# was measured at ~35 minutes. The ceiling is set to catch a hang, not to police
# a slow fetch.
_FETCH_TIMEOUT_SECONDS = 3600.0
_FETCH_ATTEMPTS = 2
_RETRY_BACKOFF_SECONDS = 10.0

# How many providers may be in flight at once.
#
# Each one holds a whole-globe, multi-timestep array while it loads, so this is
# a memory ceiling rather than a politeness one. Unbounded, a 13-provider warm
# fetch reached **13 GB RSS** on a 9 GB machine (measured 2026-08-14) and drove
# it into swap — which is very likely what turned a slow fetch into the hang the
# timeout above now catches. Three keeps peak near a few GB while still
# overlapping the long Copernicus reads with the short ERDDAP ones.
_MAX_CONCURRENT_FETCHES = 3

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

    def slice_point(
        self, latitude: float, longitude: float
    ) -> dict[str, tuple[ProviderSpec, xr.Dataset]]:
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


def _scope_key(provider_key: str, request: GridRequest, stride: int) -> str:
    """Identify a cached global field by everything *except* which fields it holds.

    Fields are deliberately excluded so that one entry can serve a request for a
    subset of it — see `_cache_get`. Two other things are conditional. A
    time-invariant provider drops the date window, because bathymetry for one
    week is bathymetry for any other. And GEBCO drops the stride, because it does
    its own server-side thinning (`gebco.choose_stride`) and ignores the value
    passed here — keying on it would refetch an identical global grid once per
    output resolution.
    """
    payload: dict[str, object] = {"provider": provider_key}
    if catalog.get(provider_key).time_varying:
        payload["start"] = request.start_date.isoformat()
        payload["end"] = request.end_date.isoformat()
    if provider_key != catalog.PROVIDER_GEBCO:
        payload["stride"] = stride
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]


def _cache_key(provider_key: str, fields: list[str], request: GridRequest, stride: int) -> str:
    """The filename for one cached fetch: its scope, then which fields it holds.

    The two halves are separate so a lookup can scan by scope and then decide on
    fields, which a single opaque hash cannot do.
    """
    fields_hash = hashlib.sha256(",".join(sorted(fields)).encode()).hexdigest()[:12]
    return f"{_scope_key(provider_key, request, stride)}-{fields_hash}"


def _read_cached(path: Path, ttl: timedelta) -> xr.Dataset | None:
    """One cache file, if it exists and is fresh enough."""
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


def _cache_get(
    provider_key: str, fields: list[str], request: GridRequest, stride: int, ttl: timedelta
) -> xr.Dataset | None:
    """A cached fetch covering `fields` — an exact match, or a superset.

    The superset half is what makes a multi-variable build affordable. Each
    variable asks its provider for only the fields it needs, so `current_u` wants
    `(uo, zos)` from the physics product and `current_v` wants `(vo, zos)`. Keyed
    on the field list alone those two miss each other, and the second variable
    repeats a whole-globe fetch that took **35 minutes** — measured, on the run
    that prompted this. Across ~26 trained variables drawing on a handful of
    datasets that is most of a day spent refetching the same product.

    So a cached entry that *contains* the requested fields is a hit, and the
    extra variables are dropped on the way out. Nothing is assumed about which
    entry that might be: the candidates are the ones sharing this scope, and
    freshest wins, so a wider cache written by `warm` is preferred over a narrow
    one written by an earlier single-variable build.
    """
    scope = _scope_key(provider_key, request, stride)
    wanted = set(fields)

    exact = _read_cached(CACHE_DIR / f"{_cache_key(provider_key, fields, request, stride)}.nc", ttl)
    if exact is not None:
        return exact

    if not CACHE_DIR.exists():
        return None
    candidates = sorted(
        CACHE_DIR.glob(f"{scope}-*.nc"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for path in candidates:
        dataset = _read_cached(path, ttl)
        if dataset is None:
            continue
        if wanted <= set(dataset.data_vars):
            logger.info(
                f"grid cache hit for {provider_key} ({', '.join(sorted(wanted))}) "
                f"from a wider cached fetch ({len(dataset.data_vars)} fields)"
            )
            return dataset[sorted(wanted)]
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


def sweep_cache(request: GridRequest) -> int:
    """Delete entries too old for anything to reuse. Returns how many went.

    **This directory had no eviction at all**, and why that went unnoticed for so
    long is the useful part. `_read_cached` *rejects* a stale entry but only
    unlinks a corrupt one, and `_cache_get` globs a single scope — so the two
    places that touch a stale file both decline to remove it. Worse, a scope
    carries the date window (`_scope_key`), so every build with a fresh window
    mints new scopes and orphans yesterday's, which are then never globbed again
    and so never even *considered*. The garbage is invisible to the cache by
    construction, not by oversight in one branch.

    Measured on 2026-08-16: 9.6 GB here, **8.16 GB of it unreachable** by the
    code that wrote it, with entries 227 hours old against a 6-hour TTL. It
    refills at roughly 1.5 GB per build day.

    Eviction hangs off the write path rather than the read path because writing
    is what *produces* the garbage — a new-scope entry is precisely the event
    that strands an old one. Sweeping on read would scan a directory dozens of
    times per build and still never look at a dead scope.

    The TTL is per provider and a filename is a hash, so entries are classified
    by scope prefix rather than by opening every NetCDF to ask. Only
    non-time-varying providers get `_STATIC_TTL`, and today that is GEBCO alone —
    whose scope drops the date window *and* the stride, making it a single
    constant and the `stride` argument below genuinely unread. If a static
    provider that does key on stride is ever added, its other-stride entries get
    swept at the field TTL: one refetch, never a wrong answer.
    """
    if not CACHE_DIR.exists():
        return 0

    static_prefixes = {
        _scope_key(key, request, 1)
        for key, spec in catalog.PROVIDERS.items()
        if not spec.time_varying
    }

    now = datetime.now(UTC)
    removed = 0
    freed = 0
    for path in itertools.chain(CACHE_DIR.glob("*.nc"), CACHE_DIR.glob("*.nc.tmp")):
        # A `.tmp` is a torn write from a crashed `_cache_put`. It is never
        # readable and no glob here or in `clear_cache` matches it, so it would
        # otherwise sit forever; the field TTL is far longer than any write.
        if path.suffix == ".tmp":
            ttl = _FIELD_TTL
        else:
            scope = path.stem.split("-", 1)[0]
            ttl = _STATIC_TTL if scope in static_prefixes else _FIELD_TTL
        try:
            stat = path.stat()
        except OSError:  # vanished under us — a concurrent sweep is fine
            continue
        if now - datetime.fromtimestamp(stat.st_mtime, tz=UTC) <= ttl:
            continue
        path.unlink(missing_ok=True)
        removed += 1
        freed += stat.st_size

    if removed:
        logger.info(f"swept {removed} stale grid cache entries ({freed / 2**30:.2f} GB)")
    return removed


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

    cached = _cache_get(provider_key, fields, request, stride, ttl)
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
            raise GridHistoryError(f"provider {provider_key!r} has no global gridded fetch path")
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
    # After the write, not before: this entry may be the one that orphans an
    # older scope, and sweeping first would leave that one behind for a whole
    # build. Never allowed to fail a fetch that has already succeeded.
    try:
        sweep_cache(request)
    except Exception as exc:  # noqa: BLE001 - eviction is housekeeping
        logger.warning(f"could not sweep the grid cache: {exc}")
    return dataset


async def _fetch_with_timeout(
    provider_key: str,
    spec: ProviderSpec,
    fields: list[str],
    request: GridRequest,
) -> xr.Dataset:
    """One provider's global field, bounded in time and retried once.

    Per-provider rather than around the whole gather, for the reason
    `history._fetch_with_retry` gives: retrying the group would re-issue the
    slow Copernicus reads to work around a fast ERDDAP blip. The coroutine is
    rebuilt per attempt, since an awaitable that has already raised cannot be
    awaited again.
    """
    for attempt in range(_FETCH_ATTEMPTS):
        try:
            return await asyncio.wait_for(
                _fetch_provider(provider_key, spec, fields, request),
                timeout=_FETCH_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            # Named separately so the log says "stopped responding" rather than
            # reporting the empty string a bare TimeoutError stringifies to,
            # which reads like a bug in this code rather than in the network.
            logger.warning(
                f"global fetch for {provider_key} stopped responding after "
                f"{_FETCH_TIMEOUT_SECONDS / 60:.0f} min "
                f"(attempt {attempt + 1}/{_FETCH_ATTEMPTS})"
            )
            if attempt == _FETCH_ATTEMPTS - 1:
                raise GridHistoryError(
                    f"global fetch for {provider_key} stopped responding "
                    f"({_FETCH_TIMEOUT_SECONDS / 60:.0f} min timeout, "
                    f"{_FETCH_ATTEMPTS} attempts). The provider accepted the "
                    "connection and then went silent; this is not a data error."
                ) from exc
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS)

    raise GridHistoryError(f"global fetch for {provider_key} failed")


async def warm(request: GridRequest) -> list[str]:
    """Fill the fetch cache for `request`, holding one provider at a time.

    Deliberately *not* `fetch_stack`, and the difference is the whole point.
    `fetch_stack` returns a `GridStack` that holds every provider's dataset at
    once, because a build genuinely needs them together to slice a cell. Warming
    does not: each dataset is written to disk and immediately useless in memory.

    Measured the hard way on 2026-08-14. A 13-provider warm through `fetch_stack`
    reached **13 GB resident on an 8 GB machine**, and the concurrency limit did
    not save it — that bounds how many are *fetching*, while the stack keeps
    every one of them alive afterwards. Sequentially, peak is one provider.

    It is also slower in wall-clock, and that is the right trade here: the warm
    pass runs once for a build measured in hours, and swapping is not a
    performance cost but a correctness one, since it is what a fetch hangs
    behind.

    Returns the provider keys warmed. A provider that fails is logged and
    skipped — warming must never fail the run it exists to speed up, and the
    real build will fetch (and properly report on) whatever is missing.
    """
    try:
        variables = resolve_variables(list(request.codes))
    except ValueError as exc:
        raise GridHistoryError(str(exc)) from exc

    griddable = {
        code: info
        for code, info in variables.items()
        if info.provider is not None and info.provider not in _UNGRIDDABLE_PROVIDERS
    }
    provider_keys = sorted({info.provider for info in griddable.values() if info.provider})

    warmed: list[str] = []
    with progress.counter(
        description="warming fetch cache", total=len(provider_keys), unit="provider"
    ) as bar:
        for key in provider_keys:
            spec = catalog.get(key)
            try:
                dataset = await _fetch_with_timeout(
                    key, spec, _needed_fields(griddable, key), request
                )
            except Exception as exc:  # noqa: BLE001 - warming is an optimisation
                logger.warning(f"could not warm {key}: {exc}")
                bar.update(1)
                continue

            warmed.append(key)
            # Explicit, not left to refcounting. `dataset` is the only reference
            # to a multi-gigabyte array and the next iteration allocates another
            # before this frame ends; on a machine already in swap the overlap is
            # exactly what must not happen.
            dataset.close()
            del dataset
            gc.collect()
            bar.update(1)

    return warmed


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

    # A bar over *providers*, not timesteps: a global fetch is one
    # `copernicusmarine` read of a whole window, so there is no per-timestep
    # event to count from out here. Coarse, but it is the difference between a
    # 35-minute silence and a job that visibly has two of three fields in hand.
    with progress.counter(
        description="global fetch", total=len(provider_keys), unit="provider"
    ) as bar:
        limit = asyncio.Semaphore(_MAX_CONCURRENT_FETCHES)

        async def _tracked(key: str) -> xr.Dataset:
            async with limit:
                dataset = await _fetch_with_timeout(
                    key, specs[key], _needed_fields(griddable, key), request
                )
            bar.update(1)
            return dataset

        try:
            datasets = await asyncio.gather(*(_tracked(key) for key in provider_keys))
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
            key: (specs[key], dataset) for key, dataset in zip(provider_keys, datasets, strict=True)
        },
        variables=griddable,
        ungriddable=tuple(sorted(ungriddable)),
        latitudes=latitudes,
        longitudes=longitudes,
        start_date=request.start_date,
        sources=catalog.source_labels(set(provider_keys)),
    )
