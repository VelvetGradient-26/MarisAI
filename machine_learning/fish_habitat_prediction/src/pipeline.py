"""End-to-end fish habitat / PFZ pipeline.

Run with ``python -m fish_habitat_prediction.src.pipeline`` from the
``machine_learning`` directory, after ``scripts/fetch_raw.py`` has populated
the raw zone.
"""

from __future__ import annotations

import sys
import time

import pandas as pd

from marine_ml import config, fusion
from marine_ml.sources import copernicus, gebco, obis

from . import features as feature_lib
from . import labels as label_lib
from . import train as train_lib

REGION = config.NORTH_INDIAN_OCEAN
START = config.HABITAT_START
END = config.HABITAT_END
FEATURE_STORE_NAME = "fish_habitat_points"


def build(refresh_features: bool = False) -> pd.DataFrame:
    """Assemble the labelled, feature-built table (cached in the feature store)."""
    if fusion.feature_store_exists(FEATURE_STORE_NAME) and not refresh_features:
        print(f"reading cached feature store {FEATURE_STORE_NAME!r}", flush=True)
        return fusion.read_feature_store(FEATURE_STORE_NAME)

    print("loading raw zone ...", flush=True)
    physics = copernicus.fetch_physics(REGION, START, END, "monthly")
    bgc = copernicus.fetch_bgc(REGION, START, END, "monthly")
    bathymetry = gebco.fetch_bathymetry(REGION)

    presences = obis.fetch_all_target_species(None, REGION, START, END)
    target_group = obis.fetch_target_group(REGION, START, END)
    print(f"  {len(presences)} presence records, {len(target_group)} target-group records",
          flush=True)

    print("building labels (target-group pseudo-absence) ...", flush=True)
    table = label_lib.build_training_table(presences, target_group)
    print(label_lib.summarise(table).to_string(index=False), flush=True)

    print("sampling ocean state and building features ...", flush=True)
    started = time.time()
    frame = feature_lib.build_features(table, physics, bgc, bathymetry, region=REGION)
    print(f"  built {frame.shape} in {time.time()-started:.1f}s", flush=True)

    fusion.write_feature_store(frame, FEATURE_STORE_NAME)
    return frame


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    refresh = "--refresh-features" in argv

    frame = build(refresh_features=refresh)

    print("\ntraining (spatial block CV) ...", flush=True)
    result = train_lib.run(frame)

    print("\n=== cross-validated skill by model (spatial block CV) ===", flush=True)
    summary = (
        result.fold_scores.groupby("model")[["roc_auc", "pr_auc", "tss", "boyce"]]
        .mean(numeric_only=True)
        .round(3)
    )
    print(summary.to_string(), flush=True)

    print("\n=== held-out spatial block ===", flush=True)
    print(
        result.holdout[
            ["model", "n", "n_positive", "roc_auc", "pr_auc", "tss", "boyce",
             "mess_extrapolating_fraction"]
        ].round(3).to_string(index=False),
        flush=True,
    )

    print("\n=== ensemble weights (from CV TSS) ===", flush=True)
    for name, weight in sorted(
        result.ensemble_weights.weights.items(), key=lambda kv: -kv[1]
    ):
        print(f"  {name:15} {weight:.3f}", flush=True)

    print("\n=== top SHAP drivers (LightGBM) ===", flush=True)
    print(result.importances.head(15).round(4).to_string(index=False), flush=True)

    train_lib.save(result)
    print(f"\nsaved models to {config.MODELS_DIR} and reports to {config.REPORTS_DIR}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
