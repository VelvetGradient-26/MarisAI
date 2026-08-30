"""Per-cell SHAP attribution for the skill-weighted three-tier ensemble.

TODO.md's "Explainability for the derived indices" item flagged this as real
design work of its own, separate from HAB's single-model case
(`marine_ml/shap_utils.py`'s own docstring says as much) — this module is
that work. Three problems had to be solved, in order:

1. **The three tiers explain in three different feature spaces.**
   `random_forest`/`lightgbm_model` share one preprocessed feature space
   (`models.py::_preprocessor` with `scale=False`); `maxent_baseline` adds a
   `HingeQuadraticExpansion` step on top of its own (`scale=True`) copy of
   the same preprocessor, multiplying the column count by `2 + n_hinges`.
   `collapse_hinge_quadratic_shap` sums MaxEnt's per-expanded-column SHAP
   back down to one value per pre-expansion column, in the same order the
   two tree tiers already use — verified against the expansion's own known,
   fixed block layout (`[X, X**2, hinge_0(X), ..., hinge_{k-1}(X)]`,
   `np.hstack`'d, never interleaved).

2. **The three tiers explain in two different *units*, and only two of
   three can be reconciled cheaply.** `EnsembleWeights.combine` blends
   `predict_proba` outputs, so an attribution meant to explain that number
   needs every tier in probability space. `RandomForestClassifier` already
   is (verified in `marine_ml/shap_utils.py`); LightGBM can be, via
   `tree_shap_matrix_probability`, at the same tree-exact cost. MaxEnt
   cannot, without a black-box explainer over its sigmoid link — measured at
   ~2–30 ms/row on a MaxEnt-shaped model (`~28` post-expansion-independent
   features), which at this problem's grid-export scale (tens of thousands
   of species-month-cell rows) is minutes-to-hours rather than the seconds
   the tree tiers cost. **Accepted as a stated approximation, not solved**:
   MaxEnt's collapsed contribution stays in logit space and is weighted into
   the combination anyway. The error this introduces is bounded by MaxEnt's
   own ensemble weight, which the shipped softmax config keeps small by
   design (`models.py::TSS_SOFTMAX_TEMPERATURE`'s own measured example:
   0.008 — under 1% of the vote) precisely because MaxEnt was the weakest
   tier on this problem's holdout.

3. **A background sample has to come from somewhere at export time,
   with no training set retained in the shipped artifact.** Drawn from the
   frame being scored itself (a fixed-size, seeded random subsample) —
   standard SHAP practice when the original fitting data is not carried
   forward, and reasonable here since the export frame and the training
   frame are drawn from the same region/variable distribution.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from marine_ml import shap_utils

from .models import EnsembleWeights

N_HINGES = 3  # must match models.py::maxent_baseline's HingeQuadraticExpansion(n_hinges=3)
BACKGROUND_SIZE = 50
BACKGROUND_SEED = 0


def collapse_hinge_quadratic_shap(
    expanded: np.ndarray, n_original: int, n_hinges: int = N_HINGES
) -> np.ndarray:
    """Sum a `HingeQuadraticExpansion`-expanded SHAP matrix back to one
    contribution per pre-expansion column.

    `HingeQuadraticExpansion.transform` lays its output out as
    `(2 + n_hinges)` blocks of `n_original` columns each, in the fixed order
    `[X, X**2, hinge_0(X), ..., hinge_{n_hinges-1}(X)]`, concatenated with
    `np.hstack` — never interleaved per original column. A linear model's
    SHAP value for one expanded column is a well-defined marginal
    contribution of that single feature; summing every block's value for
    the same original column is the natural way to answer "how much did
    this original variable, as a whole nonlinear response, move the score"
    — stated as an approximation (the blocks are deterministic functions of
    one shared variable, not independent players, so this is not a Shapley
    property in its own right), not derived as an exact one.
    """
    n_blocks = 2 + n_hinges
    if expanded.shape[1] != n_blocks * n_original:
        raise ValueError(
            f"expected {n_blocks * n_original} expanded columns ({n_blocks} "
            f"blocks of {n_original} original features), got {expanded.shape[1]}"
        )
    reshaped = expanded.reshape(expanded.shape[0], n_blocks, n_original)
    return reshaped.sum(axis=1).astype("float32")


def _background(transformed: np.ndarray, size: int, seed: int) -> np.ndarray:
    if len(transformed) <= size:
        return transformed
    rng = np.random.default_rng(seed)
    indices = rng.choice(len(transformed), size=size, replace=False)
    return transformed[indices]


def combined_feature_attribution(
    models: dict, weights: EnsembleWeights, columns: list[str], frame: pd.DataFrame
) -> tuple[np.ndarray, list[str]]:
    """Per-row, per-original-feature ensemble attribution, in the same
    skill-weighted combination the ensemble's own prediction uses.

    Returns `(contributions, feature_names)`: `contributions` is
    `(len(frame), len(feature_names))`, `feature_names` is the shared
    post-preprocessing column list every tier's `prep` step agrees on
    (verified identical across the three fitted pipelines by
    `test_the_three_tiers_preprocessors_agree_on_feature_names`) — the same
    names a plain tree-only explanation would use, so nothing about
    MaxEnt's own internal expansion leaks into the exported feature space.
    """
    per_tier: dict[str, np.ndarray] = {}
    feature_names: list[str] | None = None

    for name, pipeline in models.items():
        prep = pipeline.named_steps["prep"]
        transformed = prep.transform(frame[columns])
        names = [shap_utils.strip_transform_prefix(n) for n in prep.get_feature_names_out()]
        if feature_names is None:
            feature_names = names
        elif names != feature_names:
            raise RuntimeError(
                f"{name}'s fitted preprocessor produced different feature names "
                f"than an earlier tier's — the combined attribution assumes "
                "every tier's `prep` step agrees on one shared feature space."
            )

        if name == "maxent":
            expand = pipeline.named_steps["expand"]
            expanded = expand.transform(transformed)
            background = _background(expanded, BACKGROUND_SIZE, BACKGROUND_SEED)
            raw = shap_utils.linear_shap_matrix(pipeline.named_steps["model"], expanded, background)
            per_tier[name] = collapse_hinge_quadratic_shap(raw, len(feature_names))
        elif name == "lightgbm":
            background = _background(transformed, BACKGROUND_SIZE, BACKGROUND_SEED)
            per_tier[name] = shap_utils.tree_shap_matrix_probability(
                pipeline.named_steps["model"], transformed, background
            )
        elif name == "random_forest":
            # Already probability-space by construction — see
            # marine_ml/shap_utils.py's module docstring.
            per_tier[name] = shap_utils.tree_shap_matrix(pipeline.named_steps["model"], transformed)
        else:
            raise ValueError(f"no attribution rule for unknown model tier {name!r}")

    combined = weights.combine_shap(per_tier)
    return combined, feature_names
