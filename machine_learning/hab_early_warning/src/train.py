"""Train and validate the HAB early-warning model (approach doc 3.6, 3.7).

Validation is **rolling-origin cross-validation with an embargo gap**. Each
fold trains on everything before a cutoff and tests on the window after it,
dropping ``horizon`` days in between. The gap is not fussiness: the label at
time t is chlorophyll at t+7, so a training row within 7 days of the test
window shares its target's observation period. Without the gap the model is
partly scored on data it was trained on, and the metric is fiction.

Reported skill is **PR-AUC, not ROC-AUC**. Blooms are a small fraction of
grid-cell-days, and ROC-AUC is dominated by the huge true-negative pool — it
looks excellent while the model is useless at any threshold an agency would
alert on. Brier score and a reliability curve come alongside, because the
product surfaces a probability and that number has to mean something.

A **persistence baseline** is scored on every fold. "It is blooming now, so it
will be blooming in three days" is a genuinely strong forecast for an
autocorrelated field, and any model that cannot beat it has demonstrated
nothing. This is the internal equivalent of the doc's external
NOAA-C-HARM/INCOIS benchmark, which needs data not openly available for this
coastline.
"""

from __future__ import annotations

import gc
import json
import time
from dataclasses import dataclass, field

import joblib
import numpy as np
import pandas as pd

from marine_ml import config, tracking
from marine_ml.validation import metrics, splits

from . import features as feature_lib
from . import labels as label_lib


@dataclass
class HorizonResult:
    """Everything one forecast horizon produced."""

    horizon: int
    fold_scores: pd.DataFrame
    holdout: pd.DataFrame
    reliability: pd.DataFrame
    importances: pd.DataFrame
    model: object = None
    operating_point: dict = field(default_factory=dict)


def _as_float32(block):
    """Cast a feature block to float32. Module-level so the fitted pipeline
    stays picklable — see the note at its use site in ``build_model``."""
    return np.asarray(block, dtype=np.float32)


def build_model(frame: pd.DataFrame, columns: list[str], seed: int = config.RANDOM_SEED):
    """LightGBM classifier for bloom occurrence at one horizon.

    ``class_weight='balanced'`` rather than focal loss: with the bloom rate
    this data actually shows, reweighting is sufficient to keep the minority
    class learnable.

    It does **not** produce calibrated probabilities, and the measured
    reliability curve says so plainly — at t+7 the 0.9-1.0 prediction bin
    fires on 70% of occasions and the 0.1-0.2 bin on 9%, i.e. systematically
    overconfident. Reweighting shifts the decision boundary, which is exactly
    what inflates the scores. Ranking-based metrics (PR-AUC, TSS) are
    unaffected, but the product surfaces a probability to coastal agencies,
    so these raw scores must not be presented as one. Wrapping the fitted
    model in ``CalibratedClassifierCV(method="isotonic", cv="prefit")`` against
    a held-out slice is the fix; it is not applied here because doing it
    honestly needs a third temporal split that the current train/val/test
    layout does not carve out.
    """
    from lightgbm import LGBMClassifier
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import FunctionTransformer, OneHotEncoder

    categorical = [c for c in columns if isinstance(frame[c].dtype, pd.CategoricalDtype)]
    numeric = [c for c in columns if c not in categorical]

    # Explicit float32 rather than "passthrough". ColumnTransformer
    # concatenates its branches with numpy type promotion, and float32
    # alongside int32 promotes to float64 — which silently doubles the
    # transformed matrix and undoes the feature store's downcasting at the
    # last step before the model.
    #
    # `_as_float32` is a module-level function, not a lambda: the fitted
    # pipeline gets pickled by joblib, and pickle cannot serialise a closure.
    to_float32 = FunctionTransformer(_as_float32, feature_names_out="one-to-one")

    preprocessor = ColumnTransformer(
        [
            # LightGBM handles NaN natively, but the one-hot encoder does not,
            # so only the categorical branch is imputed.
            ("numeric", to_float32, numeric),
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        # dtype=float32 matters: ColumnTransformer concatenates
                        # the branches, so a float64 one-hot block would upcast
                        # the entire matrix back to float64 and undo the
                        # downcasting done in the feature store.
                        (
                            "encode",
                            OneHotEncoder(
                                handle_unknown="ignore",
                                sparse_output=False,
                                dtype=np.float32,
                            ),
                        ),
                    ]
                ),
                categorical,
            ),
        ],
        remainder="drop",
    )

    return Pipeline(
        [
            ("prep", preprocessor),
            (
                "model",
                LGBMClassifier(
                    n_estimators=500,
                    learning_rate=0.05,
                    num_leaves=31,
                    max_depth=6,
                    min_child_samples=50,
                    subsample=0.8,
                    subsample_freq=1,
                    colsample_bytree=0.8,
                    reg_lambda=1.0,
                    class_weight="balanced",
                    random_state=seed,
                    n_jobs=-1,
                    verbose=-1,
                ),
            ),
        ]
    )


