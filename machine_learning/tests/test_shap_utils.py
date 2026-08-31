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
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from fish_habitat_prediction.src.models import HingeQuadraticExpansion
from marine_ml.shap_utils import (
    linear_shap_matrix_probability,
    strip_transform_prefix,
    sum_hinge_quadratic_blocks,
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


# --------------------------------------------------------------------------
# Habitat ensemble: tree_shap_matrix_probability, sum_hinge_quadratic_blocks,
# linear_shap_matrix_probability. All three exist because HAB risk's
# TreeSHAP is already probability-space by default and fish habitat's
# RandomForest tier turns out to share that property, but fish habitat's
# LightGBM tier and MaxEnt tier do not -- see shap_utils.py's own docstrings
# for the empirical findings these pin.
# --------------------------------------------------------------------------


def test_tree_shap_matrix_probability_is_additive_on_a_real_fitted_booster():
    from lightgbm import LGBMClassifier

    frame, labels = _toy_frame(n=80)
    booster = LGBMClassifier(n_estimators=10, min_child_samples=2, verbosity=-1)
    booster.fit(frame, labels)

    background = frame.to_numpy()[:20]
    query = frame.to_numpy()[20:]

    import shap

    explainer = shap.TreeExplainer(
        booster, data=background, model_output="probability", feature_perturbation="interventional"
    )
    base_value = float(np.asarray(explainer.expected_value).reshape(-1)[-1])

    contributions = tree_shap_matrix_probability(booster, query, background)

    assert contributions.shape == (len(query), frame.shape[1])
    assert contributions.dtype == np.float32
    reconstructed = base_value + contributions.sum(axis=1)
    actual = booster.predict_proba(query)[:, 1]
    np.testing.assert_allclose(reconstructed, actual, atol=1e-4)


@pytest.mark.parametrize("n_hinges", [1, 2, 3])
def test_sum_hinge_quadratic_blocks_matches_a_real_fitted_expansions_layout(n_hinges):
    rng = np.random.default_rng(0)
    n_prep = 4
    X = rng.normal(size=(10, n_prep))

    expand = HingeQuadraticExpansion(n_hinges=n_hinges).fit(X)
    expanded = expand.transform(X)

    # Build the expected per-block contribution directly from the fitted
    # object's own knots, rather than re-deriving the reducer's own logic —
    # an independent computation, not a restatement of the implementation.
    blocks = [X, X**2]
    for row in range(expand.knots_.shape[0]):
        blocks.append(np.maximum(0.0, X - expand.knots_[row]))
    expected = sum(blocks)

    reduced = sum_hinge_quadratic_blocks(expanded, n_hinges)
    np.testing.assert_allclose(reduced, expected, atol=1e-9)


def test_sum_hinge_quadratic_blocks_hand_built_matrix():
    # 2 rows, n=2 original columns, n_hinges=1 -> 3 blocks of 2 columns.
    matrix = np.array(
        [
            [1.0, 2.0, 10.0, 20.0, 100.0, 200.0],
            [-1.0, -2.0, -10.0, -20.0, -100.0, -200.0],
        ]
    )
    reduced = sum_hinge_quadratic_blocks(matrix, n_hinges=1)
    np.testing.assert_allclose(reduced, [[111.0, 222.0], [-111.0, -222.0]])


def test_sum_hinge_quadratic_blocks_rejects_a_non_divisible_column_count():
    matrix = np.zeros((5, 7))  # 7 is not divisible by (2 + 2) = 4
    with pytest.raises(ValueError, match="not divisible"):
        sum_hinge_quadratic_blocks(matrix, n_hinges=2)


def _toy_maxent(n_hinges: int = 2, n: int = 60, seed: int = 0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 3))
    y = (X[:, 0] + 0.5 * X[:, 1] ** 2 > 0.3).astype(int)
    expand = HingeQuadraticExpansion(n_hinges=n_hinges).fit(X)
    model = LogisticRegression(max_iter=1000).fit(expand.transform(X), y)
    return X, y, expand, model


def test_linear_shap_matrix_probability_is_exactly_additive():
    X, _, expand, model = _toy_maxent()
    background_raw, query_raw = X[:30], X[30:]
    background = expand.transform(background_raw)
    query = expand.transform(query_raw)

    import shap

    z_base = float(
        np.asarray(shap.LinearExplainer(model, background).expected_value).reshape(-1)[-1]
    )
    p_base = 1.0 / (1.0 + np.exp(-z_base))

    contributions = linear_shap_matrix_probability(model, query, background, n_hinges=2)

    assert contributions.shape == (len(query_raw), 3)
    assert contributions.dtype == np.float32
    reconstructed = p_base + contributions.sum(axis=1)
    actual = model.predict_proba(query)[:, 1]
    np.testing.assert_allclose(reconstructed, actual, atol=1e-5)


def test_linear_shap_matrix_probability_falls_back_when_row_matches_baseline():
    """Exercises the secant's zero-denominator branch: a query row whose
    logit score equals the background's mean logit score exactly."""
    X, _, expand, model = _toy_maxent()
    background = expand.transform(X[:30])

    import shap

    explainer = shap.LinearExplainer(model, background)
    z_base = float(np.asarray(explainer.expected_value).reshape(-1)[-1])

    # Construct one query row whose logit score is exactly z_base by using
    # the background's own mean row -- its shap contributions sum to ~0 by
    # construction, so z_row == z_base (up to floating point).
    mean_row = background.mean(axis=0, keepdims=True)

    contributions = linear_shap_matrix_probability(model, mean_row, background, n_hinges=2)

    assert np.isfinite(contributions).all()


def test_maxent_probability_matches_a_permutation_reference():
    """The real correctness check for the secant-slope approximation: do
    the *raw*-feature-level attributions it produces (after
    sum_hinge_quadratic_blocks) rank similarly to an independent,
    model-agnostic permutation-SHAP reference computed directly on the
    composite raw-input -> expand -> predict_proba function?"""
    import shap

    X, _, expand, model = _toy_maxent(n=50)
    background_raw, query_raw = X[:20], X[20:23]
    background = expand.transform(background_raw)
    query = expand.transform(query_raw)

    ours = linear_shap_matrix_probability(model, query, background, n_hinges=2)

    def f(raw: np.ndarray) -> np.ndarray:
        return model.predict_proba(expand.transform(raw))[:, 1]

    reference = shap.explainers.Permutation(f, background_raw, seed=0)(query_raw, max_evals=200)

    for row in range(len(query_raw)):
        correlation = np.corrcoef(ours[row], reference.values[row])[0, 1]
        assert correlation > 0.8, f"row {row}: rank correlation {correlation} too low vs permutation reference"


def test_top_k_indices_and_values_accepts_a_narrower_index_dtype():
    matrix = np.array([[0.1, -0.9, 0.3, -0.2, 0.05]])
    indices, values = top_k_indices_and_values(matrix, top_k=2, index_dtype="int8")
    assert indices.dtype == np.int8
    assert values.dtype == np.float32


def test_top_k_indices_and_values_default_dtype_is_unchanged():
    matrix = np.array([[0.1, -0.9, 0.3, -0.2, 0.05]])
    indices, _ = top_k_indices_and_values(matrix, top_k=2)
    assert indices.dtype == np.int16
