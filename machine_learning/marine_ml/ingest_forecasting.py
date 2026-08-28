"""Ingest the backend forecasting engine's training runs into the experiment log.

The backend trains 32 configurable variables x 4 horizons and is the third
producer of model results in this repo — but `backend/` must not gain an MLflow
dependency. Keeping the modelling stack out of the API's import graph is a
deliberate boundary (`services/predictions.py` serves precomputed grids for the
same reason), and a tracking client imported by a training script still lands in
that tree.

So the direction is inverted: the backend writes plain JSON it already had to
write, and this module — which lives on the ML side, where MLflow is installed
— reads it. The backend stays unaware that tracking exists.

Two sources, both used:

* **Model artifacts** (`backend/models/forecasting/<variable>/h<horizon>/`) are
  the authoritative record. `metadata.json` carries the resolved training
  window, the point list, the skipped points and the feature count;
  `metrics.json` carries fold-level validation and SHAP. Every currently
  trained model can be backfilled from these, with no rerun.
* **Run directories** (`_reports/runs/<timestamp>/`) record which *invocation*
  produced a group of models, which model artifacts cannot know.

Ingestion is **idempotent**: a run is keyed by (variable, horizon, trained_at)
and skipped if already present, so this can be re-run after every training
batch without creating duplicates.

    python -m marine_ml.ingest_forecasting              # backfill everything new
    python -m marine_ml.ingest_forecasting --dry-run    # show what would land
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from marine_ml import config, tracking

logger = logging.getLogger("ingest_forecasting")

EXPERIMENT = "forecasting_engine"

BACKEND_ROOT = config.REPO_ROOT / "backend"
MODELS_ROOT = BACKEND_ROOT / "models" / "forecasting"
RUNS_ROOT = MODELS_ROOT / "_reports" / "runs"

# The metric everything else is judged against. Recorded under a stable name so
# runs sort by it regardless of which producer wrote them.
HEADLINE = "skill_score"


@dataclass(frozen=True)
class ModelRun:
    """One (variable, horizon) training result read off disk."""

    variable: str
    horizon: int
    metadata: dict[str, Any]
    metrics: dict[str, Any]
    path: Path

    @property
    def trained_at(self) -> str:
        return str(self.metadata.get("trained_at", ""))

    @property
    def key(self) -> str:
        """Stable identity for idempotent ingestion."""
        return f"{self.variable}/h{self.horizon}@{self.trained_at}"


def discover_models(root: Path = MODELS_ROOT) -> list[ModelRun]:
    """Every trained model artifact under `root`, newest first."""
    found: list[ModelRun] = []
    if not root.exists():
        return found

    for horizon_dir in sorted(root.glob("*/h*")):
        if not horizon_dir.is_dir() or horizon_dir.parent.name.startswith("_"):
            continue
        metadata_path = horizon_dir / "metadata.json"
        metrics_path = horizon_dir / "metrics.json"
        if not (metadata_path.exists() and metrics_path.exists()):
            continue
        try:
            metadata = json.loads(metadata_path.read_text())
            metrics = json.loads(metrics_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"skipping unreadable artifact {horizon_dir}: {exc}")
            continue
        found.append(
            ModelRun(
                variable=str(metadata.get("variable", horizon_dir.parent.name)),
                horizon=int(metadata.get("horizon", horizon_dir.name.lstrip("h"))),
                metadata=metadata,
                metrics=metrics,
                path=horizon_dir,
            )
        )
    return sorted(found, key=lambda r: r.trained_at, reverse=True)


def already_ingested(keys: set[str]) -> set[str]:
    """Which `ModelRun.key` values the tracking store already holds."""
    try:
        import mlflow
    except ImportError:
        return set()
    try:
        mlflow.set_tracking_uri(tracking.tracking_uri())
        experiment = mlflow.get_experiment_by_name(EXPERIMENT)
        if experiment is None:
            return set()
        frame = mlflow.search_runs(
            [experiment.experiment_id], output_format="pandas", max_results=50_000
        )
    except Exception as exc:  # noqa: BLE001 - an unreadable store means "ingest anyway"
        logger.warning(f"could not read existing runs ({exc}); proceeding")
        return set()

    column = "tags.source_key"
    if frame is None or len(frame) == 0 or column not in frame.columns:
        return set()
    return {value for value in frame[column].dropna().tolist() if value in keys}


def _invocation_index(runs_root: Path = RUNS_ROOT) -> dict[str, dict[str, Any]]:
    """Map a model artifact path to the invocation that produced it.

    Model artifacts cannot know which batch they came from; the run directories
    can. Missing directories are fine — every model predating this mechanism
    simply has no invocation recorded.
    """
    index: dict[str, dict[str, Any]] = {}
    if not runs_root.exists():
        return index

    for run_dir in sorted(runs_root.iterdir()):
        report = run_dir / "report.json"
        meta = run_dir / "run.json"
        if not report.exists():
            continue
        try:
            entries = json.loads(report.read_text())
            invocation = json.loads(meta.read_text()) if meta.exists() else {}
        except (OSError, json.JSONDecodeError):
            continue
        for entry in entries:
            path = entry.get("artifact_path")
            if path:
                index[str(Path(path))] = {"invocation": run_dir.name, **invocation}
    return index


def _fold_frame(metrics: dict[str, Any]) -> pd.DataFrame | None:
    folds = metrics.get("validation", {}).get("folds")
    if not folds:
        return None
    return pd.DataFrame(folds)


def _shap_frame(metrics: dict[str, Any]) -> pd.DataFrame | None:
    importance = metrics.get("feature_importance")
    if not importance:
        return None
    return pd.DataFrame(importance)


def ingest_one(run: ModelRun, invocation: dict[str, Any] | None = None) -> str | None:
    """Create one tracked run. Returns the run id, or None if tracking is off."""
    metadata, metrics = run.metadata, run.metrics
    validation = metrics.get("validation", {})
    headline = validation.get("metrics", {})

    skipped = metadata.get("skipped_points") or []
    points_used = metadata.get("training_points") or []

    params: dict[str, Any] = {
        "variable": run.variable,
        "horizon_days": run.horizon,
        "target_mode": metadata.get("target_mode"),
        "model_type": metadata.get("model_type"),
        "feature_count": metadata.get("feature_count"),
        "covariates": ", ".join(metadata.get("covariates") or []) or "none",
        "log_transform": metadata.get("log_transform"),
        "circular": metadata.get("circular"),
        "resolution": metadata.get("resolution"),
        "n_points_used": len(points_used),
        "n_points_skipped": len(skipped),
    }
    model_params = metadata.get("model_params") or {}
    params.update({f"model_{k}": v for k, v in model_params.items()})

    with tracking.track(
        EXPERIMENT,
        run_name=f"{run.variable}_h{run.horizon}",
        params=params,
        tags={
            "problem": "forecasting_engine",
            "producer": "backend",
            "variable": run.variable,
            "horizon": run.horizon,
            "source_key": run.key,
            "trained_at": run.trained_at,
            "artifact_path": str(run.path),
            **({"invocation": invocation["invocation"]} if invocation else {}),
            **(
                {"git_commit": invocation["git_commit"]}
                if invocation and invocation.get("git_commit")
                else {}
            ),
        },
    ) as tracked:
        if tracked.run_id is None:
            return None

        tracked.log_data_window(
            start=metadata.get("training_started"),
            end=metadata.get("training_ended"),
            rows=metadata.get("training_rows"),
            extra={
                "points_used": points_used,
                "points_skipped": skipped,
                "resolution": metadata.get("resolution"),
            },
        )
        tracked.log_dict(metadata, "model_metadata.json")
        tracked.log_dict(metrics, "metrics.json")

        # Headline validation metrics, including the one that matters: a
        # negative skill_score means the model lost to persistence and must not
        # ship, whatever its MAE looks like.
        tracked.log_metrics(headline)
        tracked.log_metrics({"training_duration_seconds": metadata.get("training_duration_seconds")})

        folds = _fold_frame(metrics)
        if folds is not None:
            tracked.log_fold_scores(folds)
            if HEADLINE in folds.columns:
                negative = int((folds[HEADLINE] < 0).sum())
                # The check that four horizons failed on 2026-08-05 while their
                # aggregate still printed "beats persistence".
                tracked.log_metrics(
                    {
                        "folds_negative_skill": negative,
                        "folds_total": len(folds),
                        "passes_bar": float(
                            headline.get(HEADLINE, -1) > 0 and negative <= 1
                        ),
                    }
                )

        tracked.log_shap(_shap_frame(metrics))

        if skipped:
            # Partial spatial coverage is the silent failure mode: rainfall
            # trained on 10 of 24 points, all northern hemisphere, and still
            # scored well. Surfaced as a metric so it is visible in the list.
            tracked.log_dict(skipped, "skipped_points.json")

        return tracked.run_id


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest backend forecasting training runs into MLflow.",
    )
    parser.add_argument(
        "--models-root", default=str(MODELS_ROOT), help="backend/models/forecasting"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="list what would be ingested"
    )
    parser.add_argument(
        "--force", action="store_true", help="re-ingest even if already present"
    )
    parser.add_argument("--variable", action="append", help="limit to variable(s)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    discovered = discover_models(Path(args.models_root))
    if args.variable:
        wanted = set(args.variable)
        discovered = [r for r in discovered if r.variable in wanted]

    if not discovered:
        print(f"no trained model artifacts found under {args.models_root}")
        return 0

    seen = set() if args.force else already_ingested({r.key for r in discovered})
    pending = [r for r in discovered if r.key not in seen]

    print(
        f"{len(discovered)} model artifact(s) found; "
        f"{len(seen)} already tracked; {len(pending)} to ingest"
    )
    if args.dry_run:
        for run in pending:
            skill = run.metrics.get("validation", {}).get("metrics", {}).get(HEADLINE)
            skill_text = f"{skill:+.3f}" if isinstance(skill, (int, float)) else "n/a"
            print(f"  {run.variable:26} h{run.horizon:<3} skill={skill_text}  {run.trained_at[:19]}")
        return 0

    invocations = _invocation_index()
    ingested = 0
    for run in pending:
        run_id = ingest_one(run, invocations.get(str(run.path)))
        if run_id:
            ingested += 1
    print(f"ingested {ingested} run(s) into experiment {EXPERIMENT!r} at {tracking.tracking_uri()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
