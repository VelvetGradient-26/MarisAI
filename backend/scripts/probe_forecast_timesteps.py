"""Step 0 of TODO.md's drift-trajectory-integration item: does either
Copernicus product the combined drift field is built from actually carry a
*future* timestep, and how far ahead?

`services/vector_source.py` has only ever asked for "the latest published
timestep" (`time=slice(None, now)`, walking backward). Nothing in this
codebase has ever asked `PHYSICS_DATASET_ID` (currents, `uo`/`vo`) or
`WAVES_DATASET_ID` (Stokes drift, `VSDX`/`VSDY`) for anything *after* now,
even though both are `GLOBAL_ANALYSISFORECAST_*` products — i.e. the product
family name itself claims a forecast component. This script asks directly,
using the exact same `service="arco-time-series"` fetch this codebase already
proved fast for "bounded area, many timesteps"
(`services/download/providers/copernicus.py::fetch`) rather than writing a
second fetch path.

Two things are measured, not assumed:
  1. How many hours/days beyond "now" the returned time axis actually carries
     *finite* data (a timestep existing in the index and a timestep having
     real values are different claims — this codebase has been burned by that
     distinction before, see `copernicus_wind.py`'s docstring).
  2. Real wall-clock latency for a realistic drift-trajectory-shaped request:
     a ~6-degree bbox, spanning from a day ago through 2 days beyond now.

A known-past control fetch runs first, so an all-NaN future window reads as
"no forecast data published" rather than "this script's request is wrong."

    python scripts/probe_forecast_timesteps.py
    python scripts/probe_forecast_timesteps.py --lat 15.0 --lon 65.0 --half-width 3.0
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.download.providers import copernicus  # noqa: E402

logger = logging.getLogger("probe_forecast_timesteps")

_PRODUCTS = (
    ("currents", copernicus.PHYSICS_DATASET_ID, ["uo", "vo"], copernicus.DEPTH_SURFACE),
    ("stokes_drift", copernicus.WAVES_DATASET_ID, ["VSDX", "VSDY"], copernicus.DEPTH_NONE),
)


def _valid_fraction(dataset, field: str, time_index: int) -> float:
    import numpy as np

    values = dataset[field].isel(time=time_index).values
    return float(np.isfinite(values).mean())


async def _probe_one(
    label: str,
    dataset_id: str,
    fields: list[str],
    depth_mode: str,
    lat: float,
    lon: float,
    half_width: float,
) -> None:
    today = datetime.now(UTC).date()
    bbox = dict(
        west=lon - half_width,
        south=lat - half_width,
        east=lon + half_width,
        north=lat + half_width,
    )

    print(f"\n=== {label} ({dataset_id}) ===")

    # Control: a window entirely in the past, to confirm the harness itself
    # works before trusting a blank result on the future window below.
    control_start = today - timedelta(days=5)
    control_end = today - timedelta(days=1)
    control = await copernicus.fetch(
        dataset_id=dataset_id,
        fields=fields,
        start_date=control_start,
        end_date=control_end,
        depth_mode=depth_mode,
        **bbox,
    )
    control_valid = _valid_fraction(control, fields[0], -1)
    print(
        f"control fetch ({control_start} .. {control_end}): "
        f"{control.sizes.get('time', 0)} timesteps, last-step valid fraction "
        f"{control_valid:.1%}"
    )
    if control_valid < 0.1:
        print("!! control fetch itself came back empty — investigate before trusting anything below")
        return

    # The real question: request through 2 days beyond "now" and see what
    # comes back, timed as a realistic drift-trajectory-shaped request.
    forecast_start = today - timedelta(days=1)
    forecast_end = today + timedelta(days=2)
    t0 = time.monotonic()
    forecast = await copernicus.fetch(
        dataset_id=dataset_id,
        fields=fields,
        start_date=forecast_start,
        end_date=forecast_end,
        depth_mode=depth_mode,
        **bbox,
    )
    elapsed = time.monotonic() - t0

    times = forecast["time"].values
    now = datetime.now(UTC).replace(tzinfo=None)
    print(
        f"forecast-window fetch ({forecast_start} .. {forecast_end}), "
        f"~{2 * half_width:.0f}deg bbox: {elapsed:.1f}s, {len(times)} timesteps"
    )

    future_hours: list[float] = []
    for index, raw_time in enumerate(times):
        stamp = datetime.fromisoformat(str(raw_time)[:19])
        if stamp <= now:
            continue
        lead_hours = (stamp - now).total_seconds() / 3600
        valid = _valid_fraction(forecast, fields[0], index)
        future_hours.append(lead_hours if valid >= 0.1 else float("nan"))
        print(f"  +{lead_hours:6.1f}h  ({stamp.isoformat()})  valid fraction {valid:.1%}")

    finite_future = [h for h in future_hours if h == h]  # drop NaN
    if not finite_future:
        print(f"RESULT: no usable future timestep found for {label} — falls back to the ML grid path")
    else:
        print(
            f"RESULT: {label} carries usable forecast data out to "
            f"+{max(finite_future):.1f}h ({len(finite_future)} usable future steps)"
        )


async def run(lat: float, lon: float, half_width: float) -> None:
    for label, dataset_id, fields, depth_mode in _PRODUCTS:
        try:
            await _probe_one(label, dataset_id, fields, depth_mode, lat, lon, half_width)
        except Exception:  # noqa: BLE001 - a probe script reports, never crashes opaquely
            logger.exception(f"{label} probe failed")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=float, default=15.0, help="Bbox centre latitude (default: Arabian Sea)")
    parser.add_argument("--lon", type=float, default=65.0, help="Bbox centre longitude")
    parser.add_argument("--half-width", type=float, default=3.0, help="Bbox half-width in degrees")
    args = parser.parse_args()
    asyncio.run(run(args.lat, args.lon, args.half_width))


if __name__ == "__main__":
    main()
