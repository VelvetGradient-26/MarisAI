#!/usr/bin/env python
"""Does the worldwide habitat model beat the regional one *over the region*?

    python scripts/compare_habitat_global.py

This is the gate for shipping the global PFZ model, and it exists because the
obvious check does not answer the question. A global model is scored over the
whole ocean, so it can post a healthy global average while being **worse over
the northern Indian Ocean** — which is the water this platform is actually for.
The only comparison that decides anything is both models on the same regional
holdout.

Getting that comparison honest takes one non-obvious step. The regional
holdout rows sit *inside* the global model's training set, so scoring the
shipped global model on them would be scoring it on its own training data and
would flatter it enormously. Spatial blocks are keyed on
``floor(lat/3)_floor(lon/3)`` — a pure function of coordinates, independent of
which rows are present — so the regional holdout's block ids can be computed
once and **excluded from the global model's training**, and a global model
refitted without them. Both models are then honest on identical rows.

One caveat this script cannot remove, and prints rather than hides: the two
feature stores derive their physics slightly differently. The regional store
interpolates from native 1/12 degree; the global store block-averages to 0.25
first (the 35 GB problem). So the global model is evaluated on features built
by a marginally different path than it trained on. The effect should be small
relative to the difference being measured, but it is a real asymmetry and the
number is not a pure like-for-like.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from marine_ml import config, fusion  # noqa: E402
from marine_ml.validation import metrics, splits  # noqa: E402

from fish_habitat_prediction.src import features as feature_lib  # noqa: E402
from fish_habitat_prediction.src import train as train_lib  # noqa: E402

REGIONAL_STORE = "fish_habitat_points"
GLOBAL_STORE = "fish_habitat_points_global_ocean"
BLOCK_DEGREES = 3.0
N_SPLITS = 5


def _block_ids(frame: pd.DataFrame, block_degrees: float = BLOCK_DEGREES) -> pd.Series:
    """The same block key `splits.spatial_block_splits` uses.

    Recomputed here rather than imported because the point is to apply *one*
    store's blocks to *another* store's rows, which the splitter has no reason
    to expose.
    """
    lat_block = np.floor(frame["latitude"] / block_degrees).astype(int)
    lon_block = np.floor(frame["longitude"] / block_degrees).astype(int)
    return lat_block.astype(str) + "_" + lon_block.astype(str)


def _regional_holdout(frame: pd.DataFrame, seed: int = config.RANDOM_SEED):
    """The exact final block `train.run` holds out — seed + 1, first fold."""
    split = next(
        iter(
            splits.spatial_block_splits(
                frame["latitude"], frame["longitude"],
                n_splits=N_SPLITS, block_degrees=BLOCK_DEGREES, seed=seed + 1,
            )
        )
    )
    return frame.iloc[split.train], frame.iloc[split.test]


def _score(model, niche, frame: pd.DataFrame, columns: list[str], name: str):
    """One model on one set of rows, through the project's own metric code.

    `metrics.evaluate_classification` rather than a local reimplementation, so
    a number here means the same thing as the same-named number in every
    training report.
    """
    prepared = feature_lib.apply_thermal_niche(frame, niche)
    scores = model.predict_proba(prepared[columns])[:, 1]
    return metrics.evaluate_classification(
        frame["presence"].to_numpy(), scores, name=name, compute_boyce=True
    )


def main() -> int:
    if not fusion.feature_store_exists(GLOBAL_STORE):
        print(f"global feature store {GLOBAL_STORE!r} does not exist yet — run\n"
              f"  python -m fish_habitat_prediction.src.pipeline --region global")
        return 1

    regional = fusion.read_feature_store(REGIONAL_STORE)
    world = fusion.read_feature_store(GLOBAL_STORE)

    columns = feature_lib.feature_columns(regional)
    regional = feature_lib.drop_unusable_rows(regional, columns)
    world = feature_lib.drop_unusable_rows(world, feature_lib.feature_columns(world))

    _, holdout = _regional_holdout(regional)
    holdout_blocks = set(_block_ids(holdout))
    print(f"regional holdout: {len(holdout)} rows, {int(holdout['presence'].sum())} "
          f"presences, across {len(holdout_blocks)} spatial blocks")

    # The honest bit: strip those blocks out of the world before fitting.
    world_blocks = _block_ids(world)
    world_train = world[~world_blocks.isin(holdout_blocks)]
    removed = len(world) - len(world_train)
    print(f"global store: {len(world)} rows, {removed} removed as regional-holdout "
          f"blocks, {len(world_train)} left to train on")

    print("\nfitting the regional baseline on its own training split ...", flush=True)
    regional_train, _ = _regional_holdout(regional)
    regional_fitted, regional_holdout, _ = train_lib.fit_final(
        regional_train, holdout, columns, {"lightgbm": 1.0}, config.RANDOM_SEED
    )

    print("fitting the global model without the regional holdout blocks ...", flush=True)
    global_fitted, global_holdout, _ = train_lib.fit_final(
        world_train, holdout, columns, {"lightgbm": 1.0}, config.RANDOM_SEED
    )

    # fit_final already scored the held-out block for every tier and the
    # ensemble, so take its table rather than recomputing.
    keep = ["model", "n", "n_positive", "roc_auc", "pr_auc", "tss", "boyce",
            "mess_extrapolating_fraction"]
    table = pd.concat(
        [
            regional_holdout.assign(fitted_on="regional"),
            global_holdout.assign(fitted_on="global"),
        ],
        ignore_index=True,
    )[["fitted_on", *keep]]

    print("\n=== both models on the SAME regional holdout ===")
    print(table.round(4).to_string(index=False))

    def _tss(frame: pd.DataFrame, fitted_on: str) -> float:
        row = frame[(frame["fitted_on"] == fitted_on) & (frame["model"] == "ensemble")]
        return float(row["tss"].iloc[0])

    regional_tss, global_tss = _tss(table, "regional"), _tss(table, "global")
    delta = global_tss - regional_tss
    print(f"\nensemble TSS — regional {regional_tss:.4f}, global {global_tss:.4f}")
    print(f"\nTSS delta (global - regional) over the region: {delta:+.4f}")
    print("GATE: " + (
        "global does not regress regionally — shippable"
        if delta >= 0 else
        "global is WORSE over the northern Indian Ocean — do not ship it as the "
        "regional model, whatever its global average says"
    ))

    # Per species, because the aggregate hides the thing already known: the
    # three tunas carry nearly all of the ~170x label gain, while oil sardine
    # (112 records worldwide, all already in-region) gains nothing.
    if "species_key" in holdout.columns:
        print("\n=== per species (TSS) ===")
        per_species = []
        for species, group in holdout.groupby("species_key", observed=True):
            if group["presence"].nunique() < 2:
                continue
            entry = {"species": species, "n": len(group),
                     "n_positive": int(group["presence"].sum())}
            for label, fitted in (("regional", regional_fitted), ("global", global_fitted)):
                entry[label] = _score(
                    fitted["lightgbm"], fitted["_thermal_niche"], group, columns, label
                ).tss
            entry["delta"] = entry["global"] - entry["regional"]
            per_species.append(entry)
        if per_species:
            print(pd.DataFrame(per_species).round(4).to_string(index=False))

    print("\nnote: the two stores derive physics differently (regional interpolates "
          "from 1/12 deg, global block-averages to 0.25 first), so this is not a "
          "pure like-for-like comparison.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
