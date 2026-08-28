"""Tests for ingesting the backend forecasting engine's runs.

This is the half of tracking that crosses a deliberate architectural boundary:
`backend/` must not import MLflow, so the backend writes plain JSON and the ML
side reads it. That inversion is only safe if ingestion is faithful and
repeatable, which is what these tests pin.
"""

from __future__ import annotations

import json

import pytest

from marine_ml import ingest_forecasting, tracking


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("MARINE_ML_TRACKING_URI", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("MARINE_ML_ARTIFACT_URI", (tmp_path / "artifacts").as_uri())
    monkeypatch.setattr(tracking, "DEFAULT_ARTIFACTS", tmp_path / "artifacts")
    return tmp_path


def _write_model(
    root,
    variable: str,
    horizon: int,
    *,
    skill: float,
    fold_skills: list[float],
    trained_at: str = "2026-08-05T12:00:00+00:00",
    skipped: list | None = None,
):
    """Write a model artifact pair in the backend's real on-disk shape."""
    directory = root / variable / f"h{horizon}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "metadata.json").write_text(
        json.dumps(
            {
                "variable": variable,
                "horizon": horizon,
                "trained_at": trained_at,
                "target_mode": "delta",
                "model_type": "LightGBM",
                "model_params": {"n_estimators": 400},
                "covariates": ["sea_surface_temperature"],
                "feature_count": 81,
                "training_rows": 18816,
                "training_points": ["a", "b"],
                "skipped_points": skipped or [],
                "training_started": "2024-06-06",
                "training_ended": "2026-07-29",
                "training_duration_seconds": 12.5,
                "resolution": "daily",
                "log_transform": False,
                "circular": False,
            }
        )
    )
    (directory / "metrics.json").write_text(
        json.dumps(
            {
                "validation": {
                    "metrics": {"mae": 0.1, "rmse": 0.2, "skill_score": skill},
                    "folds": [
                        {"fold": i, "skill_score": value}
                        for i, value in enumerate(fold_skills, start=1)
                    ],
                },
                "feature_importance": [
                    {"feature": "sst_lag1", "importance": 0.5},
                    {"feature": "abs_latitude", "importance": 0.2},
                ],
            }
        )
    )
    return directory


def test_discovers_model_artifacts(tmp_path):
    _write_model(tmp_path, "ph", 7, skill=0.1, fold_skills=[0.1, 0.2])
    _write_model(tmp_path, "nitrate", 1, skill=0.3, fold_skills=[0.3])

    found = ingest_forecasting.discover_models(tmp_path)
    assert {(r.variable, r.horizon) for r in found} == {("ph", 7), ("nitrate", 1)}


def test_ignores_the_reports_directory(tmp_path):
    """`_reports/` sits beside the variables and is not a model."""
    (tmp_path / "_reports" / "h1").mkdir(parents=True)
    (tmp_path / "_reports" / "h1" / "metadata.json").write_text("{}")
    (tmp_path / "_reports" / "h1" / "metrics.json").write_text("{}")
    _write_model(tmp_path, "ph", 7, skill=0.1, fold_skills=[0.1])

    found = ingest_forecasting.discover_models(tmp_path)
    assert [r.variable for r in found] == ["ph"]


def test_an_unreadable_artifact_is_skipped_not_fatal(tmp_path):
    _write_model(tmp_path, "ph", 7, skill=0.1, fold_skills=[0.1])
    broken = tmp_path / "broken" / "h1"
    broken.mkdir(parents=True)
    (broken / "metadata.json").write_text("{not json")
    (broken / "metrics.json").write_text("{}")

    found = ingest_forecasting.discover_models(tmp_path)
    assert [r.variable for r in found] == ["ph"]


def test_ingestion_records_the_headline_metrics_and_window(store, tmp_path):
    root = tmp_path / "models"
    _write_model(root, "ph", 7, skill=0.106, fold_skills=[0.1, 0.12, 0.09])
    run = ingest_forecasting.discover_models(root)[0]

    run_id = ingest_forecasting.ingest_one(run)

    import mlflow

    mlflow.set_tracking_uri(tracking.tracking_uri())
    fetched = mlflow.get_run(run_id)
    assert fetched.data.metrics["skill_score"] == pytest.approx(0.106)
    assert fetched.data.metrics["rows"] == 18816
    assert fetched.data.params["window_start"] == "2024-06-06"
    assert fetched.data.params["variable"] == "ph"
    assert fetched.data.tags["horizon"] == "7"


