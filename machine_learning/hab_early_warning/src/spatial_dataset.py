"""Dense-cube dataset for the HAB Tier 3 pilot: does spatial context help
the t+3 bloom forecast at all (TODO.md "ConvLSTM / U-Net for spatial
forecasting"; approach doc S3.6 Tier 3)?

Reuses the existing tabular pipeline's own fit/apply artefacts rather than
recomputing anything: `hab_gridded.parquet` already carries `bloom_t3`
(`labels.add_forecast_labels`'s one sanctioned forward shift, already
train-only-fitted) and every raw/derived channel below, contemporaneous, no
lag. The only new step is pivoting those columns to a dense grid
(`fusion.build_dense_cube`) instead of feeding them to LightGBM as rows.

Split fractions (`config.TRAIN_FRACTION`/`VALIDATION_FRACTION`) are the same
constants `train.py::fit_final` uses on the tabular path, so the test-period
date cutoffs match the existing model's exactly — required for the holdout
comparison in `spatial_train.py` to mean anything.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from marine_ml import config, fusion
from marine_ml.validation import splits

# Contemporaneous (no lag) channels chosen to match TODO.md's own argument
# for why a per-cell model is blind ("not an eddy, not a front, not the
# shape of a bloom") and the approach doc's S3.4 feature list: the field
# itself, a stratification proxy, frontal-strength gradients, an eddy
# structure term, and the wind-driven nutrient-supply driver.
CHANNELS: tuple[str, ...] = (
    "chl",
    "thetao",
    "mlotst",
    "chl_gradient",
    "sst_gradient",
    "okubo_weiss",
    "upwelling_index",
)
TARGET = "bloom_t3"
HORIZON = 3
STORE_NAME = "hab_gridded"

# The real (unpadded) Arabian Sea grid, measured against the feature store:
# 69 latitudes x 41 longitudes at 0.25 deg.
NATIVE_LAT = 69
NATIVE_LON = 41
# Padded up to the next multiple of 8 each side, for 3 clean stride-2 U-Net
# pooling levels (72/8=9, 48/8=6 at the bottleneck). Padding is zero-filled
# and its `valid` mask is always False, so it never contributes to the loss
# or to any reported metric.
PAD_LAT = 72
PAD_LON = 48


class SpatialDatasetError(RuntimeError):
    """Raised when the dense-cube dataset cannot be built."""


@dataclass
class SpatialSplit:
    """One split's tensors, already padded and ready for a `DataLoader`."""

    dates: np.ndarray  # datetime64[ns], (n,) — this split's dates, in order
    inputs: np.ndarray  # float32 (n, 2*len(CHANNELS), PAD_LAT, PAD_LON) — normalised channels + observed-masks
    target: np.ndarray  # float32 (n, PAD_LAT, PAD_LON) — bloom_t3, 0 where invalid (never used unmasked)
    valid: np.ndarray  # bool (n, PAD_LAT, PAD_LON) — True only at real, labelled ocean cells

    def __len__(self) -> int:
        return int(self.inputs.shape[0])


@dataclass
class SpatialDataset:
    train: SpatialSplit
    validation: SpatialSplit
    test: SpatialSplit
    channel_names: list[str]
    channel_mean: dict[str, float]
    channel_std: dict[str, float]


def pad_from_native(array: np.ndarray, target_lat: int = PAD_LAT, target_lon: int = PAD_LON) -> np.ndarray:
    """Zero-pad the trailing two (lat, lon) dims up to the target shape."""
    *lead, lat, lon = array.shape
    if lat > target_lat or lon > target_lon:
        raise SpatialDatasetError(f"grid {lat}x{lon} exceeds pad target {target_lat}x{target_lon}")
    pad_width = [(0, 0)] * len(lead) + [(0, target_lat - lat), (0, target_lon - lon)]
    return np.pad(array, pad_width, mode="constant", constant_values=0.0)


def crop_to_native(array: np.ndarray) -> np.ndarray:
    """Undo `pad_from_native`: slice the trailing two dims back to the real grid."""
    return array[..., :NATIVE_LAT, :NATIVE_LON]


def _fit_normalisation(train_cube_channel: np.ndarray) -> tuple[float, float]:
    """Mean/std over finite (non-NaN) train-period cells only.

    Fit-on-train-only, the same rule `labels.fit_bloom_thresholds` and
    `temporal.fit_climatology` follow elsewhere in this codebase — a
    normalisation fitted over the full record would leak the test period's
    own distribution into every training input.
    """
    finite = train_cube_channel[np.isfinite(train_cube_channel)]
    if finite.size == 0:
        return 0.0, 1.0
    mean = float(finite.mean())
    std = float(finite.std())
    return mean, std if std > 1e-6 else 1.0


