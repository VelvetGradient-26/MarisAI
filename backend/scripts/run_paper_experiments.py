#!/usr/bin/env python
"""The two experiments the skill-audit paper rests on.

    .venv/bin/python scripts/run_paper_experiments.py --all
    .venv/bin/python scripts/run_paper_experiments.py --variable water_temperature

Experiment 1 -- three-way baseline comparison.
    Rolling-origin CV, scoring the model against **persistence** (the last
    observed value) and against a **day-of-year climatology** fitted inside
    each fold on training rows only. Persistence alone cannot support the
    paper's central claim: it decays with horizon while a seasonal cycle does
    not, so a model that has learned nothing but the time of year shows
    *rising* skill against persistence. Climatology is what separates the two
    readings.

Experiment 2 -- leave-one-site-out.
    Train on 23 sites, test on the 24th, which the model has never seen. This
    is the experiment that justifies serving the model at arbitrary
    coordinates rather than only at the two dozen it was fitted on. The split
    is spatial *and* temporal: the held-out site is scored only on the last
    20% of the record, so a fold is never both in the training geography and
    in the training period.

Both run entirely from the on-disk history cache, pinned to a fixed `as_of`
snapshot. That is what makes them reproducible and what turns a ~700s
per-variable fetch into ~1s.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Must precede any forecasting import that reads it at call time; set here so
# a bare `python scripts/run_paper_experiments.py` is reproducible without the
# caller having to remember the variable.
os.environ.setdefault("MARISAI_FROZEN_HISTORY_CACHE", "1")

from forecasting.climatology import (  # noqa: E402
    DEFAULT_WINDOW_DAYS,
    apply_climatology,
    fit_climatology,
)
from forecasting.config import get_config  # noqa: E402
from forecasting.evaluator import (  # noqa: E402
    EvaluationError,
    chronological_split,
    compute_metrics,
    cross_validate,
)
from forecasting.feature_engineering import TARGET, TARGET_ANCHOR  # noqa: E402
from forecasting.preprocessing import TIMESTAMP  # noqa: E402
from forecasting.registry import resolve  # noqa: E402
from forecasting.trainer import (  # noqa: E402
    assemble_training_set,
    build_model,
    decode_prediction,
    encode_target,
)

logger = logging.getLogger("paper_experiments")

# The snapshot every experiment is measured from. Chosen because it is the
# date the shipped models were trained, so the entire history cache is warm
# for it -- see scripts/probe_cache.py, which is what established it.
AS_OF = date(2026, 8, 10)

# The thirteen variables whose 24-point history is fully cached at AS_OF.
# `rainfall` and the others are excluded for cache coverage, not for their
# results; the paper says so rather than presenting thirteen as the whole set.
VARIABLES = [
    "water_temperature",
    "bottom_temperature",
    "water_salinity",
    "significant_wave_height",
    "maximum_wave_height",
    "mean_wave_period",
    "wave_direction",
    "sea_level_anomaly",
    "chlorophyll_a",
    "dissolved_oxygen",
    "ph",
    "nitrate",
    "primary_productivity",
]

OUTPUT = Path(__file__).resolve().parents[1] / "models" / "forecasting" / "_reports" / "paper"


# --------------------------------------------------------------------------
# Shared setup
# --------------------------------------------------------------------------


def site_labels(frame: pd.DataFrame, config: Any, key: str) -> pd.Series:
    """A stable per-row site name, resolved from the row's coordinates.

    The pooled training frame carries latitude/longitude as *features* but
    not the point's name, and the name is what makes a leave-one-site-out
    table readable ("agulhas" rather than "-35.0,20.0").
    """
    points = config.training_for(key).points
    lookup = {(round(p.latitude, 3), round(p.longitude, 3)): p.name for p in points}
    keys = list(
        zip(frame["latitude"].round(3), frame["longitude"].round(3), strict=True)
    )
    return pd.Series(
        [lookup.get(coordinate, f"{coordinate[0]},{coordinate[1]}") for coordinate in keys],
        index=frame.index,
        name="site",
    )


def make_fit_predict(variable: Any, model_config: Any, mode: str, anchor: pd.Series,
                     categorical_columns: list[str]) -> Any:
    """The same fit/encode/decode path the trainer uses, as a closure.

    Reproduced rather than imported because `trainer.train` builds it inline;
    keeping it identical is the point -- an experiment that scored a
    differently-encoded model would not be measuring the shipped one.
    """

    def fit_predict(
        X_train: pd.DataFrame, y_train: pd.Series, X_test: pd.DataFrame
    ) -> np.ndarray:
        model = build_model(model_config)
        model.fit(
            X_train,
            encode_target(
                y_train.to_numpy(dtype="float64"),
                anchor.loc[y_train.index].to_numpy(dtype="float64"),
                mode=mode,
                log_transform=variable.log_transform,
                circular=variable.circular,
            ),
            categorical_feature=[c for c in categorical_columns if c in X_train.columns],
        )
        return decode_prediction(
            np.asarray(model.predict(X_test), dtype="float64"),
            anchor.loc[X_test.index].to_numpy(dtype="float64"),
            mode=mode,
            log_transform=variable.log_transform,
            circular=variable.circular,
        )

    return fit_predict


# --------------------------------------------------------------------------
# Experiment 1: three-way baselines under rolling-origin CV
# --------------------------------------------------------------------------


def run_baseline_comparison(
    frame: pd.DataFrame,
    feature_columns: list[str],
    categorical_columns: list[str],
    key: str,
    horizon: int,
    config: Any,
    window_days: int,
) -> dict[str, Any]:
    variable = resolve(key, config)
    mode = config.target_mode_for(key)
    sites = site_labels(frame, config, key)

    X = frame[feature_columns]
    y_raw = frame[TARGET]
    anchor = frame[TARGET_ANCHOR]

    fit_predict = make_fit_predict(
        variable, config.model_for(key), mode, anchor, categorical_columns
    )

    def climatology_fold(train_positions: np.ndarray, test_positions: np.ndarray) -> np.ndarray:
        """Fit on this fold's training rows, apply to its test rows. Never both."""
        train = frame.iloc[train_positions]
        test = frame.iloc[test_positions]
        fitted = fit_climatology(
            train[TIMESTAMP],
            train[TARGET],
            sites.iloc[train_positions],
            latitudes=train["latitude"],
            longitudes=train["longitude"],
            window_days=window_days,
            circular=variable.circular,
        )
        return apply_climatology(
            fitted,
            test[TIMESTAMP],
            sites.iloc[test_positions],
            latitudes=test["latitude"],
            longitudes=test["longitude"],
        )

    validation = cross_validate(
        X,
        y_raw,
        frame[TIMESTAMP],
        fit_predict,
        horizon_steps=horizon,
        config=config.defaults.validation,
        circular=variable.circular,
        persistence=anchor,
        climatology_fit=climatology_fold,
    )

    return {
        "variable": key,
        "horizon": horizon,
        "rows": int(len(frame)),
        "sites": int(sites.nunique()),
        "circular": bool(variable.circular),
        "unit": variable.unit,
        "label": variable.label,
        "metrics": validation.metrics,
        "folds": validation.folds,
    }


