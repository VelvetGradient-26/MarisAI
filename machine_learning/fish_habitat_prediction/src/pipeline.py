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

# Regions this pipeline can be run over, by CLI name. The default is unchanged;
# `global` is the worldwide model. See `config.GLOBAL_OCEAN` for what going
# global does and does not buy — in short, ~170x the labels inside the *same*
# 2000-2013 window, because the post-2014 drought is global rather than an
# artefact of the regional box.
REGIONS = {
    "north_indian_ocean": config.NORTH_INDIAN_OCEAN,
    "arabian_sea": config.ARABIAN_SEA,
    "global": config.GLOBAL_OCEAN,
}


def _store_name(region: config.Region) -> str:
    """Feature store for ``region``.

    The default region keeps the historic bare name so existing stores, models
    and reports are found unchanged; anything else is suffixed. A global run
    must not overwrite the regional artifacts, because the regional model is
    the baseline the global one has to beat.
    """
    if region.name == config.NORTH_INDIAN_OCEAN.name:
        return FEATURE_STORE_NAME
    return f"{FEATURE_STORE_NAME}_{region.name}"


def _artifact_name(region: config.Region) -> str:
    if region.name == config.NORTH_INDIAN_OCEAN.name:
        return "fish_habitat"
    return f"fish_habitat_{region.name}"


def build(
    refresh_features: bool = False,
    region: config.Region = REGION,
) -> pd.DataFrame:
    """Assemble the labelled, feature-built table (cached in the feature store)."""
    store = _store_name(region)
    if fusion.feature_store_exists(store) and not refresh_features:
        print(f"reading cached feature store {store!r}", flush=True)
        return fusion.read_feature_store(store)

    # A whole-globe fetch is a different access pattern from a regional one and
    # needs three different answers: geo-series over time-series (~12x on the
    # measured global monthly slice), coarsening to the common grid before the
    # array is ever materialised (35 GB otherwise), and year-at-a-time chunking.
    # See marine_ml/sources/copernicus.py for all three measurements.
    wide = region.name == config.GLOBAL_OCEAN.name
    global_kwargs = (
        {
            "coarsen_to": config.GRID_RESOLUTION,
            "chunk_years": True,
            "service": config.GLOBAL_COPERNICUS_SERVICE,
        }
        if wide
        else {}
    )

    print("loading raw zone ...", flush=True)
    physics = copernicus.fetch_physics(region, START, END, "monthly", **global_kwargs)
    bgc = copernicus.fetch_bgc(region, START, END, "monthly", **global_kwargs)
    # Native 1 arc-minute is 233M cells worldwide; thin to the common grid.
    bathymetry = gebco.fetch_bathymetry(
        region, resolution=config.GRID_RESOLUTION if wide else None
    )

    presences = obis.fetch_all_target_species(None, region, START, END)
    if wide:
        # 21.8M records worldwide — enumerating them is not a slow version of
        # this, it is a different thing that never finishes. Sample cells in
        # proportion to survey effort instead; see `obis.sample_target_group`.
        target_group = obis.sample_target_group(region, START, END)
    else:
        target_group = obis.fetch_target_group(region, START, END)
    print(f"  {len(presences)} presence records, {len(target_group)} target-group records",
          flush=True)

    print("building labels (target-group pseudo-absence) ...", flush=True)
    table = label_lib.build_training_table(presences, target_group)
    print(label_lib.summarise(table).to_string(index=False), flush=True)

    print("sampling ocean state and building features ...", flush=True)
    started = time.time()
    frame = feature_lib.build_features(
        table, physics, bgc, bathymetry, region=region, batch_years=wide
    )
    print(f"  built {frame.shape} in {time.time()-started:.1f}s", flush=True)

    fusion.write_feature_store(frame, store)
    return frame


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    refresh = "--refresh-features" in argv

    region = REGION
    if "--region" in argv:
        name = argv[argv.index("--region") + 1]
        if name not in REGIONS:
            print(f"unknown region {name!r}; choose from {', '.join(REGIONS)}")
            return 2
        region = REGIONS[name]
    print(f"region: {region.name} "
          f"({region.west}..{region.east}E, {region.south}..{region.north}N)", flush=True)

    frame = build(refresh_features=refresh, region=region)

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

    train_lib.save(result, _artifact_name(region), region=region)
    print(f"\nsaved models to {config.MODELS_DIR} and reports to {config.REPORTS_DIR}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
