"""Tiered habitat models (approach doc 4.6).

Tier 1 — MaxEnt-style baseline
    Implemented as L1-regularised logistic regression on presence-vs-background
    with quadratic and hinge feature expansion. This is not an approximation
    of convenience: Phillips & Dudik (2008) showed MaxEnt's Gibbs distribution
    is exactly the solution of regularised logistic regression on
    presence-background data, and Renner & Warton (2013) showed both are
    equivalent to an inhomogeneous Poisson point process. So this is MaxEnt's
    estimator, expressed in scikit-learn, rather than a substitute for it.
    Keeping it means fisheries scientists reviewing the work see a baseline
    they already trust, and the deep models have a defensible floor to beat.

Tier 2 — Random Forest and LightGBM
    Presence-background classifiers that capture interactions and thresholds
    the linear tier cannot, and stay explainable through SHAP.

Ensemble
    Skill-weighted average of the tiers, the ML analogue of the ensemble-SDM
    practice standard in ecological modelling (biomod2). No single method
    dominates across species and regions, so averaging weighted by
    cross-validated skill reduces single-model bias.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from marine_ml import config


def _column_types(frame: pd.DataFrame, columns: list[str]) -> tuple[list[str], list[str]]:
    categorical = [
        c for c in columns if isinstance(frame[c].dtype, pd.CategoricalDtype)
    ]
    numeric = [c for c in columns if c not in categorical]
    return numeric, categorical


def _preprocessor(frame: pd.DataFrame, columns: list[str], scale: bool) -> ColumnTransformer:
    numeric, categorical = _column_types(frame, columns)

    numeric_steps = [("impute", SimpleImputer(strategy="median"))]
    if scale:
        numeric_steps.append(("scale", StandardScaler()))

    return ColumnTransformer(
        [
            ("numeric", Pipeline(numeric_steps), numeric),
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("encode", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                    ]
                ),
                categorical,
            ),
        ],
        remainder="drop",
    )


class HingeQuadraticExpansion:
    """MaxEnt's feature classes: linear, quadratic, and hinge.

    MaxEnt owes much of its flexibility to expanding each environmental
    variable into several derived "features" before fitting a linear model.
    Quadratic terms let a response peak at an intermediate optimum — which is
    what an ecological niche looks like — and hinge features let the response
    change slope at a threshold. Without these a linear model can only say
    "warmer is always better", which is never true of a thermal niche.
    """

    def __init__(self, n_hinges: int = 3):
        self.n_hinges = n_hinges
        self.knots_: np.ndarray | None = None

    def fit(self, X: np.ndarray, y=None) -> "HingeQuadraticExpansion":
        quantiles = np.linspace(0.2, 0.8, self.n_hinges)
        self.knots_ = np.nanquantile(X, quantiles, axis=0)
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        if self.knots_ is None:
            raise RuntimeError("HingeQuadraticExpansion.fit must be called first")
        parts = [X, X**2]
        for row in range(self.knots_.shape[0]):
            parts.append(np.maximum(0.0, X - self.knots_[row]))
        return np.hstack(parts)

    def fit_transform(self, X: np.ndarray, y=None) -> np.ndarray:
        return self.fit(X, y).transform(X)

    def get_params(self, deep: bool = True) -> dict:
        return {"n_hinges": self.n_hinges}

    def set_params(self, **params) -> "HingeQuadraticExpansion":
        for key, value in params.items():
            setattr(self, key, value)
        return self


def maxent_baseline(
    frame: pd.DataFrame, columns: list[str], seed: int = config.RANDOM_SEED
) -> Pipeline:
    """Tier 1: MaxEnt's estimator — L1-regularised logistic regression on
    expanded features. ``class_weight='balanced'`` keeps the fit from being
    dominated by the background class."""
    return Pipeline(
        [
            ("prep", _preprocessor(frame, columns, scale=True)),
            ("expand", HingeQuadraticExpansion(n_hinges=3)),
            (
                "model",
                # l1_ratio=1.0 is pure L1. scikit-learn 1.8 deprecated the
                # `penalty=` string in favour of this, and saga is the solver
                # that supports the elastic-net parameterisation.
                LogisticRegression(
                    l1_ratio=1.0,
                    solver="saga",
                    C=1.0,
                    max_iter=5000,
                    class_weight="balanced",
                    random_state=seed,
                ),
            ),
        ]
    )


def random_forest(
    frame: pd.DataFrame, columns: list[str], seed: int = config.RANDOM_SEED
) -> Pipeline:
    """Tier 2: Random Forest presence-background classifier."""
    return Pipeline(
        [
            ("prep", _preprocessor(frame, columns, scale=False)),
            (
                "model",
                RandomForestClassifier(
                    n_estimators=500,
                    min_samples_leaf=3,
                    max_features="sqrt",
                    class_weight="balanced_subsample",
                    n_jobs=-1,
                    random_state=seed,
                ),
            ),
        ]
    )


def lightgbm_model(
    frame: pd.DataFrame, columns: list[str], seed: int = config.RANDOM_SEED
) -> Pipeline:
    """Tier 2: LightGBM presence-background classifier.

    Conservative depth and leaf counts: with order-1,000 presences, an
    unconstrained booster memorises the training set within a few dozen
    rounds and the spatial-block CV score collapses.
    """
    from lightgbm import LGBMClassifier

    return Pipeline(
        [
            ("prep", _preprocessor(frame, columns, scale=False)),
            (
                "model",
                LGBMClassifier(
                    n_estimators=400,
                    learning_rate=0.05,
                    num_leaves=15,
                    max_depth=5,
                    min_child_samples=20,
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


MODEL_BUILDERS = {
    "maxent": maxent_baseline,
    "random_forest": random_forest,
    "lightgbm": lightgbm_model,
}


# Softmax temperature for ensemble weighting, in TSS units.
#
# It sets how much a given skill gap is worth. The spread that has to be
# resolved on this problem is LightGBM 0.826 / Random Forest 0.821 / MaxEnt
# 0.619 — i.e. two models that are genuinely interchangeable and one that is
# not. At 0.05 the two leaders stay within a few points of each other (they
# differ by 0.005, a tenth of a temperature unit) while MaxEnt, 4 temperature
# units back, falls to ~2% of the vote.
#
# Smaller would collapse to winner-take-all and throw away the ensemble's whole
# reason for existing; larger drifts back toward the uniform average that let a
# half-as-good model hold a quarter of the vote.
#
# Measured on the held-out spatial block (2026-08-13), same folds, same fitted
# members, only the weighting changed:
#
#   rule          weights (lgbm/rf/maxent)   holdout TSS   Boyce   ROC-AUC
#   proportional  0.364 / 0.362 / 0.273      0.694         0.936   0.917
#   softmax       0.519 / 0.473 / 0.008      0.792         0.905   0.944
#
# The defect this fixes is the first column: the ensemble used to score *below
# its own best member* (0.694 against LightGBM's 0.788), which is the one thing
# an ensemble may not do, since the exported product is the ensemble. At softmax
# weights it is 0.792 — finally above every member, if only by 0.004.
#
# The cost is real and is the reason this is a constant rather than a hardcoded
# choice: Boyce falls 0.936 -> 0.905, so the old ensemble was the better
# *spatially calibrated* surface. It is still better calibrated than LightGBM
# alone (0.895), so the trade buys discrimination for a calibration penalty that
# does not take it below its best member on either axis. Raise the temperature
# to trade back.
TSS_SOFTMAX_TEMPERATURE = 0.05


@dataclass
class EnsembleWeights:
    """Cross-validated skill weights for the ensemble."""

    weights: dict[str, float]

    @classmethod
    def from_scores(
        cls,
        scores: dict[str, float],
        floor: float = 0.0,
        method: str = "softmax",
        temperature: float = TSS_SOFTMAX_TEMPERATURE,
    ) -> "EnsembleWeights":
        """Weight each model by its cross-validated skill.

        ``proportional`` is the original rule — weight is skill above ``floor``,
        normalised. It has one property that turned out to matter: because TSS is
        0 at chance and the floor is 0, the weights are proportional to the raw
        scores, so a *large* quality gap compresses into a *small* weight gap.
        Measured on this problem, MaxEnt scored CV TSS 0.619 against LightGBM's
        0.826 — it is less than half as good on the holdout (0.365 vs 0.788) —
        and still collected 27% of the vote, because 0.619 is 75% of 0.826.

        ``softmax`` weights ``exp(score / temperature)``, which makes the gap a
        tunable decision rather than an artefact of where zero happens to sit.
        See ``TSS_SOFTMAX_TEMPERATURE`` for the choice of temperature.

        Neither rule is obviously right, and that is the point of making it an
        argument: the ensemble is not a pure loss at proportional weights — it
        has the *best* Boyce index of any member (0.936 vs LightGBM's 0.895), so
        it is better spatially calibrated while being worse at discrimination.
        What was wrong was that the trade was being made implicitly, by a
        normalisation constant, rather than chosen.
        """
        finite = {name: score for name, score in scores.items() if np.isfinite(score)}
        # A model at or below the floor gets zero weight rather than a small
        # negative one — no better than chance should not drag the ensemble, and
        # biomod2's convention is the same. Applied under both rules, so the
        # floor keeps meaning the same thing.
        eligible = {name: score for name, score in finite.items() if score > floor}

        if not eligible:
            # Every model failed; fall back to an unweighted mean so the
            # ensemble still produces something rather than dividing by zero.
            n = len(scores) or 1
            return cls({name: 1.0 / n for name in scores})

        if method == "proportional":
            raw = {name: score - floor for name, score in eligible.items()}
        elif method == "softmax":
            # Shifted by the maximum before exponentiating: standard softmax
            # underflow guard, and it cancels in the normalisation.
            best = max(eligible.values())
            raw = {
                name: float(np.exp((score - best) / temperature))
                for name, score in eligible.items()
            }
        else:
            raise ValueError(
                f"unknown weighting method {method!r}; expected 'softmax' or 'proportional'"
            )

        total = sum(raw.values())
        return cls({name: value / total for name, value in raw.items()})

    def combine(self, predictions: dict[str, np.ndarray]) -> np.ndarray:
        stacked = np.zeros(len(next(iter(predictions.values()))))
        for name, values in predictions.items():
            stacked += self.weights.get(name, 0.0) * np.asarray(values)
        return stacked


@dataclass
class StackedEnsemble:
    """A logistic-regression meta-learner over the base tiers' scores —
    "stacking on out-of-fold predictions" (TODO.md), the more principled
    alternative to `EnsembleWeights`' fixed linear combination.

    **Why this needs out-of-fold predictions and `EnsembleWeights` does not.**
    `EnsembleWeights` only ever needs one *scalar* per model (its CV-mean
    TSS) to set a weight. A meta-learner needs *training data* — a score
    from each base model paired with the true label, for enough rows to fit
    on — and those scores must come from a fold where that row was held out,
    or the meta-learner would be trained on each base model's in-sample
    (near-perfect) predictions and learn nothing about how they generalise.
    `train.cross_validate` collects exactly this: every row's prediction
    from whichever fold held it out.

    **Why logistic regression, not something heavier.** The meta-learner's
    own input is only `len(MODEL_BUILDERS)` columns (three, today) — there
    is no room for a meta-learner to overfit a large feature space here, and
    a linear model on three already-informative scores is the standard,
    well-behaved choice in the stacking literature (Wolpert 1992's own
    original used a similarly simple combiner). It also degrades gracefully
    to something close to a weighted average when the scores are strongly
    correlated, rather than finding spurious structure in three collinear
    inputs the way a high-capacity model could.
    """

    meta_model: LogisticRegression
    model_names: list[str]

    @classmethod
    def fit(
        cls,
        oof_predictions: pd.DataFrame,
        model_names: list[str],
        seed: int = config.RANDOM_SEED,
    ) -> "StackedEnsemble":
        features = oof_predictions[model_names].to_numpy()
        target = oof_predictions["presence"].to_numpy()
        meta_model = LogisticRegression(random_state=seed)
        meta_model.fit(features, target)
        return cls(meta_model=meta_model, model_names=list(model_names))

    def combine(self, predictions: dict[str, np.ndarray]) -> np.ndarray:
        features = np.column_stack([np.asarray(predictions[name]) for name in self.model_names])
        return self.meta_model.predict_proba(features)[:, 1]