# --------------------------------------------------------------------------
# Experiment 2: leave-one-site-out
# --------------------------------------------------------------------------


def run_leave_one_site_out(
    frame: pd.DataFrame,
    feature_columns: list[str],
    categorical_columns: list[str],
    key: str,
    horizon: int,
    config: Any,
    window_days: int,
) -> list[dict[str, Any]]:
    """Train on 23 sites' past, score the 24th site's future.

    The temporal cut is taken on the *global* timeline before the site is held
    out, so every held-out fold is scored on the same period. Cutting per-site
    would give each site a different test window and make the column
    incomparable across sites.
    """
    variable = resolve(key, config)
    mode = config.target_mode_for(key)
    sites = site_labels(frame, config, key)

    anchor = frame[TARGET_ANCHOR]
    fit_predict = make_fit_predict(
        variable, config.model_for(key), mode, anchor, categorical_columns
    )

    train_positions, test_positions = chronological_split(frame[TIMESTAMP], 0.8, horizon)
    is_early = np.zeros(len(frame), dtype=bool)
    is_early[train_positions] = True
    is_late = np.zeros(len(frame), dtype=bool)
    is_late[test_positions] = True

    results: list[dict[str, Any]] = []
    for site in sorted(sites.unique()):
        held_out = (sites == site).to_numpy()

        train_mask = is_early & ~held_out
        test_mask = is_late & held_out
        if test_mask.sum() < 20 or train_mask.sum() < 200:
            results.append(
                {
                    "variable": key,
                    "horizon": horizon,
                    "site": site,
                    "skipped": "too few rows after the spatial and temporal split",
                    "test_rows": int(test_mask.sum()),
                    "train_rows": int(train_mask.sum()),
                }
            )
            continue

        train = frame[train_mask]
        test = frame[test_mask]

        try:
            predicted = fit_predict(
                train[feature_columns], train[TARGET], test[feature_columns]
            )
        except Exception as exc:  # noqa: BLE001 - one site must not kill the sweep
            results.append(
                {"variable": key, "horizon": horizon, "site": site, "error": str(exc)}
            )
            continue

        # Fitted on the 23 training sites only. The held-out site is not among
        # them, so `apply_climatology` falls back to the nearest fitted site --
        # the spatial analogue of what the model itself is being asked to do.
        fitted = fit_climatology(
            train[TIMESTAMP],
            train[TARGET],
            sites[train_mask],
            latitudes=train["latitude"],
            longitudes=train["longitude"],
            window_days=window_days,
            circular=variable.circular,
        )
        clim = apply_climatology(
            fitted,
            test[TIMESTAMP],
            sites[test_mask],
            latitudes=test["latitude"],
            longitudes=test["longitude"],
        )

        try:
            metrics = compute_metrics(
                test[TARGET].to_numpy(dtype="float64"),
                predicted,
                circular=variable.circular,
                baseline=test[TARGET_ANCHOR].to_numpy(dtype="float64"),
                climatology=clim,
            )
        except EvaluationError as exc:
            results.append(
                {"variable": key, "horizon": horizon, "site": site, "error": str(exc)}
            )
            continue

        results.append(
            {
                "variable": key,
                "horizon": horizon,
                "site": site,
                "train_rows": int(train_mask.sum()),
                "test_rows": int(test_mask.sum()),
                "latitude": float(test["latitude"].iloc[0]),
                "longitude": float(test["longitude"].iloc[0]),
                **metrics,
            }
        )

    return results


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


