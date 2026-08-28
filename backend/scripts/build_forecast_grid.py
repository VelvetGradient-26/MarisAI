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
from datetime import date
from pathlib import Path

# Allow `python scripts/build_forecast_grid.py` from the backend directory
# without requiring PYTHONPATH to be set by hand.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.s3_pool import widen_s3_connection_pool  # noqa: E402
from forecasting import ForecastingError, derived, progress  # noqa: E402
from forecasting.grid_history import ungriddable_reason  # noqa: E402
from forecasting.grid_history import GridRequest, warm  # noqa: E402
from forecasting.grid_predictor import (  # noqa: E402
    build_forecast_grid,
    grid_path,
    grid_request,
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

# Quieted only in this script, and only because of *where* it runs. These are
# MarisAI's own loggers and their messages are worth reading in the point path,
# which handles one location per request. The grid path calls the same code once
# per ocean cell, so each line arrives ~42,000 times per build — identical every
# time, since it reports a property of the fetch window rather than of the cell.
_PER_CELL_LOGGERS = ("forecasting.preprocessing", "forecasting.feature_engineering")


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
        if record.name.split(".")[0] in _NOISY_LOGGERS:
            return record.levelno >= logging.ERROR
        # Per-cell chatter is dropped below WARNING rather than entirely: a
        # genuine warning from the feature builder still needs to reach the
        # operator, it just must not arrive 42,000 times at INFO.
        if record.name in _PER_CELL_LOGGERS:
            return record.levelno >= logging.WARNING
        return True


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # copernicusmarine logs a banner per dataset open, and a build opens several
    # — left alone it buries the progress bar this script draws underneath it.
    quiet = _QuietFilter()
    for name in _PER_CELL_LOGGERS:
        logging.getLogger(name).addFilter(quiet)
    for noisy in _NOISY_LOGGERS:
        logger_ = logging.getLogger(noisy)
        logger_.setLevel(logging.ERROR)
        logger_.addFilter(quiet)
    for handler in logging.getLogger().handlers:
        handler.addFilter(quiet)


def _derive_one(variable: str) -> bool:
    """Assemble a bearing grid from its components rather than scoring cells.

    Seconds instead of ~25 minutes, because a direction is a pointwise function
    of two grids that already exist. It also cannot drift from the point path:
    both call the same convention in `forecasting/derived.py`.
    """
    import xarray as xr

    spec = derived.spec_for(variable)
    assert spec is not None
    missing = [c for c in spec.components if not grid_path(c).exists()]
    if missing:
        logger.warning(
            f"{variable}: cannot derive — component grid(s) missing: "
            f"{', '.join(missing)}. Build those first."
        )
        return False

    with (
        xr.open_dataset(grid_path(spec.east)) as east,
        xr.open_dataset(grid_path(spec.north)) as north,
    ):
        grid = derived.derive_grid(east, north, variable)
        save_grid(grid, variable)
    logger.info(f"{variable}: derived from {spec.east} + {spec.north}")
    return True


async def _build_one(variable: str, horizons: list[int], resolution: float) -> bool:
    started = time.monotonic()
    if derived.is_derived(variable):
        return _derive_one(variable)
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


async def _warm_shared_fetches(plan: dict[str, list[int]], resolution: float) -> None:
    """Fetch each dataset once for the whole plan, rather than once per variable.

    The grid fetch cache is keyed by scope *and* fields, and serves a request
    from any cached entry that contains the fields asked for. That superset rule
    only helps if something wide was cached first — otherwise the first variable
    caches `(uo, zos)`, the second asks for `(vo, zos)`, and the second misses.
    Measured on the run that prompted this: `current_v` repeated `current_u`'s
    whole-globe physics fetch, 35 minutes, for one different field. Across a
    26-variable build that is most of a day of refetching the same products.

    So the union is warmed up front — one provider at a time, since warming does
    not need them co-resident and holding all thirteen is what put a previous run
    into swap — grouped by the window each variable would have asked for — the window comes from `grid_predictor.grid_request`, not
    from a copy of its arithmetic here, because a planner whose window drifts
    from the real one warms a cache nothing then hits and the only symptom is
    that the build is slow.

    Best-effort by construction: a failure here is logged and left to the real
    build, which fetches what it needs and reports properly. Warming must not be
    able to fail a run it exists only to speed up.
    """
    if len(plan) < 2:
        return

    groups: dict[tuple[str, str], set[str]] = {}
    for variable in plan:
        request = grid_request(variable, resolution)
        window = (request.start_date.isoformat(), request.end_date.isoformat())
        groups.setdefault(window, set()).update(request.codes)

    for (start, end), codes in groups.items():
        logger.info(
            f"warming shared fetch for {len(codes)} code(s) over {start}..{end}: "
            f"{', '.join(sorted(codes))}"
        )
        try:
            await warm(
                GridRequest(
                    codes=tuple(sorted(codes)),
                    start_date=date.fromisoformat(start),
                    end_date=date.fromisoformat(end),
                    resolution_deg=resolution,
                )
            )
        except Exception as exc:  # noqa: BLE001 - warming is an optimisation
            logger.warning(f"could not warm shared fetch ({start}..{end}): {exc}")


async def _main_async(args: argparse.Namespace) -> int:
    trained = list_trained()
    if not trained:
        logger.error(
            "no trained models found. Train one first: "
            "python scripts/train_forecasting.py --variable sea_surface_temperature"
        )
        return 1

    # A derived bearing has no model of its own — it is assembled from its two
    # component grids — so it is offered wherever both components are trained.
    # Listed here rather than special-cased at each call site, so `--all` picks
    # them up in the same pass and lands them after the components it needs.
    derivable = {
        name: sorted(set(trained[spec.east]) & set(trained[spec.north]))
        for name, spec in derived.DERIVED.items()
        if spec.east in trained and spec.north in trained
    }

    if args.all:
        selected = {**trained, **derivable}
    else:
        if args.variable in derivable:
            selected = {args.variable: derivable[args.variable]}
        elif args.variable not in trained:
            logger.error(
                f"{args.variable!r} has no trained model. Available: "
                f"{', '.join(sorted({**trained, **derivable})) or 'none'}"
            )
            return 1
        else:
            selected = {args.variable: trained[args.variable]}

    plan: dict[str, list[int]] = {}
    skipped: dict[str, str] = {}
    for variable, available_horizons in selected.items():
        # Resume support, and the reason it exists: a full `--all` run is one
        # shared fetch plus ~30 min of cell loop per variable, so it is measured
        # in hours and anything that interrupts it should not cost the grids
        # already on disk. Mirrors the scheduler's own skip-if-fresh rule rather
        # than inventing a second definition of fresh.
        if args.skip_fresh is not None:
            existing = grid_path(variable)
            if existing.exists():
                age_hours = (time.time() - existing.stat().st_mtime) / 3600.0
                if age_hours < args.skip_fresh:
                    skipped[variable] = (
                        f"grid is {age_hours:.1f}h old, inside --skip-fresh "
                        f"{args.skip_fresh}h"
                    )
                    continue
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

    await _warm_shared_fetches(plan, args.resolution)

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
        "--skip-fresh",
        type=float,
        metavar="HOURS",
        help="skip variables whose grid is newer than HOURS, so an interrupted "
        "multi-variable run resumes instead of restarting",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="suppress the progress bars (they are on for this script by default)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    _configure_logging(args.verbose)
    # `_QuietFilter` above only silences the pool-full line; this removes the
    # handshake churn that produces it. See app/core/s3_pool.py.
    widen_s3_connection_pool()
    # On here and nowhere else. The same build runs from the API's scheduler,
    # where a bar rewriting stderr would interleave with request logs — see
    # `forecasting/progress.py`.
    progress.enable(not args.no_progress)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
