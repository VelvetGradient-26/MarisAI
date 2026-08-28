"""Build the gridded percentile climatology. Offline only.

    python scripts/build_climatology.py --variable sea_surface_temperature

Measured 2026-08-17 against the live CoastWatch ERDDAP: one calendar year of
global SST strided to 1 degree is **94.6 MB in 51 s**, so the standard
1991-2020 baseline is ~2.8 GB and ~25 minutes of fetching, plus a few minutes
of percentile work. Years are cached to disk as they arrive, so an interrupted
run resumes rather than restarting — the same construction `marine_ml`'s
`chunk_years` uses and for the same reason.

**Do not size this from a short probe.** A 5-day window measured 8.9 s here,
which extrapolates to ~11 minutes per year — 13x the truth. Per-request
overhead dominates a small griddap request, and TODO.md records the same trap
inverting a Copernicus ranking in the opposite direction.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import date
from pathlib import Path

# Allow `python scripts/build_climatology.py` from the backend directory
# without requiring PYTHONPATH to be set by hand.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import xarray as xr  # noqa: E402

from app.core.s3_pool import widen_s3_connection_pool  # noqa: E402
from services.climatology import build as build_lib  # noqa: E402
from services.climatology import oisst, store  # noqa: E402

logger = logging.getLogger("build_climatology")

# Where the per-year downloads are kept between runs. Beside the forecasting
# engine's own fetch cache, and ignored by git for the same reason: it is a
# cache keyed on a fetch window, not an artifact anyone wants back.
CACHE_ROOT = Path(__file__).resolve().parents[1] / "forecasting" / ".cache" / "oisst"

# The one variable OISST serves that this codebase forecasts. Kept as a mapping
# rather than a string so a second source (a percentile climatology for waves,
# say) is a table entry rather than an edit to the loop below.
SOURCE_VARIABLE = {"sea_surface_temperature": "sst"}


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def _year(year: int, resolution: float, refresh: bool) -> Path:
    """Fetch one calendar year, or return the cached file."""
    path = CACHE_ROOT / f"sst_{year}_{resolution:g}deg.nc"
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    if start < oisst.COVERAGE_START:
        start = oisst.COVERAGE_START

    if path.exists() and not refresh:
        # **A cached file is re-verified, not trusted.** CoastWatch returns 200
        # with a truncated body under load, and a truncated year is a valid
        # NetCDF — so a bad file cached by an earlier run (or by a version of
        # this script from before that was understood) would otherwise be
        # accepted forever without its time axis ever being read again.
        try:
            with xr.open_dataset(path) as cached:
                oisst.verify_span(cached, start, end)
            logger.info(f"{year}: cached")
            return path
        except Exception as exc:  # noqa: BLE001 - any unreadable cache re-fetches
            logger.warning(f"{year}: discarding unusable cache ({exc})")
            path.unlink(missing_ok=True)

    started = time.monotonic()
    dataset = await oisst.fetch_range(
        start, end, resolution_deg=resolution, destination=path
    )
    dataset.close()

    size_mb = path.stat().st_size / 1_048_576
    logger.info(f"{year}: {size_mb:.0f} MB in {time.monotonic() - started:.0f}s")
    return path


async def run(args: argparse.Namespace) -> int:
    source = SOURCE_VARIABLE.get(args.variable)
    if source is None:
        logger.error(
            f"no climatology source for {args.variable!r}; "
            f"known: {', '.join(sorted(SOURCE_VARIABLE))}"
        )
        return 2

    years = list(range(args.baseline_start, args.baseline_end + 1))
    logger.info(
        f"building {args.variable} climatology over {years[0]}-{years[-1]} "
        f"at {args.resolution:g} deg (+/-{args.window} day window)"
    )

    paths: list[Path] = []
    for year in years:
        paths.append(await _year(year, args.resolution, args.refresh))

    logger.info("opening the cached record ...")
    # `open_mfdataset` keeps this lazy, so peak memory is the percentile window
    # rather than the whole 2.8 GB record.
    record = xr.open_mfdataset(
        [str(p) for p in paths], combine="by_coords", chunks={"time": 366}
    )
    if "zlev" in record.dims:
        record = record.isel(zlev=0, drop=True)
    record = record.rename({source: args.variable})

    logger.info("fitting percentiles (this is the CPU half) ...")
    started = time.monotonic()
    # `.load()` here rather than inside the fit: the fit indexes the time axis
    # with fancy integer arrays 366 times, which on a dask-backed array would
    # re-read every chunk per day-of-year.
    loaded = record[[args.variable]].load()
    climatology = await asyncio.to_thread(
        build_lib.build_climatology,
        loaded,
        variable=args.variable,
        baseline_start=args.baseline_start,
        baseline_end=args.baseline_end,
        window_days=args.window,
    )
    logger.info(f"fitted in {time.monotonic() - started:.0f}s")

    climatology.attrs["resolution_deg"] = args.resolution
    path = store.save(climatology, args.variable)
    logger.info(f"wrote {path} ({path.stat().st_size / 1_048_576:.1f} MB)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variable", default="sea_surface_temperature")
    parser.add_argument("--baseline-start", type=int, default=build_lib.DEFAULT_BASELINE_START)
    parser.add_argument("--baseline-end", type=int, default=build_lib.DEFAULT_BASELINE_END)
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
        help="output grid spacing in degrees; OISST is natively 0.25",
    )
    parser.add_argument(
        "--refresh", action="store_true", help="re-download years already cached"
    )
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