def persistence_baseline(frame: pd.DataFrame) -> np.ndarray:
    """"Blooming now => blooming at t+h" as a probability.

    Uses the standardised chlorophyll anomaly squashed to 0-1 when available,
    so the baseline is a ranked score rather than a bare 0/1 — otherwise it
    would be unfairly penalised by ranking metrics that need ties broken.
    """
    if "chl_zanomaly" in frame.columns:
        z = frame["chl_zanomaly"].fillna(0.0).to_numpy(dtype=float)
        return 1.0 / (1.0 + np.exp(-z))
    if "is_bloom" in frame.columns:
        return frame["is_bloom"].fillna(0).to_numpy(dtype=float)
    return np.full(len(frame), 0.5)


# Fit on every Nth calendar day rather than every day.
#
# Consecutive daily fields in this basin are nearly identical — that is the
# same autocorrelation that makes persistence a strong baseline and forces
# blocked cross-validation. So the *effective* sample size is far below the
# row count, and striding discards little information while cutting fit time
# and memory proportionally. Whole days are dropped, never individual cells,
# so every retained timestep is still a complete spatial field.
#
# 4 rather than 2 because the 6-year window is 3x the rows the 2-year window
# had: at stride 2 the fit was killed by the OS for memory on a 9 GB machine.
# Even at 4, training still sees ~550 days spread across six years and all
# six monsoon cycles — the seasons are all represented, just less densely
# within each.
#
# This applies to model fitting only. Evaluation always uses every row of the
# test period — subsampling what you score on would be a different and much
# less defensible thing to do.
TRAINING_STRIDE = 4


def _strided(frame: pd.DataFrame, stride: int = TRAINING_STRIDE) -> pd.DataFrame:
    if stride <= 1:
        return frame
    ordinal = pd.to_datetime(frame["date"]).map(pd.Timestamp.toordinal)
    return frame[ordinal % stride == 0]


def cross_validate(
    frame: pd.DataFrame,
    columns: list[str],
    horizon: int,
    n_splits: int = 5,
    seed: int = config.RANDOM_SEED,
) -> pd.DataFrame:
    """Rolling-origin CV at one horizon, scoring the model and the baseline."""
    target = f"bloom_t{horizon}"
    rows: list[dict] = []

    for split in splits.rolling_origin_splits(
        frame["date"], n_splits=n_splits, horizon_days=horizon
    ):
        train_frame = _strided(frame.iloc[split.train])
        test_frame = frame.iloc[split.test]

        y_train = train_frame[target].astype(int)
        y_test = test_frame[target].astype(int)
        if y_train.nunique() < 2 or y_test.nunique() < 2:
            continue

        model = build_model(train_frame, columns, seed)
        model.fit(train_frame[columns], y_train)
        scores = model.predict_proba(test_frame[columns])[:, 1]

        report = metrics.evaluate_classification(y_test.to_numpy(), scores, split.name)
        rows.append(report.as_row() | {"model": "lightgbm", "horizon": horizon})

        baseline = metrics.evaluate_classification(
            y_test.to_numpy(), persistence_baseline(test_frame), split.name
        )
        rows.append(baseline.as_row() | {"model": "persistence", "horizon": horizon})

    return pd.DataFrame(rows)


