#!/usr/bin/env python
"""Offline builder for the forecast map's global grids.

    # one variable, every horizon it has a trained model for
    python scripts/build_forecast_grid.py --variable sea_surface_temperature

    # specific horizons, coarser grid (much faster — good for a smoke test)
    python scripts/build_forecast_grid.py --variable sea_surface_temperature \
        --horizons 7 --resolution 2.0

    # every variable that has trained models
    python scripts/build_forecast_grid.py --all

    # what would run, without fetching anything
    python scripts/build_forecast_grid.py --all --dry-run

Like training, this is deliberately offline. A tile request must not be able to
start a job that reads 45 global timesteps from Copernicus and scores 42,000
cells; the tile endpoints serve grids this script wrote, and render an empty
layer when one is missing.

Cost, measured rather than estimated: a sea surface temperature grid is ~35
minutes of Copernicus reads plus ~15 minutes of feature building at the
1-degree default. Every horizon after the first is nearly free, because the
feature matrix is shared and only `model.predict` runs again.

Note what `--resolution` does and does not help. The fetch is whole-globe
either way — Copernicus chunks arrive at full resolution and are thinned after
— so a coarser grid speeds up the cell loop and nothing else. `--resolution
4.0` still pays the full fetch. The reads are cached to disk for 6 hours and
shared across every variable drawing on the same dataset, so the second grid
built in a session is the cell loop alone.

Run from `backend/` so the package imports resolve:

    cd backend && .venv/bin/python scripts/build_forecast_grid.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# Allow `python scripts/build_forecast_grid.py` from the backend directory
# without requiring PYTHONPATH to be set by hand.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forecasting import ForecastingError, progress  # noqa: E402
from forecasting.grid_history import ungriddable_reason  # noqa: E402
from forecasting.grid_predictor import (  # noqa: E402
    build_forecast_grid,
    grid_path,
    save_grid,
)
from forecasting.model_store import list_trained  # noqa: E402

logger = logging.getLogger("build_forecast_grid")


# `urllib3` is here for one specific line: copernicusmarine opens more parallel
# S3 connections than its pool holds and logs "Connection pool is full,
# discarding connection" once or twice a second for the whole fetch. It is
# harmless — the connection is recycled, not the data — but it is thousands of
# lines across a 35-minute read, and it is what the progress bar has to compete
# with.
_NOISY_LOGGERS = ("copernicusmarine", "copernicus_marine_client", "httpx", "urllib3")


class _QuietFilter(logging.Filter):
    """Drops sub-ERROR records from the noisy third-party loggers.

    A filter rather than a level, because `setLevel` alone does not hold:
    `copernicusmarine` configures its own logging when it opens a dataset —
    it attaches a handler *and* resets the level — so a level set here is
    overwritten the moment the first fetch starts. The symptom was every one of
    its banner lines appearing twice, once in its format and once in ours.

    Filters survive that, since nothing upstream clears them, and one installed
    on the logger itself runs before its handlers and before propagation, so it
    silences both copies.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        noisy = record.name.split(".")[0] in _NOISY_LOGGERS
        return record.levelno >= logging.ERROR if noisy else True


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # copernicusmarine logs a banner per dataset open, and a build opens several
    # — left alone it buries the progress bar this script draws underneath it.
    quiet = _QuietFilter()
    for noisy in _NOISY_LOGGERS:
        logger_ = logging.getLogger(noisy)
        logger_.setLevel(logging.ERROR)
        logger_.addFilter(quiet)
    for handler in logging.getLogger().handlers:
        handler.addFilter(quiet)


async def _build_one(variable: str, horizons: list[int], resolution: float) -> bool:
    started = time.monotonic()
    try:
        grid = await build_forecast_grid(
            variable, horizons, resolution_deg=resolution
        )
    except ForecastingError as exc:
        logger.error(f"{variable}: {exc}")
        return False

    path = save_grid(grid, variable)
    elapsed = (time.monotonic() - started) / 60.0
    missing = grid.attrs.get("missing_covariates") or "none"
    logger.info(
        f"{variable}: {grid.attrs['cells_scored']} cells, "
        f"horizons {list(grid.horizon.values)}, {elapsed:.1f} min -> {path}"
    )
    logger.info(f"{variable}: skill {grid.attrs.get('skill_scores')}")
    if missing != "none":
        # Stated every run, not once in a docstring: a grid scored without a
        # covariate the model was trained on is a weaker forecast, and the
        # operator running this is the person who can do something about it.
        logger.warning(
            f"{variable}: scored WITHOUT covariates [{missing}] — no global "
            f"field exists for them (Open-Meteo is a point API). The map legend "
            f"reports this."
        )
    return True


async def _main_async(args: argparse.Namespace) -> int:
    trained = list_trained()
    if not trained:
        logger.error(
            "no trained models found. Train one first: "
            "python scripts/train_forecasting.py --variable sea_surface_temperature"
        )
        return 1

    if args.all:
        selected = dict(trained)
    else:
        if args.variable not in trained:
            logger.error(
                f"{args.variable!r} has no trained model. Available: "
                f"{', '.join(sorted(trained)) or 'none'}"
            )
            return 1
        selected = {args.variable: trained[args.variable]}

    plan: dict[str, list[int]] = {}
    skipped: dict[str, str] = {}
    for variable, available_horizons in selected.items():
        # Checked before any fetch: a variable whose *target* comes from a
        # point API can never have a global grid, and finding that out after
        # ten minutes of Copernicus reads would be a poor way to learn it.
        reason = ungriddable_reason(variable)
        if reason is not None:
            skipped[variable] = reason
            continue

        horizons = args.horizons or available_horizons
        missing = [h for h in horizons if h not in available_horizons]
        if missing:
            # Refuse rather than quietly publishing fewer layers than asked
            # for: a map advertising +30d that silently stops carrying it is
            # worse than a build that fails and says why.
            logger.error(
                f"{variable}: no trained model for horizon(s) "
                f"{', '.join(map(str, missing))} (has: {available_horizons})"
            )
            return 1
        plan[variable] = sorted(horizons)

    for variable, horizons in plan.items():
        existing = grid_path(variable)
        state = "rebuild" if existing.exists() else "new"
        logger.info(
            f"plan: {variable} horizons {horizons} at {args.resolution} deg ({state})"
        )
    for variable, reason in skipped.items():
        logger.warning(f"skipping {variable}: {reason}")

    if not plan:
        logger.error("nothing to build — every selected variable was skipped")
        return 1

    if args.dry_run:
        logger.info("dry run — nothing fetched, nothing written")
        return 0

    failures = 0
    for variable, horizons in plan.items():
        if not await _build_one(variable, horizons, args.resolution):
            failures += 1

    if failures:
        logger.error(f"{failures} of {len(plan)} grid(s) failed")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--variable", help="variable key to build a grid for")
    group.add_argument("--all", action="store_true", help="every variable with trained models")
    parser.add_argument(
        "--horizons",
        type=int,
        nargs="+",
        help="horizons to include (default: every trained horizon)",
    )
    parser.add_argument(
        "--resolution",
        type=float,
        default=1.0,
        help="output grid spacing in degrees (default 1.0; 2.0 is ~4x faster)",
    )
    parser.add_argument("--dry-run", action="store_true", help="plan only, fetch nothing")
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="suppress the progress bars (they are on for this script by default)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    _configure_logging(args.verbose)
    # On here and nowhere else. The same build runs from the API's scheduler,
    # where a bar rewriting stderr would interleave with request logs — see
    # `forecasting/progress.py`.
    progress.enable(not args.no_progress)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
