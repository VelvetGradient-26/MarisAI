"""Shared SHAP-attribution helpers for tree-based problem pipelines.

Both `hab_early_warning` and `fish_habitat_prediction` build their pipelines
the same way -- `Pipeline([("prep", ColumnTransformer(...)), ("model", ...)])`,
optionally wrapped in `CalibratedClassifierCV(FrozenEstimator(pipeline))` for
HAB's isotonic calibration -- so the unwrap-and-explain plumbing belongs here
rather than in one problem's `src/`.

Combining multiple explainers into one per-original-feature attribution --
fish habitat's ensemble problem (MaxEnt + RandomForest + LightGBM,
skill-weighted; see `fish_habitat_prediction/src/models.py`) -- lives here
too, as of SHAP Phase 2: `tree_shap_matrix_probability` (LightGBM, forced
into probability space -- its default output is margin/logit space, unlike
`tree_shap_matrix`'s use for HAB and for habitat's own RandomForest tier,
both of which are already exact in probability space by default),
`sum_hinge_quadratic_blocks` (reduces MaxEnt's hinge/quadratic feature
expansion back to one contribution per original column), and
`linear_shap_matrix_probability` (MaxEnt's LinearExplainer wrapper, with a
secant-slope conversion through its logistic link). The combination itself
-- the skill-weighted sum across tiers -- lives in
`scripts/export_predictions.py::export_habitat()`, next to the identical
weighted sum it already applies to the tiers' predictions, not here.
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


def tree_shap_matrix_probability(booster, transformed: np.ndarray, background: np.ndarray) -> np.ndarray:
    """Per-row, per-feature TreeSHAP contributions toward the positive class,
    forced into probability space.

    `tree_shap_matrix`'s default (`tree_path_dependent`, no background) is
    the right, cheap choice for a model whose *default* SHAP output already
    reconstructs `predict_proba` -- true for HAB's own LightGBM model and,
    verified separately, true again for fish habitat's RandomForest tier
    (both reconstruct `predict_proba` to ~1e-15 by default) -- so
    RandomForest keeps calling `tree_shap_matrix` unmodified; it does not
    need this function, and is in fact ~6x cheaper left alone (measured:
    ~18ms/row default vs ~117ms/row forced through this function's path).

    It is verified, empirically, *not* true for fish habitat's LightGBM
    tier: `TreeExplainer(lgbm_booster)`'s default output reconstructs
    `logit(predict_proba)`, not `predict_proba` -- the same margin-space
    finding as HAB's own LightGBM model. Combining fish habitat's three
    tiers means summing each tier's contribution in one shared unit --
    probability, because that is the space `EnsembleWeights.combine`
    (fish_habitat_prediction/src/models.py) actually operates in for the
    served prediction -- so LightGBM's contribution has to be forced there.
    `model_output="probability"` with `feature_perturbation="interventional"`
    does this exactly: verified against the real fitted habitat LightGBM
    model to ~6e-9 (float rounding, not a coincidence).

    This is a new function rather than a `tree_shap_matrix` parameter
    because the two have different *cost* profiles as well as different
    output spaces: `tree_shap_matrix`'s tree_path_dependent mode needs no
    background and is O(rows); this needs a background sample and is
    O(rows * background). HAB's own call site must keep costing what it
    costs today, unconditionally.

    `background` is a real `(n_background, n_features)` sample of
    already-`prep`-transformed rows, drawn from the same distribution being
    explained -- see `export_habitat()` for where and why it is drawn
    per-species. Cast to float32 for the same reason `tree_shap_matrix`
    casts its own return value: the model's own inputs are float32.
    """
    import shap

    explainer = shap.TreeExplainer(
        booster, data=background, model_output="probability",
        feature_perturbation="interventional",
    )
    values = explainer.shap_values(transformed)
    if isinstance(values, list):
        values = values[1]
    elif np.asarray(values).ndim == 3:
        values = np.asarray(values)[:, :, 1]
    return np.asarray(values, dtype="float32")


def sum_hinge_quadratic_blocks(matrix: np.ndarray, n_hinges: int) -> np.ndarray:
    """Collapse a `HingeQuadraticExpansion`-expanded SHAP/coefficient matrix
    back to one column per original (pre-expansion) feature.

    `HingeQuadraticExpansion.transform` (fish_habitat_prediction/src/
    models.py) turns `n` prep-space columns into `n * (2 + n_hinges)`
    columns, as `2 + n_hinges` contiguous blocks of `n` columns each, in
    this fixed order: linear, quadratic, then one hinge block per knot
    (`np.hstack([X, X**2, hinge_0, ..., hinge_{n_hinges-1}])`). Column `j`
    of block `b` is `expand`'s `b*n + j`-th output column and is *derived
    from*, not independent of, prep-space column `j` -- verified exactly
    against the real fitted MaxEnt model's 255 = 51*5 output columns
    (block0==X, block1==X**2, block2..4==maximum(0, X - knots_[0..2])).

    A linear model's per-column SHAP values are additive by construction
    (`shap.LinearExplainer`'s own guarantee), so summing every derived
    column's contribution back onto its one originating prep-space column
    is exact, not an approximation: it is the contribution of "this
    variable, however MaxEnt chose to bend its response to it," not of one
    specific bend in isolation.

    `n_hinges` must be the fitted `HingeQuadraticExpansion.n_hinges`
    (equivalently `knots_.shape[0]`) -- read from the fitted object, never
    assumed to be a specific value, so a future retrain with a different
    `n_hinges` keeps working with no edit here.

    `matrix` is `(n_rows, n * (2 + n_hinges))`; raises `ValueError` if that
    does not divide evenly by `2 + n_hinges`, so a shape mismatch fails
    loudly rather than silently summing the wrong columns together.
    """
    n_blocks = 2 + n_hinges
    n_rows, n_expanded = matrix.shape
    if n_expanded % n_blocks != 0:
        raise ValueError(
            f"matrix has {n_expanded} columns, not divisible by "
            f"2 + n_hinges = {n_blocks} (linear + quadratic + {n_hinges} hinge blocks)"
        )
    n = n_expanded // n_blocks
    return matrix.reshape(n_rows, n_blocks, n).sum(axis=1)


def linear_shap_matrix_probability(
    model, transformed: np.ndarray, background: np.ndarray, n_hinges: int
) -> np.ndarray:
    """MaxEnt's per-original-(prep-space)-feature contribution toward the
    positive class, in probability space.

    `shap.LinearExplainer` is exact and cheap for MaxEnt's fitted
    `LogisticRegression` -- verified additive to `logit(predict_proba)` to
    ~1e-15 on the real fitted model -- but it explains the model's linear
    score (the logit), never probability: the logistic link is the one
    nonlinear step `LinearExplainer` does not see through. There is no
    algebraic identity that splits `sigmoid(z)` into per-feature terms that
    both sum correctly and stay a genuine Shapley decomposition, short of a
    permutation/kernel explainer -- measured at ~1.4s/row on the real fitted
    model, which at this export's real row count (~189,180 rows/species x 5
    species) would take on the order of two weeks. Impractical; not used
    here.

    The approximation used instead is a **secant-slope** linearisation:

        z_base = LinearExplainer.expected_value      (scalar; mean logit over `background`)
        p_base = sigmoid(z_base)
        z_row  = z_base + sum(shap_logit_reduced, axis=1)
        p_row  = model.predict_proba(transformed)[:, 1]   (already known, exact)
        secant = (p_row - p_base) / (z_row - z_base)      (or p_row*(1-p_row) if that denominator ~ 0)
        shap_prob[i] = shap_logit_reduced[i] * secant

    This is deliberately *not* the more usual single-point derivative rule
    (`p_row * (1 - p_row)`, evaluated only at the row's own score). Checked
    against a real permutation-SHAP reference on the real fitted model, the
    single-point rule under- or over-shoots the sigmoid's actual swing
    whenever the row's and baseline's slopes differ. The secant slope is the
    unique choice that makes `shap_prob.sum(axis=1) == p_row - p_base`
    **exactly** (verified to ~3e-16 on real rows) rather than approximately,
    while leaving every feature's *relative* attribution -- and therefore
    `top_k_indices_and_values`'s ranking -- identical to either single-point
    rule, since all these choices differ only by one positive per-row
    scalar.

    `transformed`/`background` are already `prep.transform`-ed *and*
    `expand.transform`-ed, matching the convention `tree_shap_matrix`/
    `tree_shap_matrix_probability` already use of taking pre-transformed
    matrices, not raw frames. `n_hinges` must be the fitted
    `HingeQuadraticExpansion.n_hinges` -- see `sum_hinge_quadratic_blocks`.

    Returns `(n_rows, n_prep_features)` float32 -- the same shape and unit
    (probability-space, positive-class) as `tree_shap_matrix`/
    `tree_shap_matrix_probability`'s own output, so all three tiers combine
    with one weighted sum.
    """
    import shap

    explainer = shap.LinearExplainer(model, background)
    shap_logit_expanded = np.asarray(explainer.shap_values(transformed), dtype="float64")
    shap_logit = sum_hinge_quadratic_blocks(shap_logit_expanded, n_hinges)

    z_base = float(np.asarray(explainer.expected_value).reshape(-1)[-1])
    p_base = 1.0 / (1.0 + np.exp(-z_base))
    z_row = z_base + shap_logit.sum(axis=1)
    p_row = model.predict_proba(transformed)[:, 1]

    denom = z_row - z_base
    safe_denom = np.where(np.abs(denom) > 1e-9, denom, 1.0)
    secant = np.where(np.abs(denom) > 1e-9, (p_row - p_base) / safe_denom, p_row * (1.0 - p_row))

    return (shap_logit * secant[:, None]).astype("float32")


def top_k_indices_and_values(
    matrix: np.ndarray, top_k: int, index_dtype: str = "int16"
) -> tuple[np.ndarray, np.ndarray]:
    """Reduce a `(n_rows, n_features)` signed contribution matrix to the
    top-k by absolute magnitude, per row.

    Ranks by `|contribution|` for the reason `ShapExplainer.explain_row`
    (backend/forecasting/shap_explainer.py) already does: a large negative
    push is exactly as much of an explanation as a large positive one.
    Returns `(indices, values)`, each `(n_rows, top_k)` -- `values` is
    always float32.

    `index_dtype` defaults to `int16` -- HAB's own 139-column feature space
    needs it, since int8 tops out at 127. A smaller feature space (fish
    habitat's is 51 columns) can pass `index_dtype="int8"` to halve this
    array's footprint; still comfortably wide enough (-128..127) for -1's
    "no value" sentinel plus every real index. Pass whichever dtype covers
    `matrix.shape[1] - 1` (and `-1`) for a new caller -- this function does
    not check for you.
    """
    order = np.argsort(-np.abs(matrix), axis=1)[:, :top_k]
    values = np.take_along_axis(matrix, order, axis=1)
    return order.astype(index_dtype), values.astype("float32")
