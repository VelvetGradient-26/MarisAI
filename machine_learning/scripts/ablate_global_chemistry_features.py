"""Does removing the global model's two displaced-chemistry features close
the regional-holdout gap?

NOTE: restricted to the LightGBM tier only (not the full 3-model ensemble).
The paper's mechanism claim is specifically about the LightGBM tier's SHAP
ranking, so this is a more direct test of that claim, not a shortcut around
it -- and the full ensemble fit (5-fold CV x 3 tiers x 2 feature sets, plus
2 final fits) proved too slow to finish in a reasonable session. Re-run with
all three tiers restored (delete the MODEL_BUILDERS restriction below) for a
full-ensemble confirmation if time allows later.

`validate_global_on_region.py` shows the global habitat ensemble scores worse
than the regional one on identical regional holdout rows, and SHAP shows the
global model's two leading features are `o2` (dissolved oxygen) and
`thetao_lag60` (60-day lagged temperature) — displacing `depth` and
`distance_to_coast`, the regional model's leading features. That is a
*plausible reading* of the SHAP evidence for the mechanism, not a test of it:
SHAP importance says the model relies on those features, not that removing
them would help. This script is the test research/papers/global_vs_regional's
Limitations section names as missing.

Two things this is NOT trying to show: this does not retune the global
model's architecture or reweight the ensemble specially for the ablated
feature set beyond what `fit_final` already does (same CV-then-softmax
routine as every other model in this codebase); and it does not touch the
regional model, since the mechanism claim is specifically about what the
*global* model's much larger population does to feature reliance, not about
whether the regional model needs those features (it demonstrably does not —
they are not its top features to begin with).

Run:  .venv/bin/python scripts/ablate_global_chemistry_features.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fish_habitat_prediction.src import features as feature_lib  # noqa: E402
from fish_habitat_prediction.src import models as model_lib  # noqa: E402
from fish_habitat_prediction.src import train as train_lib  # noqa: E402
from marine_ml import config  # noqa: E402
from marine_ml.validation import splits  # noqa: E402

# Restricted to LightGBM only -- see module docstring. This is what
# cross_validate/fit_final iterate over internally.
model_lib.MODEL_BUILDERS = {"lightgbm": model_lib.MODEL_BUILDERS["lightgbm"]}

BLOCK_DEGREES = 3.0
N_SPLITS = 5

# The two features SHAP identifies as displacing depth / distance_to_coast in
# the global model. Named, not inferred, so the ablation tests exactly the
# claim the paper makes rather than a broader guess at "chemistry features".
ABLATED_FEATURES = ["o2", "thetao_lag60"]


def _store(name: str) -> pd.DataFrame:
    path = config.FEATURE_STORE_DIR / f"{name}.parquet"
    if not path.exists():
        raise SystemExit(f"missing feature store: {path}")
    return pd.read_parquet(path)


def _block_ids(frame: pd.DataFrame) -> pd.Series:
    lat = np.floor(frame["latitude"] / BLOCK_DEGREES).astype(int)
    lon = np.floor(frame["longitude"] / BLOCK_DEGREES).astype(int)
    return lat.astype(str) + "_" + lon.astype(str)


def _regional_holdout(regional: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reproduced exactly as in validate_global_on_region.py, so the holdout
    rows are identical across both experiments."""
    columns = feature_lib.feature_columns(regional)
    frame = feature_lib.drop_unusable_rows(regional, columns)
    split = next(
        iter(
            splits.spatial_block_splits(
                frame["latitude"],
                frame["longitude"],
                n_splits=N_SPLITS,
                block_degrees=BLOCK_DEGREES,
                seed=config.RANDOM_SEED + 1,
            )
        )
    )
    return frame.iloc[split.train], frame.iloc[split.test]


def _fit_and_score(
    train_frame: pd.DataFrame,
    test_frame: pd.DataFrame,
    columns: list[str],
    label: str,
) -> pd.DataFrame:
    _, model_scores = train_lib.cross_validate(
        train_frame, columns, n_splits=N_SPLITS, block_degrees=BLOCK_DEGREES,
        seed=config.RANDOM_SEED,
    )
    _, holdout, weights = train_lib.fit_final(
        train_frame, test_frame, columns, model_scores, config.RANDOM_SEED
    )
    holdout = holdout.copy()
    holdout.insert(0, "trained_on", label)
    holdout["train_rows"] = len(train_frame)
    holdout["n_features"] = len(columns)
    holdout["weights"] = str(weights.as_dict() if hasattr(weights, "as_dict") else weights)
    return holdout


def main() -> int:
    regional = _store("fish_habitat_points")
    global_ocean = _store("fish_habitat_points_global_ocean")

    train_frame, test_frame = _regional_holdout(regional)
    print(
        f"regional holdout: {len(test_frame):,} rows "
        f"({int(test_frame['presence'].sum()):,} presences)",
        flush=True,
    )

    held_blocks = set(_block_ids(test_frame))
    all_columns = feature_lib.feature_columns(global_ocean)
    global_usable = feature_lib.drop_unusable_rows(global_ocean, all_columns)
    global_train = global_usable[~_block_ids(global_usable).isin(held_blocks)]
    print(
        f"global store: {len(global_train):,} train rows after removing "
        f"{len(held_blocks)} held-out block(s)",
        flush=True,
    )

    regional_columns = feature_lib.feature_columns(regional)
    columns = [c for c in all_columns if c in set(regional_columns)]

    missing = [f for f in ABLATED_FEATURES if f not in columns]
    if missing:
        raise SystemExit(f"ablated feature(s) not found in column set: {missing}")
    ablated_columns = [c for c in columns if c not in ABLATED_FEATURES]
    print(f"full feature set: {len(columns)} columns", flush=True)
    print(f"ablated feature set: {len(ablated_columns)} columns "
          f"(removed {ABLATED_FEATURES})", flush=True)

    print("\n--- global model, full feature set (baseline, same as validate_global_on_region.py) ---",
          flush=True)
    full_scores = _fit_and_score(global_train, test_frame, columns, "global_full")
    print(full_scores.round(3).to_string(index=False), flush=True)

    print(f"\n--- global model, {ABLATED_FEATURES} removed ---", flush=True)
    ablated_scores = _fit_and_score(global_train, test_frame, ablated_columns, "global_ablated")
    print(ablated_scores.round(3).to_string(index=False), flush=True)

    both = pd.concat([full_scores, ablated_scores], ignore_index=True)
    ensembles = both[both["model"] == "ensemble"].set_index("trained_on")

    print("\n=== verdict: does removing the displaced features close the regional-holdout gap? ===",
          flush=True)
    # The gap this ablation is testing against, from validate_global_on_region.py:
    # regional ensemble TSS 0.798 on the same holdout rows.
    regional_tss = 0.798
    for metric in ("tss", "pr_auc", "roc_auc", "boyce"):
        if metric not in ensembles.columns:
            continue
        full_value = float(ensembles.loc["global_full", metric])
        ablated_value = float(ensembles.loc["global_ablated", metric])
        moved = "closer to regional" if metric != "tss" or ablated_value > full_value else "further from regional"
        print(
            f"  {metric:8s} global_full={full_value:+.3f}  global_ablated={ablated_value:+.3f}  "
            f"delta={ablated_value - full_value:+.3f}",
            flush=True,
        )
    print(f"  (for reference: regional ensemble TSS on this holdout = {regional_tss:.3f})", flush=True)

    out = config.REPORTS_DIR / "global_ablation_chemistry_features.csv"
    config.ensure_directories()
    both.to_csv(out, index=False)
    print(f"\nwrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