def fit_final(
    frame: pd.DataFrame,
    columns: list[str],
    horizon: int,
    seed: int = config.RANDOM_SEED,
) -> tuple[object, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Fit on the training period, calibrate on validation, score on test.

    Three disjoint, chronologically ordered periods, and the middle one has a
    job: ``class_weight="balanced"`` deliberately distorts the decision
    boundary to keep the minority class learnable, and the side effect is
    systematically overconfident probabilities. Isotonic regression fitted on
    the validation period maps those raw scores back onto observed
    frequencies.

    The calibrator must never see the training period (the model is
    near-perfect there, so the mapping it learned would be the identity) nor
    the test period (that would be scoring on data used to fit). Validation is
    the only slice that qualifies, which is why it is no longer folded back
    into training for the final fit.

    Both raw and calibrated scores are returned so the improvement is
    measurable rather than assumed. Isotonic is monotonic, so PR-AUC/ROC-AUC
    are essentially unchanged by construction — Brier score and the
    reliability curve are where it shows up.
    """
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.frozen import FrozenEstimator

    target = f"bloom_t{horizon}"
    train_mask, validation_mask, test_mask = splits.chronological_split(
        frame["date"], config.TRAIN_FRACTION, config.VALIDATION_FRACTION
    )

    # Stride the fitting period only; calibration and test stay complete.
    train_frame = _strided(frame[train_mask])
    validation_frame = frame[validation_mask]
    test_frame = frame[test_mask]

    y_train = train_frame[target].astype(int)
    y_validation = validation_frame[target].astype(int)
    y_test = test_frame[target].astype(int)

    model = build_model(train_frame, columns, seed)
    model.fit(train_frame[columns], y_train)
    raw_scores = model.predict_proba(test_frame[columns])[:, 1]

    # FrozenEstimator is the sklearn >=1.6 replacement for cv="prefit": it
    # tells CalibratedClassifierCV to fit only the calibration map and leave
    # the underlying model untouched.
    calibrated = model
    calibrated_scores = raw_scores
    if y_validation.nunique() >= 2:
        calibrated = CalibratedClassifierCV(
            FrozenEstimator(model), method="isotonic"
        )
        calibrated.fit(validation_frame[columns], y_validation)
        calibrated_scores = calibrated.predict_proba(test_frame[columns])[:, 1]

    rows = [
        metrics.evaluate_classification(
            y_test.to_numpy(), raw_scores, "holdout"
        ).as_row()
        | {"model": "lightgbm_raw", "horizon": horizon},
        metrics.evaluate_classification(
            y_test.to_numpy(), calibrated_scores, "holdout"
        ).as_row()
        | {"model": "lightgbm_calibrated", "horizon": horizon},
        metrics.evaluate_classification(
            y_test.to_numpy(), persistence_baseline(test_frame), "holdout"
        ).as_row()
        | {"model": "persistence", "horizon": horizon},
    ]
    holdout = pd.DataFrame(rows)

    reliability = pd.concat(
        [
            metrics.reliability_curve(y_test.to_numpy(), raw_scores).assign(variant="raw"),
            metrics.reliability_curve(y_test.to_numpy(), calibrated_scores).assign(
                variant="calibrated"
            ),
        ],
        ignore_index=True,
    )

    # Operating point set by the recall a coastal agency would demand, not by
    # an abstract optimum — missing a bloom costs far more than a false alarm.
    # Taken on the calibrated scores, since those are what would be shown.
    threshold = metrics.threshold_for_recall(
        y_test.to_numpy(), calibrated_scores, target_recall=0.8
    )
    precision, recall = metrics.precision_recall_at_threshold(
        y_test.to_numpy(), calibrated_scores, threshold
    )
    operating_point = {
        "target_recall": 0.8,
        "threshold": threshold,
        "precision": precision,
        "recall": recall,
        "false_alarm_rate": metrics.false_alarm_rate(
            y_test.to_numpy(), calibrated_scores, threshold
        ),
        "brier_raw": float(
            holdout.loc[holdout["model"] == "lightgbm_raw", "brier"].iloc[0]
        ),
        "brier_calibrated": float(
            holdout.loc[holdout["model"] == "lightgbm_calibrated", "brier"].iloc[0]
        ),
    }

    importances = _explain(model, train_frame, columns)
    return calibrated, holdout, reliability, importances, operating_point


def _explain(model, frame: pd.DataFrame, columns: list[str], max_samples: int = 800):
    import shap

    sample = frame.sample(min(max_samples, len(frame)), random_state=config.RANDOM_SEED)
    prep = model.named_steps["prep"]
    transformed = prep.transform(sample[columns])
    names = list(prep.get_feature_names_out())

    explainer = shap.TreeExplainer(model.named_steps["model"])
    values = explainer.shap_values(transformed)
    if isinstance(values, list):
        values = values[1]
    elif values.ndim == 3:
        values = values[:, :, 1]

    return (
        pd.DataFrame({"feature": names, "mean_abs_shap": np.abs(values).mean(axis=0)})
        .sort_values("mean_abs_shap", ascending=False)
        .reset_index(drop=True)
    )


def run(
    frame: pd.DataFrame,
    horizons: tuple[int, ...] = label_lib.DEFAULT_HORIZONS,
    n_splits: int = 4,
    seed: int = config.RANDOM_SEED,
) -> dict[int, HorizonResult]:
    """Train and validate one model per forecast horizon.

    All horizons train on one shared row set — rows usable for *every*
    horizon — rather than a per-horizon filter. Two reasons, and the second is
    the better one:

    * Memory. A per-horizon filter copies the whole multi-gigabyte table once
      per horizon while the original stays referenced for the next one. On a
      9 GB machine that is what got this process OOM-killed.
    * Comparability. The horizons are then scored on identical rows, so a
      difference between t+3 and t+7 is a difference in forecast difficulty
      and not in which rows happened to survive filtering.

    The cost is the last ``max(horizons)`` days of each cell's series, which
    have no t+7 label — a fraction of a percent of the record.
    """
    results: dict[int, HorizonResult] = {}

    columns = feature_lib.feature_columns(frame, horizons)
    usable = feature_lib.drop_unusable_rows_all_horizons(frame, columns, horizons)
    del frame
    gc.collect()

    for horizon in horizons:
        target = f"bloom_t{horizon}"
        positives = int(usable[target].sum())
        print(f"\n  horizon t+{horizon}: {len(usable)} rows, {len(columns)} features, "
              f"{positives} blooms ({positives/max(len(usable),1):.2%})", flush=True)

        started = time.time()
        fold_scores = cross_validate(usable, columns, horizon, n_splits, seed)
        print(f"    rolling-origin CV in {time.time()-started:.1f}s", flush=True)

        model, holdout, reliability, importances, operating_point = fit_final(
            usable, columns, horizon, seed
        )

        results[horizon] = HorizonResult(
            horizon=horizon,
            fold_scores=fold_scores,
            holdout=holdout,
            reliability=reliability,
            importances=importances,
            model=model,
            operating_point=operating_point,
        )
        gc.collect()

    return results


def save(
    results: dict[int, HorizonResult],
    name: str = "hab_early_warning",
    region: config.Region = config.ARABIAN_SEA,
) -> None:
    config.ensure_directories()

    joblib.dump(
        {h: r.model for h, r in results.items()},
        config.MODELS_DIR / f"{name}.joblib",
    )

    pd.concat([r.fold_scores for r in results.values()], ignore_index=True).to_csv(
        config.REPORTS_DIR / f"{name}_fold_scores.csv", index=False
    )
    pd.concat([r.holdout for r in results.values()], ignore_index=True).to_csv(
        config.REPORTS_DIR / f"{name}_holdout.csv", index=False
    )
    for horizon, result in results.items():
        result.reliability.to_csv(
            config.REPORTS_DIR / f"{name}_reliability_t{horizon}.csv", index=False
        )
        result.importances.to_csv(
            config.REPORTS_DIR / f"{name}_shap_t{horizon}.csv", index=False
        )

    summary = {
        str(horizon): {
            "operating_point": result.operating_point,
            "top_features": result.importances.head(15).to_dict("records"),
        }
        for horizon, result in results.items()
    }
    (config.REPORTS_DIR / f"{name}_summary.json").write_text(json.dumps(summary, indent=2))

    for horizon, result in results.items():
        _track(result, horizon, name, region)


def _track(
    result: HorizonResult,
    horizon: int,
    name: str,
    region: config.Region = config.ARABIAN_SEA,
) -> None:
    """Append one horizon's run to the experiment log.

    One run *per horizon* rather than one per invocation: the horizons are the
    unit anyone actually compares ("is t+7 still usable?"), and t+3 improving
    while t+7 degrades is the outcome a single averaged run would hide.
    """
    holdout = result.holdout.set_index("model") if "model" in result.holdout else None
    point = result.operating_point or {}

    with tracking.track(
        "hab_early_warning",
        run_name=f"{name}_t{horizon}",
        params={
            "horizon_days": horizon,
            "random_seed": config.RANDOM_SEED,
            "validation": "rolling_origin_cv",
            "n_features": len(result.importances),
            **{f"operating_{k}": v for k, v in point.items()},
        },
        tags={
            "problem": "hab_early_warning",
            # The real region: with several bloom boxes trained separately,
            # a hardcoded tag makes every run look like the same experiment.
            "region": region.name,
            "horizon": horizon,
        },
    ) as run:
        run.log_data_window(
            start=config.HAB_START,
            end=config.HAB_END,
            rows=int(result.holdout["n"].sum()) if "n" in result.holdout else None,
        )
        run.log_dict(tracking.snapshot_config(config), "config_snapshot.json")

        run.log_fold_scores(result.fold_scores)
        run.log_table(result.holdout, "holdout.csv")
        run.log_table(result.reliability, "reliability.csv")
        run.log_shap(result.importances)
        run.log_metrics({f"operating_{k}": v for k, v in point.items()})

        if holdout is not None:
            for metric in ("pr_auc", "roc_auc", "brier", "tss"):
                if metric in holdout.columns:
                    run.log_metrics(
                        {f"holdout_{metric}_{model}": value
                         for model, value in holdout[metric].items()}
                    )
            # The headline verdict, stored as a number so runs sort by it:
            # a model that cannot beat "it is blooming now, so it will be
            # blooming then" has demonstrated nothing.
            if "pr_auc" in holdout.columns:
                model_score = holdout["pr_auc"].get("lightgbm_calibrated")
                baseline = holdout["pr_auc"].get("persistence")
                if model_score is not None and baseline is not None:
                    run.log_metrics({"pr_auc_lift_over_persistence": model_score - baseline})
