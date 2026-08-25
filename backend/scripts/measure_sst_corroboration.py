"""Re-run of `services/sst_anomaly.py`'s own control measurement, against
whichever SST source is asked for.

    python scripts/measure_sst_corroboration.py --source oisst
    python scripts/measure_sst_corroboration.py --source copernicus_reanalysis

Reports the same two numbers the docstring's table does: the "cool anomaly"
contrast and the "below p10" contrast, each the corroborated fraction of
upwelling-favourable coastal cells minus the same fraction of downwelling-
favourable ones (the control — cool water is not expected there, so this is
the denominator of belief, not a second finding about downwelling). Both
arms are computed against the *same* live wind/currents snapshot, so the
only thing that differs between two runs is the SST source.

Not itself the climatology build (`build_climatology_copernicus.py`) — this
is the measurement TODO.md asks to be re-run *after* that baseline exists,
kept as its own script because "does this correction actually work" is a
question worth being able to ask again later, against a rebuilt climatology
or a different region, without re-deriving the methodology from a docstring.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import copernicus_currents, copernicus_sst, copernicus_wind, heatwaves, upwelling  # noqa: E402

logger = logging.getLogger("measure_sst_corroboration")

SOURCES = {
    "oisst": lambda: heatwaves.sst_anomaly_field(),
    "copernicus_reanalysis": lambda: copernicus_sst.anomaly_field(),
}


def _contrasts(field: upwelling.UpwellingField) -> dict[str, float | int | None]:
    """The exact methodology `sst_anomaly.py`'s docstring table used,
    replicated here rather than only living in `UpwellingField.corroboration`
    — that method reports `control_cool_fraction` for the cool-anomaly arm
    only; the below-p10 arm's control needs the same treatment to get a
    second, comparable contrast.
    """
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
        "cool_favourable_fraction": cool_fav_frac,
        "cool_control_fraction": cool_ctrl_frac,
        "cool_contrast": (
            round(cool_fav_frac - cool_ctrl_frac, 4)
            if cool_fav_frac is not None and cool_ctrl_frac is not None
            else None
        ),
        "below_p10_favourable_fraction": p10_fav_frac,
        "below_p10_control_fraction": p10_ctrl_frac,
        "below_p10_contrast": (
            round(p10_fav_frac - p10_ctrl_frac, 4)
            if p10_fav_frac is not None and p10_ctrl_frac is not None
            else None
        ),
    }


async def run(source_name: str) -> int:
    build_field = SOURCES.get(source_name)
    if build_field is None:
        logger.error(f"unknown source {source_name!r}; known: {', '.join(sorted(SOURCES))}")
        return 2

    logger.info("warming wind and currents caches ...")
    await asyncio.gather(copernicus_wind.refresh_wind_cache(), copernicus_currents.refresh_currents_cache())

    if source_name == "oisst":
        logger.info("warming the OISST-fitted heatwave field ...")
        await heatwaves.refresh_cache()
    else:
        logger.info("warming the live Copernicus SST cache ...")
        await copernicus_sst.refresh_sst_cache()

    sst_field = build_field()
    if sst_field is None:
        logger.error(
            f"no SST anomaly field available for source={source_name!r} — "
            "for copernicus_reanalysis, has scripts/build_climatology_copernicus.py "
            "been run yet?"
        )
        return 1

    wind = copernicus_wind.snapshot()
    currents = copernicus_currents.snapshot()
    field = upwelling.detect(wind, currents, sst_field)

    contrasts = _contrasts(field)
    print(f"\nsource: {sst_field.source}")
    print(f"sst timestamp: {sst_field.timestamp.isoformat()}  wind/currents: {field.timestamp.isoformat()}")
    print(f"baseline: {sst_field.baseline}\n")
    for key, value in contrasts.items():
        print(f"  {key}: {value}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=sorted(SOURCES))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "urllib3", "copernicusmarine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return asyncio.run(run(args.source))


if __name__ == "__main__":
    raise SystemExit(main())
