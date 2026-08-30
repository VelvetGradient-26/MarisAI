"""Shared SHAP-attribution helpers for tree-based and linear problem pipelines.

Both `hab_early_warning` and `fish_habitat_prediction` build their pipelines
the same way -- `Pipeline([("prep", ColumnTransformer(...)), ("model", ...)])`,
optionally wrapped in `CalibratedClassifierCV(FrozenEstimator(pipeline))` for
HAB's isotonic calibration -- so the unwrap-and-explain plumbing belongs here
rather than in one problem's `src/`.

**Combining multiple explainers into one per-original-feature attribution is
still not here.** That is fish habitat's ensemble problem (MaxEnt +
RandomForest + LightGBM, skill-weighted) and lives in
`fish_habitat_prediction/src/explain.py`, because it needs MaxEnt's own
hinge/quadratic feature expansion (`models.py::HingeQuadraticExpansion`) to
reconcile the tiers back to shared feature names -- knowledge this module
has no business holding. What *is* here are the two more primitives that
work required: `tree_shap_matrix_probability` and `linear_shap_matrix`.

**A tree model's SHAP output space is not one fixed thing, and mixing them
silently would be wrong.** `EnsembleWeights.combine` (`models.py`) averages
`predict_proba` outputs directly, so an attribution meant to explain *that*
number has to live in probability space too -- verified empirically (not
assumed) on real fitted models: scikit-learn's `RandomForestClassifier`
leaves store class-probability fractions, so `tree_shap_matrix`'s plain
`shap.TreeExplainer(model)` is *already* additive in probability space for it
(reconstruction error ~1e-16 on a real `class_weight="balanced_subsample"`
forest). LightGBM's leaves store raw scores, so its default TreeSHAP output
is margin/log-odds space instead (this is what `hab_risk_shap.nc` uses, and
is correct there since HAB never combines it with anything else) --
`tree_shap_matrix_probability` is the explicit probability-space request for
it, needing a background sample and costing nothing more than one extra
`shap.TreeExplainer` argument (verified ~1e-9 reconstruction error, still the
same fast tree algorithm, not a black-box fallback).
"""

from __future__ import annotations

import numpy as np


def unwrap_calibrated_pipeline(model):
    """Peel a possibly-calibrated estimator down to the underlying Pipeline.

    `CalibratedClassifierCV(FrozenEstimator(pipeline), method="isotonic")` is
    this repo's calibration wrapper (see
    `hab_early_warning/src/train.py::fit_final`). Isotonic calibration is a
    monotonic post-hoc transform of the pipeline's own output -- it changes no
    feature's relative contribution -- so SHAP explains the underlying model,
    never the calibrator, which is the same choice `train.py::_explain`
    already made for the global importance ranking.

    Returns `model` unchanged if it is already a bare `Pipeline` -- the branch
    `fit_final` takes when a horizon's validation split turned out
    single-class and calibration was skipped.
    """
    if hasattr(model, "calibrated_classifiers_"):
        estimator = model.calibrated_classifiers_[0].estimator
        return getattr(estimator, "estimator", estimator)
    return model


def strip_transform_prefix(name: str) -> str:
    """Undo a `ColumnTransformer`'s `<branch>__` output naming.

    Both problems' preprocessors name their branches "numeric" and
    "categorical" (`hab_early_warning/src/train.py::build_model`,
    `fish_habitat_prediction/src/models.py::_preprocessor`), so one stripping
    rule serves both. Already applied ad hoc in
    `scripts/export_predictions.py::_top_drivers`; this is the shared version.
    """
    return name.replace("numeric__", "").replace("categorical__", "")


