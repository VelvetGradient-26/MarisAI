"""One-off backfill of `services/wind_history.py` from real past wind data.

The live scheduler (`main.py`) calls `wind_history.record()` once per hourly
`copernicus_wind.refresh_wind_cache()` tick, so in ordinary operation the
history simply accumulates over the days the server runs. This script exists
so the "does a rolling wind mean actually widen the corroboration contrast"
question (see `services/wind_history.py`'s own docstring and TODO.md) can be
tested *now*, against real historical timesteps, rather than waiting for
several days of uptime.

    python scripts/backfill_wind_history.py --hours 30

**Deliberately `arco-geo-series`, one timestep at a time — not
`arco-time-series` over the full historical range.** `services/copernicus_wind.py`'s
own `_fetch_latest_grid` already establishes that a single global timestep
via `arco-geo-series` costs ~27s. A global, multi-timestep pull was tried
against `arco-time-series` instead (CLAUDE.md's other documented service,
"fine lat/lon chunks, huge time chunks" — right for one bounded area, many
timesteps) and measured live 2026-08-28: `open_dataset` succeeded but the
`.load()` for just 6 global timesteps did not return within several minutes
and was killed. That is the wrong service for a *global* many-timestep pull
specifically (CLAUDE.md's dichotomy assumes a bounded area on that side), so
this script pays the ~27s cost per timestep instead — slower per-call, but
each call is the one already proven to work.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from scipy.interpolate import RegularGridInterpolator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from services import wind_history  # noqa: E402
from services.vector_source import VectorSnapshot  # noqa: E402

logger = logging.getLogger("backfill_wind_history")

DATASET_ID = "cmems_obs-wind_glo_phy_nrt_l4_0.125deg_PT1H"
_MIN_VALID_FRACTION = 0.1


def _snapshot_from_timestep(ds, stamp) -> VectorSnapshot | None:
    u_da = ds.eastward_wind.sel(time=stamp).load()
    valid_fraction = float(np.isfinite(u_da.values).mean())
    if valid_fraction < _MIN_VALID_FRACTION:
        logger.warning(f"timestep {str(stamp)[:19]} is only {valid_fraction:.1%} valid globally — skipping")
        return None

    v_da = ds.northward_wind.sel(time=stamp).load()
    lat = u_da.latitude.values.astype(np.float64)
    lon = u_da.longitude.values.astype(np.float64)
    u = u_da.values.astype(np.float64)
    v = v_da.values.astype(np.float64)
    timestamp = datetime.fromisoformat(str(u_da.time.values)[:19]).replace(tzinfo=UTC)

    def interp(values):
        return RegularGridInterpolator((lat, lon), values, method="nearest", bounds_error=False, fill_value=None)

    return VectorSnapshot(
        key="backfill", lat=lat, lon=lon, u=u, v=v,
        u_interp=interp(u), v_interp=interp(v), lon_min=float(lon[0]), timestamp=timestamp,
    )


def backfill(hours: int) -> None:
    """The importable half — also called directly (same process, so the
    same in-memory `wind_history` state) by
    `scripts/measure_wind_history_corroboration.py --backfill-hours`, since
    running this script standalone populates history in a process that then
    exits, leaving nothing for a separately-invoked measurement script to
    read. `services/wind_history.py`'s ring buffer never was meant to survive
    a restart, and it does not survive a second process either."""
    import copernicusmarine

    logger.info(f"opening {DATASET_ID} (arco-geo-series) ...")
    ds = copernicusmarine.open_dataset(
        dataset_id=DATASET_ID,
        variables=["eastward_wind", "northward_wind"],
        username=settings.COPERNICUS_USERNAME,
        password=settings.COPERNICUS_PASSWORD,
        service="arco-geo-series",
    )
    now = datetime.now(UTC)
    past = ds.sel(time=slice(None, now.replace(tzinfo=None)))

    # `copernicus_wind.py`'s own docstring already measured this: the most
    # recent `_MAX_LOOKBACK_STEPS` (30) hourly slots routinely exist but are
    # 100% NaN placeholders, real data resuming only before that tail. A
    # naive `time.values[-hours:]` backfill lands entirely inside that empty
    # window and records nothing — confirmed live 2026-08-28 (24/24 requested
    # timesteps all "0.0% valid globally"). So the requested `hours` are
    # taken from *before* that known-empty tail, not from `now` itself.
    from services.copernicus_wind import _MAX_LOOKBACK_STEPS

    stamps = past.time.values[-(hours + _MAX_LOOKBACK_STEPS) : -_MAX_LOOKBACK_STEPS]

    logger.info(f"backfilling {len(stamps)} timesteps, oldest first (~27s each) ...")
    recorded = 0
    for i, stamp in enumerate(stamps, start=1):
        snapshot = _snapshot_from_timestep(past, stamp)
        if snapshot is not None:
            wind_history.record(snapshot)
            recorded += 1
        logger.info(f"[{i}/{len(stamps)}] {str(stamp)[:19]} -> {'recorded' if snapshot else 'skipped'}")

    mean = wind_history.trailing_mean(min(hours / 24.0, wind_history.RETAIN_DAYS))
    logger.info(f"recorded {recorded}/{len(stamps)} timesteps")
    logger.info(f"trailing_mean: {mean.describe() if mean else 'still unavailable (not enough coverage)'}")


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "urllib3", "copernicusmarine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=24, help="How many trailing hourly timesteps to backfill.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    _configure_logging(args.verbose)
    backfill(args.hours)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
