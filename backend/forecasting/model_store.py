"""On-disk model registry.

Layout, one directory per (variable, horizon):

    models/forecasting/
        sea_surface_temperature/
            h1/
                model.pkl
                metadata.json
                metrics.json
                feature_columns.json
            h7/
                ...
        chlorophyll_a/
            ...

The horizon subdirectory is the one departure from the spec's sketch, which
showed `models/sst/model.pkl` flat. It is forced: this engine trains a
*separate* model per horizon (direct multi-horizon forecasting, not recursive),
so a 1-day and a 30-day SST model coexist and need somewhere to live that
isn't the same filename.

`feature_columns.json` is separate from `metadata.json` on purpose, even
though it is metadata in the ordinary sense. It is the file the predictor
reads on the hot path to rebuild the feature matrix in the exact column order
the booster was fitted on, and column order silently mattering is one of the
classic ways a served model quietly diverges from the validated one.
"""

from __future__ import annotations

import json
import logging
import pickle
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forecasting import ForecastingError

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parents[1] / "models" / "forecasting"

MODEL_FILE = "model.pkl"
METADATA_FILE = "metadata.json"
METRICS_FILE = "metrics.json"
FEATURES_FILE = "feature_columns.json"

# Bumped when the on-disk contract changes in a way that makes an older
# artifact unsafe to serve. The predictor refuses a mismatch rather than
# guessing, because a silently misread model produces plausible wrong numbers.
ARTIFACT_VERSION = 1


class ModelStoreError(ForecastingError):
    """A model artifact is missing, unreadable, or the wrong version."""


class ModelNotTrainedError(ModelStoreError):
    """No artifact exists for this variable/horizon yet.

    Distinct from a corrupt artifact because the API maps them differently:
    this is a 404 with a "train it with ..." message, corruption is a 500.
    """


@dataclass(frozen=True)
class ModelArtifact:
    """A loaded model and everything needed to use and describe it."""

    model: Any
    feature_columns: list[str]
    categorical_columns: list[str]
    metadata: dict[str, Any]
    metrics: dict[str, Any]

    @property
    def variable(self) -> str:
        return str(self.metadata.get("variable", ""))

    @property
    def horizon(self) -> int:
        return int(self.metadata.get("horizon", 0))

    @property
    def version(self) -> str:
        return str(self.metadata.get("version", "unknown"))


def model_dir(variable: str, horizon: int, root: Path | None = None) -> Path:
    return (root or MODELS_DIR) / variable / f"h{horizon}"


def exists(variable: str, horizon: int, root: Path | None = None) -> bool:
    return (model_dir(variable, horizon, root) / MODEL_FILE).exists()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str))


