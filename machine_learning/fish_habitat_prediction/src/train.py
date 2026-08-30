"""Train and validate the fish habitat / PFZ model (approach doc 4.6, 4.7).

Validation is **spatial block cross-validation**, not random K-fold. This is
the single most consequential choice in the file. Occurrence records are
strongly spatially autocorrelated; a random split puts points from the same
survey transect in both training and test, and the model scores near-perfectly
by recognising its neighbours. The same model under block CV — where whole
3-degree blocks are held out — reports what it would actually do on water it
has never seen. Expect the block number to be substantially lower. That gap is
information, not a defect: it is the difference between a model that has
learned ecology and one that has memorised a map.

Reported metrics follow the SDM literature rather than generic classification:
AUC, the True Skill Statistic, and the continuous Boyce index (which needs no
true absences — the only honest option for presence-only data).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import joblib
import numpy as np
import pandas as pd

from marine_ml import config, tracking
from marine_ml.validation import metrics, splits

from . import features as feature_lib
from . import models as model_lib

# How ensemble members are weighted. `softmax` (the default) resolves a large
# quality gap into a large weight gap; `proportional` is the original rule and
# is kept so the earlier baselines can be reproduced exactly. Logged to the
# tracking store per run, because it changes what the exported product *is* —
# `habitat_suitability.nc` is the ensemble, not the best member.
ENSEMBLE_WEIGHTING = "softmax"


@dataclass
class TrainingResult:
    """Everything one training run produced."""

    fold_scores: pd.DataFrame
    model_scores: dict[str, float]
    ensemble_weights: model_lib.EnsembleWeights
    stacked_ensemble: model_lib.StackedEnsemble
    holdout: pd.DataFrame
    fitted: dict
    feature_columns: list[str]
    importances: pd.DataFrame


def cross_validate(
    frame: pd.DataFrame,
    columns: list[str],
    n_splits: int = 5,
    block_degrees: float = 3.0,
    seed: int = config.RANDOM_SEED,
) -> tuple[pd.DataFrame, dict[str, float], pd.DataFrame]:
    """Spatial block CV across all three model tiers.

    The thermal niche is refitted inside every fold, on that fold's training
    presences only. Fitting it once outside the loop would leak held-out
    temperatures into a training feature and quietly inflate every fold.

    The third return value is every test row's per-model score, from
    whichever fold actually held it out — the out-of-fold predictions
    `model_lib.StackedEnsemble.fit` needs. Collected here rather than
    recomputed separately so the stacking meta-learner trains on the exact
    same folds the reported CV metrics come from, not a second CV pass that
    could disagree with the first.
    """
    rows: list[dict] = []
    oof_rows: list[dict] = []

    for split in splits.spatial_block_splits(
        frame["latitude"], frame["longitude"],
        n_splits=n_splits, block_degrees=block_degrees, seed=seed,
    ):
        train_frame = frame.iloc[split.train]
        test_frame = frame.iloc[split.test]

        if train_frame["presence"].nunique() < 2 or test_frame["presence"].nunique() < 2:
            # A block containing only background (or only presences) cannot
            # produce a meaningful score; skipping is honest, scoring it is not.
            continue

        niche = feature_lib.fit_thermal_niche(train_frame)
        train_fold = feature_lib.apply_thermal_niche(train_frame, niche)
        test_fold = feature_lib.apply_thermal_niche(test_frame, niche)

        fold_oof: dict[str, np.ndarray] = {}
        for name, builder in model_lib.MODEL_BUILDERS.items():
            model = builder(train_fold, columns, seed)
            model.fit(train_fold[columns], train_fold["presence"])
            scores = model.predict_proba(test_fold[columns])[:, 1]
            fold_oof[name] = scores

            report = metrics.evaluate_classification(
                test_fold["presence"].to_numpy(), scores,
                name=split.name, compute_boyce=True,
            )
            row = report.as_row()
            row["model"] = name
            rows.append(row)

        oof_fold_frame = pd.DataFrame(fold_oof)
        oof_fold_frame["presence"] = test_fold["presence"].to_numpy()
        oof_rows.append(oof_fold_frame)

    fold_scores = pd.DataFrame(rows)
    if fold_scores.empty:
        raise RuntimeError("no usable spatial folds — try fewer splits or smaller blocks")

    model_scores = (
        fold_scores.groupby("model")["tss"].mean(numeric_only=True).to_dict()
    )
    oof_predictions = pd.concat(oof_rows, ignore_index=True)
    return fold_scores, model_scores, oof_predictions


def fit_final(
    train_frame: pd.DataFrame,
    test_frame: pd.DataFrame,
    columns: list[str],
    model_scores: dict[str, float],
    oof_predictions: pd.DataFrame,
    seed: int = config.RANDOM_SEED,
) -> tuple[dict, pd.DataFrame, model_lib.EnsembleWeights, model_lib.StackedEnsemble]:
    """Refit each tier on the full training set and score the held-out block.

    Fits *both* ensemble combiners — the served softmax-weighted average and
    the stacking meta-learner — and scores both on the same held-out block,
    so `holdout` is a direct, paired comparison ("was stacking ever actually
    better, measured on the same water") rather than two separate claims.
    `EnsembleWeights` stays what `habitat_suitability.nc` is exported as
    regardless of which one wins here — see `ENSEMBLE_WEIGHTING`'s own
    docstring for why that choice is not made silently.
    """
    niche = feature_lib.fit_thermal_niche(train_frame)
    train_fold = feature_lib.apply_thermal_niche(train_frame, niche)
    test_fold = feature_lib.apply_thermal_niche(test_frame, niche)

    fitted: dict = {"_thermal_niche": niche}
    predictions: dict[str, np.ndarray] = {}
    rows: list[dict] = []

    for name, builder in model_lib.MODEL_BUILDERS.items():
        model = builder(train_fold, columns, seed)
        model.fit(train_fold[columns], train_fold["presence"])
        fitted[name] = model

        scores = model.predict_proba(test_fold[columns])[:, 1]
        predictions[name] = scores
        report = metrics.evaluate_classification(
            test_fold["presence"].to_numpy(), scores, name=name, compute_boyce=True
        )
        rows.append(report.as_row() | {"model": name})

    # TSS is 0 at chance, so it is its own floor. The rule is named rather than
    # defaulted: under `proportional`, weight is skill *relative to chance*, so a
    # model less than half as good on the holdout still drew 27% of the vote
    # merely because 0.619 is 75% of 0.826. See `EnsembleWeights.from_scores`.
    weights = model_lib.EnsembleWeights.from_scores(
        model_scores, floor=0.0, method=ENSEMBLE_WEIGHTING
    )
    ensemble_scores = weights.combine(predictions)
    ensemble_report = metrics.evaluate_classification(
        test_fold["presence"].to_numpy(), ensemble_scores,
        name="ensemble", compute_boyce=True,
    )
    rows.append(ensemble_report.as_row() | {"model": "ensemble"})

    stacked = model_lib.StackedEnsemble.fit(oof_predictions, list(model_lib.MODEL_BUILDERS), seed=seed)
    stacked_scores = stacked.combine(predictions)
    stacked_report = metrics.evaluate_classification(
        test_fold["presence"].to_numpy(), stacked_scores,
        name="stacked_ensemble", compute_boyce=True,
    )
    rows.append(stacked_report.as_row() | {"model": "stacked_ensemble"})

    # Extrapolation check: how much of the held-out block sits outside the
    # environmental envelope the model was fitted on.
    numeric = [c for c in columns if pd.api.types.is_numeric_dtype(train_fold[c])]
    similarity = metrics.mess(train_fold[numeric], test_fold[numeric])
    holdout = pd.DataFrame(rows)
    holdout["mess_median"] = float(np.nanmedian(similarity))
    holdout["mess_extrapolating_fraction"] = float(np.mean(similarity < 0))

    return fitted, holdout, weights, stacked


def explain(
    model,
    frame: pd.DataFrame,
    columns: list[str],
    max_samples: int = 500,
) -> pd.DataFrame:
    """Mean absolute SHAP value per input feature.

    This is what feeds the product's Explainable AI Assistant: a per-prediction
    reason list ("high suitability due to a strong thermal front and elevated
    chlorophyll two weeks prior") rather than a bare score.

    Names come back in post-preprocessing space (one-hot categories appear
    separately), which is the space SHAP actually attributes in — mapping them
    back to source columns would merge signals the model treats separately.
    """
    import shap

    sample = frame.sample(min(max_samples, len(frame)), random_state=config.RANDOM_SEED)
    prep = model.named_steps["prep"]
    transformed = prep.transform(sample[columns])
    names = list(prep.get_feature_names_out())

    estimator = model.named_steps["model"]
    explainer = shap.TreeExplainer(estimator)
    values = explainer.shap_values(transformed)
    # Binary classifiers return either a list per class or a 3-D array.
    if isinstance(values, list):
        values = values[1]
    elif values.ndim == 3:
        values = values[:, :, 1]

    importance = np.abs(values).mean(axis=0)
    return (
        pd.DataFrame({"feature": names, "mean_abs_shap": importance})
        .sort_values("mean_abs_shap", ascending=False)
        .reset_index(drop=True)
    )


def run(
    frame: pd.DataFrame,
    n_splits: int = 5,
    block_degrees: float = 3.0,
    seed: int = config.RANDOM_SEED,
) -> TrainingResult:
    """Full train/validate cycle over a feature-built, labelled frame."""
    columns = feature_lib.feature_columns(frame)
    frame = feature_lib.drop_unusable_rows(frame, columns)

    print(f"  {len(frame)} rows, {len(columns)} features, "
          f"{int(frame['presence'].sum())} presences", flush=True)

    started = time.time()
    fold_scores, model_scores, oof_predictions = cross_validate(
        frame, columns, n_splits=n_splits, block_degrees=block_degrees, seed=seed
    )
    print(f"  spatial block CV done in {time.time()-started:.1f}s", flush=True)

    # Final held-out block: one spatial fold never used for model selection.
    final_split = next(
        iter(splits.spatial_block_splits(
            frame["latitude"], frame["longitude"],
            n_splits=n_splits, block_degrees=block_degrees, seed=seed + 1,
        ))
    )
    train_frame = frame.iloc[final_split.train]
    test_frame = frame.iloc[final_split.test]

    fitted, holdout, weights, stacked = fit_final(
        train_frame, test_frame, columns, model_scores, oof_predictions, seed
    )

    niche = fitted["_thermal_niche"]
    importances = explain(
        fitted["lightgbm"], feature_lib.apply_thermal_niche(train_frame, niche), columns
    )

    return TrainingResult(
        fold_scores=fold_scores,
        model_scores=model_scores,
        ensemble_weights=weights,
        stacked_ensemble=stacked,
        holdout=holdout,
        fitted=fitted,
        feature_columns=columns,
        importances=importances,
    )


def save(
    result: TrainingResult,
    name: str = "fish_habitat",
    region: config.Region = config.NORTH_INDIAN_OCEAN,
) -> None:
    """Persist models, weights and reports."""
    config.ensure_directories()

    joblib.dump(
        {
            "models": {k: v for k, v in result.fitted.items() if not k.startswith("_")},
            "thermal_niche": result.fitted["_thermal_niche"],
            "ensemble_weights": result.ensemble_weights.weights,
            "feature_columns": result.feature_columns,
        },
        config.MODELS_DIR / f"{name}.joblib",
    )

    result.fold_scores.to_csv(config.REPORTS_DIR / f"{name}_fold_scores.csv", index=False)
    result.holdout.to_csv(config.REPORTS_DIR / f"{name}_holdout.csv", index=False)
    result.importances.to_csv(config.REPORTS_DIR / f"{name}_shap.csv", index=False)

    summary = {
        "cv_tss_by_model": result.model_scores,
        "ensemble_weights": result.ensemble_weights.weights,
        "n_features": len(result.feature_columns),
        "top_features": result.importances.head(15).to_dict("records"),
    }
    (config.REPORTS_DIR / f"{name}_summary.json").write_text(json.dumps(summary, indent=2))

    _track(result, name, region)


def _track(
    result: TrainingResult,
    name: str,
    region: config.Region = config.NORTH_INDIAN_OCEAN,
) -> None:
    """Append this run to the experiment log.

    Every file `save` just wrote is on a fixed path and will be destroyed by
    the next run; this is the copy that survives so "did that change help?"
    stays answerable. Tracking is best-effort by construction — see
    `marine_ml.tracking`.
    """
    holdout = result.holdout.set_index("model") if "model" in result.holdout else None

    with tracking.track(
        "fish_habitat_prediction",
        run_name=name,
        params={
            "n_features": len(result.feature_columns),
            "models": ", ".join(sorted(result.model_scores)),
            "random_seed": config.RANDOM_SEED,
            "validation": "spatial_block_cv",
            # The weighting rule, beside the weights it produced. Without it two
            # runs with different ensemble scores look like noise rather than
            # like the deliberate change one of them was.
            "ensemble_weighting": ENSEMBLE_WEIGHTING,
            **{f"weight_{k}": round(v, 4) for k, v in result.ensemble_weights.weights.items()},
        },
        # The real region, not a constant: a global run and a regional one are
        # the two things anyone will want to compare here, and a hardcoded tag
        # makes them indistinguishable in the tracking UI.
        tags={"problem": "fish_habitat", "region": region.name},
    ) as run:
        run.log_data_window(
            start=config.HABITAT_START,
            end=config.HABITAT_END,
            rows=int(result.holdout["n"].sum()) if "n" in result.holdout else None,
            extra={
                "region": region.name,
                "note": (
                    "OBIS target-species records stop after 2014 — verified "
                    "2026-08-10 to be a global cliff, not a regional artefact "
                    "(yellowfin worldwide: 67,780 records 2000-2013, 772 after)"
                ),
            },
        )
        run.log_params({"feature_count": len(result.feature_columns)})
        run.log_dict(result.feature_columns, "feature_columns.json")
        run.log_dict(tracking.snapshot_config(config), "config_snapshot.json")

        run.log_fold_scores(result.fold_scores)
        run.log_table(result.holdout, "holdout.csv")
        run.log_shap(result.importances)

        # CV TSS per model, and the holdout number for each. The ensemble
        # scoring below its own best member is a live finding in TODO.md; it
        # is only visible if both are recorded side by side.
        run.log_metrics({f"cv_tss_{k}": v for k, v in result.model_scores.items()})
        if holdout is not None:
            for metric in ("tss", "roc_auc", "pr_auc", "boyce"):
                if metric in holdout.columns:
                    run.log_metrics(
                        {f"holdout_{metric}_{model}": value
                         for model, value in holdout[metric].items()}
                    )

    # Each ensemble member as its own child run, *after* the parent closes its
    # own metrics but inside the same tracking session.
    #
    # The flattened metrics above are kept rather than replaced: they are what
    # makes one run readable at a glance. What they cannot do is answer a
    # question *across* runs — MLflow cannot sort or plot by a member when the
    # member is baked into the metric name — and the ensemble findings this
    # project keeps hitting are exactly that shape: the softmax weighting change
    # traded 0.03 of Boyce for 0.10 of TSS, and seeing that required reading two
    # runs by hand. As child runs it is a sort.
    _track_members(result, name, region, holdout)


def _track_members(
    result: TrainingResult,
    name: str,
    region: config.Region,
    holdout,
) -> None:
    """One nested run per ensemble member.

    Opened inside the parent's tracking context by MLflow's own active-run
    stack, so these attach to the run `_track` just wrote rather than floating
    loose. Best-effort like everything else here: a member that cannot be logged
    is a warning, never a failed training run.
    """
    for model, cv_tss in sorted(result.model_scores.items()):
        metrics = {"cv_tss": cv_tss}
        if holdout is not None and model in holdout.index:
            for metric in ("tss", "roc_auc", "pr_auc", "boyce"):
                if metric in holdout.columns:
                    value = holdout.loc[model, metric]
                    if value is not None:
                        metrics[f"holdout_{metric}"] = value

        with tracking.track(
            "fish_habitat_prediction",
            run_name=f"{name}::{model}",
            nested=True,
            params={
                "member": model,
                # The weight this member drew, beside its own quality. The whole
                # point of the softmax change was that these two had come apart:
                # MaxEnt scored 0.619 against LightGBM's 0.826 and still drew 27%
                # of the vote under proportional weighting.
                "ensemble_weight": round(
                    result.ensemble_weights.weights.get(model, 0.0), 4
                ),
                "ensemble_weighting": ENSEMBLE_WEIGHTING,
            },
            tags={
                "problem": "fish_habitat",
                "region": region.name,
                "member": model,
                "parent_run": name,
            },
        ) as member_run:
            member_run.log_metrics(metrics)
