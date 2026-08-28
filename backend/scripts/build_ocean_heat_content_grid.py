"""Offline builder for the ocean heat content **field** — the grid
`services/ocean_heat_content_field.py` serves and `services/dashboard/copernicus_series.py`
only ever gives one point of.

    python scripts/build_ocean_heat_content_grid.py

Like the forecast tile grids, this is deliberately offline: a tile/map
request must not be able to start a multi-level Copernicus depth fetch, so
the field endpoints only ever read whatever this script last wrote.

**One fetch, four layers.** The point-series implementation
(`copernicus_series.py`) issues one Copernicus call per layer, because each
is an independent point-timeseries request already paying its own ~10s
regardless. A grid build's fetch is the expensive part, so this script
fetches the full 0-700 m column **once** and integrates all four layers
(50/100/200/700 m — `OHC_LAYERS_M`) from the same array, truncating the
depth axis per layer rather than re-fetching a shallower bound each time.

**Regional (55-95 degE, 5S-25N), not global — see
`services/ocean_heat_content_field.py`'s own docstring for why**: this needs
the whole depth column at every cell, not one surface value, and a global
fetch at that vertical resolution was not attempted. The habitat/HAB
models' own region is reused rather than inventing a new box.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from services.dashboard.copernicus_series import (  # noqa: E402
    _SEAWATER_DENSITY,
    _SEAWATER_HEAT_CAPACITY,
    OHC_LAYERS_M,
    ohc_key,
)
from services.download.providers.copernicus import THETAO_DEPTH_DATASET_ID  # noqa: E402
from services.ocean_heat_content_field import (  # noqa: E402
    GRID_PATH,
    REGION_EAST,
    REGION_NORTH,
    REGION_SOUTH,
    REGION_WEST,
)

logger = logging.getLogger("build_ocean_heat_content_grid")


def _integrate_layer(temperatures: np.ndarray, depths: np.ndarray, max_depth: float) -> np.ndarray:
    """OHC (GJ/m^2) for every (lat, lon) cell, over levels <= `max_depth`.

    Vectorised sibling of `copernicus_series._integrate_heat_content`, which
    operates on one profile at a time — this does every cell in one pass.
    `temperatures` is (depth, lat, lon); NaN only ever appears below a
    cell's own seafloor in this product (contiguous from the bottom), which
    is what makes a per-segment finite-pair mask equivalent to closing each
    column's integral at its real bottom rather than assuming every cell
    reaches `max_depth`.
    """
    within = depths <= max_depth
    if not within.any():
        return np.full(temperatures.shape[1:], np.nan, dtype="float32")

    sub_temps = temperatures[within]
    sub_depths = depths[within]

    # Closed at the surface — the shallowest model level is not exactly at
    # 0 m, the same treatment the scalar version gives a single profile.
    if sub_depths[0] > 0.0:
        sub_temps = np.concatenate([sub_temps[:1], sub_temps], axis=0)
        sub_depths = np.concatenate([[0.0], sub_depths])

    finite = np.isfinite(sub_temps)
    pair_valid = finite[:-1] & finite[1:]
    segment = 0.5 * (np.where(finite[:-1], sub_temps[:-1], 0.0) + np.where(finite[1:], sub_temps[1:], 0.0))
    dz = np.diff(sub_depths)[:, None, None]
    terms = np.where(pair_valid, segment * dz, 0.0)

    has_any_segment = pair_valid.any(axis=0)
    joules = _SEAWATER_DENSITY * _SEAWATER_HEAT_CAPACITY * terms.sum(axis=0)
    return np.where(has_any_segment, joules / 1e9, np.nan).astype("float32")


def build() -> int:
    import copernicusmarine

    now = datetime.now(UTC)
    # The product publishes daily; asking for the last few days and taking
    # the newest lets the dataset's own index name its latest real day
    # rather than guessing "today" and risking an unpublished date — the
    # same `fetch_recent`-style reasoning `services/climatology/oisst.py`
    # already uses for a daily product with a lag.
    start = now - timedelta(days=5)

    logger.info(f"opening {THETAO_DEPTH_DATASET_ID} for {REGION_WEST}-{REGION_EAST}E, {REGION_SOUTH}-{REGION_NORTH}N ...")
    started = time.monotonic()
    dataset = copernicusmarine.open_dataset(
        dataset_id=THETAO_DEPTH_DATASET_ID,
        variables=["thetao"],
        minimum_longitude=REGION_WEST,
        maximum_longitude=REGION_EAST,
        minimum_latitude=REGION_SOUTH,
        maximum_latitude=REGION_NORTH,
        minimum_depth=0.0,
        maximum_depth=OHC_LAYERS_M[-1],
        start_datetime=start.strftime("%Y-%m-%dT00:00:00"),
        end_datetime=now.strftime("%Y-%m-%dT23:59:59"),
        username=settings.COPERNICUS_USERNAME,
        password=settings.COPERNICUS_PASSWORD,
        service="arco-time-series",
    )
    field = dataset["thetao"].isel(time=-1).load()
    timestamp = datetime.fromisoformat(str(field.time.values)[:19]).replace(tzinfo=UTC)
    logger.info(f"fetched timestep {timestamp.isoformat()} in {time.monotonic() - started:.1f}s, shape {field.shape}")

    depths = np.asarray(dataset["depth"].values, dtype="float64")
    values = np.asarray(field.values, dtype="float64")  # (depth, lat, lon)
    latitude = np.asarray(field["latitude"].values, dtype="float64")
    longitude = np.asarray(field["longitude"].values, dtype="float64")

    data_vars = {}
    for depth_m in OHC_LAYERS_M:
        logger.info(f"integrating 0-{depth_m:.0f} m ...")
        layer = _integrate_layer(values, depths, depth_m)
        finite = np.isfinite(layer)
        logger.info(
            f"  {ohc_key(depth_m)}: {int(finite.sum())} valid cells, "
            f"mean {float(np.nanmean(layer)) if finite.any() else float('nan'):.2f} GJ/m^2"
        )
        data_vars[ohc_key(depth_m)] = (("latitude", "longitude"), layer)

    built_at = datetime.now(UTC)
    out = xr.Dataset(
        data_vars,
        coords={"latitude": latitude, "longitude": longitude},
        attrs={"timestamp": timestamp.isoformat(), "built_at": built_at.isoformat()},
    )
    GRID_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_netcdf(GRID_PATH)
    logger.info(f"wrote {GRID_PATH}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "urllib3", "copernicusmarine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return build()


if __name__ == "__main__":
    raise SystemExit(main())
