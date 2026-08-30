"""Combined-ensemble SHAP attribution (fish_habitat_prediction/src/explain.py).

Real fits on synthetic data throughout, matching test_shap_utils.py's own
convention — the failure mode this guards against (a preprocessor disagreeing
between tiers, a reshape assumption about HingeQuadraticExpansion's column
order) only shows up against real fitted objects, not mocks.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fish_habitat_prediction.src.explain import (
    collapse_hinge_quadratic_shap,
    combined_feature_attribution,
)
from fish_habitat_prediction.src.models import (
    MODEL_BUILDERS,
    EnsembleWeights,
    HingeQuadraticExpansion,
)


def test_collapse_sums_each_original_columns_own_expansion_blocks():
    """Two original columns, `n_hinges=1` -> 3 blocks (linear, squared,
    hinge0) of 2 columns each, laid out `[a, b, a^2, b^2, hinge_a, hinge_b]`
    -- exactly HingeQuadraticExpansion's own hstack order, not a made-up one."""
    expanded = np.array(
        [
            # a=1, b=2, a^2=10, b^2=20, hinge_a=100, hinge_b=200
            [1.0, 2.0, 10.0, 20.0, 100.0, 200.0],
        ]
    )

    collapsed = collapse_hinge_quadratic_shap(expanded, n_original=2, n_hinges=1)

    np.testing.assert_allclose(collapsed, [[111.0, 222.0]])
    assert collapsed.dtype == np.float32


def test_collapse_rejects_a_column_count_that_does_not_match_the_expected_layout():
    expanded = np.zeros((3, 7))  # not a multiple of (2 + n_hinges) * n_original
    with pytest.raises(ValueError, match="expected"):
        collapse_hinge_quadratic_shap(expanded, n_original=2, n_hinges=1)


def test_collapse_matches_a_real_hinge_quadratic_expansion_round_trip():
    """Not just the hand-derived layout above -- fit the real
    HingeQuadraticExpansion and confirm the block order collapse assumes is
    what it actually produces, so a future change to that class's transform
    order fails this test rather than silently corrupting MaxEnt's share of
    the combined attribution."""
    rng = np.random.default_rng(0)
    X = rng.random((30, 3))
    expansion = HingeQuadraticExpansion(n_hinges=2)
    expanded = expansion.fit_transform(X)

    # A SHAP-shaped matrix where the "contribution" of expanded column j is
    # just its own value -- collapsing must then sum, per original column,
    # X + X^2 + hinge_0(X) + hinge_1(X), computed independently here.
    collapsed = collapse_hinge_quadratic_shap(expanded, n_original=3, n_hinges=2)
    expected = (
        X
        + X**2
        + np.maximum(0.0, X - expansion.knots_[0])
        + np.maximum(0.0, X - expansion.knots_[1])
    )
    np.testing.assert_allclose(collapsed, expected, atol=1e-5)


def _toy_habitat_frame(n: int = 120, seed: int = 0) -> pd.DataFrame:
    """Numeric *and* categorical columns, like the real habitat feature
    frame — the categorical branch is what would break a naive assumption
    that every tier's preprocessor output is purely numeric."""
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame(
        {
            "thetao": rng.normal(28, 2, n),
            "chl": rng.exponential(0.3, n),
            "depth": rng.uniform(10, 3000, n),
            "depth_bucket": pd.Categorical(
                rng.choice(["nearshore", "shelf", "slope"], n)
            ),
        }
    )
    presence = (
        (frame["thetao"] > 27.5) & (frame["chl"] > 0.2) & (frame["depth"] < 1500)
    ).astype(int)
    return frame, presence.to_numpy()


_COLUMNS = ["thetao", "chl", "depth", "depth_bucket"]


def _fit_all_tiers(frame: pd.DataFrame, labels: np.ndarray) -> dict:
    return {
        name: builder(frame, _COLUMNS, seed=0).fit(frame[_COLUMNS], labels)
        for name, builder in MODEL_BUILDERS.items()
    }


def test_the_three_tiers_preprocessors_agree_on_feature_names():
    """The load-bearing assumption `combined_feature_attribution` checks at
    runtime (and raises on) -- pinned here as its own test so a future
    change to one tier's `_preprocessor` call breaks a fast, obvious test
    rather than surfacing as a cryptic reshape/RuntimeError deep in an
    export run."""
    frame, labels = _toy_habitat_frame()
    models = _fit_all_tiers(frame, labels)

    names_per_tier = {
        name: list(pipeline.named_steps["prep"].get_feature_names_out())
        for name, pipeline in models.items()
    }
    first = next(iter(names_per_tier.values()))
    assert all(names == first for names in names_per_tier.values())


def test_combined_attribution_shape_and_finiteness_on_real_fitted_tiers():
    frame, labels = _toy_habitat_frame()
    models = _fit_all_tiers(frame, labels)
    weights = EnsembleWeights.from_scores({"lightgbm": 0.8, "random_forest": 0.75, "maxent": 0.4})

    contributions, feature_names = combined_feature_attribution(models, weights, _COLUMNS, frame)

    assert contributions.shape[0] == len(frame)
    assert contributions.shape[1] == len(feature_names)
    assert contributions.dtype == np.float32
    assert np.isfinite(contributions).all()
    # depth_bucket one-hot-encodes to 3 columns, so the shared feature space
    # is bigger than _COLUMNS itself -- a regression here would mean the
    # categorical branch silently stopped being explained.
    assert len(feature_names) > len(_COLUMNS)


def test_a_weight_of_one_reduces_to_that_tiers_own_contribution():
    """The combination is genuinely the weighted sum it claims to be, not
    something that happens to look plausible -- checked by collapsing the
    ensemble to a single tier and comparing against that tier's attribution
    computed directly, the same way it is computed inside the combiner."""
    frame, labels = _toy_habitat_frame(seed=1)
    models = _fit_all_tiers(frame, labels)
    weights = EnsembleWeights({"random_forest": 1.0, "lightgbm": 0.0, "maxent": 0.0})

    combined, feature_names = combined_feature_attribution(models, weights, _COLUMNS, frame)

    from marine_ml.shap_utils import strip_transform_prefix, tree_shap_matrix

    rf = models["random_forest"]
    transformed = rf.named_steps["prep"].transform(frame[_COLUMNS])
    direct = tree_shap_matrix(rf.named_steps["model"], transformed)
    direct_names = [
        strip_transform_prefix(n) for n in rf.named_steps["prep"].get_feature_names_out()
    ]

    assert direct_names == feature_names
    np.testing.assert_allclose(combined, direct, atol=1e-5)
