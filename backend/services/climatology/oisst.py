"""NOAA OISST v2.1 through ERDDAP griddap, fetched one calendar year at a time.

The dataset (probed live 2026-08-17): `ncdcOisst21Agg_LonPM180` on the
CoastWatch ERDDAP, daily, 0.25 degree, 1981-09-01 to present, variables
`sst`/`anom`/`err`/`ice` on `[time][zlev][latitude][longitude]` with a singleton
`zlev`.

**The `_LonPM180` suffix is load-bearing and must not be "fixed".** The plain
`ncdcOisst21Agg` serves the same data on a 0-360 longitude axis. Everything in
this codebase — the forecast grids, `field_sampling.is_globally_periodic`, every
bbox a router parses — is -180..180. Switching datasets would keep working and
silently relocate every cell, which is the same failure `services/crw.py`
documents for `NOAA_DHW_Lon0360`.

Two things learned from the rest of this repo apply unchanged:

* **Subscript brackets are percent-encoded.** `providers/gebco.py` records that
  Ifremer's fronting Tomcat 400s on a bare `[`. NOAA tolerates it, but there is
  no reason for two conventions and a host can change.
* **A short probe window measures per-request overhead, not throughput.**
  5 days cost 8.9 s here and a whole year cost far less than 73x that. Do not
  size this fetch from a toy window — TODO.md records the same trap inverting a
  Copernicus ranking.
"""

from __future__ import annotations

import asyncio
import random
from datetime import date

import httpx
import xarray as xr
from loguru import logger

ERDDAP_URL = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/ncdcOisst21Agg_LonPM180.nc"

# The dataset's own coverage, read off its time axis rather than from the
# product page. `crw.py` and `catalog.py` both record coverage this way.
COVERAGE_START = date(1981, 9, 1)

NATIVE_SPACING_DEG = 0.25

# Outer cell centres of the native grid. griddap selects by *value*, so these
# are what a "whole globe" request asks for.
LAT_MIN, LAT_MAX = -89.875, 89.875
LON_MIN, LON_MAX = -179.875, 179.875

# A year of global 1 degree data is ~95 MB and takes minutes, so the timeout is
# generous. It is still a timeout: `forecasting/history` records that the worst
# failure found in this codebase was not an error but a read that never
# returned, and sat there for 98 minutes looking healthy.
_TIMEOUT = httpx.Timeout(900.0, connect=60.0)

# ERDDAP hosts flap, and a 404 is not proof of permanence — the server answers
# 404 "Currently unknown datasetID" while reloading a dataset. Same policy as
# `forecasting/history.is_retryable`: retry the transient ones, and give 404
# exactly one attempt rather than three.
_RETRY_STATUSES = frozenset({404, 408, 425, 429, 500, 502, 503, 504})

# **The backoff is minutes, not seconds, and that is measured rather than
# cautious.** A first draft used 2s/4s and lost the whole 1991 fetch to three
# rejections inside six seconds; probing the host immediately afterwards gave
# a 60s timeout and two 503s, while the identical URL had served 94.6 MB
# twenty minutes earlier. CoastWatch flaps on the ~100s scale (the same
# behaviour `forecasting/history.is_retryable` and `services/crw.py` both
# record), so a retry policy tighter than the flap cannot outlast one — it
# just converts a recoverable outage into a failed batch job while adding
# load to a server that is already struggling.
#
# This is an offline job whose unit of work is a 51s fetch, so waiting minutes
# is proportionate. Jitter keeps a resumed run from re-synchronising with
# whatever it collided with the first time.
_MAX_ATTEMPTS = 5
_BACKOFF_SECONDS = 60.0
_BACKOFF_CEILING_SECONDS = 300.0


class OisstError(RuntimeError):
    """An OISST/ERDDAP request failed."""


def stride_for(resolution_deg: float) -> int:
    """Griddap stride giving `resolution_deg` from the native 0.25 degree grid."""
    stride = round(resolution_deg / NATIVE_SPACING_DEG)
    if stride < 1:
        raise OisstError(
            f"resolution {resolution_deg} deg is finer than OISST's native "
            f"{NATIVE_SPACING_DEG} deg grid"
        )
    return stride


