"""Validation first, bias correction second (see TODO.md): does the live
surface product this platform already serves agree with a real ARGO float's
own shallowest reading?

    python scripts/compare_against_argo.py --lat 15.0 --lon 65.0

**Scope, stated rather than implied.** ARGO floats measure temperature and
salinity by pressure — they do not measure currents, so this cannot validate
`services/currents_depth.py` at all (a genuinely different physical
quantity; validating that would need trajectory-derived velocity, a
different and harder analysis). `water_temperature`/`water_salinity` exist
only as trained forecast models under `models/forecasting/` with no live
backend service to query directly, and `machine_learning/` is a separate
pipeline this backend does not import (see CLAUDE.md) — comparing a
forecast against one profile is also a different, noisier question than
comparing a live field. What this script *can* honestly check, with
services already in `backend/services/`: does `services/copernicus_sst.py`'s
live surface temperature agree with a real float's own shallowest bin, at
the float's own position and as close to its own timestamp as the live
cache allows.

Not a bias-correction pass — see the module's own docstring on why that
must come second. This reports what the disagreement actually is; it does
not try to close it.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import argo, copernicus_sst  # noqa: E402

logger = logging.getLogger("compare_against_argo")


async def run(latitude: float, longitude: float, radius_km: float, lookback_days: int) -> int:
    logger.info(f"searching for an ARGO float within {radius_km:.0f} km of ({latitude}, {longitude}) ...")
    result = await argo.nearest_profile(latitude, longitude, radius_km, lookback_days)
    if not result["available"]:
        logger.error(result["unavailable_reason"])
        return 1

    profile = result["profile"]
    shallowest = next(
        (level for level in profile["levels"] if level["temperature_c"] is not None),
        None,
    )
    if shallowest is None:
        logger.error(f"profile {profile['profile_id']!r} has no level with a temperature reading")
        return 1

    logger.info(
        f"found float {profile['float_id']} — {profile['distance_km']:.1f} km away, "
        f"profiled {profile['timestamp']}, shallowest reading at {shallowest['depth_m']:.1f} m"
    )

    logger.info("warming the live Copernicus SST cache ...")
    await copernicus_sst.refresh_sst_cache()

    live = copernicus_sst.get_point(profile["latitude"], profile["longitude"])
    if live["temperature_c"] is None:
        logger.error("the live SST field has no data at the float's own position (land or no-data cell)")
        return 1

    difference = live["temperature_c"] - shallowest["temperature_c"]
    print("\n--- ARGO vs. live surface SST ---")
    print(f"float:        {profile['float_id']}  (profile {profile['profile_id']})")
    print(f"position:     {profile['latitude']:.3f}, {profile['longitude']:.3f}  ({profile['distance_km']:.1f} km from the query point)")
    print(f"ARGO reading: {shallowest['temperature_c']:.2f} C at {shallowest['depth_m']:.1f} m, profiled {profile['timestamp']}")
    print(f"live SST:     {live['temperature_c']:.2f} C at {live['depth_m']} m, {live['timestamp']} ({live['source']})")
    print(f"difference:   {difference:+.2f} C (live minus ARGO)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--radius-km", type=float, default=argo.DEFAULT_RADIUS_KM)
    parser.add_argument("--lookback-days", type=int, default=argo.DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "urllib3", "copernicusmarine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return asyncio.run(run(args.lat, args.lon, args.radius_km, args.lookback_days))


if __name__ == "__main__":
    raise SystemExit(main())
