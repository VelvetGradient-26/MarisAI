"""Experiment tracking — the one place a training run is recorded permanently.

Every report this project writes lands on a *fixed* filename
(``reports/hab_early_warning_summary.json``, ``reports/fish_habitat_shap.csv``,
the backend's ``_reports/training_report.json``), so each rerun destroys the
one before it. That makes "did that feature help?" unanswerable, which in turn
makes every modelling improvement unmeasurable. This module is the fix: a run
is appended here and never overwritten.

Design notes worth keeping:

* **The store is local and file-backed by default** (SQLite at
  ``machine_learning/mlruns.db``, artifacts under ``machine_learning/mlruns/``).
  No server process. ``MARINE_ML_TRACKING_URI`` overrides it if a real server
  ever appears.

* **``mlflow-skinny`` is the dependency, not ``mlflow``.** The full package
  pins ``pandas<3`` and ``pyarrow<23``, which would downgrade this environment
  from pandas 3.0.5 / pyarrow 25 — a major-version downgrade underneath a
  3.9M-row parquet feature store. Skinny plus SQLAlchemy gives the whole
  tracking client with none of that. The web UI is not installed; run it
  without touching this venv:

      uvx --from mlflow mlflow ui --backend-store-uri sqlite:///mlruns.db

* **Tracking never fails a training run.** A run that took 40 minutes must not
  be lost because a tracking store was locked or a metric was NaN. Every entry
  point degrades to a warning — see `_guard`. The inverse (silently recording
  nothing) is guarded by `active_run_id`, which the pipelines print.

* **`backend/` must never import this.** The backend forecasting engine is
  tracked by ingesting the immutable run directories it writes
  (`ingest_forecasting.py`), which is why that engine needs no MLflow
  dependency and keeps its import graph free of this package.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from marine_ml import config

logger = logging.getLogger(__name__)

# MLflow rejects a param value over 6000 chars and a name over 250. Long
# feature lists therefore go to an artifact and only their *count* to a param.
_MAX_PARAM_CHARS = 500

# Integer columns that identify a row rather than score it. Aggregating them
# produces meaningless metrics that crowd out the real ones.
_INDEX_COLUMNS = {"fold", "horizon", "split", "seed", "n", "index", "step"}

DEFAULT_DB = config.PROJECT_ROOT / "mlruns.db"
DEFAULT_ARTIFACTS = config.PROJECT_ROOT / "mlruns"


def tracking_uri() -> str:
    """Where runs are written. Override with ``MARINE_ML_TRACKING_URI``."""
    override = os.getenv("MARINE_ML_TRACKING_URI", "").strip()
    return override or f"sqlite:///{DEFAULT_DB}"


def artifact_uri() -> str:
    return os.getenv("MARINE_ML_ARTIFACT_URI", "").strip() or DEFAULT_ARTIFACTS.as_uri()


def _git_commit() -> str | None:
    """The commit the run was trained at, so a result maps back to code.

    Best-effort: a tarball export or a detached worktree has no git, and that
    is not a reason to fail a training run.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=config.REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = result.stdout.strip()
    return commit or None


