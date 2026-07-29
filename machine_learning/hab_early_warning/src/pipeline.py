"""End-to-end HAB early-warning pipeline.

Run with ``python -m hab_early_warning.src.pipeline`` from the
``machine_learning`` directory, after ``scripts/fetch_raw.py``.

Order of operations matters here and is worth stating, because getting it
wrong is the standard way this kind of pipeline reports skill it does not
have. Bloom thresholds and the climatology are fitted **only on the training
period**, then applied everywhere. Both define what counts as an anomaly, so
fitting them on the full record would push the held-out period's own
distribution into the label definition and into the features.
"""

from __future__ import annotations

import sys
import time

import pandas as pd

from marine_ml import config, fusion
from marine_ml.features import temporal
from marine_ml.sources import copernicus, gebco
from marine_ml.validation import splits

from . import features as feature_lib
from . import labels as label_lib
from . import train as train_lib

REGION = config.ARABIAN_SEA
START = config.HAB_START
END = config.HAB_END
FEATURE_STORE_NAME = "hab_gridded"


def build(refresh_features: bool = False) -> pd.DataFrame:
    """Build the labelled, feature-built gridded frame (cached)."""
    if fusion.feature_store_exists(FEATURE_STORE_NAME) and not refresh_features:
        print(f"reading cached feature store {FEATURE_STORE_NAME!r}", flush=True)
        return fusion.read_feature_store(FEATURE_STORE_NAME)

    print("loading raw zone ...", flush=True)
    physics = copernicus.fetch_physics(REGION, START, END, "daily")
    bgc = copernicus.fetch_bgc(REGION, START, END, "daily")
    wind = copernicus.fetch_wind(REGION, START, END)
    bathymetry = gebco.fetch_bathymetry(REGION)

    print("fusing onto the common grid ...", flush=True)
    started = time.time()
    frame = fusion.build_gridded_frame(
        physics, bgc, bathymetry, region=REGION, wind=wind
    )
    print(f"  {frame.shape} in {time.time()-started:.1f}s", flush=True)

    # --- training-period-only fits -------------------------------------
    train_mask, _, _ = splits.chronological_split(
        frame["date"], config.TRAIN_FRACTION, config.VALIDATION_FRACTION
    )
    train_frame = frame[train_mask]
    print(f"  fitting thresholds/climatology on {len(train_frame)} training rows "
          f"({train_frame['date'].min().date()}..{train_frame['date'].max().date()})",
          flush=True)

    thresholds = label_lib.fit_bloom_thresholds(train_frame)
    climatology = temporal.fit_climatology(train_frame, ["chl", "thetao"])

    # --- apply everywhere ----------------------------------------------
    frame = label_lib.apply_bloom_thresholds(frame, thresholds)
    frame = temporal.apply_climatology(frame, climatology, ["chl", "thetao"])
    frame = label_lib.add_forecast_labels(frame)

    print("building features ...", flush=True)
    started = time.time()
    frame = feature_lib.build_features(frame)
    frame = feature_lib.add_marine_heatwave_flag(frame)
    print(f"  {frame.shape} in {time.time()-started:.1f}s", flush=True)

    print("\n=== bloom label rates ===", flush=True)
    print(label_lib.summarise(frame).to_string(index=False), flush=True)

    fusion.write_feature_store(frame, FEATURE_STORE_NAME)
    return frame


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    refresh = "--refresh-features" in argv

    frame = build(refresh_features=refresh)
    print("\ntraining (rolling-origin CV) ...", flush=True)
    results = train_lib.run(frame)

    print("\n=== rolling-origin CV: mean skill by horizon ===", flush=True)
    all_folds = pd.concat([r.fold_scores for r in results.values()], ignore_index=True)
    print(
        all_folds.groupby(["horizon", "model"])[["pr_auc", "roc_auc", "brier", "tss"]]
        .mean(numeric_only=True).round(3).to_string(),
        flush=True,
    )

    print("\n=== held-out final period ===", flush=True)
    holdout = pd.concat([r.holdout for r in results.values()], ignore_index=True)
    print(
        holdout[["horizon", "model", "n", "n_positive", "positive_rate",
                 "pr_auc", "roc_auc", "brier", "tss"]].round(3).to_string(index=False),
        flush=True,
    )

    # The verdict that matters: does the model beat "it is blooming now, so it
    # will be blooming then"? Printed explicitly so it cannot be skimmed past.
    print("\n=== model vs persistence baseline (held-out PR-AUC) ===", flush=True)
    for horizon in sorted(results):
        rows = results[horizon].holdout.set_index("model")["pr_auc"]
        model_score = rows.get("lightgbm_calibrated", float("nan"))
        baseline = rows.get("persistence", float("nan"))
        verdict = "BEATS baseline" if model_score > baseline else "LOSES to baseline"
        print(f"  t+{horizon}: model={model_score:.3f} persistence={baseline:.3f}"
              f"  -> {verdict}", flush=True)

    print("\n=== operating point (threshold set for 80% recall) ===", flush=True)
    for horizon, result in results.items():
        point = result.operating_point
        print(f"  t+{horizon}: threshold={point['threshold']:.3f} "
              f"precision={point['precision']:.3f} recall={point['recall']:.3f} "
              f"false_alarm_rate={point['false_alarm_rate']:.3f} "
              f"brier {point['brier_raw']:.3f} -> {point['brier_calibrated']:.3f}",
              flush=True)

    print("\n=== calibration: t+7 reliability, raw vs calibrated ===", flush=True)
    if 7 in results:
        table = results[7].reliability.pivot_table(
            index="bin_lower", columns="variant",
            values=["mean_predicted", "observed_frequency"],
        )
        print(table.round(3).to_string(), flush=True)

    print("\n=== top SHAP drivers (t+7) ===", flush=True)
    if 7 in results:
        print(results[7].importances.head(15).round(4).to_string(index=False), flush=True)

    train_lib.save(results)
    print(f"\nsaved models to {config.MODELS_DIR} and reports to {config.REPORTS_DIR}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
