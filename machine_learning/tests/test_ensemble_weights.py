"""The ensemble weighting rule.

The exported product (`habitat_suitability.nc`) is the *ensemble*, not the best
member, so how members are weighted is a property of what gets served rather
than an internal detail. These pin the property that failed in practice: a model
less than half as good on the holdout must not hold a quarter of the vote.
"""

from __future__ import annotations

import numpy as np
import pytest

from fish_habitat_prediction.src.models import EnsembleWeights

# The real cross-validated scores this problem produces.
MEASURED = {"lightgbm": 0.826, "random_forest": 0.821, "maxent": 0.619}


def test_softmax_separates_a_weak_member_that_proportional_keeps():
    proportional = EnsembleWeights.from_scores(MEASURED, method="proportional").weights
    softmax = EnsembleWeights.from_scores(MEASURED, method="softmax").weights

    # The defect, still reproducible: 0.619 is 75% of 0.826, so proportional
    # weighting hands a much worse model most of a fair share.
    assert proportional["maxent"] > 0.25

    assert softmax["maxent"] < 0.05
    # ...without collapsing to winner-take-all. The two leaders differ by 0.005
    # TSS and must stay comparable, or the ensemble is just its best member.
    assert softmax["lightgbm"] == pytest.approx(softmax["random_forest"], abs=0.1)


@pytest.mark.parametrize("method", ["proportional", "softmax"])
def test_weights_are_a_distribution(method):
    weights = EnsembleWeights.from_scores(MEASURED, method=method).weights
    assert sum(weights.values()) == pytest.approx(1.0)
    assert all(value >= 0.0 for value in weights.values())


@pytest.mark.parametrize("method", ["proportional", "softmax"])
def test_a_model_at_or_below_chance_gets_no_weight(method):
    """TSS is 0 at chance, so the floor means the same thing under both rules —
    a model no better than a coin must not drag the surface that gets served."""
    scores = MEASURED | {"broken": 0.0, "worse_than_chance": -0.3}

    weights = EnsembleWeights.from_scores(scores, floor=0.0, method=method).weights

    assert weights.get("broken", 0.0) == 0.0
    assert weights.get("worse_than_chance", 0.0) == 0.0
    assert sum(weights.values()) == pytest.approx(1.0)


@pytest.mark.parametrize("method", ["proportional", "softmax"])
def test_every_model_failing_falls_back_to_an_unweighted_mean(method):
    """Rather than dividing by zero. A degenerate ensemble is still an answer;
    a traceback in the middle of a 40-minute run is not."""
    weights = EnsembleWeights.from_scores(
        {"a": 0.0, "b": -0.1}, floor=0.0, method=method
    ).weights

    assert weights == {"a": 0.5, "b": 0.5}


def test_a_non_finite_score_is_ignored_rather_than_poisoning_the_weights():
    weights = EnsembleWeights.from_scores(
        MEASURED | {"crashed": float("nan")}, method="softmax"
    ).weights

    assert "crashed" not in weights
    assert sum(weights.values()) == pytest.approx(1.0)


def test_an_unknown_method_is_refused():
    with pytest.raises(ValueError, match="unknown weighting method"):
        EnsembleWeights.from_scores(MEASURED, method="inverse_variance")


def test_combine_is_the_weighted_average_it_claims_to_be():
    weights = EnsembleWeights({"a": 0.75, "b": 0.25})

    combined = weights.combine(
        {"a": np.array([1.0, 0.0]), "b": np.array([0.0, 1.0])}
    )

    assert combined == pytest.approx([0.75, 0.25])


def test_combine_shap_is_combine_for_matrices():
    """Same weighted-sum rule as `combine`, just over `(n_rows, n_features)`
    contribution matrices instead of `(n_rows,)` prediction vectors — the
    attribution analogue used to build one ensemble driver list out of three
    tiers' own attributions (fish_habitat_prediction/src/explain.py)."""
    weights = EnsembleWeights({"a": 0.75, "b": 0.25})

    combined = weights.combine_shap(
        {
            "a": np.array([[1.0, 0.0], [2.0, 0.0]]),
            "b": np.array([[0.0, 1.0], [0.0, 4.0]]),
        }
    )

    np.testing.assert_allclose(combined, [[0.75, 0.25], [1.5, 1.0]])
    assert combined.dtype == np.float32