def build_query(start: date, end: date, stride: int, variable: str = "sst") -> str:
    """The percent-encoded griddap selector for a date range."""
    selector = (
        f"{variable}"
        f"[({start.isoformat()}):1:({end.isoformat()})]"
        f"[(0.0):1:(0.0)]"
        f"[({LAT_MIN}):{stride}:({LAT_MAX})]"
        f"[({LON_MIN}):{stride}:({LON_MAX})]"
    )
    return selector.replace("[", "%5B").replace("]", "%5D")


def backoff_for(attempt: int) -> float:
    """Exponential backoff with jitter, capped. See `_BACKOFF_SECONDS`."""
    delay = min(_BACKOFF_SECONDS * (2 ** (attempt - 1)), _BACKOFF_CEILING_SECONDS)
    return delay * random.uniform(0.75, 1.25)


def _retryable(status: int, attempt: int) -> bool:
    """Whether to try again.

    **404 is retried like any other transient here, and that is a deliberate
    departure from `forecasting/history.is_retryable`, which allows it exactly
    one retry.** The rule is the same; the cost that shaped it is not. There,
    a 404 sits on the request path, so retrying a permanently-dead dataset three
    times with backoff adds ~8s to *every* forecast — measured, and the reason
    the allowance is one. Here the caller is a 25-minute offline batch job whose
    unit of work is a 51s fetch, nothing is waiting on it, and the dataset is
    known to exist because the previous years came from it.

    That distinction is not hypothetical: this job died on
    `404 "Currently unknown datasetID=ncdcOisst21Agg_LonPM180"` seven years into
    a thirty-year build — the exact reload window ERDDAP answers 404 during, and
    indistinguishable from a removed dataset except by waiting.
    """
    return status in _RETRY_STATUSES


async def fetch_range(
    start: date,
    end: date,
    *,
    resolution_deg: float = 1.0,
    destination=None,
) -> xr.Dataset:
    """One inclusive date range of global SST, strided to `resolution_deg`.

    Returns a Dataset on `(time, latitude, longitude)` — the singleton `zlev`
    is dropped here rather than by every caller, the same way
    `providers/copernicus.py::_resolve_depth` drops a scalar depth coord so it
    cannot collide in a later merge.
    """
    query = build_query(start, end, stride_for(resolution_deg))
    url = f"{ERDDAP_URL}?{query}"

    payload = await _get(url)
    return _open(payload, destination, start, end)



async def _get(url: str) -> bytes:
    """One retrying GET. Shared so `fetch_range` and `fetch_recent` cannot drift
    apart on retry policy — the half that is easy to get wrong."""
    last: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.content
            break
        except httpx.HTTPStatusError as exc:
            last = exc
            if not _retryable(exc.response.status_code, attempt):
                # ERDDAP puts its real complaint in the body, not the status line.
                raise OisstError(
                    f"OISST returned status {exc.response.status_code}: "
                    f"{exc.response.text[:300]}"
                ) from exc
        except httpx.RequestError as exc:
            last = exc
        if attempt < _MAX_ATTEMPTS:
            delay = backoff_for(attempt)
            logger.warning(
                f"OISST attempt {attempt}/{_MAX_ATTEMPTS} failed ({last}); "
                f"retrying in {delay:.0f}s"
            )
            await asyncio.sleep(delay)
    else:
        raise OisstError(f"OISST request failed after {_MAX_ATTEMPTS} attempts: {last}")
    return payload


def expected_days(start: date, end: date) -> int:
    """Daily fields a complete response covers, inclusive of both ends."""
    return (end - start).days + 1


