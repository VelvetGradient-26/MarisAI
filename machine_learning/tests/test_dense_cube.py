"""`fusion.build_dense_cube`: the tidy frame pivoted back to a dense grid.

Two things matter and neither is exercised by the existing tabular tests:
the pivot must be lossless and place every value at the *correct* cell
(not just some cell — a transposed lat/lon would pass a shape check and
silently mirror the whole domain), and a frame with land already dropped
must come back as a complete rectangle with land as NaN, not as a smaller
grid. `test_leakage.py` guards the tabular path's temporal discipline;
the chronological test here closes the one gap `docs/ml-notes.md` and
TODO.md's spatial-forecast plan both call out: nothing previously checked
that a *tensor* pivot keeps dates in an order `chronological_split` can
safely cut.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from marine_ml import config, fusion
from marine_ml.validation import splits

REGION = config.Region("probe", west=10.0, east=10.5, south=0.0, north=0.5)
RESOLUTION = 0.25  # -> 3x3 grid: lat/lon each {0.0, 0.25, 0.5} / {10.0, 10.25, 10.5}


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_round_trip_places_values_at_the_correct_cell_not_just_some_cell():
    frame = _frame(
        [
            {"date": "2020-01-01", "latitude": 0.0, "longitude": 10.0, "chl": 1.0},
            {"date": "2020-01-01", "latitude": 0.25, "longitude": 10.5, "chl": 2.0},
            {"date": "2020-01-02", "latitude": 0.5, "longitude": 10.0, "chl": 3.0},
        ]
    )
    cube = fusion.build_dense_cube(frame, ["chl"], region=REGION, resolution=RESOLUTION)

    assert cube["chl"].sel(date="2020-01-01", latitude=0.0, longitude=10.0).item() == 1.0
    assert cube["chl"].sel(date="2020-01-01", latitude=0.25, longitude=10.5).item() == 2.0
    assert cube["chl"].sel(date="2020-01-02", latitude=0.5, longitude=10.0).item() == 3.0
    # A cell that was never a row in the tidy frame (dropped land, or just
    # absent that day) must be NaN, not zero and not absent from the cube.
    assert np.isnan(cube["chl"].sel(date="2020-01-01", latitude=0.5, longitude=10.5).item())


def test_dropped_land_comes_back_as_a_complete_rectangle():
    # Only one of the 9 cells present, as `build_gridded_frame(drop_land=True)`
    # would leave for a mostly-land tile.
    frame = _frame([{"date": "2020-01-01", "latitude": 0.25, "longitude": 10.25, "chl": 5.0}])
    cube = fusion.build_dense_cube(frame, ["chl"], region=REGION, resolution=RESOLUTION)

    assert cube.sizes == {"date": 1, "latitude": 3, "longitude": 3}
    assert int(np.isfinite(cube["chl"].values).sum()) == 1


def test_missing_channel_names_the_column():
    frame = _frame([{"date": "2020-01-01", "latitude": 0.0, "longitude": 10.0, "chl": 1.0}])
    with pytest.raises(fusion.FusionError, match="sst"):
        fusion.build_dense_cube(frame, ["chl", "sst"], region=REGION, resolution=RESOLUTION)


def test_row_outside_the_grid_raises_rather_than_silently_clipping():
    frame = _frame(
        [
            {"date": "2020-01-01", "latitude": 0.0, "longitude": 10.0, "chl": 1.0},
            # 5 degrees north of the probe region's own north edge (0.5).
            {"date": "2020-01-01", "latitude": 5.0, "longitude": 10.0, "chl": 9.0},
        ]
    )
    with pytest.raises(fusion.FusionError, match="probe"):
        fusion.build_dense_cube(frame, ["chl"], region=REGION, resolution=RESOLUTION)


def test_float32_feature_store_round_trip_is_not_an_off_by_one_cell():
    """Regression guard for the reason this indexes by rounding rather than
    exact float equality: a feature store column read back as float32 must
    still land in the same cell a float64 `common_grid` value would."""
    frame = _frame(
        [{"date": "2020-01-01", "latitude": 0.25, "longitude": 10.25, "chl": 7.0}]
    )
    frame["latitude"] = frame["latitude"].astype("float32")
    frame["longitude"] = frame["longitude"].astype("float32")

    cube = fusion.build_dense_cube(frame, ["chl"], region=REGION, resolution=RESOLUTION)
    assert cube["chl"].sel(date="2020-01-01", latitude=0.25, longitude=10.25).item() == 7.0


def test_date_axis_stays_chronologically_splittable():
    """The gap `test_leakage.py` doesn't cover: a *tensor* pivot must keep
    dates in an order `splits.chronological_split` can cut cleanly, so
    `cube.isel(date=train_mask)` and `cube.isel(date=test_mask)` are true
    non-overlapping time blocks rather than an arbitrary partition."""
    dates = pd.date_range("2020-01-01", periods=20, freq="D")
    rng = np.random.default_rng(0)
    frame = _frame(
        [
            {
                "date": d.strftime("%Y-%m-%d"),
                "latitude": 0.0,
                "longitude": 10.0,
                "chl": float(rng.normal()),
            }
            for d in dates
        ]
    )
    cube = fusion.build_dense_cube(frame, ["chl"], region=REGION, resolution=RESOLUTION)

    # `cube.date` must already be sorted for positional train/test masks to
    # mean "everything before/after a point in time" rather than a shuffle.
    cube_dates = pd.to_datetime(cube["date"].values)
    assert list(cube_dates) == sorted(cube_dates)

    train_mask, validation_mask, test_mask = splits.chronological_split(
        pd.Series(cube_dates), train_fraction=0.5, validation_fraction=0.25
    )
    train_dates = cube_dates[train_mask]
    test_dates = cube_dates[test_mask]

    assert len(train_dates) and len(test_dates)
    assert train_dates.max() < test_dates.min()

    train_cube = cube.isel(date=train_mask)
    test_cube = cube.isel(date=test_mask)
    assert set(pd.to_datetime(train_cube["date"].values)) & set(
        pd.to_datetime(test_cube["date"].values)
    ) == set()
