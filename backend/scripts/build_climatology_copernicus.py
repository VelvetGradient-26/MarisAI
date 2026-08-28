"""Build the percentile climatology from the Copernicus GLORYS reanalysis.

    python scripts/build_climatology_copernicus.py

A second climatology beside `scripts/build_climatology.py`'s OISST one, not a
replacement — `services/heatwaves.py`'s detection stays OISST's own answer.
This one exists so `services/upwelling.py`'s SST corroboration can score the
live Copernicus physics field against a climatology fitted on *its own*
product family, which `services/sst_anomaly.py` measured and found
necessary: scoring that field against the OISST-fitted climatology left the
weak tier's contrast unchanged and inverted the strong one.

**The baseline window is not 1991-2020.** The reanalysis (`cmems_mod_glo_phy_
my_0.083deg_P1D-m`) only reaches back to 1993 (altimetry-assimilation era),
so a 1991-2020 baseline is not available and `build_climatology` would reject
it outright (missing years, not silently truncated). This uses 1993-2022 —
30 full years, the longest window this record actually supports — stated
here rather than left for a reader to notice the fitted attrs disagree with
the WMO-standard default.
"""

from __future__ import annotations

import argparse
import asyncio
import calendar
import logging
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import xarray as xr  # noqa: E402

from app.core.s3_pool import widen_s3_connection_pool  # noqa: E402
from forecasting.history import is_retryable  # noqa: E402
from services.climatology import build as build_lib  # noqa: E402
from services.climatology import copernicus_reanalysis, store  # noqa: E402
from services.copernicus_sst import REANALYSIS_CLIMATOLOGY_VARIABLE  # noqa: E402

logger = logging.getLogger("build_climatology_copernicus")

CACHE_ROOT = Path(__file__).resolve().parents[1] / "forecasting" / ".cache" / "copernicus_reanalysis"

VARIABLE = REANALYSIS_CLIMATOLOGY_VARIABLE
SOURCE_FIELD = "thetao"

# The longest 30-year window the reanalysis's own coverage supports — see the
# module docstring for why this is not the OISST climatology's 1991-2020.
DEFAULT_BASELINE_START = 1993
DEFAULT_BASELINE_END = 2022

# The first real 30-year run crashed on a `ReadTimeoutError` against
# `s3.waw3-1.cloudferro.com` after ~10 years, following a multi-hour gap in
# the log consistent with the build machine sleeping mid-run — an otherwise
# healthy CloudFerro session going stale is exactly the transient failure
# `is_retryable`'s fallback (an unrecognised exception is retried) is meant
# to absorb, not a reason to fail a 30-year job outright. Retried per month,
# not per year: a month is ~28s to redo, a year is ~5-8 minutes, and retrying
# the whole gather would repeat the eleven other months that already
# succeeded to work around one that didn't.
_RETRY_ATTEMPTS = 4
_RETRY_BACKOFF_SECONDS = (10.0, 30.0, 60.0)


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "urllib3", "copernicusmarine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def _fetch_month_with_retry(month_start: date, month_end: date, resolution: float) -> xr.Dataset:
    """One month's fetch, retried with backoff on a transient network failure.

    `copernicus_reanalysis.fetch_range` has no retry of its own — it is a thin
    `asyncio.to_thread` wrapper, same as every other fetch in this codebase —
    so this lives at the call site, same split `forecasting/history.py` uses.
    """
    last: Exception | None = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            return await copernicus_reanalysis.fetch_range(month_start, month_end, resolution_deg=resolution)
        except Exception as exc:  # noqa: BLE001 - copernicusmarine/requests raise widely
            last = exc
            if not is_retryable(exc, attempt) or attempt == _RETRY_ATTEMPTS - 1:
                break
            delay = _RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)]
            logger.warning(
                f"{month_start.isoformat()}..{month_end.isoformat()} failed "
                f"(attempt {attempt + 1}/{_RETRY_ATTEMPTS}): {str(exc)[:160]} — retrying in {delay:.0f}s"
            )
            await asyncio.sleep(delay)
    raise last  # type: ignore[misc]


