"""Train the spatial U-Net pilot and answer the question TODO.md's
"ConvLSTM / U-Net for spatial forecasting" item actually asks: does letting
a t+3 bloom forecast see its neighbourhood beat the existing per-cell
LightGBM model, scored on identical rows?

Run: `PYTHONPATH=. .venv/bin/python -m hab_early_warning.src.spatial_train`

The comparison is the point, so it is run for real rather than cited from
`hab_early_warning/readme.md`'s 0.661/0.511 numbers — those were measured
over `features.drop_unusable_rows_all_horizons`'s multi-horizon-coverage
row set, not necessarily identical to the t+3-only set this pilot uses.
Reloading the shipped LightGBM model and scoring it on this run's own exact
test rows removes that ambiguity.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, TensorDataset

from hab_early_warning.src import spatial_dataset as sd
from hab_early_warning.src import spatial_model as sm
from marine_ml import config, tracking
from marine_ml.validation import metrics

RUN_NAME = "hab_early_warning_spatial"
DEFAULT_EPOCHS = 40
DEFAULT_PATIENCE = 8
DEFAULT_BATCH_SIZE = 16
DEFAULT_LR = 1e-3


def _loader(split: sd.SpatialSplit, batch_size: int, shuffle: bool) -> DataLoader:
    dataset = TensorDataset(
        torch.from_numpy(split.inputs),
        torch.from_numpy(split.target),
        torch.from_numpy(split.valid),
    )
    return DataLoader(dataset, batch_size=batch_size, shuffle=shuffle)


def _run_epoch(model, loader, device, optimizer=None) -> float:
    train_mode = optimizer is not None
    model.train(train_mode)
    total_loss = 0.0
    total_weight = 0.0
    with torch.set_grad_enabled(train_mode):
        for inputs, target, valid in loader:
            inputs = inputs.to(device)
            target = target.to(device)
            valid = valid.to(device)

            logits = model(inputs)
            loss = sm.masked_focal_loss(logits, target, valid)

            if train_mode:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            weight = max(float(valid.sum().item()), 1.0)
            total_loss += loss.item() * weight
            total_weight += weight
    return total_loss / total_weight


@torch.no_grad()
def _predict(model, split: sd.SpatialSplit, device, batch_size: int) -> np.ndarray:
    model.eval()
    loader = DataLoader(TensorDataset(torch.from_numpy(split.inputs)), batch_size=batch_size, shuffle=False)
    chunks = [torch.sigmoid(model(batch.to(device))).cpu().numpy() for (batch,) in loader]
    return sd.crop_to_native(np.concatenate(chunks, axis=0))


def train_model(
    dataset: sd.SpatialDataset,
    epochs: int = DEFAULT_EPOCHS,
    patience: int = DEFAULT_PATIENCE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    lr: float = DEFAULT_LR,
    seed: int = config.RANDOM_SEED,
) -> tuple[sm.SpatialBloomUNet, torch.device, dict]:
    """Early-stop on validation loss; the returned model is the
    best-validation-loss checkpoint, not necessarily the last epoch run."""
    torch.manual_seed(seed)
    device = sm.resolve_device()

    model = sm.SpatialBloomUNet(in_channels=dataset.train.inputs.shape[1]).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    train_loader = _loader(dataset.train, batch_size, shuffle=True)
    validation_loader = _loader(dataset.validation, batch_size, shuffle=False)

    best_state = None
    best_validation_loss = float("inf")
    bad_epochs = 0
    history: list[dict] = []

    started = time.time()
    for epoch in range(1, epochs + 1):
        train_loss = _run_epoch(model, train_loader, device, optimizer)
        validation_loss = _run_epoch(model, validation_loader, device, optimizer=None)
        history.append({"epoch": epoch, "train_loss": train_loss, "validation_loss": validation_loss})
        print(f"  epoch {epoch:3d}  train_loss={train_loss:.4f}  validation_loss={validation_loss:.4f}", flush=True)

        if validation_loss < best_validation_loss - 1e-5:
            best_validation_loss = validation_loss
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                print(f"  early stop at epoch {epoch} (no improvement for {patience} epochs)", flush=True)
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    return model, device, {
        "history": history,
        "elapsed_seconds": time.time() - started,
        "epochs_run": len(history),
        "best_validation_loss": best_validation_loss,
        "device": str(device),
    }


def _run_lightgbm_subprocess(test_dates: np.ndarray) -> pd.DataFrame:
    """Score the reloaded LightGBM model + persistence in a **separate
    process** — never in this one, which already has `torch` loaded.

    Measured directly on this machine: `torch` imported anywhere earlier in
    a process, followed by `joblib.load` of the LightGBM artifact,
    segfaults (SIGSEGV, no traceback) — even with `KMP_DUPLICATE_LIB_OK=
    TRUE` set. The reverse order doesn't crash, but this process necessarily
    loads torch first (it trains the U-Net), so no import ordering within
    *this* process avoids it; only running the LightGBM side out-of-process
    does. See `spatial_lightgbm_subprocess.py`'s own docstring.
    """
    with tempfile.TemporaryDirectory() as tmp:
        dates_path = Path(tmp) / "test_dates.parquet"
        output_path = Path(tmp) / "lightgbm_scores.parquet"
        pd.DataFrame({"date": pd.to_datetime(test_dates)}).to_parquet(dates_path, index=False)

        machine_learning_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "hab_early_warning.src.spatial_lightgbm_subprocess",
                "--test-dates-file",
                str(dates_path),
                "--output",
                str(output_path),
            ],
            cwd=machine_learning_root,
            env={**os.environ, "PYTHONPATH": "."},
            capture_output=True,
            text=True,
        )
        print(result.stdout, end="", flush=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"spatial_lightgbm_subprocess failed (exit {result.returncode}):\n{result.stderr}"
            )
        return pd.read_parquet(output_path)


def evaluate_and_compare(
    model: sm.SpatialBloomUNet,
    device: torch.device,
    dataset: sd.SpatialDataset,
    batch_size: int = 32,
) -> pd.DataFrame:
    """Score the spatial model, the reloaded tabular LightGBM model, and
    persistence — all three on the exact same test rows.

    The LightGBM/persistence half runs in a subprocess (see
    `_run_lightgbm_subprocess`) and returns one row per test cell with its
    `bloom_t3` label and both baseline scores attached — that returned
    frame's own `date`/`latitude`/`longitude` columns are then the row set
    `gather_predictions_at_rows` uses to pull the *matching* spatial-model
    prediction for each one, which is what makes the three-way comparison
    row-identical despite running in two processes.
    """
    predictions = _predict(model, dataset.test, device, batch_size)  # (n_test, 69, 41) probabilities

    print("  scoring reloaded LightGBM + persistence in a subprocess (no torch there)...", flush=True)
    scored = _run_lightgbm_subprocess(dataset.test.dates)
    print(f"  test rows: {len(scored)}", flush=True)
    if scored.empty:
        raise sd.SpatialDatasetError("no test rows with a valid bloom_t3 label")

    y_true = scored[sd.TARGET].astype(int).to_numpy()
    spatial_scores = sd.gather_predictions_at_rows(predictions, dataset.test.dates, scored)

    return pd.DataFrame(
        [
            metrics.evaluate_classification(y_true, spatial_scores, "spatial_unet").as_row(),
            metrics.evaluate_classification(y_true, scored["lightgbm_score"].to_numpy(), "lightgbm_reloaded").as_row(),
            metrics.evaluate_classification(y_true, scored["persistence_score"].to_numpy(), "persistence").as_row(),
        ]
    )


def _track_run(training_summary: dict, report: pd.DataFrame, dataset: sd.SpatialDataset) -> None:
    with tracking.track(
        RUN_NAME,
        run_name=f"{RUN_NAME}_t{sd.HORIZON}",
        params={
            "horizon_days": sd.HORIZON,
            "random_seed": config.RANDOM_SEED,
            "channels": ",".join(dataset.channel_names),
            "epochs_run": training_summary["epochs_run"],
            "device": training_summary["device"],
            "n_train_dates": len(dataset.train),
            "n_validation_dates": len(dataset.validation),
            "n_test_dates": len(dataset.test),
        },
        tags={"problem": "hab_early_warning", "region": config.ARABIAN_SEA.name, "horizon": sd.HORIZON, "tier": "spatial_unet"},
    ) as run:
        run.log_data_window(start=config.HAB_START, end=config.HAB_END, rows=None)
        run.log_table(report, "holdout.csv")
        run.log_table(pd.DataFrame(training_summary["history"]), "training_history.csv")
        run.log_metrics({"training_elapsed_seconds": training_summary["elapsed_seconds"]})

        indexed = report.set_index("split")
        for metric in ("pr_auc", "roc_auc", "brier", "tss"):
            if metric in indexed.columns:
                run.log_metrics({f"holdout_{metric}_{model}": value for model, value in indexed[metric].items()})
        if "pr_auc" in indexed.columns:
            spatial_score = indexed["pr_auc"].get("spatial_unet")
            lightgbm_score = indexed["pr_auc"].get("lightgbm_reloaded")
            if spatial_score is not None and lightgbm_score is not None:
                run.log_metrics({"pr_auc_spatial_minus_lightgbm": spatial_score - lightgbm_score})


CHECKPOINT_PATH = config.MODELS_DIR / "hab_early_warning_spatial.pt"


def save_checkpoint(model: sm.SpatialBloomUNet, dataset: sd.SpatialDataset, path: Path = CHECKPOINT_PATH) -> None:
    """Save the trained weights plus the train-only-fitted normalisation
    stats `spatial_dataset.build_dataset` produced — `export_spatial_
    forecast.py` must score new days with the *same* per-channel mean/std
    fit on this training run's train period, not a freshly refit one, or
    the exported grid and this holdout comparison silently stop being the
    same model."""
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "in_channels": model.enc1[0].in_channels,
            "channel_names": dataset.channel_names,
            "channel_mean": dataset.channel_mean,
            "channel_std": dataset.channel_std,
            "horizon": sd.HORIZON,
        },
        path,
    )
    print(f"  wrote {path}", flush=True)


def main(epochs: int = DEFAULT_EPOCHS) -> pd.DataFrame:
    print(f"building dense-cube dataset (channels={sd.CHANNELS})", flush=True)
    dataset = sd.build_dataset()
    print(
        f"  train={len(dataset.train)} validation={len(dataset.validation)} "
        f"test={len(dataset.test)} dates",
        flush=True,
    )

    print("training", flush=True)
    model, device, training_summary = train_model(dataset, epochs=epochs)
    print(
        f"  done in {training_summary['elapsed_seconds']:.1f}s over "
        f"{training_summary['epochs_run']} epochs on {device}",
        flush=True,
    )

    print("scoring: spatial U-Net vs. reloaded LightGBM vs. persistence, identical rows", flush=True)
    report = evaluate_and_compare(model, device, dataset)
    print(report.to_string(index=False), flush=True)

    save_checkpoint(model, dataset)
    _track_run(training_summary, report, dataset)
    return report


if __name__ == "__main__":
    main()
