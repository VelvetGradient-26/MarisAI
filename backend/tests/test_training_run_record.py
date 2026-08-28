"""The training CLI must not destroy the previous run's report.

`training_report.json` is a fixed filename. On 2026-08-05 two training batches
ran back to back and the second overwrote the first, leaving no way to compare
them — the concrete failure that motivated experiment tracking. The fix is an
immutable per-invocation record beside the fixed-name report.

The other property pinned here is architectural: this record is plain JSON
written with the standard library, because `backend/` must not gain an MLflow
dependency. Tracking lives in `machine_learning/` and *reads* these files. A
test asserts the import never appears, since the natural "improvement" someone
makes later is to log directly from the training script.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.train_forecasting import write_run_record

SUMMARY = [
    {"variable": "ph", "horizon": 7, "rows": 18816, "metrics": {"skill_score": 0.106}},
    {"variable": "ph", "horizon": 30, "error": "boom"},
]


def _record(tmp_path: Path, *, when: datetime, summary=None) -> Path:
    return write_run_record(
        tmp_path,
        run_started=when,
        summary=SUMMARY if summary is None else summary,
        elapsed=12.5,
        variables=["ph"],
        horizons=[7, 30],
        failures=1,
    )


def test_writes_report_and_invocation_metadata(tmp_path):
    run_dir = _record(tmp_path, when=datetime(2026, 8, 5, 12, 0, tzinfo=UTC))

    report = json.loads((run_dir / "report.json").read_text())
    assert report == SUMMARY

    meta = json.loads((run_dir / "run.json").read_text())
    assert meta["variables"] == ["ph"]
    assert meta["horizons"] == [7, 30]
    assert meta["models_trained"] == 1  # the errored entry is not a model
    assert meta["models_failed"] == 1
    assert meta["duration_seconds"] == 12.5
    assert meta["started_at"].startswith("2026-08-05T12:00:00")


def test_two_runs_do_not_overwrite_each_other(tmp_path):
    """The regression. Before this, the second batch destroyed the first."""
    first = _record(tmp_path, when=datetime(2026, 8, 5, 12, 0, tzinfo=UTC))
    second = _record(
        tmp_path,
        when=datetime(2026, 8, 5, 14, 30, tzinfo=UTC),
        summary=[{"variable": "nitrate", "horizon": 1, "metrics": {"skill_score": 0.39}}],
    )

    assert first != second
    assert json.loads((first / "report.json").read_text())[0]["variable"] == "ph"
    assert json.loads((second / "report.json").read_text())[0]["variable"] == "nitrate"
    assert len(list((tmp_path / "runs").iterdir())) == 2


def test_run_directories_sort_chronologically(tmp_path):
    """The ingester reads these in order; a timestamp that sorts wrong would
    silently associate models with the wrong invocation."""
    for hour in (9, 14, 3):
        _record(tmp_path, when=datetime(2026, 8, 5, hour, 0, tzinfo=UTC))

    names = [p.name for p in sorted((tmp_path / "runs").iterdir())]
    assert names == sorted(names)
    assert names[0].startswith("20260805T03")


def test_records_the_git_commit(tmp_path):
    """A result has to map back to the code that produced it."""
    run_dir = _record(tmp_path, when=datetime(2026, 8, 5, 12, 0, tzinfo=UTC))
    meta = json.loads((run_dir / "run.json").read_text())
    assert "git_commit" in meta  # may be None off a checkout, but must be recorded


def test_the_backend_never_imports_mlflow():
    """The boundary this whole design exists to preserve.

    `machine_learning/` is kept out of the backend's import graph deliberately;
    a tracking client imported by a training script lands in that same tree.
    Tracking is done by ingesting these JSON files from the ML side instead.
    """
    backend = Path(__file__).resolve().parents[1]
    offenders = []
    for path in backend.rglob("*.py"):
        if ".venv" in path.parts or path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import mlflow", "from mlflow")):
                offenders.append(f"{path.relative_to(backend)}: {stripped}")

    assert not offenders, "backend must not import mlflow:\n" + "\n".join(offenders)


@pytest.mark.parametrize("dependency_file", ["pyproject.toml", "requirements.txt"])
def test_mlflow_is_not_a_backend_dependency(dependency_file):
    backend = Path(__file__).resolve().parents[1]
    path = backend / dependency_file
    if not path.exists():
        pytest.skip(f"{dependency_file} not present")
    assert "mlflow" not in path.read_text().lower()
