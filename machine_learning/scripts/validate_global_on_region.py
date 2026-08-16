"""Does the global habitat model beat the regional one *over the region*?

TODO §1's last open ML item. A global model that scores well on a global
average can still be worse over the northern Indian Ocean, which is the water
this platform exists for — and a global average will never say so, because the
region is ~2% of the rows.

**The comparison has to be built, not read off the two training reports**, for
two reasons that would each invalidate it:

1. *Different holdouts.* Each model's shipped holdout is its own spatial block
   of its own store. Two numbers from two different sets of water are not a
   comparison.
2. *Leakage.* The shipped global model was trained on every ocean including
   this one, so scoring it on the regional holdout scores it on water it has
   already seen. That is not a forecast of how it generalises here; it is an
   upper bound with the answer written on it.

So this refits the global ensemble with the regional holdout's **spatial blocks
removed from the global training set** — not merely the matching rows, because
a global point 50 km from a held-out regional point is the same water, and
block removal is the whole reason `spatial_block_splits` exists. Both models
are then scored on identical rows.

Run:  .venv/bin/python scripts/validate_global_on_region.py
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
from marine_ml.validation import metrics, splits  # noqa: E402

BLOCK_DEGREES = 3.0
N_SPLITS = 5


def _store(name: str) -> pd.DataFrame:
    path = config.FEATURE_STORE_DIR / f"{name}.parquet"
    if not path.exists():
        raise SystemExit(f"missing feature store: {path}")
    return pd.read_parquet(path)


def _block_ids(frame: pd.DataFrame) -> pd.Series:
    """The same block identity `spatial_block_splits` bins on, recomputed here
    so the global store can be filtered by the *regional* holdout's blocks."""
    lat = np.floor(frame["latitude"] / BLOCK_DEGREES).astype(int)
    lon = np.floor(frame["longitude"] / BLOCK_DEGREES).astype(int)
    return lat.astype(str) + "_" + lon.astype(str)


def _regional_holdout(regional: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The regional model's own final holdout block, reproduced exactly.

    Same construction as `train.run`: `seed + 1`, first fold. Reproduced rather
    than re-derived so the rows are the ones the shipped regional model was
    actually scored on.
    """
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
    """Fit every tier plus the ensemble, and score them on `test_frame`.

    Uses `train.fit_final`, not a private copy — the weighting rule (softmax
    over CV TSS at temperature 0.05) is a decision this repo made once, and a
    validation script that re-implemented it would silently drift from the
    thing being validated.
    """
    # `fit_final` needs per-model CV scores for the ensemble weights. Computing
    # them on the training half keeps the holdout untouched.
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
    holdout["weights"] = str(weights.as_dict() if hasattr(weights, "as_dict") else weights)
    return holdout


def main() -> int:
    regional = _store("fish_habitat_points")
    global_ocean = _store("fish_habitat_points_global_ocean")

    train_frame, test_frame = _regional_holdout(regional)
    print(
        f"regional store: {len(regional):,} rows -> holdout {len(test_frame):,} rows "
        f"({int(test_frame['presence'].sum()):,} presences), "
        f"train {len(train_frame):,}",
        flush=True,
    )

    held_blocks = set(_block_ids(test_frame))
    columns = feature_lib.feature_columns(global_ocean)
    global_usable = feature_lib.drop_unusable_rows(global_ocean, columns)
    global_train = global_usable[~_block_ids(global_usable).isin(held_blocks)]
    removed = len(global_usable) - len(global_train)
    print(
        f"global store: {len(global_usable):,} usable rows, {removed:,} removed for "
        f"falling in {len(held_blocks)} held-out block(s) -> {len(global_train):,} train rows",
        flush=True,
    )

    # One feature space for both. The regional holdout is scored by a model
    # fitted on global columns, so the two column lists must agree; they do,
    # because both stores come from the same fusion layer.
    regional_columns = feature_lib.feature_columns(regional)
    if set(regional_columns) != set(columns):
        missing = set(regional_columns) ^ set(columns)
        print(f"WARNING: column sets differ by {sorted(missing)}", flush=True)
        columns = [c for c in columns if c in set(regional_columns)]

    print("\n--- regional model (trained on the region only) ---", flush=True)
    regional_scores = _fit_and_score(train_frame, test_frame, columns, "region")
    print(regional_scores.round(3).to_string(index=False), flush=True)

    print("\n--- global model (trained worldwide, holdout blocks removed) ---", flush=True)
    global_scores = _fit_and_score(global_train, test_frame, columns, "global")
    print(global_scores.round(3).to_string(index=False), flush=True)

    both = pd.concat([regional_scores, global_scores], ignore_index=True)
    ensembles = both[both["model"] == "ensemble"].set_index("trained_on")

    print("\n=== verdict: the same regional water, both models ===", flush=True)
    for metric in ("tss", "pr_auc", "roc_auc", "boyce"):
        if metric not in ensembles.columns:
            continue
        region_value = float(ensembles.loc["region", metric])
        global_value = float(ensembles.loc["global", metric])
        better = "global" if global_value > region_value else "regional"
        print(
            f"  {metric:8s} regional={region_value:+.3f}  global={global_value:+.3f}  "
            f"-> {better} is better by {abs(global_value - region_value):.3f}",
            flush=True,
        )

    out = config.REPORTS_DIR / "global_vs_regional_habitat.csv"
    config.ensure_directories()
    both.to_csv(out, index=False)
    print(f"\nwrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