def _make_split(
    cube_subset,
    channels: tuple[str, ...],
    mean: dict[str, float],
    std: dict[str, float],
) -> SpatialSplit:
    n = cube_subset.sizes["date"]
    data_layers = []
    mask_layers = []
    for channel in channels:
        values = cube_subset[channel].to_numpy().astype("float32")  # (n, lat, lon)
        observed = np.isfinite(values)
        normalised = (values - mean[channel]) / std[channel]
        normalised = np.where(observed, normalised, 0.0).astype("float32")
        data_layers.append(normalised)
        mask_layers.append(observed.astype("float32"))

    # Data channels first, then one observed-mask per data channel (not one
    # shared mask): land is a shared gap across every channel, but
    # `upwelling_index` additionally carries its own ~39%-coverage fixed
    # spatial mask that the others don't (docs/ml-notes.md) — the
    # missingness patterns are not identical, so a single shared mask would
    # hide `upwelling_index`'s narrower coverage from the network.
    inputs = np.stack(data_layers + mask_layers, axis=1)
    inputs = pad_from_native(inputs)

    target = cube_subset[TARGET].to_numpy().astype("float32")
    valid = np.isfinite(target)
    target_filled = np.where(valid, target, 0.0).astype("float32")

    return SpatialSplit(
        dates=pd.to_datetime(cube_subset["date"].to_numpy()).to_numpy(),
        inputs=inputs,
        target=pad_from_native(target_filled),
        valid=pad_from_native(valid.astype("float32")) > 0.5,
    )


def build_dataset(
    region: config.Region = config.ARABIAN_SEA,
    resolution: float = config.GRID_RESOLUTION,
    channels: tuple[str, ...] = CHANNELS,
) -> SpatialDataset:
    """Load, pivot and split the dense HAB cube. The one entry point
    `spatial_train.py` and its tests call."""
    columns = ["latitude", "longitude", "date", *channels, TARGET]
    frame = fusion.read_feature_store(STORE_NAME, columns=columns)

    cube = fusion.build_dense_cube(frame, list(channels) + [TARGET], region=region, resolution=resolution)
    del frame

    dates = pd.to_datetime(cube["date"].to_numpy())
    train_mask, validation_mask, test_mask = splits.chronological_split(
        pd.Series(dates), config.TRAIN_FRACTION, config.VALIDATION_FRACTION
    )
    if not (train_mask.any() and validation_mask.any() and test_mask.any()):
        raise SpatialDatasetError("one of train/validation/test has zero dates")

    train_cube = cube.isel(date=train_mask)

    mean: dict[str, float] = {}
    std: dict[str, float] = {}
    for channel in channels:
        mean[channel], std[channel] = _fit_normalisation(train_cube[channel].to_numpy())

    return SpatialDataset(
        train=_make_split(train_cube, channels, mean, std),
        validation=_make_split(cube.isel(date=validation_mask), channels, mean, std),
        test=_make_split(cube.isel(date=test_mask), channels, mean, std),
        channel_names=list(channels),
        channel_mean=mean,
        channel_std=std,
    )


def gather_predictions_at_rows(
    predictions: np.ndarray,
    dates: np.ndarray,
    frame: pd.DataFrame,
    region: config.Region = config.ARABIAN_SEA,
    resolution: float = config.GRID_RESOLUTION,
) -> np.ndarray:
    """The inverse of the cube pivot: read a dense `(date, lat, lon)` array
    back at exactly `frame`'s own rows, in `frame`'s row order.

    Used to score the spatial model on precisely the same test rows the
    tabular model is scored on — every pixel in the padded rectangle would
    include land and off-record cells the tabular model never had to
    predict, which is a strictly easier and not-comparable number. Kept
    local to this module rather than in `fusion.py`: it is specific to
    "evaluate a spatial prediction against a tidy row set," not a second
    generic access shape onto the fusion layer.
    """
    if predictions.shape[-2:] != (NATIVE_LAT, NATIVE_LON):
        predictions = crop_to_native(predictions)

    latitudes, longitudes = fusion.common_grid(region, resolution)
    date_index = pd.Index(pd.to_datetime(dates))

    lat_idx = np.rint((frame["latitude"].to_numpy(dtype="float64") - latitudes[0]) / resolution).astype("int64")
    lon_idx = np.rint((frame["longitude"].to_numpy(dtype="float64") - longitudes[0]) / resolution).astype("int64")
    date_idx = date_index.get_indexer(pd.to_datetime(frame["date"]).dt.normalize())

    missing = date_idx < 0
    if missing.any():
        raise SpatialDatasetError(
            f"{int(missing.sum())} row(s) fall on a date outside the "
            "predictions array — frame and dates must cover the same period"
        )

    return predictions[date_idx, lat_idx, lon_idx]