async def _year(year: int, resolution: float, refresh: bool) -> Path:
    """Fetch one calendar year, or return the cached file — same construction
    as `build_climatology.py::_year`, cached separately by source.

    **Fetched one month at a time, not as a single whole-year request, and
    that split is measured rather than a style choice.** Probed live
    2026-08-24 against this dataset's `arco-geo-series` service: a one-month
    request reliably completes in ~28s, while a one-year request did not
    finish in 20+ minutes — worse than 20x a single month's cost, not the
    ~12x a linear per-timestep rate would predict. Twelve monthly requests
    per year costs more fixed per-request overhead than one big request
    would if that scaled, but the whole-year request does not scale, so this
    is the actually-faster shape, not merely the safer one.
    """
    path = CACHE_ROOT / f"thetao_{year}_{resolution:g}deg.nc"

    if path.exists() and not refresh:
        try:
            with xr.open_dataset(path) as cached:
                if "time" not in cached.sizes or int(cached.sizes["time"]) == 0:
                    raise ValueError("cached file has no time axis")
            logger.info(f"{year}: cached")
            return path
        except Exception as exc:  # noqa: BLE001 - any unreadable cache re-fetches
            logger.warning(f"{year}: discarding unusable cache ({exc})")
            path.unlink(missing_ok=True)

    started = time.monotonic()
    monthly: list[xr.Dataset] = []
    for month in range(1, 13):
        month_start = date(year, month, 1)
        month_end = date(year, month, calendar.monthrange(year, month)[1])
        if month_end < copernicus_reanalysis.COVERAGE_START:
            continue
        if month_start < copernicus_reanalysis.COVERAGE_START:
            month_start = copernicus_reanalysis.COVERAGE_START

        month_started = time.monotonic()
        dataset = await _fetch_month_with_retry(month_start, month_end, resolution)
        monthly.append(dataset.load())
        logger.debug(f"{year}-{month:02d}: {time.monotonic() - month_started:.0f}s")

    if not monthly:
        raise copernicus_reanalysis.CopernicusReanalysisError(
            f"{year} is entirely before the reanalysis's coverage start "
            f"({copernicus_reanalysis.COVERAGE_START.isoformat()})"
        )

    combined = xr.concat(monthly, dim="time")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".nc.tmp")
    combined.to_netcdf(temporary)
    temporary.replace(path)
    combined.close()
    for dataset in monthly:
        dataset.close()

    size_mb = path.stat().st_size / 1_048_576
    logger.info(f"{year}: {size_mb:.0f} MB in {time.monotonic() - started:.0f}s")
    return path


async def run(args: argparse.Namespace) -> int:
    years = list(range(args.baseline_start, args.baseline_end + 1))
    logger.info(
        f"building {VARIABLE} climatology over {years[0]}-{years[-1]} "
        f"at {args.resolution:g} deg (+/-{args.window} day window)"
    )

    paths: list[Path] = []
    for year in years:
        paths.append(await _year(year, args.resolution, args.refresh))

    logger.info("opening the cached record ...")
    record = xr.open_mfdataset([str(p) for p in paths], combine="by_coords", chunks={"time": 366})
    record = record.rename({SOURCE_FIELD: "sea_surface_temperature"})

    logger.info("fitting percentiles (this is the CPU half) ...")
    started = time.monotonic()
    loaded = record[["sea_surface_temperature"]].load()
    climatology = await asyncio.to_thread(
        build_lib.build_climatology,
        loaded,
        variable="sea_surface_temperature",
        baseline_start=args.baseline_start,
        baseline_end=args.baseline_end,
        window_days=args.window,
    )
    logger.info(f"fitted in {time.monotonic() - started:.0f}s")

    climatology.attrs["resolution_deg"] = args.resolution
    climatology.attrs["source"] = (
        "Copernicus Marine Service GLORYS reanalysis "
        "(cmems_mod_glo_phy_my_0.083deg_P1D-m, thetao at the surface)"
    )
    path = store.save(climatology, VARIABLE)
    logger.info(f"wrote {path} ({path.stat().st_size / 1_048_576:.1f} MB)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-start", type=int, default=DEFAULT_BASELINE_START)
    parser.add_argument("--baseline-end", type=int, default=DEFAULT_BASELINE_END)
    parser.add_argument(
        "--window",
        type=int,
        default=build_lib.DEFAULT_WINDOW_DAYS,
        help="half-width in days of the day-of-year pooling window",
    )
    parser.add_argument(
        "--resolution",
        type=float,
        default=1.0,
        help="output grid spacing in degrees; the reanalysis is natively 1/12",
    )
    parser.add_argument("--refresh", action="store_true", help="re-download years already cached")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    _configure_logging(args.verbose)
    widen_s3_connection_pool()

    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        logger.warning("interrupted; cached years are kept, rerun to resume")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
