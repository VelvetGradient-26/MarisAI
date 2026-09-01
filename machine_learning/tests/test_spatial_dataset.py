"""`spatial_dataset.py`: the dense-cube split/normalise/pad pipeline the
U-Net pilot trains on, and its inverse (`gather_predictions_at_rows`).

Three risks specific to this module, none covered by `test_dense_cube.py`
(which only tests the pivot) or `test_leakage.py` (which only tests the
tabular path): normalisation fit on the wrong period would leak the test
distribution into every training input; padding could silently leak into
the loss if its `valid` mask were ever True; and the predict-time gather
could misalign date/lat/lon and silently score the wrong cells.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hab_early_warning.src import spatial_dataset as sd
from marine_ml import config, fusion

REGION = config.Region("probe_hab", west=10.0, east=10.5, south=0.0, north=0.5)
RESOLUTION = 0.25  # -> 3x3 grid
CHANNELS = ("chl", "thetao")


def _synthetic_frame(n_dates: int = 20, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n_dates, freq="D")
    lats = [0.0, 0.25, 0.5]
    lons = [10.0, 10.25, 10.5]

    rows = []
    for date_index, date in enumerate(dates):
        for lat in lats:
            for lon in lons:
                # bloom_t3 NaN for the last 3 days, like a real forward-shift
                # target running off the end of the record.
                bloom = np.nan if date_index >= n_dates - 3 else float(rng.integers(0, 2))
                rows.append(
                    {
                        "date": date,
                        "latitude": lat,
                        "longitude": lon,
                        "chl": float(rng.normal(1.0, 0.2)),
                        "thetao": float(rng.normal(28.0, 1.0)),
                        "bloom_t3": bloom,
                    }
                )
    return pd.DataFrame(rows)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FEATURE_STORE_DIR", tmp_path)
    frame = _synthetic_frame()
    fusion.write_feature_store(frame, sd.STORE_NAME)
    return frame


def test_pad_and_crop_round_trip():
    array = np.arange(2 * 3 * 5).reshape(2, 3, 5).astype("float32")
    padded = sd.pad_from_native(array, target_lat=8, target_lon=8)
    assert padded.shape == (2, 8, 8)
    np.testing.assert_array_equal(padded[:, :3, :5], array)
    assert (padded[:, 3:, :] == 0).all()
    assert (padded[:, :, 5:] == 0).all()


def test_normalisation_is_fit_on_train_dates_only():
    """A mean/std fitted over the full record would encode the test
    period's own distribution into every training input — the same leakage
    `fit_bloom_thresholds` and `fit_climatology` are built to avoid."""
    train_only = np.array([[[1.0, 1.0], [1.0, 1.0]]] * 10, dtype="float32")  # constant, mean=1
    full_record = np.concatenate(
        [train_only, np.array([[[100.0, 100.0], [100.0, 100.0]]] * 10, dtype="float32")]
    )
    mean_from_train, _ = sd._fit_normalisation(train_only)
    mean_from_full, _ = sd._fit_normalisation(full_record)
    assert mean_from_train == pytest.approx(1.0)
    assert mean_from_full != pytest.approx(1.0)  # sanity: the two really differ


def test_build_dataset_shapes_and_chronological_order(store):
    dataset = sd.build_dataset(region=REGION, resolution=RESOLUTION, channels=CHANNELS)

    n_total = len(dataset.train) + len(dataset.validation) + len(dataset.test)
    assert n_total == 20
    # 0.70/0.15 of 20 dates.
    assert len(dataset.train) == 14
    assert len(dataset.validation) == 3
    assert len(dataset.test) == 3

    for split in (dataset.train, dataset.validation, dataset.test):
        assert split.inputs.shape == (len(split), 2 * len(CHANNELS), sd.PAD_LAT, sd.PAD_LON)
        assert split.target.shape == (len(split), sd.PAD_LAT, sd.PAD_LON)
        assert split.valid.shape == (len(split), sd.PAD_LAT, sd.PAD_LON)
        # Padding must never be marked valid — it would otherwise pull
        # fabricated all-zero cells into the loss.
        assert not split.valid[:, sd.NATIVE_LAT :, :].any()
        assert not split.valid[:, :, sd.NATIVE_LON :].any()

    # Every split's dates strictly precede the next split's — the whole
    # point of `chronological_split` over a random shuffle.
    assert dataset.train.dates.max() < dataset.validation.dates.min()
    assert dataset.validation.dates.max() < dataset.test.dates.min()


def test_target_nan_is_masked_out_not_zero_filled_into_the_loss(store):
    dataset = sd.build_dataset(region=REGION, resolution=RESOLUTION, channels=CHANNELS)
    # The synthetic frame's last 3 dates have bloom_t3 = NaN everywhere, and
    # fall in the test split (last 3 of 20 chronologically).
    assert not dataset.test.valid.any()


def test_gather_predictions_at_rows_is_the_inverse_of_build_dense_cube():
    frame = pd.DataFrame(
        [
            {"date": "2020-01-01", "latitude": 0.0, "longitude": 10.0, "chl": 1.0},
            {"date": "2020-01-01", "latitude": 0.5, "longitude": 10.5, "chl": 2.0},
            {"date": "2020-01-02", "latitude": 0.25, "longitude": 10.25, "chl": 3.0},
        ]
    )
    cube = fusion.build_dense_cube(frame, ["chl"], region=REGION, resolution=RESOLUTION)
    dates = pd.to_datetime(cube["date"].to_numpy())

    gathered = sd.gather_predictions_at_rows(cube["chl"].to_numpy(), dates, frame, region=REGION, resolution=RESOLUTION)
    np.testing.assert_allclose(gathered, frame["chl"].to_numpy())


def test_gather_predictions_rejects_a_date_outside_the_array():
    frame = pd.DataFrame([{"date": "2099-01-01", "latitude": 0.0, "longitude": 10.0, "chl": 1.0}])
    predictions = np.zeros((1, sd.NATIVE_LAT, sd.NATIVE_LON), dtype="float32")
    dates = pd.to_datetime(["2020-01-01"])
    with pytest.raises(sd.SpatialDatasetError):
        sd.gather_predictions_at_rows(predictions, dates, frame, region=REGION, resolution=RESOLUTION)
