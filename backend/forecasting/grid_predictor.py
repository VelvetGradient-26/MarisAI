"""Batch inference over a global grid — the forecast map's producer.

The design constraint that shapes everything here: **this must not become a
second inference path.** `predictor.py` explains at length why a separate
inference-time feature builder is how train/serve skew gets in, and a grid is
exactly where the temptation is strongest, because a vectorised builder over
40,000 cells would be a great deal faster than 40,000 calls to a
DataFrame-shaped one.

So the loop below is deliberately the *point* pipeline, run per cell, with the
network replaced by an in-memory slice:

    grid_history.slice_point   <- stands in for history._fetch_frame's gather
    cleaning.build_dataframe   <- the same function, unchanged
    preprocessing.clean        <- the same function, unchanged
    feature_engineering.build_features  <- the same function, unchanged

Nothing in that chain knows it is being called for a map. `tests/
test_forecast_grid.py` asserts the grid and the point path agree cell for cell
on identical inputs, and that test is the reason it is safe to optimise this
later.

Measured cost, so the next person can judge a change rather than guess:
22 ms/cell for the four-function chain above, giving ~15 min for a 1-degree
global ocean grid (~42,000 cells). The fetch is the larger half and is
described in `grid_history` — ~35 min, and *independent of resolution*, so a
coarser grid speeds up the loop below and nothing else.

The cell loop is embarrassingly parallel and is factored as a pure function
over a cell list for that reason. It is serial today because a process pool is
not free to get right and the fetch dominates anyway; parallelising it would
cut total build time by about a third, not by 8x.

One feature build serves every horizon. The features do not depend on the
horizon — only the model and the decode do — so the expensive part is paid once
and each horizon is one extra `model.predict` over the same matrix.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from forecasting import ForecastingError, progress
from forecasting.config import ForecastingConfig, get_config
from forecasting.feature_engineering import build_features
from forecasting.grid_history import GridRequest, GridStack, fetch_stack
from forecasting.model_store import ModelArtifact, load
from forecasting.preprocessing import clean
from forecasting.registry import fetch_codes, resolve
from forecasting.trainer import decode_prediction
from services.download.cleaning import build_dataframe
from services.download.models import Resolution

logger = logging.getLogger(__name__)

# Where the produced grids live. Under `models/forecasting/` beside `_reports`,
# and underscore-prefixed for the same reason: `model_store.list_trained`
# already skips `_`-prefixed directories, so a grid can never be mistaken for a
# trained variable.
GRID_DIR = Path(__file__).resolve().parents[1] / "models" / "forecasting" / "_grids"

# Extra days fetched beyond the longest trailing feature window. `clean`
# regularises onto a complete daily axis and leaves genuine gaps as NaN, so a
# window sized exactly to `max_lookback_days` would leave the final row's
# 30-day trend undefined wherever a provider skipped a step.
_LOOKBACK_MARGIN_DAYS = 15

# Progress cadence for the cell loop. At 22ms/cell this is roughly every 2 min.
_LOG_EVERY = 5_000


class GridPredictionError(ForecastingError):
    """A forecast grid could not be produced."""


@dataclass
class CellMatrix:
    """Every scored cell's features, as one dense array rather than N Series.

    Built column-wise into a preallocated array because the previous shape —
    a `list[CellFeatures]` holding one `pd.Series` per cell, assembled at the
    end with `pd.DataFrame([...])` — was the single largest allocation in a
    grid build. Profiled at 1 s resolution over a 42,499-cell run, the loop
    itself held a flat 0.07-0.11 GB and then the assembly spiked to **1.16 GB
    in about twelve seconds**: 42,499 Series objects alive at once, plus the
    frame pandas builds from them.

    A Series per row costs far more than the ~100 floats it carries — object
    header, block manager and an index reference each — and none of it is
    needed, because every row has the same columns in the same order. That is
    what makes a plain (n_cells x n_features) float64 array the right shape:
    34 MB for the same 42,499 x 103 numbers.

    `values` is a *view* of the preallocated array trimmed to the rows that
    actually built, so dropped cells cost nothing and no copy is made.
    """

    columns: list[str]
    values: np.ndarray
    anchors: np.ndarray
    latitude_indices: np.ndarray
    longitude_indices: np.ndarray

    def __len__(self) -> int:
        return int(self.values.shape[0])


def grid_path(variable: str, root: Path | None = None) -> Path:
    return (root or GRID_DIR) / f"{variable}.nc"


# --------------------------------------------------------------------------
# The cell loop
# --------------------------------------------------------------------------


def _cell_features(
    stack: GridStack,
    variable_key: str,
    config: ForecastingConfig,
    cells: list[tuple[int, int, float, float]],
) -> tuple[CellMatrix | None, dict[str, int]]:
    """Build one feature row per cell. Pure: no network, no model.

    Returns the built rows and a tally of why cells were dropped. A dropped
    cell becomes NaN in the output grid rather than a guess — the same rule the
    dashboard holds everywhere, that a missing reading is never replaced by a
    number. Returns `None` when no cell built at all.
    """
    variable = resolve(variable_key, config)
    features_config = config.features_for(variable_key)
    training = config.training_for(variable_key)
    resolution = Resolution(training.resolution)
    outliers = config.outliers_for(variable_key)

    codes = [code for code in fetch_codes(variable) if code in stack.variables]

    # Allocated on the first successful cell, once the feature columns are
    # known — the count depends on the variable's covariates, so it cannot be
    # derived up front without duplicating `build_features`' own logic.
    columns: list[str] | None = None
    values: np.ndarray | None = None
    anchors = np.empty(len(cells), dtype="float64")
    latitude_indices = np.empty(len(cells), dtype="int32")
    longitude_indices = np.empty(len(cells), dtype="int32")
    written = 0

    dropped = {"no_rows": 0, "no_anchor": 0, "failed": 0}
    # Not a drop — the cell is still scored, on the established columns. Kept
    # out of `dropped` because the caller sums that dict to report how many
    # cells the grid lost, and these were not lost.
    unseen_columns = 0
    started = time.monotonic()

    tracked = progress.track(cells, description=f"{variable_key} cells", total=len(cells))
    for position, (lat_index, lon_index, latitude, longitude) in enumerate(tracked):
        try:
            frame = build_dataframe(
                fetched=stack.slice_point(latitude, longitude),
                variables=stack.variables,
                resolution=resolution,
                start_date=stack.start_date,
            )
            if frame.empty:
                dropped["no_rows"] += 1
                continue

            value_columns = [code for code in codes if code in frame.columns]
            cleaned, _quality = clean(
                frame, value_columns, resolution=resolution, outliers=outliers
            )

            # The resolved provider coordinate, not the requested one — exactly
            # what `history.fetch` reports back and what `predictor.predict`
            # feeds the builder. Using the output-grid centre instead would
            # shift every lat/lon feature by up to half a cell relative to
            # training.
            resolved_lat = float(cleaned["latitude"].iloc[0])
            resolved_lon = float(cleaned["longitude"].iloc[0])

            matrix = build_features(
                cleaned,
                variable,
                features_config,
                latitude=resolved_lat,
                longitude=resolved_lon,
                horizon=None,
            )
            if matrix.frame.empty:
                dropped["no_rows"] += 1
                continue

            last = cleaned.iloc[-1]
            anchor = (
                float(last[variable.code])
                if variable.code in cleaned.columns and pd.notna(last[variable.code])
                else np.nan
            )
            if not np.isfinite(anchor):
                # A delta model has nothing to add its output to. The point path
                # raises here; a grid cannot fail wholesale for one cell, so it
                # drops the cell and says how many were dropped.
                dropped["no_anchor"] += 1
                continue

            if columns is None:
                # First success fixes the column order for the whole grid, the
                # same way `feature_columns.json` fixes it for the trained
                # model. Every later row is reindexed onto it.
                #
                # Numeric columns only: the feature frame also carries the
                # timestamp it was built from, and a dense float array cannot
                # hold a Timestamp. Nothing is lost — `_predict_horizon`
                # reindexes onto the artifact's own feature columns, which are
                # numeric by construction because LightGBM was fitted on them,
                # so a non-numeric column was always discarded a step later.
                columns = list(
                    matrix.frame.select_dtypes(include=["number", "bool"]).columns
                )
                # Built once, not per cell: constructing this inside the loop
                # allocated a fresh Index for all 42,499 iterations and cost
                # ~5% of the loop's wall clock for a value that never changes.
                columns_index = pd.Index(columns)
                values = np.empty((len(cells), len(columns)), dtype="float64")

            row = matrix.frame.iloc[-1]
            if not row.index.equals(columns_index):
                # The old `pd.DataFrame([...])` aligned differing rows into a
                # union, filling gaps with NaN — silently, and only for rows
                # built after the column appeared. A fixed array cannot do
                # that, so reindex onto the established order (missing -> NaN,
                # which LightGBM handles) and count anything genuinely new
                # rather than passing over it without a word.
                if not set(row.index) <= set(columns):
                    unseen_columns += 1
                row = row.reindex(columns_index)

            values[written] = row.to_numpy(dtype="float64")
            anchors[written] = anchor
            latitude_indices[written] = lat_index
            longitude_indices[written] = lon_index
            written += 1
        except Exception as exc:  # noqa: BLE001 - one bad cell must not end the run
            dropped["failed"] += 1
            if dropped["failed"] <= 3:
                logger.warning(
                    f"cell {latitude:.2f},{longitude:.2f} failed: {str(exc)[:160]}"
                )

        # Skipped while a bar is drawing: it already reports rate and ETA, and a
        # log line every 5,000 cells lands in the middle of the bar's own line.
        if position and position % _LOG_EVERY == 0 and not progress.enabled():
            rate = position / max(1e-9, time.monotonic() - started)
            remaining = (len(cells) - position) / max(1e-9, rate)
            logger.info(
                f"{position}/{len(cells)} cells ({rate:.0f}/s, "
                f"~{remaining / 60:.0f} min left)"
            )

    if unseen_columns:
        logger.warning(
            f"{unseen_columns} cell(s) produced feature columns absent from the "
            "first scored cell; those columns were ignored so every row stays "
            "on one schema. Investigate before trusting the grid — the model "
            "was fitted on a fixed column set."
        )

    if columns is None or values is None or written == 0:
        return None, dropped

    # Views, not copies: the arrays were sized for every candidate cell, and
    # trimming to the ones that built costs nothing.
    return (
        CellMatrix(
            columns=columns,
            values=values[:written],
            anchors=anchors[:written],
            latitude_indices=latitude_indices[:written],
            longitude_indices=longitude_indices[:written],
        ),
        dropped,
    )


def _nice_step(span: float) -> float:
    """A rounding step of the same order as the span (1, 2 or 5 x 10^n).

    Used to round display bounds outward so a legend does not shift every time
    the grid refreshes. A raw percentile moves by a few hundredths daily, which
    would repaint the scale under a user comparing two days.
    """
    if not np.isfinite(span) or span <= 0:
        return 1.0
    magnitude = 10.0 ** np.floor(np.log10(span))
    for multiple in (1.0, 2.0, 5.0):
        if span / (magnitude * multiple) <= 5.0:
            return magnitude * multiple
    return magnitude * 10.0


def _display_bounds(values: np.ndarray) -> tuple[float, float]:
    """Robust display range, rounded outward.

    2nd-98th percentile rather than min/max: a single extreme cell would
    otherwise compress the entire colour scale into a narrow band and make the
    map look uniform. The tails are still *drawn* — `build_colormap` clamps
    rather than discarding them — they just stop setting the scale.
    """
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0, 1.0
    low, high = np.percentile(finite, [2.0, 98.0])
    step = _nice_step(max(float(high - low), 1e-9))
    return float(np.floor(low / step) * step), float(np.ceil(high / step) * step)


def _predict_horizon(
    matrix: pd.DataFrame,
    anchors: np.ndarray,
    artifact: ModelArtifact,
    variable_min: float | None,
    variable_max: float | None,
) -> np.ndarray:
    """One horizon's predictions over every built cell, decoded and bounded."""
    aligned = matrix.reindex(columns=artifact.feature_columns)
    try:
        raw = np.asarray(artifact.model.predict(aligned), dtype="float64")
    except Exception as exc:  # noqa: BLE001 - lightgbm raises varied types
        raise GridPredictionError(f"grid inference failed: {exc}") from exc

    decoded = decode_prediction(
        raw,
        anchors,
        mode=str(artifact.metadata.get("target_mode", "level")),
        log_transform=bool(artifact.metadata.get("log_transform")),
        circular=bool(artifact.metadata.get("circular")),
    )
    if variable_min is not None:
        decoded = np.maximum(decoded, variable_min)
    if variable_max is not None:
        decoded = np.minimum(decoded, variable_max)
    return decoded


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------