def verify_span(dataset: xr.Dataset, start: date, end: date) -> None:
    """Reject a response with no usable time axis, and only that.

    **A short year is not an error, and finding that out corrected a wrong
    diagnosis worth recording.** Whole-year requests come back with markedly
    different day counts — measured 2026-08-17: 1991 returns a clean 365 with
    every gap exactly one day, while 1993 returns **163** days spaced mostly two
    and three days apart with 15- and 20-day holes. The first reading was that
    CoastWatch was truncating responses under load, since the host was
    simultaneously flapping. It is not: re-fetching 1993 on a healthy connection
    returns the identical 163 days, and the dataset's own metadata says so —
    `ncdcOisst21Agg` reports `evenlySpaced=false, averageSpacing=1 day 1h 53m`
    over 15,210 values spanning ~16,400 days, i.e. **~1,200 days genuinely
    missing from the aggregate**, concentrated in the early record.

    So the gaps are the archive, not the transport, and a completeness check
    here would reject real data forever. What actually protects the artifact is
    a floor on the samples behind each *estimate*, which is where the
    statistical requirement lives —
    `build.MIN_SAMPLES_PER_ESTIMATE`. A day-of-year percentile does not care
    which years its samples came from; it cares how many there are.
    """
    if "time" not in dataset.sizes or int(dataset.sizes["time"]) == 0:
        raise OisstError(
            f"OISST returned no daily fields for "
            f"{start.isoformat()}..{end.isoformat()}"
        )


def _open(payload: bytes, destination, start: date, end: date) -> xr.Dataset:
    """Open the payload, verify it, and only then promote it into the cache.

    The order is the point. Verifying *after* the rename would leave a truncated
    year sitting in the cache under its final name, where the next run's
    "already cached" check would accept it without ever re-reading the time
    axis — turning a transient server symptom into a permanent bad artifact.
    """
    if destination is None:
        dataset = _drop_zlev(xr.open_dataset(payload))
        verify_span(dataset, start, end)
        return dataset

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".nc.tmp")
    temporary.write_bytes(payload)
    try:
        with xr.open_dataset(temporary) as probe:
            verify_span(probe, start, end)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    temporary.replace(destination)
    return _drop_zlev(xr.open_dataset(destination))


def _drop_zlev(dataset: xr.Dataset) -> xr.Dataset:
    """OISST carries a singleton depth dim. Dropped here rather than by every
    caller, the same way `providers/copernicus.py::_resolve_depth` drops a
    scalar depth coord so it cannot collide in a later merge."""
    if "zlev" in dataset.dims:
        return dataset.isel(zlev=0, drop=True)
    if "zlev" in dataset.coords:
        return dataset.drop_vars("zlev")
    return dataset


# Native grid extents in *index* space, for the `last` selector below.
_LAT_INDEX_MAX = 719
_LON_INDEX_MAX = 1439


def build_recent_query(days: int, stride: int, variable: str = "sst") -> str:
    """A selector for the last `days` timesteps, in ERDDAP index space.

    **Asking for "the last N days" by date does not work, and the failure is
    disguised as a flap.** OISST publishes with a lag — coverage ended
    2026-08-01 when checked on 2026-08-17 — and a griddap request whose time
    range runs past the dataset's end answers **404**, not an empty result. That
    is indistinguishable by status code from the "Currently unknown datasetID"
    reload 404 this module retries, so the refresh burned five attempts and
    about eight minutes of backoff before failing, every time, for a reason no
    amount of retrying could fix.

    `last` sidesteps it entirely by letting the dataset name its own end. It is
    index-space, hence the explicit lat/lon index bounds: the value-space form
    `(last-34)` is accepted but means something else and returns a near-empty
    grid.
    """
    return (
        f"{variable}"
        f"[last-{max(days - 1, 0)}:1:last]"
        f"[0:1:0]"
        f"[0:{stride}:{_LAT_INDEX_MAX}]"
        f"[0:{stride}:{_LON_INDEX_MAX}]"
    ).replace("[", "%5B").replace("]", "%5D")


async def fetch_recent(days: int, *, resolution_deg: float = 1.0) -> xr.Dataset:
    """The dataset's most recent `days` daily fields, whenever they end."""
    query = build_recent_query(days, stride_for(resolution_deg))
    payload = await _get(f"{ERDDAP_URL}?{query}")
    dataset = _drop_zlev(xr.open_dataset(payload))
    if "time" not in dataset.sizes or int(dataset.sizes["time"]) == 0:
        raise OisstError("OISST returned no recent daily fields")
    return dataset
