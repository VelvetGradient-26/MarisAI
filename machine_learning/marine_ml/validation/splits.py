"""Leakage-free cross-validation splitters.

Both problems are heavily autocorrelated in space *and* time, so a random
shuffle is not a mild inaccuracy here — it is a way of scoring a model on
information it already saw. Adjacent days are nearly identical fields;
adjacent pixels are nearly identical fields. A random 80/20 split puts a
cell's Tuesday in training and its Wednesday in test and reports a skill
number that will not survive contact with an actual forecast.

Three splitters, matching the doc:

``rolling_origin_splits``
    Expanding-window time-series CV with a gap. For the HAB forecast.
``spatial_block_splits``
    Contiguous lat/lon blocks held out whole. For the habitat SDM.
``leave_one_region_out``
    Named coastal segments held out whole, to test transfer to unseen coast.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Split:
    """One fold: positional indices into the frame that produced it."""

    name: str
    train: np.ndarray
    test: np.ndarray

    def __repr__(self) -> str:  # keeps fold logs readable
        return f"Split({self.name!r}, train={len(self.train)}, test={len(self.test)})"


def rolling_origin_splits(
    dates: pd.Series,
    n_splits: int = 5,
    horizon_days: int = 7,
    gap_days: int | None = None,
    min_train_fraction: float = 0.3,
) -> Iterator[Split]:
    """Expanding-window splits over time, with an embargo gap.

    Fold k trains on everything up to a cutoff and tests on the window after
    it, with ``gap_days`` of data dropped in between. That gap is not
    decoration: to predict a bloom at t+7 the label at time t depends on
    observations up to t+7, so training rows within 7 days of the test period
    share information with it. Defaults to ``horizon_days``.
    """
    dates = pd.to_datetime(pd.Series(dates).reset_index(drop=True))
    gap = pd.Timedelta(days=horizon_days if gap_days is None else gap_days)

    start, end = dates.min(), dates.max()
    span = end - start
    if span <= gap:
        raise ValueError("date range is too short for the requested gap")

    first_cutoff = start + span * min_train_fraction
    cutoffs = pd.date_range(first_cutoff, end, periods=n_splits + 1)[:-1]

    for fold, cutoff in enumerate(cutoffs, start=1):
        test_end = cutoffs[fold] if fold < len(cutoffs) else end
        train_mask = dates <= (cutoff - gap)
        test_mask = (dates > cutoff) & (dates <= test_end)
        if not train_mask.any() or not test_mask.any():
            continue
        yield Split(
            name=f"fold{fold}_test_{cutoff.date()}_{pd.Timestamp(test_end).date()}",
            train=np.flatnonzero(train_mask.to_numpy()),
            test=np.flatnonzero(test_mask.to_numpy()),
        )


def spatial_block_splits(
    latitude: pd.Series,
    longitude: pd.Series,
    n_splits: int = 5,
    block_degrees: float = 3.0,
    seed: int = 42,
) -> Iterator[Split]:
    """K-fold CV over contiguous lat/lon blocks.

    Points are binned into ``block_degrees`` squares, and whole blocks — not
    individual points — are assigned to folds. Held-out points are therefore
    spatially distant from training points, which is the only way to measure
    whether the model generalises to new water rather than interpolating
    between neighbours it has already seen.

    ``block_degrees`` should exceed the autocorrelation range of the drivers;
    3 degrees (~330 km) comfortably exceeds the mesoscale eddy scale here.
    """
    latitude = pd.Series(latitude).reset_index(drop=True)
    longitude = pd.Series(longitude).reset_index(drop=True)

    lat_block = np.floor(latitude / block_degrees).astype(int)
    lon_block = np.floor(longitude / block_degrees).astype(int)
    block_id = lat_block.astype(str) + "_" + lon_block.astype(str)

    unique_blocks = np.array(sorted(block_id.unique()))
    if len(unique_blocks) < n_splits:
        raise ValueError(
            f"only {len(unique_blocks)} spatial blocks for {n_splits} folds — "
            "lower block_degrees or n_splits"
        )

    rng = np.random.default_rng(seed)
    shuffled = rng.permutation(unique_blocks)
    fold_of_block = {
        block: index % n_splits for index, block in enumerate(shuffled)
    }
    fold_assignment = block_id.map(fold_of_block).to_numpy()

    for fold in range(n_splits):
        test_mask = fold_assignment == fold
        if not test_mask.any() or test_mask.all():
            continue
        yield Split(
            name=f"spatial_fold{fold + 1}",
            train=np.flatnonzero(~test_mask),
            test=np.flatnonzero(test_mask),
        )


def leave_one_region_out(region_labels: pd.Series) -> Iterator[Split]:
    """Hold out one named region at a time.

    Coarser and more honest than block CV when the question is specifically
    "does this transfer to a coastline segment we never trained on".
    """
    labels = pd.Series(region_labels).reset_index(drop=True)
    for region in sorted(labels.dropna().unique()):
        test_mask = (labels == region).to_numpy()
        if not test_mask.any() or test_mask.all():
            continue
        yield Split(
            name=f"holdout_{region}",
            train=np.flatnonzero(~test_mask),
            test=np.flatnonzero(test_mask),
        )


def chronological_split(
    dates: pd.Series,
    train_fraction: float = 0.70,
    validation_fraction: float = 0.15,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split into train / validation / test by calendar time, never at random.

    Returns three boolean masks. The test period is the most recent slice and
    should be touched exactly once, at the end.
    """
    dates = pd.to_datetime(pd.Series(dates).reset_index(drop=True))
    start, end = dates.min(), dates.max()
    span = end - start

    train_end = start + span * train_fraction
    validation_end = start + span * (train_fraction + validation_fraction)

    train = (dates <= train_end).to_numpy()
    validation = ((dates > train_end) & (dates <= validation_end)).to_numpy()
    test = (dates > validation_end).to_numpy()
    return train, validation, test


def coastal_region_label(
    latitude: pd.Series, longitude: pd.Series
) -> pd.Series:
    """Label points by northern-Indian-Ocean sub-basin.

    Used for leave-one-region-out validation and as a categorical covariate.
    Boundaries are the conventional oceanographic ones: the Indian peninsula
    at ~77E separates the Arabian Sea from the Bay of Bengal, and ~5N marks
    the transition to the equatorial Indian Ocean.
    """
    latitude = pd.Series(latitude).reset_index(drop=True)
    longitude = pd.Series(longitude).reset_index(drop=True)

    label = pd.Series("equatorial_indian", index=latitude.index, dtype="object")
    northern = latitude >= 5.0
    label[northern & (longitude < 77.0)] = "arabian_sea"
    label[northern & (longitude >= 77.0)] = "bay_of_bengal"
    label[(latitude >= 20.0) & (longitude < 70.0)] = "northern_arabian_sea"
    return label.astype("category")