async def build_forecast_grid(
    variable_key: str,
    horizons: list[int],
    *,
    resolution_deg: float = 1.0,
    config: ForecastingConfig | None = None,
    root: Path | None = None,
    end_date: date | None = None,
) -> xr.Dataset:
    """Produce a global forecast grid for one variable across several horizons.

    Every requested horizon must already have a trained model; a missing one is
    an error rather than a silently shorter horizon axis, so a scheduled run
    cannot quietly start publishing fewer layers than the map advertises.
    """
    config = config or get_config()
    variable = resolve(variable_key, config)

    if not horizons:
        raise GridPredictionError("at least one horizon is required")

    artifacts = {horizon: load(variable_key, horizon, root) for horizon in sorted(horizons)}

    features_config = config.features_for(variable_key)
    lookback = features_config.max_lookback_days + _LOOKBACK_MARGIN_DAYS
    end = end_date or datetime.now(UTC).date()

    stack = await fetch_stack(
        GridRequest(
            codes=fetch_codes(variable),
            start_date=end - timedelta(days=lookback),
            end_date=end,
            resolution_deg=resolution_deg,
        )
    )

    # Everything past the fetch is CPU-bound and contains no await — about 15
    # minutes of pandas and LightGBM at 1 degree. Run inline it would hold the
    # event loop for that entire time, and this is called from a 12-hourly
    # scheduler job *and* at boot, so every tile request, dashboard poll and
    # download would queue behind it. Threaded for the same reason
    # `ocean_state` and `copernicus_sst` thread their fetches.
    return await asyncio.to_thread(
        _score_stack, stack, variable_key, artifacts, config, resolution_deg, end
    )