def tree_shap_matrix(booster, transformed: np.ndarray) -> np.ndarray:
    """Per-row, per-feature TreeSHAP contributions toward the positive class.

    `shap`'s return shape for a binary classifier has varied across versions
    -- verified empirically here it is a plain `(n_rows, n_features)` ndarray
    for this LightGBM model under `shap==0.51.0`, but older releases return a
    length-2 list or a 3D `(n_rows, n_features, 2)` array. All three are
    normalised to one `(n_rows, n_features)` array of positive-class
    contributions -- the same defensive handling `train.py::_explain` uses.
    Cast to float32: the model's own inputs are float32, so float64 SHAP
    output would be false precision.
    """
    import shap

    explainer = shap.TreeExplainer(booster)
    values = explainer.shap_values(transformed)
    if isinstance(values, list):
        values = values[1]
    elif np.asarray(values).ndim == 3:
        values = np.asarray(values)[:, :, 1]
    return np.asarray(values, dtype="float32")


def top_k_indices_and_values(matrix: np.ndarray, top_k: int) -> tuple[np.ndarray, np.ndarray]:
    """Reduce a `(n_rows, n_features)` signed contribution matrix to the
    top-k by absolute magnitude, per row.

    Ranks by `|contribution|` for the reason `ShapExplainer.explain_row`
    (backend/forecasting/shap_explainer.py) already does: a large negative
    push is exactly as much of an explanation as a large positive one.
    Returns `(indices, values)`, each `(n_rows, top_k)` -- `indices` are int16
    positions into the caller's feature-name list (this repo's HAB feature
    space is 139 columns; int16 covers up to 32,767, comfortably beyond
    int8's 127-value ceiling, which 139 already exceeds).
    """
    order = np.argsort(-np.abs(matrix), axis=1)[:, :top_k]
    values = np.take_along_axis(matrix, order, axis=1)
    return order.astype("int16"), values.astype("float32")


def tree_shap_matrix_probability(booster, transformed: np.ndarray, background: np.ndarray) -> np.ndarray:
    """Per-row, per-feature TreeSHAP contributions toward `predict_proba`'s
    positive-class probability, for a booster whose leaves are *not*
    already probability-valued (LightGBM, XGBoost, CatBoost) -- see this
    module's docstring for why `tree_shap_matrix` is the right call instead
    for a `RandomForestClassifier`.

    `feature_perturbation="interventional"` is what makes `model_output=
    "probability"` possible at all: TreeSHAP's fast default algorithm
    (`"tree_path_dependent"`) only supports the model's own raw output, so
    the probability-space request needs the slower-but-still-tree-exact
    interventional algorithm and a `background` sample to estimate feature
    marginals against. Still the same order of cost as `tree_shap_matrix`,
    not a black-box fallback -- verified ~1e-9 reconstruction error against
    a real fitted LightGBM's own `predict_proba`.
    """
    import shap

    explainer = shap.TreeExplainer(
        booster, data=background, model_output="probability", feature_perturbation="interventional"
    )
    values = explainer.shap_values(transformed)
    if isinstance(values, list):
        values = values[1]
    elif np.asarray(values).ndim == 3:
        values = np.asarray(values)[:, :, 1]
    return np.asarray(values, dtype="float32")


def linear_shap_matrix(model, transformed: np.ndarray, background: np.ndarray) -> np.ndarray:
    """Per-row, per-feature LinearSHAP contributions toward a linear model's
    raw decision-function output (logit / log-odds for a classifier) --
    deliberately *not* probability space.

    `shap.LinearExplainer`'s `model_output="probability"` option does not
    give an additive decomposition of `predict_proba` for a model behind a
    nonlinear (sigmoid) link -- checked empirically on a real fit, off by
    several probability units, because a Shapley decomposition of a
    nonlinear function of a linear score is a different (and here,
    prohibitively slower black-box) computation, not a flag on the linear
    explainer. Callers combining this with a tree tier's probability-space
    attribution (`fish_habitat_prediction/src/explain.py`) must treat the
    mixed units as a stated approximation, not paper over it.
    """
    import shap

    explainer = shap.LinearExplainer(model, background)
    return np.asarray(explainer.shap_values(transformed), dtype="float32")