def _jsonable(value: Any) -> Any:
    """Coerce numpy/pandas/date scalars into something json.dumps accepts."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    item = getattr(value, "item", None)
    if callable(item):  # numpy scalar
        try:
            return item()
        except (ValueError, TypeError):
            pass
    return str(value)


@contextmanager
def _guard(what: str) -> Iterator[None]:
    """Never let tracking take down a training run.

    A HAB run is ~40 minutes on 1.3M rows. Losing it because the tracking
    store was locked, or because a metric came out NaN, would be a strictly
    worse outcome than an untracked run.
    """
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - deliberate: tracking is not critical path
        logger.warning(f"experiment tracking: {what} failed ({exc}) — run continues")


@dataclass
class RunHandle:
    """A live tracking run. Returned by `track`; methods are all no-fail."""

    run_id: str | None
    experiment: str

    # ----------------------------------------------------------------- params

    def log_params(self, params: Mapping[str, Any]) -> None:
        """Record run inputs. Long values are truncated, not dropped."""
        if self.run_id is None:
            return
        import mlflow

        with _guard("log_params"):
            flat = {}
            for key, value in params.items():
                rendered = value if isinstance(value, (str, int, float, bool)) else json.dumps(
                    _jsonable(value), default=str
                )
                text = str(rendered)
                if len(text) > _MAX_PARAM_CHARS:
                    text = text[: _MAX_PARAM_CHARS - 3] + "..."
                flat[str(key)[:250]] = text
            mlflow.log_params(flat)

    def log_metrics(self, metrics: Mapping[str, Any], *, step: int | None = None) -> None:
        """Record numeric outcomes. Non-numeric and NaN entries are skipped.

        NaN is skipped rather than logged because MLflow stores it as a real
        value and it then pollutes every "best run" comparison.
        """
        if self.run_id is None:
            return
        import mlflow

        with _guard("log_metrics"):
            numeric: dict[str, float] = {}
            for key, value in metrics.items():
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                if number != number or number in (float("inf"), float("-inf")):
                    continue
                numeric[str(key)[:250]] = number
            if numeric:
                mlflow.log_metrics(numeric, step=step)

    def set_tags(self, tags: Mapping[str, Any]) -> None:
        if self.run_id is None:
            return
        import mlflow

        with _guard("set_tags"):
            mlflow.set_tags({str(k): str(_jsonable(v)) for k, v in tags.items()})

    # -------------------------------------------------------------- artifacts

    def log_dict(self, payload: Any, filename: str) -> None:
        """Store a JSON artifact (config snapshot, feature list, window)."""
        if self.run_id is None:
            return
        import mlflow

        with _guard(f"log_dict({filename})"):
            mlflow.log_dict(_jsonable(payload), filename)

    def log_table(self, frame: Any, filename: str) -> None:
        """Store a DataFrame as CSV alongside the run.

        Fold scores, holdout rows and SHAP rankings are already DataFrames in
        every trainer, so this keeps the call site to one line.
        """
        if self.run_id is None or frame is None:
            return
        import mlflow

        with _guard(f"log_table({filename})"):
            mlflow.log_text(frame.to_csv(index=False), filename)

    def log_file(self, path: Path | str, *, subdir: str | None = None) -> None:
        if self.run_id is None:
            return
        import mlflow

        source = Path(path)
        if not source.exists():
            return
        with _guard(f"log_file({source.name})"):
            mlflow.log_artifact(str(source), artifact_path=subdir)

    # ------------------------------------------------------- domain shortcuts

    def log_fold_scores(self, frame: Any, *, prefix: str = "cv") -> None:
        """Log per-fold results as an artifact *and* aggregate them as metrics.

        The aggregate matters as much as the table: a mean that looks fine
        while individual folds go negative is exactly the failure this project
        keeps hitting (four forecasting horizons printed "beats persistence"
        on the mean while failing on folds). Logging the spread makes that
        visible in the run list instead of only inside a CSV.
        """
        if frame is None or self.run_id is None:
            return
        self.log_table(frame, f"{prefix}_fold_scores.csv")
        with _guard("log_fold_scores"):
            numeric = frame.select_dtypes("number")
            summary: dict[str, float] = {}
            for column in numeric.columns:
                # `fold`/`horizon` are identifiers that happen to be integers;
                # aggregating them yields "cv_fold_mean = 2.0", which is noise
                # in a run list whose whole purpose is comparing scores.
                if str(column).lower() in _INDEX_COLUMNS:
                    continue
                series = numeric[column].dropna()
                if series.empty:
                    continue
                summary[f"{prefix}_{column}_mean"] = float(series.mean())
                summary[f"{prefix}_{column}_min"] = float(series.min())
                summary[f"{prefix}_{column}_max"] = float(series.max())
                if len(series) > 1:
                    summary[f"{prefix}_{column}_std"] = float(series.std())
            self.log_metrics(summary)

    def log_shap(self, frame: Any, *, top_n: int = 20, prefix: str = "shap") -> None:
        """Log the full SHAP ranking, plus the top-N ordering as a param.

        The ordering is what a later comparison actually reads ("did adding
        that feature change what the model leans on?"), and an artifact you
        have to download to see does not support that at a glance.
        """
        if frame is None or self.run_id is None:
            return
        self.log_table(frame, f"{prefix}_importances.csv")
        with _guard("log_shap"):
            if "feature" not in frame.columns:
                return
            top = frame.head(top_n)["feature"].astype(str).tolist()
            self.log_params({f"{prefix}_top{top_n}": ", ".join(top)})
            value_column = next(
                (c for c in ("mean_abs_shap", "importance", "gain") if c in frame.columns),
                None,
            )
            if value_column is not None:
                self.log_metrics(
                    {
                        f"{prefix}_top1_{frame.iloc[0]['feature']}"[:250]: frame.iloc[0][
                            value_column
                        ]
                    }
                )

    def log_data_window(
        self,
        *,
        start: Any,
        end: Any,
        rows: int | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        """Record the window the run actually resolved to.

        "Resolved" rather than "requested" is the point: coverage clamping
        moves a start date silently, and a run trained on a shorter window is
        not comparable to one trained on the full record.
        """
        payload: dict[str, Any] = {"start": start, "end": end, "rows": rows}
        if extra:
            payload.update(dict(extra))
        self.log_params(
            {"window_start": _jsonable(start), "window_end": _jsonable(end)}
        )
        if rows is not None:
            self.log_metrics({"rows": rows})
        self.log_dict(payload, "data_window.json")


@contextmanager
def track(
    experiment: str,
    *,
    run_name: str | None = None,
    params: Mapping[str, Any] | None = None,
    tags: Mapping[str, Any] | None = None,
    enabled: bool | None = None,
    nested: bool = False,
) -> Iterator[RunHandle]:
    """Open a tracked run. Yields a `RunHandle` that never raises.

    `enabled=False` (or ``MARINE_ML_TRACKING=0``) yields an inert handle, so a
    quick experiment can opt out without the call sites growing conditionals.

    `nested=True` opens a **child** of the run already active, which is how an
    ensemble's members are recorded. The alternative — and what this codebase did
    first — is to flatten members into the parent's metric names
    (`cv_tss_lightgbm`, `holdout_boyce_maxent`, ...). That is legible in a single
    run and useless across runs: MLflow cannot sort, filter or plot by a member
    when the member is part of the key, so "is MaxEnt's Boyce drifting?" needs
    reading every run by hand. As a child run the member is a row, and the
    question is a sort.
    """
    if enabled is None:
        enabled = os.getenv("MARINE_ML_TRACKING", "1").strip().lower() not in {
            "0",
            "false",
            "no",
        }

    if not enabled:
        yield RunHandle(run_id=None, experiment=experiment)
        return

    try:
        import mlflow
    except ImportError:
        logger.warning(
            "mlflow is not installed — run will not be tracked. "
            "Install with: uv pip install mlflow-skinny sqlalchemy alembic"
        )
        yield RunHandle(run_id=None, experiment=experiment)
        return

    handle = RunHandle(run_id=None, experiment=experiment)
    started = False
    try:
        DEFAULT_ARTIFACTS.mkdir(parents=True, exist_ok=True)
        mlflow.set_tracking_uri(tracking_uri())
        existing = mlflow.get_experiment_by_name(experiment)
        if existing is None:
            mlflow.create_experiment(experiment, artifact_location=artifact_uri())
        mlflow.set_experiment(experiment)
        run = mlflow.start_run(run_name=run_name, nested=nested)
        started = True
        handle.run_id = run.info.run_id
    except Exception as exc:  # noqa: BLE001 - tracking must not block training
        logger.warning(f"experiment tracking unavailable ({exc}) — run continues untracked")
        yield RunHandle(run_id=None, experiment=experiment)
        return

    commit = _git_commit()
    handle.set_tags({"git_commit": commit or "unknown", **(dict(tags) if tags else {})})
    if params:
        handle.log_params(params)

    try:
        yield handle
    except Exception:
        if started:
            with _guard("terminate FAILED"):
                mlflow.end_run(status="FAILED")
            started = False
        raise
    finally:
        if started:
            with _guard("end_run"):
                mlflow.end_run()


def snapshot_config(module: Any, *, include: Sequence[str] | None = None) -> dict[str, Any]:
    """Capture a config module's public constants as a plain dict.

    Used to record what `marine_ml.config` looked like for a run. Callables,
    modules and privates are skipped; everything else is coerced via
    `_jsonable` so dates and Paths survive.
    """
    keys = include if include is not None else [
        name
        for name in dir(module)
        if name.isupper() and not name.startswith("_")
    ]
    snapshot: dict[str, Any] = {}
    for name in keys:
        value = getattr(module, name, None)
        if callable(value) or isinstance(value, type):
            continue
        snapshot[name] = _jsonable(value)
    return snapshot
