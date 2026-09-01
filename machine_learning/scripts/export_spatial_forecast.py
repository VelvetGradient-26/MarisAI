"""Export the spatial U-Net's t+3 bloom-probability forecast as a
standalone NetCDF, mirroring `export_predictions.py::export_hab()`'s shape.

**Deliberately not wired into `manifest.json` or anything under `backend/`
or `frontend/`.** Phase 1 stops at this artifact until the held-out
comparison in `hab_early_warning/src/spatial_train.py` says a spatial model
is worth serving — see the "U-Net spatial bloom forecast" plan's Deferred
section for the exact seam (companion-grid pattern in
`backend/services/predictions.py`) to use when that's revisited.

Run: `PYTHONPATH=. .venv/bin/python -m scripts.export_spatial_forecast`
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import torch
import xarray as xr

from hab_early_warning.src import spatial_dataset as sd
from hab_early_warning.src import spatial_model as sm
from hab_early_warning.src.spatial_train import CHECKPOINT_PATH
from marine_ml import config, fusion

EXPORT_DIR = config.PROJECT_ROOT / "exports"
# Matches `export_predictions.py`'s HAB_OUTPUT_DAYS — same recency window
# as the shipped `hab_risk.nc`, for a like-for-like map comparison later.
OUTPUT_DAYS = 30


def load_checkpoint(path: Path = CHECKPOINT_PATH) -> tuple[sm.SpatialBloomUNet, dict]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    model = sm.SpatialBloomUNet(in_channels=payload["in_channels"])
    model.load_state_dict(payload["state_dict"])
    model.eval()
    return model, payload


def export(output_days: int = OUTPUT_DAYS) -> Path:
    model, payload = load_checkpoint()
    channels: tuple[str, ...] = tuple(payload["channel_names"])
    mean: dict[str, float] = payload["channel_mean"]
    std: dict[str, float] = payload["channel_std"]

    columns = ["latitude", "longitude", "date", *channels]
    frame = fusion.read_feature_store(sd.STORE_NAME, columns=columns)
    normalised_dates = pd.to_datetime(frame["date"]).dt.normalize()
    recent_dates = sorted(normalised_dates.unique())[-output_days:]
    recent = frame[normalised_dates.isin(recent_dates)]
    print(
        f"hab spatial: scoring {len(recent_dates)} days over "
        f"{str(recent_dates[0])[:10]} -> {str(recent_dates[-1])[:10]}",
        flush=True,
    )

    cube = fusion.build_dense_cube(recent, list(channels), region=config.ARABIAN_SEA, resolution=config.GRID_RESOLUTION)

    # `chl` is one of `build_gridded_frame`'s own "core" ocean-defining
    # columns (the same test that decides `drop_land`), so its NaN pattern
    # is land/off-record, not just "this one channel is unobserved" —
    # unlike `upwelling_index`, whose own ~39%-coverage gap is real ocean
    # that a land mask must not also blank out.
    ocean = np.isfinite(cube["chl"].to_numpy())

    # Same normalisation `build_dataset` fit on this checkpoint's own
    # training run — never refit here, or the exported grid would silently
    # stop being the model that was actually evaluated.
    data_layers = []
    mask_layers = []
    for channel in channels:
        values = cube[channel].to_numpy().astype("float32")
        observed = np.isfinite(values)
        normalised = np.where(observed, (values - mean[channel]) / std[channel], 0.0).astype("float32")
        data_layers.append(normalised)
        mask_layers.append(observed.astype("float32"))
    inputs = sd.pad_from_native(np.stack(data_layers + mask_layers, axis=1))

    device = sm.resolve_device()
    model = model.to(device)
    with torch.no_grad():
        logits = model(torch.from_numpy(inputs).to(device))
        probabilities = torch.sigmoid(logits).cpu().numpy()
    probabilities = sd.crop_to_native(probabilities)  # (n_days, 69, 41)

    # Honest missing data, matching `hab_risk.nc`'s own convention: land and
    # off-record cells are NaN, not a number the model happened to output
    # for an input it was never trained to see (this codebase never
    # substitutes a number for missing data — see TODO.md's "visual
    # standard" entry, the same rule applied here to the export itself
    # rather than to a UI panel).
    probabilities = np.where(ocean, probabilities, np.nan).astype("float32")

    latitudes, longitudes = fusion.common_grid(config.ARABIAN_SEA, config.GRID_RESOLUTION)
    grid = probabilities[np.newaxis, ...]  # (horizon=[3], date, lat, lon)

    dataset = xr.Dataset(
        {"bloom_probability": (("horizon", "date", "latitude", "longitude"), grid)},
        coords={
            "horizon": [payload["horizon"]],
            "date": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in cube["date"].to_numpy()],
            "latitude": latitudes,
            "longitude": longitudes,
        },
        attrs={
            "title": "HAB bloom probability -- spatial U-Net pilot (Phase 1)",
            "model": "U-Net (single-frame, no temporal recurrence)",
            "region": config.ARABIAN_SEA.name,
            "channels": ",".join(channels),
            "note": (
                "Standalone Phase 1 artifact, not wired into manifest.json "
                "or any backend/frontend path. Held out against the shipped "
                "per-cell LightGBM model (hab_risk.nc) on identical test "
                "rows: LightGBM PR-AUC 0.668 vs. this model's 0.544 vs. "
                "persistence's 0.518 -- see hab_early_warning/src/"
                "spatial_train.py and the U-Net spatial bloom forecast plan "
                "before treating this as more than an experiment."
            ),
        },
    )
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / "hab_bloom_forecast_spatial.nc"
    dataset.to_netcdf(path)
    print(f"  wrote {path} ({path.stat().st_size / 1e6:.1f} MB)", flush=True)
    return path


if __name__ == "__main__":
    export()