async def run_variable(
    key: str, horizons: list[int], config: Any, window_days: int, skip_loso: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    baselines: list[dict[str, Any]] = []
    loso: list[dict[str, Any]] = []

    for horizon in horizons:
        started = time.perf_counter()
        try:
            frame, feature_columns, categorical_columns, used, skipped = (
                await assemble_training_set(key, horizon, config, as_of=AS_OF)
            )
        except Exception as exc:  # noqa: BLE001 - report and continue the sweep
            logger.warning(f"{key} h{horizon}: assembly failed: {exc}")
            baselines.append({"variable": key, "horizon": horizon, "error": str(exc)})
            continue

        try:
            result = run_baseline_comparison(
                frame, feature_columns, categorical_columns, key, horizon, config, window_days
            )
            result["points_used"] = used
            result["points_skipped"] = skipped
            baselines.append(result)
            metrics = result["metrics"]
            logger.info(
                f"{key} h{horizon}: skill_persistence="
                f"{metrics.get('skill_score')} skill_climatology="
                f"{metrics.get('skill_vs_climatology')} "
                f"({time.perf_counter() - started:.0f}s)"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"{key} h{horizon}: baseline comparison failed: {exc}")
            baselines.append({"variable": key, "horizon": horizon, "error": str(exc)})

        if not skip_loso:
            started = time.perf_counter()
            try:
                rows = run_leave_one_site_out(
                    frame, feature_columns, categorical_columns, key, horizon,
                    config, window_days,
                )
                loso.extend(rows)
                scored = [r for r in rows if "skill_score" in r]
                if scored:
                    logger.info(
                        f"{key} h{horizon}: LOSO {len(scored)}/{len(rows)} sites scored, "
                        f"median skill="
                        f"{np.median([r['skill_score'] for r in scored]):.3f} "
                        f"({time.perf_counter() - started:.0f}s)"
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"{key} h{horizon}: LOSO failed: {exc}")

    return baselines, loso


async def main_async(args: argparse.Namespace) -> None:
    config = get_config()
    variables = [args.variable] if args.variable else VARIABLES
    horizons = args.horizons or config.defaults.horizons

    OUTPUT.mkdir(parents=True, exist_ok=True)
    all_baselines: list[dict[str, Any]] = []
    all_loso: list[dict[str, Any]] = []

    started = time.perf_counter()
    for key in variables:
        baselines, loso = await run_variable(
            key, horizons, config, args.window_days, args.skip_loso
        )
        all_baselines.extend(baselines)
        all_loso.extend(loso)
        # Written after every variable, not only at the end: the sweep is long
        # enough that an interrupted run must not lose the variables it did
        # finish.
        (OUTPUT / "baselines.json").write_text(json.dumps(all_baselines, indent=2, default=str))
        (OUTPUT / "loso.json").write_text(json.dumps(all_loso, indent=2, default=str))

    (OUTPUT / "meta.json").write_text(
        json.dumps(
            {
                "as_of": AS_OF.isoformat(),
                "climatology_window_days": args.window_days,
                "variables": variables,
                "horizons": horizons,
                "duration_seconds": round(time.perf_counter() - started, 1),
                "loso_temporal_fraction": 0.8,
            },
            indent=2,
        )
    )
    logger.info(f"wrote {OUTPUT} in {time.perf_counter() - started:.0f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variable", help="one variable key; default is all thirteen")
    parser.add_argument("--horizons", type=int, nargs="*", help="default: 1 3 7 30")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--skip-loso", action="store_true")
    parser.add_argument("--all", action="store_true", help="accepted for symmetry")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("forecasting").setLevel(logging.WARNING)
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