def save(
    *,
    variable: str,
    horizon: int,
    model: Any,
    feature_columns: list[str],
    categorical_columns: list[str],
    metadata: dict[str, Any],
    metrics: dict[str, Any],
    root: Path | None = None,
) -> Path:
    """Write a complete artifact set atomically.

    Staged in a temporary directory and moved into place, so a run interrupted
    partway never leaves a directory holding a new `model.pkl` beside the
    previous run's `metrics.json` — a pairing that looks valid, loads fine, and
    reports the wrong accuracy for the wrong model.
    """
    destination = model_dir(variable, horizon, root)
    destination.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        **metadata,
        "variable": variable,
        "horizon": horizon,
        "artifact_version": ARTIFACT_VERSION,
        "saved_at": datetime.now(UTC).isoformat(),
    }

    staging = Path(tempfile.mkdtemp(prefix=f".{variable}_h{horizon}_", dir=destination.parent))
    try:
        (staging / MODEL_FILE).write_bytes(pickle.dumps(model))
        _write_json(staging / METADATA_FILE, payload)
        _write_json(staging / METRICS_FILE, metrics)
        _write_json(
            staging / FEATURES_FILE,
            {
                "feature_columns": feature_columns,
                "categorical_columns": categorical_columns,
                "n_features": len(feature_columns),
            },
        )

        if destination.exists():
            shutil.rmtree(destination)
        staging.replace(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    logger.info(f"saved {variable} h{horizon} model to {destination}")
    return destination


def load(variable: str, horizon: int, root: Path | None = None) -> ModelArtifact:
    """Read an artifact set. Raises ModelNotTrainedError if it was never built."""
    directory = model_dir(variable, horizon, root)
    model_path = directory / MODEL_FILE

    if not model_path.exists():
        raise ModelNotTrainedError(
            f"no trained model for {variable!r} at horizon {horizon}. "
            f"Train it with: python scripts/train_forecasting.py "
            f"--variable {variable} --horizons {horizon}"
        )

    try:
        model = pickle.loads(model_path.read_bytes())
        metadata = json.loads((directory / METADATA_FILE).read_text())
        metrics = json.loads((directory / METRICS_FILE).read_text())
        features = json.loads((directory / FEATURES_FILE).read_text())
    except Exception as exc:  # noqa: BLE001 - pickle/json raise many types
        raise ModelStoreError(
            f"model artifact for {variable!r} h{horizon} at {directory} is unreadable: {exc}"
        ) from exc

    stored_version = metadata.get("artifact_version")
    if stored_version != ARTIFACT_VERSION:
        raise ModelStoreError(
            f"model artifact for {variable!r} h{horizon} was written by format "
            f"version {stored_version}, this build expects {ARTIFACT_VERSION}. "
            f"Retrain it."
        )

    return ModelArtifact(
        model=model,
        feature_columns=list(features["feature_columns"]),
        categorical_columns=list(features.get("categorical_columns", [])),
        metadata=metadata,
        metrics=metrics,
    )


def list_trained(root: Path | None = None) -> dict[str, list[int]]:
    """Every variable with at least one trained horizon, and which.

    Drives the API's catalog endpoint, so the dashboard can grey out what is
    not trained rather than offering it and failing.
    """
    base = root or MODELS_DIR
    if not base.exists():
        return {}

    trained: dict[str, list[int]] = {}
    for variable_dir in sorted(base.iterdir()):
        # `_reports` (training reports and diagnostic PNGs) lives alongside the
        # variable directories. It survives the horizon check below anyway
        # since it holds no `h*` subdirectory, but skipping it by name keeps
        # that from being a coincidence that a future filename could break.
        if not variable_dir.is_dir() or variable_dir.name.startswith((".", "_")):
            continue
        horizons = []
        for horizon_dir in variable_dir.iterdir():
            if not horizon_dir.is_dir() or not horizon_dir.name.startswith("h"):
                continue
            if not (horizon_dir / MODEL_FILE).exists():
                continue
            try:
                horizons.append(int(horizon_dir.name[1:]))
            except ValueError:
                continue
        if horizons:
            trained[variable_dir.name] = sorted(horizons)
    return trained


def summary(root: Path | None = None) -> list[dict[str, Any]]:
    """Registry contents with each model's headline metrics, for /models."""
    entries = []
    for variable, horizons in list_trained(root).items():
        for horizon in horizons:
            try:
                artifact = load(variable, horizon, root)
            except ModelStoreError as exc:
                entries.append(
                    {"variable": variable, "horizon": horizon, "error": str(exc)}
                )
                continue
            metrics = artifact.metrics.get("validation", {}).get("metrics", {})
            entries.append(
                {
                    "variable": variable,
                    "horizon": horizon,
                    "version": artifact.version,
                    "trained_at": artifact.metadata.get("trained_at"),
                    "training_rows": artifact.metadata.get("training_rows"),
                    "n_features": len(artifact.feature_columns),
                    "mae": metrics.get("mae"),
                    "rmse": metrics.get("rmse"),
                    "r2": metrics.get("r2"),
                    "skill_score": metrics.get("skill_score"),
                }
            )
    return entries


def delete(variable: str, horizon: int, root: Path | None = None) -> bool:
    directory = model_dir(variable, horizon, root)
    if not directory.exists():
        return False
    shutil.rmtree(directory)
    return True
