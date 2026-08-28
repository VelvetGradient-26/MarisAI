"""Does a trailing multi-day wind mean widen the upwelling/SST corroboration
contrast, against the *same* SST source and the *same* currents snapshot?

    python scripts/measure_wind_history_corroboration.py --backfill-hours 72 --window-days 3

`--backfill-hours` calls `scripts/backfill_wind_history.py`'s logic directly,
in this same process, before measuring — running that script on its own
populates `services/wind_history.py`'s in-memory ring buffer in a process
that then exits, leaving nothing for a separately-invoked measurement run to
read. Omit it once the live server has been running long enough on its own
(`services/wind_history.py` records once per hourly wind refresh).

This is the other half of `scripts/measure_sst_corroboration.py`: that
script holds the wind fixed and varies the SST source; this one holds the
SST source fixed (OISST, the one `services/upwelling.py` actually uses in
production) and varies the wind — one instantaneous snapshot
(`upwelling.detect`) against a trailing mean (`upwelling.detect_from_history`).
`services/sst_anomaly.py` and `services/upwelling.py`'s own docstrings both
point at this as the one lever neither of the two already-tried, already-
failed attempts touched: both control arms so far scored an instantaneous
wind against an instantaneous SST reading.

The contrast metric duplicates `_contrasts` in `measure_sst_corroboration.py`
rather than importing it, for the same reason that script gives for not
reusing `UpwellingField.corroboration()` directly: the control arm
(downwelling-favourable cells) needs the identical treatment the favourable
arm gets, computed here so both scripts stay standalone, runnable analyses
rather than needing each other.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.backfill_wind_history import backfill  # noqa: E402
from services import copernicus_currents, copernicus_wind, heatwaves, upwelling, wind_history  # noqa: E402

logger = logging.getLogger("measure_wind_history_corroboration")


def _contrasts(field: upwelling.UpwellingField) -> dict[str, float | int | None]:
    index = field.index
    scored = np.isfinite(index)
    favourable = scored & (index > 0)
    control = scored & (index < 0)

    with_sst_fav = favourable & np.isfinite(field.sst_anomaly)
    with_sst_ctrl = control & np.isfinite(field.sst_anomaly)

    def fraction(mask: np.ndarray, denom: np.ndarray) -> float | None:
        n = int(denom.sum())
        return round(float(mask.sum() / n), 4) if n else None

    cool_fav = with_sst_fav & (field.sst_anomaly <= -upwelling.COOL_ANOMALY_C)
    cool_ctrl = with_sst_ctrl & (field.sst_anomaly <= -upwelling.COOL_ANOMALY_C)
    below_p10_fav = with_sst_fav & np.isfinite(field.sst_cold_exceedance) & (field.sst_cold_exceedance < 0)
    below_p10_ctrl = with_sst_ctrl & np.isfinite(field.sst_cold_exceedance) & (field.sst_cold_exceedance < 0)

    cool_fav_frac = fraction(cool_fav, with_sst_fav)
    cool_ctrl_frac = fraction(cool_ctrl, with_sst_ctrl)
    p10_fav_frac = fraction(below_p10_fav, with_sst_fav)
    p10_ctrl_frac = fraction(below_p10_ctrl, with_sst_ctrl)

    return {
        "favourable_cells_with_sst": int(with_sst_fav.sum()),
        "control_cells_with_sst": int(with_sst_ctrl.sum()),
        "cool_contrast": (
            round(cool_fav_frac - cool_ctrl_frac, 4) if cool_fav_frac is not None and cool_ctrl_frac is not None else None
        ),
        "below_p10_contrast": (
            round(p10_fav_frac - p10_ctrl_frac, 4) if p10_fav_frac is not None and p10_ctrl_frac is not None else None
        ),
    }


async def run(window_days: float, backfill_hours: int | None) -> int:
    if backfill_hours:
        logger.info(f"backfilling {backfill_hours}h of wind history first ...")
        backfill(backfill_hours)

    logger.info("warming wind and currents caches ...")
    await asyncio.gather(copernicus_wind.refresh_wind_cache(), copernicus_currents.refresh_currents_cache())
    logger.info("warming the OISST-fitted heatwave field ...")
    await heatwaves.refresh_cache()

    sst_field = heatwaves.sst_anomaly_field()
    if sst_field is None:
        logger.error("no OISST anomaly field available — has scripts/build_climatology.py been run?")
        return 1

    wind = copernicus_wind.snapshot()
    currents = copernicus_currents.snapshot()

    instantaneous = upwelling.detect(wind, currents, sst_field)
    instantaneous_contrasts = _contrasts(instantaneous)

    mean_transport = wind_history.trailing_mean(window_days)
    if mean_transport is None:
        logger.error(
            f"no {window_days}-day wind history available yet — run "
            "scripts/backfill_wind_history.py first, or let the live server "
            "accumulate it (services/wind_history.py records once per hourly "
            "wind refresh)"
        )
        return 1

    windowed = upwelling.detect_from_history(mean_transport, currents, sst_field)
    windowed_contrasts = _contrasts(windowed)

    print(f"\nsst source: {sst_field.source}  baseline: {sst_field.baseline}")
    print(f"instantaneous wind/currents: {instantaneous.timestamp.isoformat()}")
    print(f"wind window: {mean_transport.describe()}\n")
    print("instantaneous:")
    for key, value in instantaneous_contrasts.items():
        print(f"  {key}: {value}")
    print(f"{window_days}-day trailing mean:")
    for key, value in windowed_contrasts.items():
        print(f"  {key}: {value}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-days", type=float, default=3.0)
    parser.add_argument(
        "--backfill-hours", type=int, default=None,
        help="Populate wind history from real past timesteps first, in this same process.",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "urllib3", "copernicusmarine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return asyncio.run(run(args.window_days, args.backfill_hours))


if __name__ == "__main__":
    raise SystemExit(main())