def _score_stack(
    stack: GridStack,
    variable_key: str,
    artifacts: dict[int, ModelArtifact],
    config: ForecastingConfig,
    resolution_deg: float,
    end: date,
) -> xr.Dataset:
    """The CPU-bound half of a grid build: cell loop, inference, assembly.

    Split out of `build_forecast_grid` so the whole span can be handed to a
    worker thread in one call rather than in pieces. It touches no network and
    no event loop, which is what makes that safe — keep it that way, and put
    any new await-ing work in the caller.
    """
    variable = resolve(variable_key, config)

    mask = stack.ocean_mask(variable.code)
    lat_indices, lon_indices = np.nonzero(mask)
    cells = [
        (int(i), int(j), float(stack.latitudes[i]), float(stack.longitudes[j]))
        for i, j in zip(lat_indices, lon_indices, strict=True)
    ]
    logger.info(
        f"building {variable_key} forecast grid at {resolution_deg} deg: "
        f"{len(cells)} ocean cells, horizons {list(artifacts)}"
    )

    started = time.monotonic()
    built, dropped = _cell_features(stack, variable_key, config, cells)
    if built is None:
        raise GridPredictionError(
            f"no cell produced usable features for {variable_key}; "
            f"dropped {dropped}"
        )

    # `copy=False` so this wraps the array the loop already filled instead of
    # duplicating 42,499 x ~100 float64s to hand LightGBM the same numbers.
    matrix = pd.DataFrame(built.values, columns=built.columns, copy=False)
    anchors = built.anchors
    rows_lat = built.latitude_indices
    rows_lon = built.longitude_indices

    shape = (len(stack.latitudes), len(stack.longitudes))
    forecast = np.full((len(artifacts), *shape), np.nan, dtype="float32")
    for index, artifact in enumerate(artifacts.values()):
        values = _predict_horizon(
            matrix, anchors, artifact, variable.valid_min, variable.valid_max
        )
        forecast[index, rows_lat, rows_lon] = values.astype("float32")

    anchor_grid = np.full(shape, np.nan, dtype="float32")
    anchor_grid[rows_lat, rows_lon] = anchors.astype("float32")

    elapsed = time.monotonic() - started
    logger.info(
        f"{variable_key} grid built: {len(built)} cells scored, "
        f"{sum(dropped.values())} dropped {dropped}, {elapsed / 60:.1f} min"
    )

    dataset = xr.Dataset(
        {
            "forecast": (("horizon", "latitude", "longitude"), forecast),
            # The value the delta was added to — the persistence forecast, and
            # what the change layer is measured against. Carried in the file so
            # the tile renderer never has to re-derive it from a second source
            # that could be a different timestep.
            "anchor": (("latitude", "longitude"), anchor_grid),
        },
        coords={
            "horizon": list(artifacts),
            "latitude": stack.latitudes,
            "longitude": stack.longitudes,
        },
    )

    if variable.circular:
        # A bearing's display range is its domain, and its largest possible
        # change is half a turn. Percentiles are meaningless on a circle — the
        # 98th percentile of a field spanning 0.31 to 359.97 degrees is not a
        # bound, it is an artefact of where zero happens to be, and it is how a
        # `display_max` of 400 was written to the shipped grid.
        display_min, display_max = 0.0, 360.0
        change_scale = 180.0
    else:
        display_min, display_max = _display_bounds(forecast)
        # The change layer's scale is symmetric by construction: zero must sit at
        # the neutral colour, or a diverging ramp reads as though the ocean were
        # warming everywhere simply because the positive tail is longer.
        change = forecast - anchor_grid[None, :, :]
        finite_change = np.abs(change[np.isfinite(change)])
        change_scale = 1.0
        if finite_change.size:
            magnitude = float(np.percentile(finite_change, 98.0))
            step = _nice_step(max(magnitude, 1e-9))
            change_scale = float(max(np.ceil(magnitude / step) * step, step))

    first = next(iter(artifacts.values()))
    dataset.attrs.update(
        {
            "variable": variable_key,
            "label": variable.label,
            "unit": variable.unit,
            "resolution_deg": resolution_deg,
            # Legend bounds live with the data so the tile renderer and the
            # frontend legend cannot disagree about what a colour means.
            "display_min": display_min,
            "display_max": display_max,
            "change_scale": change_scale,
            "generated_at": datetime.now(UTC).isoformat(),
            "observation_date": end.isoformat(),
            "cells_scored": len(built),
            "cells_dropped": int(sum(dropped.values())),
            "model": str(first.metadata.get("model_type", "LightGBM")),
            "trained_at": str(first.metadata.get("trained_at", "")),
            "sources": "; ".join(stack.sources),
            # The honest part. These covariates were in the model at training
            # time and have no global field, so every cell was scored without
            # them. The map states this rather than letting LightGBM's
            # missing-value branch absorb it invisibly.
            "missing_covariates": ", ".join(stack.ungriddable),
            "skill_scores": ", ".join(
                f"h{horizon}={artifact.metrics.get('validation', {}).get('metrics', {}).get('skill_score')}"
                for horizon, artifact in artifacts.items()
            ),
        }
    )
    return dataset


def save_grid(dataset: xr.Dataset, variable: str, root: Path | None = None) -> Path:
    """Write a grid atomically, so a reader never sees a half-written file."""
    path = grid_path(variable, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".nc.tmp")
    dataset.to_netcdf(temporary)
    temporary.replace(path)
    logger.info(f"wrote forecast grid to {path}")
    return path
