"""The data-quality report must not itself misreport quality.

Every assertion here is about a way this panel could be *confidently wrong*,
which is the only interesting failure mode for something whose entire job is
telling the truth about the platform's own data. A report that crashes is
obvious; a report that quietly grades a bad model as good, or lists work that
can never be done as pending, is the thing that gets believed.

Four properties, each pinning a mistake that was either made once already or
is one edit away:

* **The grade reads the folds, not the mean.** The shipping bar (TODO.md §2)
  is skill > 0 *and* at most one of five folds negative, and six rejected
  horizons printed `beats persistence` on their aggregate. A grade computed
  from `skill_score` alone would have called all six of them good.
* **Ungriddable is not ungridded.** The five Open-Meteo variables can never
  have a global field — a point API capped at 900 points — so listing them as
  grids awaiting a build is a permanent false gap.
* **Describing a model does not unpickle it.** `summary()` used to call
  `load()`, deserialising 115 LightGBM boosters to read four JSON numbers.
* **A broken artifact is reported, never dropped.** Silently shrinking the
  model list is how a failed retrain looks like a healthy platform.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forecasting import model_store
from services.dashboard import data_quality


# --- Grading -----------------------------------------------------------------


def test_grade_demotes_a_model_carried_by_a_minority_of_folds():
    """The exact case the aggregate hides.

    Positive overall skill with two of five folds negative is
    `sea_level_anomaly` h7 as actually trained (+0.073, folds spanning
    -0.296..+0.222). It printed `beats persistence` and was deleted on the
    fold rule. Grading on the mean alone would call it good.
    """
    carried = data_quality._grade_from_skill(0.073, negative_folds=2, n_folds=5)
    clean = data_quality._grade_from_skill(0.073, negative_folds=0, n_folds=5)

    assert carried == "fair"
    assert clean == "strong"
    # The point: identical headline skill, different grade.
    assert carried != clean


def test_grade_is_poor_when_persistence_wins():
    assert data_quality._grade_from_skill(-0.12, negative_folds=3, n_folds=5) == "poor"
    assert data_quality._grade_from_skill(0.0, negative_folds=0, n_folds=5) == "poor"


def test_grade_is_unknown_rather_than_optimistic_without_folds():
    """No evidence must not read as good evidence."""
    assert data_quality._grade_from_skill(0.4, negative_folds=0, n_folds=0) == "unknown"
    assert data_quality._grade_from_skill(None, negative_folds=0, n_folds=5) == "unknown"


def test_one_negative_fold_still_passes_the_bar():
    """The bar allows one, and `diffuse_attenuation` h3 shipped on exactly that."""
    assert data_quality._grade_from_skill(0.026, negative_folds=1, n_folds=5) == "good"


# --- Cadence labelling -------------------------------------------------------


def test_three_hourly_is_not_rounded_to_daily():
    """Waves publish 8 steps a day. Calling that 'daily' understates it 3x."""
    assert data_quality._cadence_label(8, time_varying=True) == "3-hourly"
    assert data_quality._cadence_label(24, time_varying=True) == "hourly"
    assert data_quality._cadence_label(1, time_varying=True) == "daily"


def test_bathymetry_is_time_invariant_not_zero_cadence():
    """GEBCO has no time dimension; '0 steps per day' would read as broken."""
    assert data_quality._cadence_label(0, time_varying=False) == "time-invariant"


# --- Coverage ----------------------------------------------------------------


def test_openmeteo_variables_are_ungriddable_not_merely_ungridded():
    coverage = data_quality.coverage()

    ungriddable = {entry["code"] for entry in coverage["trained_but_ungriddable"]}
    ungridded = set(coverage["trained_but_ungridded"])

    # Every Open-Meteo target lands in the permanent bucket...
    assert "air_temperature" in ungriddable
    # ...and never in the pending-work bucket.
    assert not (ungriddable & ungridded)
    # And the reason is in words, not a bare flag.
    for entry in coverage["trained_but_ungriddable"]:
        assert entry["reason"]


def test_coverage_separates_untrained_from_ungridded():
    """Three distinct stages, three distinct counts.

    A variable can be servable but never forecast, or forecast but not
    visible. Collapsing them hides which stage the gap is in.
    """
    coverage = data_quality.coverage()

    assert coverage["variables_served"] <= coverage["variables_total"]
    assert coverage["variables_trained"] <= coverage["variables_configured_for_forecast"]
    assert coverage["models_trained"] >= coverage["variables_trained"]
    # Untrained means configured-but-absent, so it cannot name a trained one.
    trained = set(model_store.list_trained())
    assert not (set(coverage["configured_but_untrained"]) & trained)


def test_unavailable_variables_are_named_not_just_counted():
    """`tidal_height` and `ammonium` have no global source. Say which."""
    coverage = data_quality.coverage()
    codes = {entry["code"] for entry in coverage["variables_unavailable"]}
    assert "tidal_height" in codes
    assert "ammonium" in codes


# --- Describing without loading ----------------------------------------------


def test_describe_does_not_unpickle_the_booster(monkeypatch):
    """The whole reason `describe()` exists.

    Reading 115 artifacts to render a table must not deserialise 115 gradient
    boosting models. Fails loudly if anyone routes `describe` back through
    `load`.
    """
    trained = model_store.list_trained()
    if not trained:
        pytest.skip("no trained models on disk")

    def explode(*args, **kwargs):  # pragma: no cover - only runs on regression
        raise AssertionError("describe() must not unpickle model.pkl")

    monkeypatch.setattr(model_store.pickle, "loads", explode)

    variable = sorted(trained)[0]
    horizon = trained[variable][0]
    described = model_store.describe(variable, horizon)

    assert described.variable == variable
    assert described.horizon == horizon
    assert described.feature_columns


def test_describe_refuses_a_directory_with_json_but_no_model(tmp_path: Path):
    """A metadata-only directory is an interrupted save, not a trained model."""
    directory = tmp_path / "some_variable" / "h1"
    directory.mkdir(parents=True)
    (directory / model_store.METADATA_FILE).write_text(
        json.dumps({"artifact_version": model_store.ARTIFACT_VERSION})
    )

    with pytest.raises(model_store.ModelNotTrainedError):
        model_store.describe("some_variable", 1, root=tmp_path)


def test_describe_refuses_a_stale_artifact_version(tmp_path: Path):
    directory = tmp_path / "some_variable" / "h1"
    directory.mkdir(parents=True)
    (directory / model_store.MODEL_FILE).write_bytes(b"not-a-real-pickle")
    (directory / model_store.METADATA_FILE).write_text(
        json.dumps({"artifact_version": model_store.ARTIFACT_VERSION + 99})
    )
    (directory / model_store.METRICS_FILE).write_text("{}")
    (directory / model_store.FEATURES_FILE).write_text(json.dumps({"feature_columns": []}))

    with pytest.raises(model_store.ModelStoreError):
        model_store.describe("some_variable", 1, root=tmp_path)


def test_negative_folds_counts_zero_as_negative():
    """Zero skill is chance, not a pass. `<= 0`, not `< 0`."""
    described = model_store.ModelDescription(
        variable="x",
        horizon=1,
        metadata={},
        metrics={
            "validation": {
                "folds": [
                    {"skill_score": 0.2},
                    {"skill_score": 0.0},
                    {"skill_score": -0.1},
                    {"skill_score": None},
                ]
            }
        },
        feature_columns=[],
    )
    assert described.negative_folds == 2


# --- The assembled report ----------------------------------------------------


def test_build_reports_every_catalogued_dataset():
    report = data_quality.build()

    from services.download import catalog

    assert len(report["datasets"]) == len(catalog.PROVIDERS)
    for entry in report["datasets"]:
        # Citation and licence must survive to the panel — they are the point
        # of a provenance display.
        assert entry["licence"]
        assert entry["source_label"]
        assert entry["cadence"]


def test_a_dataset_without_a_live_cache_says_so_rather_than_reading_as_down():
    """Most datasets are fetched per request and hold no warm copy.

    Reporting those as unhealthy would red-light eleven of fourteen rows
    permanently, which is the "cry wolf" failure the codebase already fixed
    once in the grounding checker.
    """
    report = data_quality.build()
    uncached = [d for d in report["datasets"] if d["cache"]["health"] == "not_cached"]

    assert uncached, "expected per-request datasets to be reported as uncached"
    for entry in uncached:
        assert entry["cache"]["unavailable_reason"]
        assert entry["cache"]["health"] != "down"


def test_every_model_entry_carries_the_fold_spread():
    report = data_quality.build()
    models = [m for m in report["models"] if m["available"]]
    if not models:
        pytest.skip("no trained models on disk")

    for entry in models:
        assert entry["n_folds"] >= 0
        assert entry["negative_folds"] <= entry["n_folds"]
        assert entry["grade"] in {"strong", "good", "fair", "poor", "unknown"}
        # Geography loss is reported: a global model missing points has lost
        # coverage, not just rows.
        assert entry["points_used"] >= 0
        assert entry["points_skipped"] >= 0


def test_the_endpoints_serve_the_report():
    """Thin-router check: 200 and the whole payload, not a 500 on a cold cache.

    The panel must render on a freshly started server, where every live cache
    is still empty — that is the state a data-quality page is *most* needed in,
    and failing there would be self-defeating.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import dashboard as dashboard_router

    app = FastAPI()
    app.include_router(dashboard_router.router)
    client = TestClient(app)

    response = client.get("/api/dashboard/data-quality")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) >= {"datasets", "models", "coverage", "model_summary"}

    models_only = client.get("/api/dashboard/data-quality/models")
    assert models_only.status_code == 200
    assert len(models_only.json()["models"]) == len(payload["models"])


def test_an_unreadable_artifact_is_reported_not_omitted(tmp_path, monkeypatch):
    """A corrupt model must appear as unavailable, with a reason."""
    root = tmp_path / "models"
    directory = root / "broken_variable" / "h1"
    directory.mkdir(parents=True)
    (directory / model_store.MODEL_FILE).write_bytes(b"stub")
    (directory / model_store.METADATA_FILE).write_text("{ not json")
    (directory / model_store.METRICS_FILE).write_text("{}")
    (directory / model_store.FEATURES_FILE).write_text(json.dumps({"feature_columns": []}))

    monkeypatch.setattr(model_store, "MODELS_DIR", root)

    entries = data_quality.models()
    broken = [e for e in entries if e["variable"] == "broken_variable"]

    assert len(broken) == 1
    assert broken[0]["available"] is False
    assert broken[0]["unavailable_reason"]
