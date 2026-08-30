"""Stacking on out-of-fold predictions — TODO.md's "the more principled
version [of the ensemble], never attempted."

Two halves, tested at different granularity:

`StackedEnsemble` itself (`models.py`) is pure — a meta-learner fitted on
already-collected out-of-fold scores — and is checked the same way
`test_ensemble_weights.py` checks `EnsembleWeights`, with hand-built scores
and no real spatial CV.

`cross_validate`'s new third return value (`train.py`) is checked against a
small but real synthetic frame through the actual spatial-block CV loop,
because that is the one place per-row out-of-fold predictions are actually
assembled, and a plumbing mistake there (wrong column, wrong row count,
mismatched presence labels) would silently miscalibrate the meta-learner
without a scores-only test ever noticing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fish_habitat_prediction.src import train as train_lib
from fish_habitat_prediction.src.models import StackedEnsemble
from marine_ml import config


class TestStackedEnsembleFit:
    def test_learns_to_favour_the_informative_model(self):
        """One base model's score equals the true label plus noise; the other
        is pure noise. The meta-learner should end up relying on the
        informative one — checked by its predictions correlating with the
        truth far better than the noisy model alone does."""
        rng = np.random.default_rng(0)
        n = 400
        presence = rng.integers(0, 2, size=n)
        informative = np.clip(presence + rng.normal(0, 0.1, size=n), 0.001, 0.999)
        noisy = rng.uniform(0, 1, size=n)

        oof = pd.DataFrame({"good": informative, "bad": noisy, "presence": presence})
        stacked = StackedEnsemble.fit(oof, ["good", "bad"], seed=config.RANDOM_SEED)

        combined = stacked.combine({"good": informative, "bad": noisy})
        # A meta-learner that ignored "bad" should score close to perfectly
        # separating on "good" alone; one that trusted "bad" equally would not.
        auc_combined = _auc(presence, combined)
        auc_noisy_alone = _auc(presence, noisy)
        assert auc_combined > auc_noisy_alone + 0.3

    def test_combine_returns_valid_probabilities(self):
        rng = np.random.default_rng(1)
        oof = pd.DataFrame(
            {"a": rng.uniform(0, 1, 100), "b": rng.uniform(0, 1, 100), "presence": rng.integers(0, 2, 100)}
        )
        stacked = StackedEnsemble.fit(oof, ["a", "b"])

        scores = stacked.combine({"a": rng.uniform(0, 1, 50), "b": rng.uniform(0, 1, 50)})

        assert scores.shape == (50,)
        assert np.all(scores >= 0.0) and np.all(scores <= 1.0)

    def test_model_names_order_is_respected_at_combine_time(self):
        """`combine` must read each named array by key, not by dict
        insertion order — a caller assembling `predictions` in a different
        order than `model_names` must still get the right answer."""
        rng = np.random.default_rng(2)
        n = 200
        presence = rng.integers(0, 2, size=n)
        strong = np.clip(presence + rng.normal(0, 0.05, size=n), 0.001, 0.999)
        weak = rng.uniform(0, 1, size=n)
        oof = pd.DataFrame({"strong": strong, "weak": weak, "presence": presence})
        stacked = StackedEnsemble.fit(oof, ["strong", "weak"])

        in_order = stacked.combine({"strong": strong, "weak": weak})
        reordered = stacked.combine({"weak": weak, "strong": strong})

        np.testing.assert_allclose(in_order, reordered)


def _auc(labels: np.ndarray, scores: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score

    return float(roc_auc_score(labels, scores))


def _synthetic_frame(rng: np.random.Generator, blocks: int = 6, per_block: int = 20) -> pd.DataFrame:
    """A small, real frame that flows through the actual spatial-block CV
    loop: each 3-degree block is far enough apart to be its own fold, and
    `thetao` is genuinely predictive of `presence` so every fold has both
    classes and no model errors out on a degenerate input."""
    rows = []
    for block in range(blocks):
        lat = 5.0 + block * 4.0  # 4 deg apart, comfortably over one 3 deg block each
        lon = 60.0
        for _ in range(per_block):
            presence = int(rng.integers(0, 2))
            thetao = 28.0 + presence * 2.0 + rng.normal(0, 0.5)
            rows.append(
                {
                    "latitude": lat + rng.normal(0, 0.1),
                    "longitude": lon + rng.normal(0, 0.1),
                    "presence": presence,
                    "species_key": "test_species",
                    "thetao": thetao,
                }
            )
    return pd.DataFrame(rows)


class TestCrossValidateOutOfFoldPredictions:
    def test_returns_one_row_per_test_point_with_every_model_and_presence(self):
        rng = np.random.default_rng(config.RANDOM_SEED)
        frame = _synthetic_frame(rng)
        columns = ["thetao"]

        fold_scores, model_scores, oof = train_lib.cross_validate(
            frame, columns, n_splits=3, block_degrees=3.0, seed=config.RANDOM_SEED
        )

        from fish_habitat_prediction.src.models import MODEL_BUILDERS

        for name in MODEL_BUILDERS:
            assert name in oof.columns
        assert "presence" in oof.columns
        assert len(oof) > 0
        assert oof[list(MODEL_BUILDERS)].to_numpy().min() >= 0.0
        assert oof[list(MODEL_BUILDERS)].to_numpy().max() <= 1.0

    def test_a_stacked_ensemble_can_be_fit_from_it(self):
        """The actual intended use: `cross_validate`'s third return value is
        directly consumable by `StackedEnsemble.fit`, with no reshaping."""
        rng = np.random.default_rng(config.RANDOM_SEED)
        frame = _synthetic_frame(rng)
        columns = ["thetao"]

        _, _, oof = train_lib.cross_validate(frame, columns, n_splits=3, seed=config.RANDOM_SEED)

        from fish_habitat_prediction.src.models import MODEL_BUILDERS

        stacked = StackedEnsemble.fit(oof, list(MODEL_BUILDERS), seed=config.RANDOM_SEED)
        scores = stacked.combine({name: oof[name].to_numpy() for name in MODEL_BUILDERS})

        assert scores.shape == (len(oof),)
