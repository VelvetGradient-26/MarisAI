"""Shared SHAP-attribution primitives (`marine_ml.shap_utils`).

Both HAB and habitat pipelines wrap a `Pipeline` in
`CalibratedClassifierCV(FrozenEstimator(...))` for calibration, and both name
their `ColumnTransformer` branches "numeric"/"categorical" — these pin the
unwrap and stripping rules against real fitted objects (not mocks), because a
version-specific attribute name (`.estimator` vs `.base_estimator`,
`FrozenEstimator` vs the removed `cv="prefit"`) is exactly the kind of thing
that silently breaks across an sklearn upgrade without a real fit-and-unwrap
round trip to catch it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from marine_ml.shap_utils import (
    linear_shap_matrix,
    strip_transform_prefix,
    top_k_indices_and_values,
    tree_shap_matrix,
    tree_shap_matrix_probability,
    unwrap_calibrated_pipeline,
)


def _toy_pipeline() -> Pipeline:
    prep = ColumnTransformer([("numeric", SimpleImputer(strategy="median"), ["a", "b"])])
    return Pipeline([("prep", prep), ("model", RandomForestClassifier(n_estimators=8, random_state=0))])


def _toy_frame(n: int = 40, seed: int = 0) -> tuple[pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({"a": rng.random(n), "b": rng.random(n)})
    labels = (frame["a"] + frame["b"] > 1.0).astype(int).to_numpy()
    return frame, labels


def test_unwrap_recovers_the_exact_prefit_pipeline_through_calibration():
    frame, labels = _toy_frame()
    pipeline = _toy_pipeline().fit(frame[:20], labels[:20])

    calibrated = CalibratedClassifierCV(FrozenEstimator(pipeline), method="isotonic")
    calibrated.fit(frame[20:], labels[20:])

    unwrapped = unwrap_calibrated_pipeline(calibrated)

    assert unwrapped is pipeline


def test_unwrap_passes_through_a_bare_pipeline_unchanged():
    """The branch `hab_early_warning/src/train.py::fit_final` takes when a
    horizon's validation split turned out single-class and calibration was
    skipped — `unwrap_calibrated_pipeline` must not assume it always has a
    `CalibratedClassifierCV` to peel."""
    frame, labels = _toy_frame()
    pipeline = _toy_pipeline().fit(frame, labels)

    assert unwrap_calibrated_pipeline(pipeline) is pipeline


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("numeric__thetao", "thetao"),
        ("categorical__monsoon_phase_summer", "monsoon_phase_summer"),
        ("chl_lag3", "chl_lag3"),
    ],
)
def test_strip_transform_prefix(raw, expected):
    assert strip_transform_prefix(raw) == expected


def test_top_k_indices_and_values_picks_largest_magnitude_per_row_descending():
    matrix = np.array(
        [
            [0.1, -0.9, 0.3, -0.2, 0.05, 0.01],
            [-0.5, 0.4, 0.0, 0.6, -0.1, 0.2],
        ]
    )

    indices, values = top_k_indices_and_values(matrix, top_k=2)

    assert indices.dtype == np.int16
    assert values.dtype == np.float32
    assert indices.shape == (2, 2)

    # Row 0: |-0.9| then |0.3|. Row 1: |0.6| then |-0.5|.
    np.testing.assert_array_equal(indices, [[1, 2], [3, 0]])
    np.testing.assert_allclose(values, [[-0.9, 0.3], [0.6, -0.5]], atol=1e-6)


def test_tree_shap_matrix_shape_and_dtype_on_a_real_fitted_booster():
    from lightgbm import LGBMClassifier

    frame, labels = _toy_frame(n=60)
    booster = LGBMClassifier(n_estimators=10, min_child_samples=2, verbosity=-1)
    booster.fit(frame, labels)

    contributions = tree_shap_matrix(booster, frame.to_numpy())

    assert contributions.shape == (len(frame), frame.shape[1])
    assert contributions.dtype == np.float32
    assert np.isfinite(contributions).all()


def test_a_random_forests_default_shap_output_is_already_probability_space():
    """The empirical finding `tree_shap_matrix_probability`'s docstring
    depends on: a scikit-learn RandomForestClassifier's leaves store
    class-probability fractions, so the *plain* `tree_shap_matrix` -- no
    special request needed -- reconstructs `predict_proba` to float
    precision. Pinned here so an sklearn upgrade that changed this silently
    would fail a test rather than corrupt an ensemble combination that
    assumes it."""
    frame, labels = _toy_frame(n=80, seed=2)
    forest = RandomForestClassifier(
        n_estimators=40, class_weight="balanced_subsample", random_state=0
    )
    forest.fit(frame, labels)

    contributions = tree_shap_matrix(forest, frame.to_numpy())
    proba = forest.predict_proba(frame.to_numpy())[:, 1]
    # expected_value for the positive class, matching tree_shap_matrix's own
    # binary-classifier unwrapping.
    import shap

    base = shap.TreeExplainer(forest).expected_value
    base = base[1] if isinstance(base, (list, np.ndarray)) and np.ndim(base) > 0 else base

    reconstructed = contributions.sum(axis=1) + base
    np.testing.assert_allclose(reconstructed, proba, atol=1e-4)


def test_tree_shap_matrix_probability_reconstructs_predict_proba_for_lightgbm():
    """LightGBM's leaves store raw scores, not probabilities -- unlike the
    RandomForest case above, this needs the explicit probability-space
    request (`model_output="probability"` + `feature_perturbation=
    "interventional"` + a background sample) to be additive against
    `predict_proba`, which is the whole point of this function existing
    beside the margin-space `tree_shap_matrix`."""
    from lightgbm import LGBMClassifier

    frame, labels = _toy_frame(n=100, seed=3)
    booster = LGBMClassifier(n_estimators=20, min_child_samples=2, verbosity=-1)
    booster.fit(frame, labels)

    background = frame.to_numpy()[:20]
    contributions = tree_shap_matrix_probability(booster, frame.to_numpy(), background)
    proba = booster.predict_proba(frame.to_numpy())[:, 1]

    import shap

    explainer = shap.TreeExplainer(
        booster, data=background, model_output="probability", feature_perturbation="interventional"
    )
    base = explainer.expected_value
    base = base[1] if isinstance(base, (list, np.ndarray)) and np.ndim(base) > 0 else base

    assert contributions.dtype == np.float32
    reconstructed = contributions.sum(axis=1) + base
    np.testing.assert_allclose(reconstructed, proba, atol=1e-3)


def test_linear_shap_matrix_reconstructs_the_decision_function_not_probability():
    """Pins the documented limitation: LinearSHAP is additive in logit
    space, and deliberately not asked to be anything else -- a caller that
    wants probability space from a linear model has to go elsewhere (a
    black-box explainer, measured too slow for grid-export scale, see
    fish_habitat_prediction/src/explain.py)."""
    from sklearn.linear_model import LogisticRegression

    frame, labels = _toy_frame(n=80, seed=4)
    model = LogisticRegression().fit(frame, labels)

    background = frame.to_numpy()[:20]
    contributions = linear_shap_matrix(model, frame.to_numpy(), background)
    decision = model.decision_function(frame.to_numpy())
    proba = model.predict_proba(frame.to_numpy())[:, 1]

    import shap

    base = shap.LinearExplainer(model, background).expected_value
    reconstructed = contributions.sum(axis=1) + base

    np.testing.assert_allclose(reconstructed, decision, atol=1e-6)
    assert not np.allclose(reconstructed, proba, atol=0.05)
