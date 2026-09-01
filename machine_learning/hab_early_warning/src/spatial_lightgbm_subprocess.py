"""Score the reloaded tabular LightGBM model and the persistence baseline
on a given set of test dates — run as a **separate process**, never
imported into anything that also imports `torch`.

Why this file exists at all: measured directly on this machine, `torch`
imported anywhere earlier in the process followed by `joblib.load` of the
LightGBM artifact segfaults (SIGSEGV, no Python traceback — silent) even
with `KMP_DUPLICATE_LIB_OK=TRUE` set. The reverse order (LightGBM first,
`import torch` after) does not crash, but `spatial_train.py` necessarily
loads torch first (it trains the U-Net), so within *that* process there is
no ordering that avoids it. Process isolation is the actual fix — this
script never imports torch, so it never triggers the conflict.

Invoked via `subprocess.run` from `spatial_train.py`, not run by hand.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import joblib
import pandas as pd

from hab_early_warning.src import features as feature_lib
from hab_early_warning.src import train as tabular_train
from hab_early_warning.src import spatial_dataset as sd
from marine_ml import config, fusion


def score(test_dates: pd.DatetimeIndex) -> pd.DataFrame:
    frame = fusion.read_feature_store(sd.STORE_NAME)
    feature_names = feature_lib.feature_columns(frame, (3, 5, 7))
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    mask = frame["date"].isin(set(test_dates)) & frame[sd.TARGET].notna()
    needed = list(dict.fromkeys([*feature_names, sd.TARGET, "chl_zanomaly", "latitude", "longitude", "date"]))
    rows = frame.loc[mask, needed].reset_index(drop=True)
    del frame, mask
    if rows.empty:
        raise sd.SpatialDatasetError("no test rows with a valid bloom_t3 label")

    models_by_horizon = joblib.load(config.MODELS_DIR / "hab_early_warning.joblib")
    lightgbm_model = models_by_horizon[sd.HORIZON]

    result = rows[["date", "latitude", "longitude", sd.TARGET]].copy()
    result["lightgbm_score"] = lightgbm_model.predict_proba(rows[feature_names])[:, 1]
    result["persistence_score"] = tabular_train.persistence_baseline(rows)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-dates-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    test_dates = pd.to_datetime(pd.read_parquet(args.test_dates_file)["date"])
    result = score(test_dates)
    result.to_parquet(args.output, index=False)
    print(f"wrote {len(result)} scored rows to {args.output}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - report cleanly to the parent process
        print(f"spatial_lightgbm_subprocess failed: {exc}", file=sys.stderr, flush=True)
        raise
