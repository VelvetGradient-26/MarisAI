#!/usr/bin/env python
"""Does the long-horizon skill actually come from the seasonal cycle?

    .venv/bin/python scripts/run_seasonality_ablation.py --all

The audit established that models beat persistence while losing to climatology
at long horizons. It did **not** establish *why*. Losing to climatology shows
the model is no better than the seasonal cycle; it does not show the model's
skill is seasonal in origin. A model could be exploiting autocorrelation,
covariate structure and season simultaneously and still lose.

That distinction is the difference between an observation and an explanation,
so it is tested here rather than asserted. Three arms, identical rows,
identical folds, identical hyperparameters -- only the feature set differs:

  full           every feature the shipped model uses
  no_calendar    the same, minus day-of-year/month/week and their sin/cos
                 encodings. If long-horizon skill survives this, it was not
                 coming from the calendar.
  seasonal_only  calendar + static site descriptors ONLY. No lags, no rolling
                 statistics, no trends, and -- critically -- not the raw
                 contemporaneous value either.

The `seasonal_only` arm is defined by *column subsetting rather than config*,
because `build_features` deliberately keeps the raw value y(t) as a feature
(it is the strongest short-horizon predictor there is). Zeroing the lag lists
would leave y(t) in place, and an arm containing y(t) is a persistence model
wearing a seasonal label -- exactly the confound this experiment exists to
rule out.

All three arms share one assembled frame per (variable, horizon), so the
comparison is controlled to the row.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("MARISAI_FROZEN_HISTORY_CACHE", "1")

from forecasting.climatology import apply_climatology, fit_climatology  # noqa: E402
from forecasting.config import get_config  # noqa: E402
from forecasting.evaluator import cross_validate  # noqa: E402
from forecasting.feature_engineering import (  # noqa: E402
    TARGET,
    TARGET_ANCHOR,
    build_features,
)
from forecasting.preprocessing import TIMESTAMP  # noqa: E402
from forecasting.registry import resolve  # noqa: E402
from forecasting.trainer import (  # noqa: E402
    assemble_training_set,
    build_model,
    decode_prediction,
    encode_target,
)
from scripts.run_paper_experiments import AS_OF, VARIABLES, site_labels  # noqa: E402

logger = logging.getLogger("seasonality_ablation")

OUTPUT = Path(__file__).resolve().parents[1] / "models" / "forecasting" / "_reports" / "paper"

STATIC = ("latitude", "longitude", "ocean_depth", "basin")


def _produced_names(key: str, config: Any, features: Any) -> set[str]:
    """Feature names produced for `key` under a given FeatureConfig.

    Built on a tiny synthetic frame, because only the column *names* matter.
    """
    variable = resolve(key, config)
    index = pd.date_range("2024-01-01", periods=150, freq="D")
    frame = pd.DataFrame({TIMESTAMP: index, variable.code: np.linspace(1.0, 2.0, 150)})
    for covariate in variable.covariates:
        frame[covariate] = np.linspace(0.5, 1.5, 150)
    matrix = build_features(
        frame, variable, features, latitude=10.0, longitude=20.0, horizon=1
    )
    return set(matrix.feature_columns)


def calendar_columns(config: Any, key: str) -> set[str]:
    """Which feature names come from the calendar/cyclical encoders.

    Determined by rebuilding the name list with those encoders off and taking
    the set difference, rather than by matching name patterns. Pattern matching
    on `_sin`/`_cos` would also catch a circular variable's own bearing
    encoding, which has nothing to do with the calendar -- ablating it would
    silently remove the wrong thing and make the arm mean something else.
    """
    features = config.features_for(key)
    without = features.model_copy(update={"calendar": False, "cyclical": False})
    return _produced_names(key, config, features) - _produced_names(key, config, without)


def arms_for(config: Any, key: str, feature_columns: list[str]) -> dict[str, list[str]]:
    calendar = calendar_columns(config, key)
    return {
        "full": list(feature_columns),
        "no_calendar": [c for c in feature_columns if c not in calendar],
        "seasonal_only": [c for c in feature_columns if c in calendar or c in STATIC],
    }


def score_arm(
    frame: pd.DataFrame,
    columns: list[str],
    categorical_columns: list[str],
    key: str,
    horizon: int,
    config: Any,
    sites: pd.Series,
) -> dict[str, Any]:
    variable = resolve(key, config)
    mode = config.target_mode_for(key)
    anchor = frame[TARGET_ANCHOR]
    X = frame[columns]

    def fit_predict(X_train, y_train, X_test):
        model = build_model(config.model_for(key))
        model.fit(
            X_train,
            encode_target(
                y_train.to_numpy(dtype="float64"),
                anchor.loc[y_train.index].to_numpy(dtype="float64"),
                mode=mode, log_transform=variable.log_transform,
                circular=variable.circular,
            ),
            categorical_feature=[c for c in categorical_columns if c in X_train.columns],
        )
        return decode_prediction(
            np.asarray(model.predict(X_test), dtype="float64"),
            anchor.loc[X_test.index].to_numpy(dtype="float64"),
            mode=mode, log_transform=variable.log_transform,
            circular=variable.circular,
        )

    def climatology_fold(train_positions, test_positions):
        train, test = frame.iloc[train_positions], frame.iloc[test_positions]
        fitted = fit_climatology(
            train[TIMESTAMP], train[TARGET], sites.iloc[train_positions],
            latitudes=train["latitude"], longitudes=train["longitude"],
            circular=variable.circular,
        )
        return apply_climatology(
            fitted, test[TIMESTAMP], sites.iloc[test_positions],
            latitudes=test["latitude"], longitudes=test["longitude"],
        )

    result = cross_validate(
        X, frame[TARGET], frame[TIMESTAMP], fit_predict,
        horizon_steps=horizon, config=config.defaults.validation,
        circular=variable.circular, persistence=anchor,
        climatology_fit=climatology_fold,
    )
    return result.metrics


async def main_async(args: argparse.Namespace) -> None:
    config = get_config()
    variables = [args.variable] if args.variable else VARIABLES
    horizons = args.horizons or config.defaults.horizons

    records: list[dict[str, Any]] = []
    started = time.perf_counter()

    for key in variables:
        for horizon in horizons:
            try:
                frame, feature_columns, categorical_columns, _used, _skipped = (
                    await assemble_training_set(key, horizon, config, as_of=AS_OF)
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"{key} h{horizon}: assembly failed: {exc}")
                continue

            sites = site_labels(frame, config, key)
            arms = arms_for(config, key, feature_columns)
            report = [f"{key} h{horizon}"]
            for arm, columns in arms.items():
                if not columns:
                    logger.warning(f"{key} h{horizon} [{arm}]: no columns, skipped")
                    continue
                try:
                    metrics = score_arm(frame, columns, categorical_columns,
                                        key, horizon, config, sites)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"{key} h{horizon} [{arm}]: {exc}")
                    continue
                records.append({
                    "variable": key, "horizon": horizon, "arm": arm,
                    "n_features": len(columns),
                    "rmse": metrics.get("rmse"),
                    "persistence_rmse": metrics.get("persistence_rmse"),
                    "climatology_rmse": metrics.get("climatology_rmse"),
                    "skill_p": metrics.get("skill_score"),
                    "skill_c": metrics.get("skill_vs_climatology"),
                })
                report.append(f"{arm}={metrics.get('skill_score')}")
            logger.info("  ".join(report))
            OUTPUT.mkdir(parents=True, exist_ok=True)
            (OUTPUT / "ablation.json").write_text(
                json.dumps(records, indent=2, default=str)
            )

    (OUTPUT / "ablation_meta.json").write_text(json.dumps({
        "as_of": AS_OF.isoformat(),
        "arms": ["full", "no_calendar", "seasonal_only"],
        "variables": variables,
        "horizons": horizons,
        "duration_seconds": round(time.perf_counter() - started, 1),
    }, indent=2))
    logger.info(f"wrote {OUTPUT / 'ablation.json'} in {time.perf_counter() - started:.0f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variable")
    parser.add_argument("--horizons", type=int, nargs="*")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("forecasting").setLevel(logging.WARNING)
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
