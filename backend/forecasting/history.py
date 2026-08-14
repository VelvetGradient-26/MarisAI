"""The engine's one source of historical data: a point time series for any
variable the download registry can serve.

This is deliberately a thin adapter over `services/download/` rather than a
second ingestion stack. That package already resolves 34 variables across 14
providers, already knows each provider's grid, cadence and coverage window,
already merges providers of differing cadence onto one time axis, and already
returns a tidy frame. Re-implementing any of that here would mean two places
to fix when a provider changes — and would break the promise that adding a
variable is config-only, since the new variable would have to be taught to
both stacks.

What this module adds on top is the three things a forecaster needs and a
downloader does not:

* **A point series, not a file.** `run_download` ends in CSV/JSON/PDF bytes;
  training needs the DataFrame that was on its way there.
* **Coverage clamping.** A request for two years of sea level anomaly against
  a product that starts mid-2024 is not an error here, it is a shorter series.
  The downloader is right to refuse it (a user asked for a specific range);
  the trainer is right to take what exists.
* **Caching.** A training run fetches the same point-years repeatedly across
  horizons and variables, and an uncached Copernicus point-series costs
  8-13s. Parquet on disk, keyed by exactly what was asked for.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd
import xarray as xr

from forecasting import ForecastingError
from services.download import catalog
from services.download.catalog import ProviderSpec
from services.download.cleaning import build_dataframe
from services.download.models import Resolution
from services.download.registry import VariableInfo, resolve_variables

logger = logging.getLogger(__name__)

# Matches `services/download/service.py`: a point is widened to a small bbox
# before fetching so it clears the coarsest provider grid (0.25deg), then the
# exact nearest cell is selected afterwards.
_POINT_HALF_WIDTH_DEG = 0.3

# Disk cache. Training reuses the same (point, variable, window) across four
# horizons, and the dashboard re-requests the same point within a session.
CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "history"
_DISK_TTL = timedelta(hours=6)

# A second, in-process layer in front of the disk. Parquet reads are fast but
# not free, and the predictor touches the same frame several times per request.
_MEMORY_TTL = timedelta(minutes=15)
_MEMORY_MAX = 64
_memory_cache: dict[str, tuple[datetime, pd.DataFrame]] = {}
_memory_lock = threading.Lock()


class HistoryError(ForecastingError):
    """History could not be assembled for the requested point/variables.

    Means the data genuinely is not there — the point is over land, or the
    window predates coverage. Retrying will not help, so the API answers 404.
    """


class ProviderUnavailableError(HistoryError):
    """An upstream provider failed the request (timeout, 5xx, auth).

    Deliberately separate from its parent, because the two need opposite
    advice. A GEBCO 503 or a Copernicus timeout is transient and *will* clear;
    reporting it as "no data at this point — it may be over land" sends the
    user to check their coordinates when the coordinates were fine. This maps
    to 503, not 404.
    """


@dataclass(frozen=True)
class HistoryRequest:
    """What to fetch. Hashable, so it doubles as the cache key."""

    codes: tuple[str, ...]
    latitude: float
    longitude: float
    start_date: date
    end_date: date
    resolution: Resolution = Resolution.daily
    depth_m: float = 0.0

    def cache_key(self) -> str:
        payload = json.dumps(
            {
                "codes": sorted(self.codes),
                # Rounded to the provider grid's order of magnitude. Two
                # requests 0.001deg apart resolve to the same model cell, and
                # caching them separately would double every fetch for no
                # difference in the data.
                "lat": round(self.latitude, 3),
                "lon": round(self.longitude, 3),
                "start": self.start_date.isoformat(),
                "end": self.end_date.isoformat(),
                "resolution": self.resolution.value,
                "depth": round(self.depth_m, 1),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class HistorySeries:
    """A point time series plus the provenance a forecast has to carry."""

    frame: pd.DataFrame
    latitude: float
    longitude: float
    resolution: Resolution
    # Per-code coverage start, clamped from the provider catalog. The trainer
    # reports this so a short series is explained rather than mysterious.
    coverage: dict[str, date]
    sources: list[str]

    @property
    def start(self) -> pd.Timestamp | None:
        return None if self.frame.empty else self.frame["timestamp"].min()

    @property
    def end(self) -> pd.Timestamp | None:
        return None if self.frame.empty else self.frame["timestamp"].max()


# --------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------


def earliest_start(codes: tuple[str, ...]) -> date | None:
    """The earliest date all of `codes` are simultaneously available.

    The *latest* of the providers' coverage starts, because `build_dataframe`
    inner-joins on time: a covariate that starts two years after the target
    truncates the joined frame to its own start. Surfacing that here lets the
    trainer log "chlorophyll history begins 2021-11-01 because the optics
    product does" instead of silently training on a third of the data.
    """
    try:
        variables = resolve_variables(list(codes))
    except ValueError as exc:
        raise HistoryError(str(exc)) from exc

    starts: list[date] = []
    for info in variables.values():
        if info.provider is None:
            continue
        coverage_start = catalog.get(info.provider).coverage_start
        # Bathymetry is time-invariant and reports no coverage start; it must
        # not drag the floor to None, or a request pairing it with anything
        # else would lose that variable's real lower bound.
        if coverage_start is not None:
            starts.append(coverage_start)
    return max(starts) if starts else None


def clamp_to_coverage(request: HistoryRequest) -> HistoryRequest:
    """Move `start_date` forward to the first date every code exists.

    Returns the request unchanged when coverage already contains it. Raises
    only when the window collapses entirely — that is a genuine
    "this variable cannot be forecast from this date" and must not be
    papered over.
    """
    floor = earliest_start(request.codes)
    if floor is None or request.start_date >= floor:
        return request
    if floor >= request.end_date:
        raise HistoryError(
            f"No overlapping coverage: the requested window ends {request.end_date}, "
            f"but data for {', '.join(sorted(request.codes))} only begins {floor}."
        )
    logger.info(
        f"history window clamped {request.start_date} -> {floor} "
        f"(provider coverage for {', '.join(sorted(request.codes))})"
    )
    return HistoryRequest(
        codes=request.codes,
        latitude=request.latitude,
        longitude=request.longitude,
        start_date=floor,
        end_date=request.end_date,
        resolution=request.resolution,
        depth_m=request.depth_m,
    )


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------


def _memory_get(key: str) -> pd.DataFrame | None:
    with _memory_lock:
        entry = _memory_cache.get(key)
        if entry is None:
            return None
        stored_at, frame = entry
        if datetime.now(UTC) - stored_at > _MEMORY_TTL:
            _memory_cache.pop(key, None)
            return None
        return frame.copy()


def _memory_put(key: str, frame: pd.DataFrame) -> None:
    with _memory_lock:
        _memory_cache[key] = (datetime.now(UTC), frame.copy())
        if len(_memory_cache) > _MEMORY_MAX:
            oldest = min(_memory_cache, key=lambda k: _memory_cache[k][0])
            _memory_cache.pop(oldest, None)


def _disk_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.parquet"


def frozen_cache() -> bool:
    """Whether to serve disk cache entries regardless of age.

    The TTL exists because a *live* request asks for a window ending "now",
    and yesterday's answer to that question is stale by construction. An
    offline experiment is the opposite case: it pins `as_of`, so the window is
    a closed historical interval that upstream cannot revise. Re-fetching it
    yields the same bytes at the cost of ~700s per variable, and — because the
    providers flap — occasionally yields *fewer* points, which silently makes
    two runs of the same experiment incomparable.

    Off by default and set only by the experiment scripts, so no serving path
    can inherit it.
    """
    return os.environ.get("MARISAI_FROZEN_HISTORY_CACHE") == "1"


def _disk_get(key: str) -> pd.DataFrame | None:
    path = _disk_path(key)
    if not path.exists():
        return None
    age = datetime.now(UTC) - datetime.fromtimestamp(
        path.stat().st_mtime, tz=UTC
    )
    if age > _DISK_TTL and not frozen_cache():
        return None
    try:
        return pd.read_parquet(path)
    except Exception as exc:  # noqa: BLE001 - a corrupt cache entry is not fatal
        logger.warning(f"discarding unreadable history cache entry {path.name}: {exc}")
        path.unlink(missing_ok=True)
        return None


def _disk_put(key: str, frame: pd.DataFrame) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _disk_path(key)
    try:
        # Write-then-rename: a training run interrupted mid-write would
        # otherwise leave a truncated parquet that every later run reads and
        # discards, silently costing the cache.
        temporary = path.with_suffix(".parquet.tmp")
        frame.to_parquet(temporary, index=False)
        temporary.replace(path)
    except Exception as exc:  # noqa: BLE001 - caching is an optimisation
        logger.warning(f"could not cache history to {path.name}: {exc}")


def clear_cache() -> int:
    """Drop every cached series. Returns how many files were removed."""
    with _memory_lock:
        _memory_cache.clear()
    if not CACHE_DIR.exists():
        return 0
    removed = 0
    for path in CACHE_DIR.glob("*.parquet"):
        path.unlink(missing_ok=True)
        removed += 1
    return removed


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------


def _needed_fields(variables: dict[str, VariableInfo], provider_key: str) -> list[str]:
    fields: set[str] = set()
    for info in variables.values():
        if info.provider != provider_key:
            continue
        if info.source_field:
            fields.add(info.source_field)
        if info.derived_from:
            fields.update(info.derived_from)
    return sorted(fields)


# Transient upstream failures are common enough to plan for and cheap enough
# to absorb. A single ERDDAP 503 during one training run cost 6 of 24 training
# points — a quarter of the model's geography, including the entire Gulf
# Stream and Coral Sea — for a provider that supplies one constant column and
# was fine again seconds later.
_FETCH_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = (2.0, 6.0)

# Hard ceiling on a single provider fetch. Retrying on an exception is not
# enough on its own, because the failure mode that actually cost the most here
# was not an error — it was a Copernicus zarr read that simply never returned.
# A training run sat on one for 98 minutes looking healthy: the process was
# alive, no exception was pending, and nothing would ever have raised. A
# timeout is what turns that silence into a retryable failure.
#
# Generous relative to the ~8-13s a normal point-series fetch takes, because
# a genuinely slow multi-year request must not be killed mid-flight; the point
# is to catch a hang, not to police latency.
_FETCH_TIMEOUT_SECONDS = 300.0


def is_retryable(exc: BaseException, attempt: int = 0) -> bool:
    """Whether another attempt could plausibly succeed.

    Retrying a *permanent* failure is not merely wasteful, it is the dominant
    cost: a provider answering 404 took three attempts and 8s of backoff on
    **every** request, which turned a warm 6s forecast into 14.5s and made the
    page look broken.

    404 is nonetheless allowed *one* retry, because on ERDDAP it is not
    reliably permanent. ERDDAP unloads a dataset while reloading it and answers
    404 "Currently unknown datasetID=..." in the meantime — the same code and
    the same message a genuinely removed dataset gives, so the two cannot be
    told apart from the response. Measured on NOAA CoastWatch: `NOAA_DHW` and
    `GEBCO_2020` each 404'd for ~100s and then returned to 200, and the server
    had been fully 503 shortly before. One retry recovers a request that lands
    in a reload window; capping it at one keeps a truly dead dataset to a
    single 2s backoff instead of the 8s that motivated this rule.

    Classification walks the exception's cause chain for an `httpx` status
    rather than matching on message text, because the provider modules wrap
    their failures in their own error types but preserve the cause (`raise X
    from exc`). An unrecognised failure is treated as retryable — the cost of
    one extra attempt is far lower than giving up on a real blip.
    """
    seen: set[int] = set()
    current: BaseException | None = exc

    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, httpx.HTTPStatusError):
            status = current.response.status_code
            if status == 404:
                return attempt == 0
            # 408 request timeout, 425 too early and 429 rate limited are the
            # 4xx codes that clear on their own; every other 4xx says the
            # request itself is wrong and will stay wrong.
            return status in (408, 425, 429) or status >= 500
        if isinstance(current, httpx.TimeoutException | httpx.NetworkError):
            return True
        current = current.__cause__ or current.__context__

    return True


async def _fetch_with_retry(
    key: str, coroutine_factory: Callable[[], Awaitable[xr.Dataset]]
) -> xr.Dataset:
    """One provider's fetch, retried with backoff on a transient failure.

    Per-provider rather than around the whole gather: retrying the group would
    re-issue the slow Copernicus zarr reads to work around a fast ERDDAP blip,
    turning a 2-second recovery into a 30-second one.

    The coroutine is rebuilt per attempt via the factory — an awaitable that
    has already raised cannot be awaited again.
    """
    last: Exception | None = None
    for attempt in range(_FETCH_ATTEMPTS):
        try:
            dataset: xr.Dataset = await asyncio.wait_for(
                coroutine_factory(), timeout=_FETCH_TIMEOUT_SECONDS
            )
            return dataset
        except TimeoutError as exc:
            # Named separately so the log says "hung" rather than reporting an
            # empty exception message, which is what a bare TimeoutError
            # stringifies to and which reads like a bug in this code.
            last = exc
            logger.warning(
                f"provider {key} did not respond within {_FETCH_TIMEOUT_SECONDS:.0f}s "
                f"(attempt {attempt + 1}/{_FETCH_ATTEMPTS})"
            )
            if attempt == _FETCH_ATTEMPTS - 1:
                raise ProviderUnavailableError(
                    f"Historical data provider {key} stopped responding "
                    f"({_FETCH_TIMEOUT_SECONDS:.0f}s timeout, {_FETCH_ATTEMPTS} attempts)."
                ) from exc
            await asyncio.sleep(
                _RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)]
            )
            continue
        except Exception as exc:  # noqa: BLE001 - provider libraries raise widely
            last = exc
            if not is_retryable(exc, attempt):
                logger.warning(
                    f"provider {key} failed permanently, not retrying: {str(exc)[:160]}"
                )
                break
            if attempt == _FETCH_ATTEMPTS - 1:
                break
            delay = _RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)]
            logger.warning(
                f"provider {key} failed (attempt {attempt + 1}/{_FETCH_ATTEMPTS}): "
                f"{str(exc)[:120]} — retrying in {delay:.0f}s"
            )
            await asyncio.sleep(delay)

    raise ProviderUnavailableError(
        f"Historical data provider {key} failed after {_FETCH_ATTEMPTS} attempts: {last}"
    ) from last


async def _fetch_frame(request: HistoryRequest, variables: dict[str, VariableInfo]) -> pd.DataFrame:
    """Fetch every provider concurrently and merge to one point frame.

    Mirrors `services/download/service.run_download`'s fetch stage — same
    widen-then-select-nearest, same one-gather-for-all-providers — and stops
    where that function starts exporting.
    """
    provider_keys = {info.provider for info in variables.values() if info.provider}
    specs = {key: catalog.get(key) for key in provider_keys}

    west = request.longitude - _POINT_HALF_WIDTH_DEG
    east = request.longitude + _POINT_HALF_WIDTH_DEG
    south = request.latitude - _POINT_HALF_WIDTH_DEG
    north = request.latitude + _POINT_HALF_WIDTH_DEG

    def factory(key: str, spec: ProviderSpec) -> Callable[[], Awaitable[xr.Dataset]]:
        # `spec` and `key` are bound as defaults rather than captured, so each
        # closure keeps its own provider instead of every one of them seeing
        # whichever pair the loop finished on.
        def build(spec: ProviderSpec = spec) -> Awaitable[xr.Dataset]:
            return spec.fetch(
                fields=_needed_fields(variables, key),
                west=west,
                south=south,
                east=east,
                north=north,
                start_date=request.start_date,
                end_date=request.end_date,
                depth_m=request.depth_m,
            )

        return build

    keys = list(specs)
    try:
        results = await asyncio.gather(
            *(_fetch_with_retry(key, factory(key, specs[key])) for key in keys)
        )
    except ProviderUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001 - never leak a provider traceback
        raise ProviderUnavailableError(
            f"Historical data provider request failed: {exc}"
        ) from exc

    fetched: dict[str, tuple[ProviderSpec, xr.Dataset]] = {}
    for key, dataset in zip(keys, results, strict=True):
        fetched[key] = (
            specs[key],
            dataset.sel(
                latitude=request.latitude, longitude=request.longitude, method="nearest"
            ),
        )

    return build_dataframe(
        fetched=fetched,
        variables=variables,
        resolution=request.resolution,
        start_date=request.start_date,
    )


async def fetch(request: HistoryRequest, *, use_cache: bool = True) -> HistorySeries:
    """A point time series for `request.codes`, clamped to real coverage.

    The returned frame has one row per timestamp with columns
    `timestamp, latitude, longitude, <code>...`. It is *not* gap-filled or
    feature-engineered — that is `preprocessing` and `feature_engineering`,
    kept separate so a caller can inspect exactly what the provider said.
    """
    request = clamp_to_coverage(request)

    try:
        variables = resolve_variables(list(request.codes))
    except ValueError as exc:
        raise HistoryError(str(exc)) from exc

    key = request.cache_key()
    frame = _memory_get(key) if use_cache else None
    if frame is None and use_cache:
        frame = _disk_get(key)
        if frame is not None:
            _memory_put(key, frame)

    if frame is None:
        frame = await _fetch_frame(request, variables)
        if use_cache:
            _disk_put(key, frame)
            _memory_put(key, frame)

    if frame.empty:
        raise HistoryError(
            f"No historical data at {request.latitude:.3f}, {request.longitude:.3f} for "
            f"{', '.join(sorted(request.codes))} between {request.start_date} and "
            f"{request.end_date} — the point may be over land, or outside the "
            f"product's coverage."
        )

    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame = frame.sort_values("timestamp").reset_index(drop=True)

    coverage = {}
    for code, info in variables.items():
        if info.provider is None:
            continue
        start = catalog.get(info.provider).coverage_start
        if start is not None:
            coverage[code] = start

    provider_keys = {info.provider for info in variables.values() if info.provider}
    return HistorySeries(
        frame=frame,
        latitude=float(frame["latitude"].iloc[0]),
        longitude=float(frame["longitude"].iloc[0]),
        resolution=request.resolution,
        coverage=coverage,
        sources=catalog.source_labels(provider_keys),
    )


async def fetch_recent(
    codes: tuple[str, ...],
    latitude: float,
    longitude: float,
    days: int,
    *,
    resolution: Resolution = Resolution.daily,
    depth_m: float = 0.0,
    use_cache: bool = True,
) -> HistorySeries:
    """`fetch` for the common "last N days up to today" case.

    `days` should already include the feature lookback — see
    `FeatureConfig.max_lookback_days`. Asking for exactly the history window a
    user requested would leave the earliest rows with NaN 30-day rolling
    features and quietly shorten the usable series.
    """
    end = datetime.now(UTC).date()
    return await fetch(
        HistoryRequest(
            codes=codes,
            latitude=latitude,
            longitude=longitude,
            start_date=end - timedelta(days=days),
            end_date=end,
            resolution=resolution,
            depth_m=depth_m,
        ),
        use_cache=use_cache,
    )