@pytest.mark.parametrize(
    ("skill", "folds", "expected"),
    [
        # Clean pass.
        (0.25, [0.2, 0.3, 0.25, 0.22, 0.28], 1.0),
        # Negative overall — never ships, whatever the folds say.
        (-0.056, [0.1, -0.2, -0.1, 0.05, 0.02], 0.0),
        # Positive mean carried by a minority of folds: this is the case that
        # printed "beats persistence" and still had to be deleted.
        (0.050, [-0.065, 0.067, -0.123, 0.194, 0.208], 0.0),
        # Exactly one negative fold is tolerated (the pre-existing SST h3 case).
        (0.065, [-0.01, 0.08, 0.09, 0.07, 0.08], 1.0),
    ],
)
def test_passes_bar_reproduces_the_shipping_rule(store, tmp_path, skill, folds, expected):
    """The bar is recorded as a metric so it cannot drift from the prose.

    Ship only if overall skill > 0 AND at most one of five folds is negative.
    """
    root = tmp_path / "models"
    _write_model(root, "v", 7, skill=skill, fold_skills=folds)
    run = ingest_forecasting.discover_models(root)[0]

    run_id = ingest_forecasting.ingest_one(run)

    import mlflow

    mlflow.set_tracking_uri(tracking.tracking_uri())
    assert mlflow.get_run(run_id).data.metrics["passes_bar"] == expected


def test_skipped_points_are_surfaced(store, tmp_path):
    """Partial spatial coverage is the silent failure mode — rainfall trained
    on 10 of 24 points, all northern, and still scored +0.38."""
    root = tmp_path / "models"
    _write_model(
        root,
        "rainfall",
        1,
        skill=0.377,
        fold_skills=[0.3, 0.4],
        skipped=[{"point": "south_pacific_gyre", "reason": "429"}],
    )
    run = ingest_forecasting.discover_models(root)[0]

    run_id = ingest_forecasting.ingest_one(run)

    import mlflow

    mlflow.set_tracking_uri(tracking.tracking_uri())
    assert mlflow.get_run(run_id).data.params["n_points_skipped"] == "1"


def test_ingestion_is_idempotent(store, tmp_path, monkeypatch):
    """Re-running after every training batch must not duplicate runs."""
    root = tmp_path / "models"
    _write_model(root, "ph", 7, skill=0.1, fold_skills=[0.1, 0.2])
    monkeypatch.setattr(ingest_forecasting, "MODELS_ROOT", root)

    ingest_forecasting.run_cli(["--models-root", str(root)])
    ingest_forecasting.run_cli(["--models-root", str(root)])

    import mlflow

    mlflow.set_tracking_uri(tracking.tracking_uri())
    experiment = mlflow.get_experiment_by_name(ingest_forecasting.EXPERIMENT)
    assert len(mlflow.search_runs([experiment.experiment_id])) == 1


def test_retraining_the_same_model_creates_a_new_run(store, tmp_path, monkeypatch):
    """A retrain must be a *new* record — that is the whole point.

    Identity is (variable, horizon, trained_at), so the previous result
    survives instead of being overwritten the way the JSON reports are.
    """
    root = tmp_path / "models"
    monkeypatch.setattr(ingest_forecasting, "MODELS_ROOT", root)

    _write_model(root, "ph", 7, skill=0.10, fold_skills=[0.1], trained_at="2026-08-05T12:00:00Z")
    ingest_forecasting.run_cli(["--models-root", str(root)])

    _write_model(root, "ph", 7, skill=0.22, fold_skills=[0.2], trained_at="2026-08-06T09:00:00Z")
    ingest_forecasting.run_cli(["--models-root", str(root)])

    import mlflow

    mlflow.set_tracking_uri(tracking.tracking_uri())
    experiment = mlflow.get_experiment_by_name(ingest_forecasting.EXPERIMENT)
    frame = mlflow.search_runs([experiment.experiment_id])
    assert len(frame) == 2
    assert sorted(frame["metrics.skill_score"].round(2)) == [0.10, 0.22]
