"""Tests for experiment tracking.

The properties worth pinning are not "MLflow works" — that is MLflow's problem.
They are the two ways this integration could quietly do harm:

1. **Tracking must never break a training run.** A HAB run is ~40 minutes on
   1.3M rows; losing it to a locked tracking store would be strictly worse than
   not tracking at all. Every failure path must degrade to a warning.
2. **A recorded run must be honest.** NaN metrics, index columns aggregated as
   if they were scores, and silently dropped values all corrupt exactly the
   comparison the tracker exists to enable.
"""

from __future__ import annotations

import pandas as pd
import pytest

from marine_ml import tracking


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point tracking at a throwaway store so tests never touch mlruns.db."""
    monkeypatch.setenv("MARINE_ML_TRACKING_URI", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("MARINE_ML_ARTIFACT_URI", (tmp_path / "artifacts").as_uri())
    monkeypatch.setattr(tracking, "DEFAULT_ARTIFACTS", tmp_path / "artifacts")
    return tmp_path


def _fetch(run_id):
    import mlflow

    mlflow.set_tracking_uri(tracking.tracking_uri())
    return mlflow.get_run(run_id)


# --------------------------------------------------------------------------
# Tracking must never break a training run
# --------------------------------------------------------------------------


def test_disabled_tracking_yields_an_inert_handle_that_still_accepts_calls(store):
    """`enabled=False` must not force call sites to grow conditionals."""
    with tracking.track("x", enabled=False) as run:
        assert run.run_id is None
        # Every method still callable, all no-ops.
        run.log_params({"a": 1})
        run.log_metrics({"b": 2.0})
        run.log_fold_scores(pd.DataFrame({"tss": [0.5]}))
        run.log_shap(pd.DataFrame({"feature": ["f"], "mean_abs_shap": [1.0]}))
        run.log_data_window(start="2020-01-01", end="2020-12-31", rows=10)
        run.set_tags({"t": "v"})


def test_env_var_disables_tracking(store, monkeypatch):
    monkeypatch.setenv("MARINE_ML_TRACKING", "0")
    with tracking.track("x") as run:
        assert run.run_id is None


def test_a_failing_logger_does_not_propagate(store):
    """A broken metric must not take the run down with it."""
    with tracking.track("guard") as run:
        assert run.run_id is not None
        # A DataFrame with no `feature` column: log_shap must cope silently.
        run.log_shap(pd.DataFrame({"nope": [1, 2]}))
        # An unserialisable object as a param value.
        run.log_params({"weird": object()})
        run.log_metrics({"not_a_number": "abc"})


def test_an_exception_inside_the_run_still_propagates(store):
    """Tracking swallows *its own* errors, never the caller's."""
    with pytest.raises(ValueError, match="training blew up"):
        with tracking.track("guard") as run:
            assert run.run_id is not None
            raise ValueError("training blew up")


# --------------------------------------------------------------------------
# A recorded run must be honest
# --------------------------------------------------------------------------


def test_nan_and_infinite_metrics_are_skipped_not_stored(store):
    """MLflow stores NaN as a real value, which poisons every comparison."""
    with tracking.track("honesty") as run:
        run.log_metrics(
            {"good": 0.5, "nan": float("nan"), "inf": float("inf"), "ninf": float("-inf")}
        )
        run_id = run.run_id

    metrics = _fetch(run_id).data.metrics
    assert metrics["good"] == 0.5
    assert "nan" not in metrics
    assert "inf" not in metrics
    assert "ninf" not in metrics


def test_fold_scores_log_the_spread_not_only_the_mean(store):
    """The mean alone hides the failure this project keeps hitting.

    Four forecasting horizons printed "beats persistence" on an aggregate while
    individual folds were negative. Min/max/std are what make that visible.
    """
    folds = pd.DataFrame({"fold": [1, 2, 3], "skill_score": [-0.2, 0.3, 0.4]})
    with tracking.track("honesty") as run:
        run.log_fold_scores(folds)
        run_id = run.run_id

    metrics = _fetch(run_id).data.metrics
    assert metrics["cv_skill_score_mean"] == pytest.approx(0.1666, abs=1e-3)
    assert metrics["cv_skill_score_min"] == pytest.approx(-0.2)
    assert metrics["cv_skill_score_max"] == pytest.approx(0.4)
    assert "cv_skill_score_std" in metrics


def test_index_columns_are_not_aggregated_as_scores(store):
    """`fold` is an identifier; "cv_fold_mean = 2.0" is noise in a run list."""
    folds = pd.DataFrame({"fold": [1, 2, 3], "horizon": [7, 7, 7], "tss": [0.5, 0.6, 0.7]})
    with tracking.track("honesty") as run:
        run.log_fold_scores(folds)
        run_id = run.run_id

    metrics = _fetch(run_id).data.metrics
    assert "cv_tss_mean" in metrics
    assert not any(key.startswith("cv_fold_") for key in metrics)
    assert not any(key.startswith("cv_horizon_") for key in metrics)


def test_shap_ordering_is_recorded_as_a_param(store):
    """"Did the model's drivers change?" must be answerable without downloads."""
    importances = pd.DataFrame(
        {"feature": ["sst", "chl", "depth"], "mean_abs_shap": [0.5, 0.3, 0.1]}
    )
    with tracking.track("honesty") as run:
        run.log_shap(importances, top_n=3)
        run_id = run.run_id

    assert _fetch(run_id).data.params["shap_top3"] == "sst, chl, depth"


def test_resolved_data_window_is_recorded(store):
    """Coverage clamping moves a start date silently; a run trained on a
    shorter window is not comparable to one trained on the full record."""
    with tracking.track("honesty") as run:
        run.log_data_window(start="2024-06-13", end="2026-08-05", rows=18960)
        run_id = run.run_id

    fetched = _fetch(run_id)
    assert fetched.data.params["window_start"] == "2024-06-13"
    assert fetched.data.params["window_end"] == "2026-08-05"
    assert fetched.data.metrics["rows"] == 18960


def test_runs_accumulate_rather_than_overwrite(store):
    """The whole point: the previous result must survive the next run.

    This is the property every fixed-filename report in this repo lacks.
    """
    for index in range(3):
        with tracking.track("accumulate", run_name=f"run{index}") as run:
            run.log_metrics({"skill_score": index / 10})

    import mlflow

    mlflow.set_tracking_uri(tracking.tracking_uri())
    experiment = mlflow.get_experiment_by_name("accumulate")
    frame = mlflow.search_runs([experiment.experiment_id])
    assert len(frame) == 3
    assert sorted(frame["metrics.skill_score"].tolist()) == [0.0, 0.1, 0.2]


def test_snapshot_config_captures_constants_and_skips_callables():
    import types

    module = types.SimpleNamespace(
        HAB_START="2016-01-01",
        RANDOM_SEED=42,
        lowercase_ignored=1,
        SOME_FUNC=lambda: None,
    )
    snapshot = tracking.snapshot_config(module)
    assert snapshot["RANDOM_SEED"] == 42
    assert snapshot["HAB_START"] == "2016-01-01"
    assert "lowercase_ignored" not in snapshot
    assert "SOME_FUNC" not in snapshot
