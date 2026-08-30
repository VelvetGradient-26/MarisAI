"""Shared SHAP-attribution helpers for tree-based problem pipelines.

Both `hab_early_warning` and `fish_habitat_prediction` build their pipelines
the same way -- `Pipeline([("prep", ColumnTransformer(...)), ("model", ...)])`,
optionally wrapped in `CalibratedClassifierCV(FrozenEstimator(pipeline))` for
HAB's isotonic calibration -- so the unwrap-and-explain plumbing belongs here
rather than in one problem's `src/`.

What is deliberately *not* here: combining multiple explainers (TreeExplainer
+ LinearExplainer) into one per-original-feature attribution. That is fish
habitat's ensemble problem (MaxEnt + RandomForest + LightGBM, skill-weighted;
see `fish_habitat_prediction/src/models.py`), it needs real design work of its
own, and it is out of scope for this pass -- see TODO.md's "Explainability for
the derived indices" item.
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
