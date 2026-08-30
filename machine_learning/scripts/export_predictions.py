"""Export precomputed prediction grids and a manifest for the web app.

**Batch inference, not live inference.** The approach doc specifies batch
scoring aligned to data cadence (3x/week for PFZ, satellite overpass for HAB),
and that is what this implements: the models run here, offline, and the API
serves the resulting rasters. Three things fall out of that choice:

* The backend needs no scikit-learn, LightGBM or SHAP — it reads NetCDF with
  the numpy/xarray it already has. That keeps `machine_learning` out of the
  backend's import graph, which is a documented boundary in this repo.
* A request can never be slow or fail because a model was slow or failed.
* What the user sees is exactly what was validated, rather than a fresh
  inference path that has never been scored.

Outputs land in ``machine_learning/exports/``:

``habitat_suitability.nc``
    dims (species, month, latitude, longitude) — one seasonal cycle.
``hab_risk.nc``
    dims (horizon, date, latitude, longitude) — recent daily bloom risk.
``hab_risk_shap.nc``
    Companion to ``hab_risk.nc``: per-cell top-k SHAP driver indices and
    contributions, dims (horizon, date, latitude, longitude, top_k). Indices
    resolve against ``manifest.json``'s ``products.hab.shap.feature_names``.
    Optional from the backend's point of view — ``services/predictions.py``
    degrades to ``drivers: None`` if this file is absent.
``manifest.json``
    What exists, what its measured skill is, what drives it, and — as
    prominently — where it should not be trusted.

Run from ``machine_learning``:  ``PYTHONPATH=. python scripts/export_predictions.py``
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

import joblib
import numpy as np
import pandas as pd
import xarray as xr
from tqdm.auto import tqdm

from marine_ml import config, fusion, shap_utils
from marine_ml.features import temporal
from marine_ml.sources import copernicus, gebco

EXPORT_DIR = config.PROJECT_ROOT / "exports"

# Habitat is a monthly model, so one full seasonal cycle is the natural
# export. Lags reach back 60 days, so the frame is built with a run-up and
# then trimmed — otherwise the first two months would carry null lag features
# and quietly score differently from the rest.
HABITAT_OUTPUT_YEAR = 2013
HABITAT_RUNUP_MONTHS = 4

# HAB is daily; the most recent stretch of the held-out period is what a
# dashboard would show.
HAB_OUTPUT_DAYS = 30

# Matches ShapExplainer.explain_row's own default (backend/forecasting/
# shap_explainer.py) so a HAB cell and a live per-variable forecast show the
# same shape of attribution. Independent of _top_drivers' limit=8 (that is
# the *global* mean-|SHAP| ranking over the training sample; this is a
# *local*, per-cell ranking, and the two numbers do not need to match).
HAB_SHAP_TOP_K = 5


# --------------------------------------------------------------------------
# Habitat suitability
# --------------------------------------------------------------------------


def _habitat_feature_frame(region, start: date, end: date) -> pd.DataFrame:
    """Gridded habitat features over a date range.

    Deliberately *not* the median-filling shortcut: the prey-availability lags
    are computed from the real monthly series here, because a suitability
    surface built on imputed prey signal is a different (and worse) product
    than the one that was validated.
    """
    physics = copernicus.fetch_physics(region, config.HABITAT_START, config.HABITAT_END, "monthly")
    bgc = copernicus.fetch_bgc(region, config.HABITAT_START, config.HABITAT_END, "monthly")
    bathymetry = gebco.fetch_bathymetry(region)

    window = slice(start.isoformat(), end.isoformat())
    frame = fusion.build_gridded_frame(
        physics.sel(time=window), bgc.sel(time=window), bathymetry,
        region=region, resolution=config.GRID_RESOLUTION,
    )

    # Monthly cadence, so a "30-day" lag is one step and "60-day" is two.
    frame = temporal.add_lag_features(
        frame, [c for c in ("chl", "thetao", "nppv") if c in frame.columns],
        lags=(30, 60), freq_days=30,
    )
    if {"chl", "chl_lag30"} <= set(frame.columns):
        frame["chl_trend_30d"] = frame["chl"] - frame["chl_lag30"]

    frame["log_depth"] = np.log1p(frame["depth"].clip(lower=0))
    frame["depth_bucket"] = pd.cut(
        frame["depth"], bins=[-np.inf, 50, 200, 1000, 3000, np.inf],
        labels=["nearshore", "shelf", "slope", "deep", "abyssal"],
    ).astype("category")

    cyclical = temporal.cyclical_time_features(frame["date"])
    frame = pd.concat([frame.reset_index(drop=True), cyclical.reset_index(drop=True)], axis=1)
    frame["monsoon_phase"] = temporal.monsoon_phase(frame["date"])
    return frame


def export_habitat() -> dict:
    from fish_habitat_prediction.src import features as feature_lib

    artifact = joblib.load(config.MODELS_DIR / "fish_habitat.joblib")
    models = artifact["models"]
    niche = artifact["thermal_niche"]
    weights = artifact["ensemble_weights"]
    columns = artifact["feature_columns"]

    region = config.NORTH_INDIAN_OCEAN
    runup_start = date(HABITAT_OUTPUT_YEAR - 1, 12 - HABITAT_RUNUP_MONTHS + 1, 1)
    end = date(HABITAT_OUTPUT_YEAR, 12, 31)

    print(f"habitat: building gridded features {runup_start} → {end} ...", flush=True)
    frame = _habitat_feature_frame(region, runup_start, end)
    frame = frame[pd.to_datetime(frame["date"]).dt.year == HABITAT_OUTPUT_YEAR]
    print(f"  {len(frame)} grid-cell-months after trimming the run-up", flush=True)

    latitudes, longitudes = fusion.common_grid(region, config.GRID_RESOLUTION)
    months = sorted(pd.to_datetime(frame["date"]).dt.month.unique())
    species_keys = sorted(config.TARGET_SPECIES)

    grid = np.full((len(species_keys), len(months), len(latitudes), len(longitudes)),
                   np.nan, dtype="float32")

    for si, species_key in enumerate(tqdm(species_keys, desc="habitat species")):
        scored = frame.copy()
        scored["species_key"] = species_key
        scored = feature_lib.apply_thermal_niche(scored, niche)

        missing = [c for c in columns if c not in scored.columns]
        for column in missing:
            scored[column] = np.nan

        # Skill-weighted ensemble — the same combination that was validated,
        # not whichever single model happened to look best.
        blended = np.zeros(len(scored), dtype="float64")
        for name, model in models.items():
            blended += weights.get(name, 0.0) * model.predict_proba(scored[columns])[:, 1]
        scored["suitability"] = blended

        for mi, month in enumerate(months):
            month_rows = scored[pd.to_datetime(scored["date"]).dt.month == month]
            lat_index = np.searchsorted(latitudes, month_rows["latitude"].to_numpy())
            lon_index = np.searchsorted(longitudes, month_rows["longitude"].to_numpy())
            grid[si, mi, lat_index, lon_index] = month_rows["suitability"].to_numpy()

    dataset = xr.Dataset(
        {"suitability": (("species", "month", "latitude", "longitude"), grid)},
        coords={"species": species_keys, "month": months,
                "latitude": latitudes, "longitude": longitudes},
        attrs={
            "title": "Fish habitat suitability (ensemble)",
            "model": "MaxEnt + RandomForest + LightGBM, skill-weighted",
            "year": HABITAT_OUTPUT_YEAR,
            "region": region.name,
            "note": ("Presence-only model. Values are relative habitat suitability, "
                     "not probability of catch."),
        },
    )
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / "habitat_suitability.nc"
    dataset.to_netcdf(path)
    print(f"  wrote {path} ({path.stat().st_size / 1e6:.1f} MB)", flush=True)

    return {
        "species": species_keys,
        "months": [int(m) for m in months],
        "year": HABITAT_OUTPUT_YEAR,
        "missing_features": missing,
    }


# --------------------------------------------------------------------------
# HAB bloom risk
# --------------------------------------------------------------------------


def export_hab() -> dict:
    from hab_early_warning.src import features as feature_lib

    models = joblib.load(config.MODELS_DIR / "hab_early_warning.joblib")
    horizons = sorted(models)

    frame = fusion.read_feature_store("hab_gridded")
    columns = feature_lib.feature_columns(frame, tuple(horizons))
    usable = feature_lib.drop_unusable_rows_all_horizons(frame, columns, tuple(horizons))

    recent_dates = sorted(pd.to_datetime(usable["date"]).unique())[-HAB_OUTPUT_DAYS:]
    recent = usable[pd.to_datetime(usable["date"]).isin(recent_dates)]
    print(f"hab: scoring {len(recent)} grid-cell-days over "
          f"{str(recent_dates[0])[:10]} → {str(recent_dates[-1])[:10]}", flush=True)

    region = config.ARABIAN_SEA
    latitudes, longitudes = fusion.common_grid(region, config.GRID_RESOLUTION)
    grid = np.full((len(horizons), len(recent_dates), len(latitudes), len(longitudes)),
                   np.nan, dtype="float32")
    driver_index_grid = np.full(
        (len(horizons), len(recent_dates), len(latitudes), len(longitudes), HAB_SHAP_TOP_K),
        -1, dtype="int16",
    )
    driver_contribution_grid = np.full(
        (len(horizons), len(recent_dates), len(latitudes), len(longitudes), HAB_SHAP_TOP_K),
        np.nan, dtype="float32",
    )
    shap_feature_names: list[str] | None = None

    for hi, horizon in enumerate(tqdm(horizons, desc="hab horizons")):
        pipeline = shap_utils.unwrap_calibrated_pipeline(models[horizon])
        prep = pipeline.named_steps["prep"]
        booster = pipeline.named_steps["model"]

        # These are the calibrated models, so the numbers are usable as
        # probabilities rather than as bare ranking scores.
        risk = models[horizon].predict_proba(recent[columns])[:, 1]

        # SHAP explains the pre-calibration tree model, not the isotonic
        # wrapper around it -- see marine_ml.shap_utils.unwrap_calibrated_pipeline.
        transformed = prep.transform(recent[columns])
        feature_names = [shap_utils.strip_transform_prefix(n) for n in prep.get_feature_names_out()]
        if shap_feature_names is None:
            shap_feature_names = feature_names
        elif feature_names != shap_feature_names:
            raise RuntimeError(
                f"t+{horizon}'s fitted preprocessor produced different feature "
                f"names than t+{horizons[0]}'s; hab_risk_shap.nc's shared "
                "feature vocabulary (see manifest.json's products.hab.shap."
                "feature_names) assumes every horizon shares one feature "
                "space. Re-check hab_early_warning/src/train.py::build_model, "
                "or give hab_risk_shap.nc a per-horizon feature axis instead."
            )
        contributions = shap_utils.tree_shap_matrix(booster, transformed)
        driver_index, driver_contribution = shap_utils.top_k_indices_and_values(
            contributions, HAB_SHAP_TOP_K
        )

        scored = recent[["latitude", "longitude", "date"]].copy()
        scored["risk"] = risk

        for di, day in enumerate(recent_dates):
            day_mask = (pd.to_datetime(scored["date"]) == day).to_numpy()
            rows = scored[day_mask]
            lat_index = np.searchsorted(latitudes, rows["latitude"].to_numpy())
            lon_index = np.searchsorted(longitudes, rows["longitude"].to_numpy())
            grid[hi, di, lat_index, lon_index] = rows["risk"].to_numpy()
            driver_index_grid[hi, di, lat_index, lon_index, :] = driver_index[day_mask]
            driver_contribution_grid[hi, di, lat_index, lon_index, :] = driver_contribution[day_mask]

    dataset = xr.Dataset(
        {"risk": (("horizon", "date", "latitude", "longitude"), grid)},
        coords={"horizon": horizons,
                "date": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in recent_dates],
                "latitude": latitudes, "longitude": longitudes},
        attrs={
            "title": "Harmful algal bloom risk (calibrated)",
            "model": "LightGBM + isotonic calibration",
            "region": region.name,
            "note": ("Weak labels: chlorophyll above a local seasonal percentile is a "
                     "proxy for a bloom, not a verified or toxic one."),
        },
    )
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / "hab_risk.nc"
    dataset.to_netcdf(path)
    print(f"  wrote {path} ({path.stat().st_size / 1e6:.1f} MB)", flush=True)

    shap_dataset = xr.Dataset(
        {
            "driver_index": (("horizon", "date", "latitude", "longitude", "top_k"), driver_index_grid),
            "driver_contribution": (
                ("horizon", "date", "latitude", "longitude", "top_k"), driver_contribution_grid
            ),
        },
        coords={"horizon": horizons,
                "date": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in recent_dates],
                "latitude": latitudes, "longitude": longitudes,
                "top_k": np.arange(HAB_SHAP_TOP_K)},
        attrs={
            "title": "Harmful algal bloom risk — per-cell SHAP attribution",
            "model": "LightGBM (pre-calibration) TreeSHAP",
            "region": region.name,
            "note": ("driver_index[..., k] indexes into manifest.json's "
                     "products.hab.shap.feature_names for the k-th ranked "
                     "driver at that cell (k=0 strongest |contribution|); -1 "
                     "means no value, same convention as hab_risk.nc's risk "
                     "NaNs. driver_contribution is the signed TreeSHAP value "
                     "in the underlying LightGBM model's margin (log-odds) "
                     "space, on the pre-calibration model -- calibration is "
                     "a monotonic transform of the score, not of which "
                     "feature moved it, so these are not directly additive "
                     "with the calibrated `risk` value in hab_risk.nc."),
        },
    )
    shap_path = EXPORT_DIR / "hab_risk_shap.nc"
    shap_dataset.to_netcdf(shap_path)
    print(f"  wrote {shap_path} ({shap_path.stat().st_size / 1e6:.1f} MB)", flush=True)

    return {
        "horizons": [int(h) for h in horizons],
        "shap_top_k": HAB_SHAP_TOP_K,
        "shap_feature_names": shap_feature_names,
        "dates": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in recent_dates],
    }


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------


def _top_drivers(path, limit=8) -> list[dict]:
    if not path.exists():
        return []
    frame = pd.read_csv(path).head(limit)
    return [
        {
            "feature": row.feature.replace("numeric__", "").replace("categorical__", ""),
            "importance": round(float(row.mean_abs_shap), 4),
        }
        for row in frame.itertuples()
    ]


def build_manifest(habitat_meta: dict, hab_meta: dict) -> dict:
    reports = config.REPORTS_DIR

    habitat_folds = pd.read_csv(reports / "fish_habitat_fold_scores.csv")
    habitat_holdout = pd.read_csv(reports / "fish_habitat_holdout.csv")
    habitat_cv = habitat_folds.groupby("model")[["roc_auc", "pr_auc", "tss", "boyce"]].mean()

    hab_holdout = pd.read_csv(reports / "hab_early_warning_holdout.csv")

    def hab_metric(horizon: int, model: str, column: str):
        rows = hab_holdout[(hab_holdout.horizon == horizon) & (hab_holdout.model == model)]
        return round(float(rows[column].iloc[0]), 3) if len(rows) else None

    horizons_block = []
    for horizon in hab_meta["horizons"]:
        model_score = hab_metric(horizon, "lightgbm_calibrated", "pr_auc")
        baseline = hab_metric(horizon, "persistence", "pr_auc")
        reliability_path = reports / f"hab_early_warning_reliability_t{horizon}.csv"
        reliability = []
        if reliability_path.exists():
            table = pd.read_csv(reliability_path)
            calibrated = table[table.variant == "calibrated"] if "variant" in table else table
            reliability = [
                {"predicted": round(float(r.mean_predicted), 3),
                 "observed": round(float(r.observed_frequency), 3),
                 "n": int(r.n)}
                for r in calibrated.itertuples()
            ]
        horizons_block.append({
            "horizon_days": horizon,
            "pr_auc": model_score,
            "persistence_pr_auc": baseline,
            "beats_baseline": bool(model_score and baseline and model_score > baseline),
            "roc_auc": hab_metric(horizon, "lightgbm_calibrated", "roc_auc"),
            "brier": hab_metric(horizon, "lightgbm_calibrated", "brier"),
            "brier_uncalibrated": hab_metric(horizon, "lightgbm_raw", "brier"),
            "tss": hab_metric(horizon, "lightgbm_calibrated", "tss"),
            "reliability": reliability,
            "drivers": _top_drivers(reports / f"hab_early_warning_shap_t{horizon}.csv"),
        })

    return {
        "generated": pd.Timestamp.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "products": {
            "habitat": {
                "title": "Fish habitat suitability",
                "subtitle": "Potential Fishing Zone — presence-only species distribution model",
                "grid": "habitat_suitability.nc",
                "species": [
                    {"key": key, "scientific_name": config.TARGET_SPECIES[key],
                     "label": key.replace("_", " ").title()}
                    for key in habitat_meta["species"]
                ],
                "months": habitat_meta["months"],
                "year": habitat_meta["year"],
                "region": {
                    "name": config.NORTH_INDIAN_OCEAN.name,
                    "west": config.NORTH_INDIAN_OCEAN.west,
                    "east": config.NORTH_INDIAN_OCEAN.east,
                    "south": config.NORTH_INDIAN_OCEAN.south,
                    "north": config.NORTH_INDIAN_OCEAN.north,
                },
                "training_window": [config.HABITAT_START.isoformat(),
                                    config.HABITAT_END.isoformat()],
                "validation": "spatial block cross-validation, 3° blocks",
                "metrics": {
                    name: {k: round(float(v), 3) for k, v in row.items()}
                    for name, row in habitat_cv.iterrows()
                },
                "holdout": [
                    {"model": row.model,
                     "roc_auc": round(float(row.roc_auc), 3),
                     "pr_auc": round(float(row.pr_auc), 3),
                     "tss": round(float(row.tss), 3),
                     "boyce": round(float(row.boyce), 3)}
                    for row in habitat_holdout.itertuples()
                ],
                "drivers": _top_drivers(reports / "fish_habitat_shap.csv"),
                "value_label": "relative habitat suitability",
                "caveats": [
                    "Presence-only labels — there are no verified absences anywhere in "
                    "this model. Pseudo-absences are drawn from other ray-finned fish "
                    "records so survey bias largely cancels.",
                    "Depth and distance-to-coast dominate the model, and part of that is "
                    "residual sampling geometry rather than pure habitat preference: the "
                    "background pool skews shallower than the pelagic tunas.",
                    "Trained on 2000–2013, the period where occurrence records exist. "
                    "Applying it to present-day conditions is extrapolation.",
                    "Monthly resolution supports strategic questions, not "
                    "'where should a boat go tomorrow'.",
                    "Suitability is relative, not a probability of catch.",
                ],
            },
            "hab": {
                "title": "Harmful algal bloom risk",
                "subtitle": "Early warning — forecast-then-threshold, calibrated probabilities",
                "grid": "hab_risk.nc",
                "horizons": horizons_block,
                "dates": hab_meta["dates"],
                "region": {
                    "name": config.ARABIAN_SEA.name,
                    "west": config.ARABIAN_SEA.west,
                    "east": config.ARABIAN_SEA.east,
                    "south": config.ARABIAN_SEA.south,
                    "north": config.ARABIAN_SEA.north,
                },
                "training_window": [config.HAB_START.isoformat(), config.HAB_END.isoformat()],
                "validation": "rolling-origin cross-validation with an embargo gap",
                "value_label": "probability of bloom",
                "shap": {
                    "available": True,
                    "grid": "hab_risk_shap.nc",
                    "top_k": hab_meta["shap_top_k"],
                    "feature_names": hab_meta["shap_feature_names"],
                },
                "caveats": [
                    "Weak labels: a 'bloom' here is model chlorophyll above a local "
                    "seasonal 90th percentile — a proxy, not a verified bloom, and it "
                    "says nothing about toxicity.",
                    "Toxic-species classification is not implemented; the in-situ genus "
                    "and toxin data it needs is not openly available for this coastline.",
                    "Skill falls sharply with lead time. At 80% recall the false-alarm "
                    "rate is 0.55 at t+3 but 0.80 at t+7 — four in five week-ahead "
                    "alerts would be false.",
                    "Probabilities are isotonic-calibrated on a held-out period, so they "
                    "can be read as probabilities rather than bare scores.",
                    "Per-cell driver attribution (hab_risk_shap.nc) explains the "
                    "pre-calibration LightGBM model in its own margin (log-odds) space, "
                    "not the calibrated probability shown as risk — read it as which "
                    "features moved the model's score, not as a probability-space "
                    "decomposition of that number.",
                ],
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", choices=("habitat", "hab", "both"), default="both")
    args = parser.parse_args(argv)

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    habitat_meta = export_habitat() if args.product in ("habitat", "both") else {}
    hab_meta = export_hab() if args.product in ("hab", "both") else {}

    if args.product == "both":
        manifest = build_manifest(habitat_meta, hab_meta)
        path = EXPORT_DIR / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2))
        print(f"\nwrote {path}", flush=True)

    print("exports ready.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
