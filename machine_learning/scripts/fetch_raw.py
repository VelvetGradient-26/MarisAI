"""Populate the raw zone for both problem statements.

Two fetch profiles, because the two problems have genuinely different
resolution needs and the cost difference is large:

``habitat`` (Problem B)
    Monthly means over the wide northern-Indian-Ocean region. OBIS occurrence
    density collapses in a small box, so the region has to be wide; monthly
    means make that affordable (~13 s per year vs. hours for daily), and
    occurrence records carry imprecise dates anyway, so daily fields would be
    false precision against this label source.

``hab`` (Problem A)
    Daily fields over a bounded Arabian Sea box. Daily is not negotiable here
    — the whole product is a t+3/t+5/t+7 day forecast — so the region is what
    gives.

Run with no arguments to fetch both.
"""

from __future__ import annotations

import argparse
import sys
import time

from marine_ml import config
from marine_ml.sources import copernicus, gebco, obis

# Problem B: wide region, monthly, over the window where OBIS labels exist.
HABITAT_REGION = config.NORTH_INDIAN_OCEAN
HABITAT_START = config.HABITAT_START
HABITAT_END = config.HABITAT_END

# Problem A: bounded region, daily.
HAB_REGION = config.ARABIAN_SEA
HAB_START = config.HAB_START
HAB_END = config.HAB_END


def _step(label: str, fn, *args, **kwargs):
    print(f"[{time.strftime('%H:%M:%S')}] {label} ...", flush=True)
    started = time.time()
    result = fn(*args, **kwargs)
    print(f"[{time.strftime('%H:%M:%S')}] {label} done in {time.time()-started:.1f}s", flush=True)
    return result


def fetch_habitat(refresh: bool = False) -> None:
    print(f"\n=== Problem B (fish habitat): {HABITAT_REGION.name}, monthly, "
          f"{HABITAT_START}..{HABITAT_END} ===", flush=True)

    phy = _step("physics (monthly)", copernicus.fetch_physics,
                HABITAT_REGION, HABITAT_START, HABITAT_END, "monthly", refresh=refresh)
    print(f"    dims={dict(phy.sizes)}", flush=True)

    bgc = _step("biogeochemistry (monthly)", copernicus.fetch_bgc,
                HABITAT_REGION, HABITAT_START, HABITAT_END, "monthly", refresh=refresh)
    print(f"    dims={dict(bgc.sizes)}", flush=True)

    bathy = _step("bathymetry", gebco.fetch_bathymetry, HABITAT_REGION, refresh=refresh)
    print(f"    dims={dict(bathy.sizes)}", flush=True)

    presences = _step("OBIS target species", obis.fetch_all_target_species,
                      None, HABITAT_REGION, HABITAT_START, HABITAT_END, refresh)
    print(f"    {len(presences)} presence records", flush=True)
    print(presences.groupby("species_key").size().to_string(), flush=True)

    background = _step("OBIS target group (Actinopterygii)", obis.fetch_target_group,
                       HABITAT_REGION, HABITAT_START, HABITAT_END, refresh=refresh)
    print(f"    {len(background)} background records", flush=True)


def fetch_hab(refresh: bool = False) -> None:
    print(f"\n=== Problem A (HAB): {HAB_REGION.name}, daily, "
          f"{HAB_START}..{HAB_END} ===", flush=True)

    bgc = _step("biogeochemistry (daily)", copernicus.fetch_bgc,
                HAB_REGION, HAB_START, HAB_END, "daily", refresh=refresh)
    print(f"    dims={dict(bgc.sizes)}", flush=True)

    phy = _step("physics (daily)", copernicus.fetch_physics,
                HAB_REGION, HAB_START, HAB_END, "daily", refresh=refresh)
    print(f"    dims={dict(phy.sizes)}", flush=True)

    # Hourly source, fetched a month at a time and averaged to daily — the
    # slowest step in the raw zone (~25 min for two years).
    wind = _step("wind stress (hourly -> daily)", copernicus.fetch_wind,
                 HAB_REGION, HAB_START, HAB_END, refresh=refresh)
    print(f"    dims={dict(wind.sizes)}", flush=True)

    bathy = _step("bathymetry", gebco.fetch_bathymetry, HAB_REGION, refresh=refresh)
    print(f"    dims={dict(bathy.sizes)}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("habitat", "hab", "both"), default="both")
    parser.add_argument("--refresh", action="store_true",
                        help="re-download even if a cached file exists")
    args = parser.parse_args(argv)

    config.ensure_directories()
    if args.profile in ("habitat", "both"):
        fetch_habitat(args.refresh)
    if args.profile in ("hab", "both"):
        fetch_hab(args.refresh)
    print("\nraw zone ready.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
