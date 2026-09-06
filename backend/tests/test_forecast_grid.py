"""Tests for the global forecast grid.

No network: every test builds a synthetic `GridStack` in memory, so a failure
here means a code defect rather than a Copernicus outage.

**The load-bearing test is `test_grid_matches_the_point_path`.** The grid exists
to render the same model the point API serves, and the only way that stays true
is if both paths run the identical feature chain. A vectorised grid-native
feature builder would be much faster and would silently produce a different
answer; this test is what makes that optimisation safe to attempt, because it
compares the two paths cell for cell on byte-identical inputs.

The stub model is chosen for the same reason. It returns a weighted sum over the
aligned feature row, so any difference in feature *values* or column *order*
between the two call sites changes the prediction — a model that ignored its
input would pass the parity test while proving nothing.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from forecasting import grid_history, grid_predictor, predictor
from forecasting.config import get_config
from forecasting.grid_history import GridStack, output_grid
from forecasting.grid_predictor import build_forecast_grid
from forecasting.history import HistorySeries
from forecasting.model_store import save
from forecasting.registry import fetch_codes, resolve
from services.download import catalog
from services.download.cleaning import build_dataframe
from services.download.models import Resolution
from services.download.registry import resolve_variables

VARIABLE = "sea_surface_temperature"
HORIZON = 7
DAYS = 60
# Coarse on purpose. The cell loop costs ~22ms per cell, and these tests care
# about agreement between two code paths, not about spatial detail — 10 degrees
# gives 648 cells, enough to sample ten scattered comparisons, and keeps the
# file under a minute instead of over three.
RESOLUTION_DEG = 10.0
# One 256x256 tile, for coverage assertions on the rendered PNG.
TILE_SIZE = 256
TILE_PIXELS = TILE_SIZE * TILE_SIZE


class WeightedSumModel:
    """A deterministic stand-in for a booster.

    Module-level (not a closure) so `model_store.save` can pickle it. The
    prediction is a weighted sum whose weights rise with column position, which
    is what makes the parity test sensitive to column *order* and not just to
    the set of columns present.
    """

    def predict(self, X):  # noqa: N803 - matches the sklearn/lightgbm signature
        values = np.nan_to_num(np.asarray(X, dtype="float64"), nan=0.0)
        weights = np.arange(1, values.shape[1] + 1, dtype="float64")
        # Scaled to a small delta so the decoded forecast stays inside the
        # variable's valid range and the bounds clamp never hides a difference.
        return (values @ weights) / (values.shape[1] * 1e6)


# --------------------------------------------------------------------------
# Synthetic stack
# --------------------------------------------------------------------------


def _field(times, lat, lon, base, scale, seed):
    rng = np.random.default_rng(seed)
    trend = np.linspace(0.0, 1.0, len(times))[:, None, None]
    noise = rng.standard_normal((len(times), len(lat), len(lon)))
    gradient = np.cos(np.radians(lat))[None, :, None]
    return (base + scale * (trend + 0.3 * noise) * gradient).astype("float32")


@pytest.fixture
def stack() -> GridStack:
    """A global stack at 5 degrees — coarse enough to score in a test, real
    enough that every provider in the variable's fetch list is present."""
    latitudes, longitudes = output_grid(RESOLUTION_DEG)
    end = date(2026, 6, 30)
    times = pd.date_range(end - timedelta(days=DAYS - 1), periods=DAYS, freq="D")

    physics = xr.Dataset(
        {
            "thetao": (
                ("time", "latitude", "longitude"),
                _field(times, latitudes, longitudes, 20.0, 4.0, 1),
            ),
            "so": (
                ("time", "latitude", "longitude"),
                _field(times, latitudes, longitudes, 35.0, 0.5, 2),
            ),
        },
        coords={"time": times, "latitude": latitudes, "longitude": longitudes},
    )
    wind = xr.Dataset(
        {
            "eastward_wind": (
                ("time", "latitude", "longitude"),
                _field(times, latitudes, longitudes, 3.0, 2.0, 3),
            ),
            "northward_wind": (
                ("time", "latitude", "longitude"),
                _field(times, latitudes, longitudes, -2.0, 2.0, 4),
            ),
        },
        coords={"time": times, "latitude": latitudes, "longitude": longitudes},
    )
    rng = np.random.default_rng(5)
    depth = xr.Dataset(
        {
            "ocean_depth": (
                ("latitude", "longitude"),
                rng.uniform(20.0, 5000.0, (len(latitudes), len(longitudes))),
            )
        },
        coords={"latitude": latitudes, "longitude": longitudes},
    )

    variable = resolve(VARIABLE, get_config())
    codes = fetch_codes(variable)
    # Open-Meteo has no global field, exactly as in production.
    griddable = [code for code in codes if code != "air_temperature"]

    return GridStack(
        providers={
            catalog.PROVIDER_COPERNICUS_PHYSICS: (
                catalog.get(catalog.PROVIDER_COPERNICUS_PHYSICS),
                physics,
            ),
            catalog.PROVIDER_COPERNICUS_WIND: (catalog.get(catalog.PROVIDER_COPERNICUS_WIND), wind),
            catalog.PROVIDER_GEBCO: (catalog.get(catalog.PROVIDER_GEBCO), depth),
        },
        variables=resolve_variables(griddable),
        ungriddable=("air_temperature",),
        latitudes=latitudes,
        longitudes=longitudes,
        start_date=times[0].date(),
        sources=["synthetic"],
    )


@pytest.fixture
def model_root(tmp_path):
    """A trained-looking artifact whose model is the weighted-sum stub."""
    variable = resolve(VARIABLE, get_config())
    feature_columns = _feature_columns_for(variable)
    save(
        variable=VARIABLE,
        horizon=HORIZON,
        model=WeightedSumModel(),
        feature_columns=feature_columns,
        categorical_columns=["basin"],
        metadata={
            "trained_at": "2026-06-30T00:00:00Z",
            "target_mode": "delta",
            "log_transform": False,
            "circular": False,
            "model_type": "stub",
            "residual_quantiles": {
                "lower_offset": -0.5,
                "upper_offset": 0.5,
                "confidence_level": 0.95,
                "n_residuals": 100,
                "bias": 0.0,
            },
        },
        metrics={"validation": {"metrics": {"rmse": 0.5, "skill_score": 0.2}}},
        root=tmp_path,
    )
    return tmp_path


def _feature_columns_for(variable) -> list[str]:
    """The exact column set the builder emits for this variable, discovered by
    running it once — the trainer records the same thing."""
    from forecasting.feature_engineering import build_features

    config = get_config()
    times = pd.date_range("2026-01-01", periods=DAYS, freq="D")
    frame = pd.DataFrame(
        {
            "timestamp": times,
            "latitude": 10.0,
            "longitude": 70.0,
            "sea_surface_temperature": np.linspace(20, 25, DAYS),
            "sea_surface_salinity": np.linspace(35, 35.5, DAYS),
            "wind_speed": np.linspace(3, 6, DAYS),
            "ocean_depth": 1000.0,
        }
    )
    matrix = build_features(
        frame,
        variable,
        config.features_for(VARIABLE),
        latitude=10.0,
        longitude=70.0,
        horizon=None,
    )
    return matrix.feature_columns


# --------------------------------------------------------------------------
# The parity test
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grid_matches_the_point_path(stack, model_root, monkeypatch):
    """The grid and `predictor.predict` must agree on identical inputs.

    This is the test that keeps the two inference paths from drifting. It fails
    if the cell loop stops using `build_dataframe`/`clean`/`build_features`, if
    it feeds the builder the output-grid centre instead of the resolved provider
    coordinate, or if the feature row is assembled in a different column order.
    """
    monkeypatch.setattr(grid_predictor, "fetch_stack", _stack_returning(stack))

    grid = await build_forecast_grid(
        VARIABLE,
        [HORIZON],
        resolution_deg=RESOLUTION_DEG,
        root=model_root,
        end_date=date(2026, 6, 30),
    )

    # Scatter the sample points across basins and hemispheres rather than
    # taking the first N cells, which would all sit in the Southern Ocean.
    scored = np.argwhere(np.isfinite(grid["forecast"].isel(horizon=0).values))
    assert len(scored) >= 10, "synthetic stack produced too few ocean cells to compare"
    sample = scored[:: max(1, len(scored) // 10)][:10]

    monkeypatch.setattr(predictor, "fetch", _point_fetch_from(stack))
    predictor.clear_model_cache()

    compared = 0
    for lat_index, lon_index in sample:
        latitude = float(grid.latitude.values[lat_index])
        longitude = float(grid.longitude.values[lon_index])

        point = await predictor.predict(
            VARIABLE,
            latitude,
            longitude,
            HORIZON,
            root=model_root,
            include_history=False,
        )
        from_grid = float(grid["forecast"].isel(horizon=0).values[lat_index, lon_index])

        assert from_grid == pytest.approx(point.prediction, abs=1e-6), (
            f"grid and point path disagree at {latitude}, {longitude}: "
            f"{from_grid} vs {point.prediction}"
        )
        compared += 1

    assert compared == len(sample)


@pytest.mark.asyncio
async def test_anchor_grid_is_the_last_observation(stack, model_root, monkeypatch):
    """The anchor a delta decodes from must be the cell's own latest value."""
    monkeypatch.setattr(grid_predictor, "fetch_stack", _stack_returning(stack))
    grid = await build_forecast_grid(
        VARIABLE,
        [HORIZON],
        resolution_deg=RESOLUTION_DEG,
        root=model_root,
        end_date=date(2026, 6, 30),
    )

    physics = stack.providers[catalog.PROVIDER_COPERNICUS_PHYSICS][1]
    scored = np.argwhere(np.isfinite(grid["anchor"].values))
    for lat_index, lon_index in scored[:: max(1, len(scored) // 5)][:5]:
        latitude = float(grid.latitude.values[lat_index])
        longitude = float(grid.longitude.values[lon_index])
        expected = float(
            physics["thetao"]
            .sel(latitude=latitude, longitude=longitude, method="nearest")
            .isel(time=-1)
        )
        assert float(grid["anchor"].values[lat_index, lon_index]) == pytest.approx(
            expected, abs=1e-3
        )


@pytest.mark.asyncio
async def test_the_cell_loop_does_not_run_on_the_event_loop(stack, model_root, monkeypatch):
    """The CPU-bound span must be threaded, not awaited inline.

    At production resolution the cell loop is ~15 minutes of pandas and
    LightGBM with no await anywhere inside it, and `services.forecast_tiles`
    starts it both at boot and from a 12-hourly scheduler job. Inline, that
    holds the event loop for the whole window and every tile request, dashboard
    poll and download on the server hangs behind it.

    Asserting on the *thread* rather than on observed responsiveness is
    deliberate: the synthetic stack here builds in milliseconds, so a timing
    check would pass just as happily with the work back on the loop.
    """
    monkeypatch.setattr(grid_predictor, "fetch_stack", _stack_returning(stack))

    loop_thread = threading.get_ident()
    ran_on: dict[str, int] = {}
    original = grid_predictor._score_stack

    def recording(*args, **kwargs):
        ran_on["thread"] = threading.get_ident()
        return original(*args, **kwargs)

    monkeypatch.setattr(grid_predictor, "_score_stack", recording)

    await build_forecast_grid(
        VARIABLE,
        [HORIZON],
        resolution_deg=RESOLUTION_DEG,
        root=model_root,
        end_date=date(2026, 6, 30),
    )

    assert ran_on, "_score_stack was never called — the build was restructured"
    assert ran_on["thread"] != loop_thread, (
        "the grid build ran on the event loop thread; it must go through "
        "asyncio.to_thread or the API stalls for the length of a rebuild"
    )


@pytest.mark.asyncio
async def test_missing_covariates_are_recorded_not_hidden(stack, model_root, monkeypatch):
    """A covariate with no global field must be named in the output.

    LightGBM routes an absent feature down its missing-value branch without
    complaint, so the only thing standing between that and a map which looks
    exactly as confident as a complete one is this attribute.
    """
    monkeypatch.setattr(grid_predictor, "fetch_stack", _stack_returning(stack))
    grid = await build_forecast_grid(
        VARIABLE,
        [HORIZON],
        resolution_deg=RESOLUTION_DEG,
        root=model_root,
        end_date=date(2026, 6, 30),
    )
    assert "air_temperature" in grid.attrs["missing_covariates"]


@pytest.mark.asyncio
async def test_a_correct_build_does_not_warn_about_unknown_columns(
    stack, model_root, monkeypatch, caplog
):
    """The schema warning must fire on schema drift, and only on schema drift.

    It used to fire on *every* cell of every build — 64,440 of 64,440 on a real
    wind_u grid, and 648 of 648 here — because rows were tested against the
    numeric column subset while every feature frame also carries the
    `timestamp` column that subset deliberately excludes. A warning reading
    "investigate before trusting the grid" that appears on every correct build
    is one nobody reads, which is the same cry-wolf failure the assistant's
    grounding checker was fixed for.
    """
    monkeypatch.setattr(grid_predictor, "fetch_stack", _stack_returning(stack))
    with caplog.at_level(logging.WARNING, logger="forecasting.grid_predictor"):
        await build_forecast_grid(
            VARIABLE,
            [HORIZON],
            resolution_deg=RESOLUTION_DEG,
            root=model_root,
            end_date=date(2026, 6, 30),
        )
    assert not any("absent from the first" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_cells_without_a_recent_observation_are_dropped(stack, model_root, monkeypatch):
    """A cell whose latest value is missing gets NaN, never an invented anchor.

    The point path raises for this case; a grid cannot fail wholesale for one
    cell, so it must drop it instead — and the two must agree that the cell is
    unforecastable rather than one of them guessing.
    """
    physics = stack.providers[catalog.PROVIDER_COPERNICUS_PHYSICS][1]
    blanked = physics.copy(deep=True)
    # Blank the whole final timestep: every cell loses its anchor.
    blanked["thetao"][-1, :, :] = np.nan
    stack.providers[catalog.PROVIDER_COPERNICUS_PHYSICS] = (
        stack.providers[catalog.PROVIDER_COPERNICUS_PHYSICS][0],
        blanked,
    )

    monkeypatch.setattr(grid_predictor, "fetch_stack", _stack_returning(stack))
    with pytest.raises(grid_predictor.GridPredictionError):
        await build_forecast_grid(
            VARIABLE,
            [HORIZON],
            resolution_deg=RESOLUTION_DEG,
            root=model_root,
            end_date=date(2026, 6, 30),
        )


def test_ocean_mask_reads_the_latest_timestep(stack):
    """The mask and the anchor must come from the same timestep, or the grid
    would score cells it cannot anchor."""
    physics = stack.providers[catalog.PROVIDER_COPERNICUS_PHYSICS][1]
    blanked = physics.copy(deep=True)
    blanked["thetao"][-1, :5, :] = np.nan
    stack.providers[catalog.PROVIDER_COPERNICUS_PHYSICS] = (
        stack.providers[catalog.PROVIDER_COPERNICUS_PHYSICS][0],
        blanked,
    )
    mask = stack.ocean_mask(VARIABLE)
    assert not mask[:5, :].any()
    assert mask[5:, :].any()


# --------------------------------------------------------------------------
# Tile rendering
# --------------------------------------------------------------------------


def _write_tile_grid(
    directory,
    *,
    forecast_offset: float,
    unforecastable: bool = False,
    observed: bool = True,
    land_east_of: float | None = None,
) -> None:
    """A global grid whose temperature ramps with latitude, so a rendered tile
    has something to vary across.

    `unforecastable` punches a hole in the *forecast* while leaving `anchor`
    intact — observable water the model could not score, which is a different
    thing from land and must not render like it. `observed=False` removes the
    anchor too, which is that other thing: land, or outside coverage.

    `land_east_of` makes every cell east of that longitude land in both fields,
    giving a coastline at a known place to measure the painted edge against.
    """
    latitudes = np.arange(-89.0, 90.0, 2.0)
    longitudes = np.arange(-179.0, 180.0, 2.0)
    anchor = np.tile(np.linspace(0.0, 30.0, len(latitudes))[:, None], (1, len(longitudes))).astype(
        "float32"
    )

    forecast = anchor + forecast_offset
    if unforecastable:
        forecast = np.full_like(forecast, np.nan)
    if observed is False:
        anchor = np.full_like(anchor, np.nan)
        forecast = np.full_like(forecast, np.nan)
    if land_east_of is not None:
        is_land = longitudes > land_east_of
        anchor[:, is_land] = np.nan
        forecast[:, is_land] = np.nan

    dataset = xr.Dataset(
        {
            "forecast": (
                ("horizon", "latitude", "longitude"),
                forecast[None, :, :],
            ),
            "anchor": (("latitude", "longitude"), anchor),
        },
        coords={"horizon": [HORIZON], "latitude": latitudes, "longitude": longitudes},
    )
    dataset.attrs.update(
        {
            "variable": VARIABLE,
            "label": "Sea Surface Temperature",
            "unit": "degC",
            "display_min": 0.0,
            "display_max": 30.0,
            "change_scale": 2.0,
            "resolution_deg": 2.0,
            "generated_at": "2026-08-05T00:00:00Z",
        }
    )
    dataset.to_netcdf(directory / f"{VARIABLE}.nc")


def _decode(png: bytes) -> np.ndarray:
    """Opaque pixels only, as (n, 3).

    Transparent pixels carry RGB (0, 0, 0) — a no-data marker, not a colour —
    and folding them in would make a correct tile look like it contains black.
    """
    from io import BytesIO

    from PIL import Image

    rgba = np.array(Image.open(BytesIO(png)).convert("RGBA"))
    flat = rgba.reshape(-1, 4)
    return flat[flat[:, 3] > 0][:, :3]


def test_absolute_tile_paints_in_the_variables_own_units(tmp_path):
    """A colormap in degrees Celsius must be handed degrees Celsius.

    The shared ramps in `colormaps.py` live on a unit domain and `SST_COLORMAP_
    STOPS` lives on -2..35 degC. Normalising values to [0, 1] before calling the
    latter paints the whole ocean the colour of -2 degC — a map that renders,
    returns plausible PNG bytes, and is entirely wrong. This asserts on pixels
    because byte counts do not notice.
    """
    from services import forecast_tiles

    _write_tile_grid(tmp_path, forecast_offset=0.0)
    forecast_tiles.clear_cache()

    pixels = _decode(
        forecast_tiles.tile_or_placeholder(VARIABLE, HORIZON, "absolute", 0, 0, 0, tmp_path)
    )
    opaque = pixels

    # A 0-30 degC ramp must cross most of the scale, not collapse onto one end.
    spread = opaque.max(axis=0).astype(int) - opaque.min(axis=0).astype(int)
    assert spread.max() > 120, f"absolute tile is nearly flat: channel spread {spread}"
    assert len(np.unique(opaque, axis=0)) > 20


def test_change_tile_is_neutral_where_nothing_changes(tmp_path):
    """Zero change must land on the diverging ramp's neutral centre.

    If the symmetric domain is mishandled, zero drifts off centre and an
    unchanged ocean reads as uniformly warming or cooling.
    """
    from services import forecast_tiles

    _write_tile_grid(tmp_path, forecast_offset=0.0)
    forecast_tiles.clear_cache()

    pixels = _decode(
        forecast_tiles.tile_or_placeholder(VARIABLE, HORIZON, "change", 0, 0, 0, tmp_path)
    )
    # DIVERGING_STOPS' centre is (247, 247, 247).
    assert np.abs(pixels.astype(int) - 247).max() <= 3


def test_change_tile_separates_warming_from_cooling(tmp_path):
    """A uniform warming and a uniform cooling must not paint the same colour."""
    from services import forecast_tiles

    warm_dir = tmp_path / "warm"
    cool_dir = tmp_path / "cool"
    warm_dir.mkdir()
    cool_dir.mkdir()
    _write_tile_grid(warm_dir, forecast_offset=1.5)
    _write_tile_grid(cool_dir, forecast_offset=-1.5)
    forecast_tiles.clear_cache()

    warm = _decode(
        forecast_tiles.tile_or_placeholder(VARIABLE, HORIZON, "change", 0, 0, 0, warm_dir)
    ).mean(axis=0)
    forecast_tiles.clear_cache()
    cool = _decode(
        forecast_tiles.tile_or_placeholder(VARIABLE, HORIZON, "change", 0, 0, 0, cool_dir)
    ).mean(axis=0)

    # Forecast change is drawn on PRGn: warming runs green, cooling runs purple
    # (both red and blue elevated over green) — the green channel must
    # dominate one and recede in the other.
    assert warm[1] > warm[0] and warm[1] > warm[2], f"warming did not render green: {warm}"
    assert cool[1] < cool[0] and cool[1] < cool[2], f"cooling did not render purple: {cool}"


def test_unforecastable_water_does_not_render_as_an_extreme_value(tmp_path):
    """ "No forecast here" and "the strongest cooling on the scale" must differ.

    Measured, not assumed: every ramp this module uses bottoms out near black,
    and the map's default basemap is a near-black ocean (#030f1e). At the
    layer's 0.7 opacity the darkest step of each ramp sits at 1.13-1.27:1
    contrast against bare basemap, against a 2:1 floor — and no ramp end clears
    2:1 even at full opacity. So an unscored cell left transparent is, to a
    reader, the bottom of the colour scale.

    That is the visual form of the rule this codebase is built on: never let
    missing data wear the costume of a value. Absence is marked with texture,
    which is the one channel the colour ramp does not already occupy.
    """
    from services import forecast_tiles

    blank = tmp_path / "blank"
    coldest = tmp_path / "coldest"
    blank.mkdir()
    coldest.mkdir()
    _write_tile_grid(blank, forecast_offset=0.0, unforecastable=True)
    # Past the -2 degC change scale, so every cell clamps to the ramp's end.
    _write_tile_grid(coldest, forecast_offset=-10.0)
    forecast_tiles.clear_cache()

    marked = _decode(
        forecast_tiles.tile_or_placeholder(VARIABLE, HORIZON, "change", 0, 0, 0, blank)
    )
    forecast_tiles.clear_cache()
    extreme = _decode(
        forecast_tiles.tile_or_placeholder(VARIABLE, HORIZON, "change", 0, 0, 0, coldest)
    )

    # The unscored tile is not blank: the hatch leaves opaque pixels behind.
    assert len(marked) > 0, "unforecastable water rendered as an empty tile"
    # ...and it is a hatch, so the tile is mostly still transparent. A solid
    # fill would be a colour, and a colour is what must not happen here.
    assert len(marked) < TILE_PIXELS // 2, "the marker is a fill, not a hatch"

    # The two must be separable by colour, not merely by coverage.
    assert np.unique(marked, axis=0).shape[0] == 1, f"hatch is not one colour: {marked[:5]}"
    separation = np.abs(marked[0].astype(int) - extreme.mean(axis=0)).max()
    assert separation > 40, (
        f"unforecastable water {marked[0]} is indistinguishable from the ramp's "
        f"cold end {extreme.mean(axis=0).round()}"
    )


def test_land_stays_transparent(tmp_path):
    """The hatch marks water we could see but not score — never land.

    `anchor` is the discriminator: finite exactly where a latest observation
    existed. Keying the mark on the forecast alone would hatch every continent,
    which is why this test exists next to the one above rather than inside it.
    """
    from services import forecast_tiles

    _write_tile_grid(tmp_path, forecast_offset=0.0, observed=False)
    forecast_tiles.clear_cache()

    pixels = _decode(
        forecast_tiles.tile_or_placeholder(VARIABLE, HORIZON, "change", 0, 0, 0, tmp_path)
    )
    assert len(pixels) == 0, f"{len(pixels)} opaque pixels painted where nothing was observed"


def _alpha_row(png: bytes, row: int) -> np.ndarray:
    from io import BytesIO

    from PIL import Image

    return np.array(Image.open(BytesIO(png)).convert("RGBA"))[row, :, 3]


def test_the_painted_edge_reaches_halfway_to_the_first_land_cell(tmp_path):
    """Coastal water must be painted, and its edge must sit at the half-cell
    contour rather than on the last whole cell.

    A plain bilinear read of a NaN-holed field is poisoned by the hole: every
    pixel with a land cell among its four neighbours comes back NaN, so the
    painted ocean retreats a full cell from the coast and its edge is forced
    onto the grid's own axis-aligned steps. On the shipped 1-degree grids that
    erased 3,609 of chlorophyll's 42,499 ocean cells — 8.5%, and the 8.5% a
    fisheries map is most about.

    Here the last ocean cell centre is 1 degE and the first land centre 3 degE,
    so the correct nearest-cell footprint ends at 2 degE. Asserting on the
    boundary's *position* rather than on "some coastal pixel is opaque" is what
    catches the failure in either direction: erosion pulls it back to 1 degE,
    and a fill that bleeds instead of being masked pushes it past 3 degE onto
    land.
    """
    from services import forecast_tiles

    _write_tile_grid(tmp_path, forecast_offset=0.0, land_east_of=1.0)
    forecast_tiles.clear_cache()

    # z2/x=2 spans 0-90 degE, so the coast falls a few pixels in and each pixel
    # is 0.352 deg — fine enough to locate a half-cell edge.
    png = forecast_tiles.tile_or_placeholder(VARIABLE, HORIZON, "absolute", 2, 2, 1, tmp_path)
    alpha = _alpha_row(png, TILE_SIZE // 2)

    opaque = np.flatnonzero(alpha > 0)
    assert opaque.size > 0, "the coastal row painted nothing at all"
    edge_lon = (opaque[-1] + 0.5) / TILE_SIZE * 90.0

    assert 1.0 < edge_lon <= 2.0, (
        f"painted ocean ends at {edge_lon:.2f} degE; expected the half-cell "
        f"boundary between the last ocean cell (1 degE) and the first land cell (3 degE)"
    )


def test_no_no_data_seam_at_the_antimeridian(tmp_path):
    """The grid's last cell centre is short of 180 deg, and sampling must wrap.

    Longitude is periodic but the stored axis is not: every pixel between the
    final cell centre and the antimeridian falls outside it and, left alone,
    renders as a transparent stripe down an ocean that is continuous in
    reality. Measured on the shipped chlorophyll grid before the wrap: the
    final pixel column of a z2 dateline tile was 0/256 opaque against 223/256
    in the column beside it. Same fix, same reason, as
    `copernicus_sst._build_interpolator`.
    """
    from services import forecast_tiles

    _write_tile_grid(tmp_path, forecast_offset=0.0)
    forecast_tiles.clear_cache()

    png = forecast_tiles.tile_or_placeholder(VARIABLE, HORIZON, "absolute", 0, 0, 0, tmp_path)
    alpha = _alpha_row(png, TILE_SIZE // 2)

    assert alpha[-1] > 0, "the antimeridian column is transparent — the wrap is missing"
    assert (alpha > 0).all(), f"{int((alpha == 0).sum())} transparent pixels in an all-ocean row"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _stack_returning(stack: GridStack):
    async def _fetch(_request):
        return stack

    return _fetch


def _point_fetch_from(stack: GridStack):
    """Stand in for `history.fetch`, serving the same synthetic stack.

    Builds the frame through `build_dataframe` on the stack slice — the same
    call the grid path makes — so the comparison isolates the *pipeline* rather
    than re-testing that two different data sources agree.
    """

    async def _fetch(request, **_kwargs):
        frame = build_dataframe(
            fetched=stack.slice_point(request.latitude, request.longitude),
            variables=stack.variables,
            resolution=Resolution.daily,
            start_date=stack.start_date,
        )
        return HistorySeries(
            frame=frame,
            latitude=float(frame["latitude"].iloc[0]),
            longitude=float(frame["longitude"].iloc[0]),
            resolution=Resolution.daily,
            coverage={},
            sources=["synthetic"],
        )

    return _fetch


# --------------------------------------------------------------------------
# Fetch-cache eviction
# --------------------------------------------------------------------------
#
# The cache had no eviction and accumulated 9.6 GB, 8.16 GB of it unreachable
# (measured 2026-08-16). The leak is structural rather than a bad branch: a
# scope key carries the date window, so a build with a fresh window orphans
# yesterday's entries, and `_cache_get` only ever globs the scope it wants.
# Nothing looks at a dead scope, so nothing can delete it.


def _touch(path, age_hours: float) -> None:
    """A cache file of a given age. Size is real so `freed` has something to add."""
    path.write_bytes(b"\0" * 1024)
    stamp = (datetime.now(UTC) - timedelta(hours=age_hours)).timestamp()
    os.utime(path, (stamp, stamp))


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(grid_history, "CACHE_DIR", tmp_path)
    return tmp_path


def _request() -> grid_history.GridRequest:
    return grid_history.GridRequest(
        codes=("sea_surface_temperature",),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 1),
    )


def test_sweep_drops_stale_field_entries_and_keeps_fresh_ones(cache_dir):
    request = _request()
    scope = grid_history._scope_key(catalog.PROVIDER_COPERNICUS_PHYSICS, request, 12)

    stale = cache_dir / f"{scope}-aaaaaaaaaaaa.nc"
    fresh = cache_dir / f"{scope}-bbbbbbbbbbbb.nc"
    _touch(stale, age_hours=227)  # the real age observed on disk
    _touch(fresh, age_hours=1)

    assert grid_history.sweep_cache(request) == 1
    assert not stale.exists()
    assert fresh.exists()


def test_sweep_reaches_orphaned_scopes(cache_dir):
    """The whole point: an entry whose scope will never be requested again.

    `_cache_get` would never glob this file, which is why age alone has to be
    the test rather than membership of a live scope.
    """
    dead = _request()
    live = grid_history.GridRequest(
        codes=("sea_surface_temperature",),
        start_date=date(2026, 3, 1),
        end_date=date(2026, 4, 1),
    )
    orphan_scope = grid_history._scope_key(catalog.PROVIDER_COPERNICUS_PHYSICS, dead, 12)
    orphan = cache_dir / f"{orphan_scope}-cccccccccccc.nc"
    _touch(orphan, age_hours=48)

    assert grid_history.sweep_cache(live) == 1
    assert not orphan.exists()


def test_sweep_honours_the_static_ttl_for_bathymetry(cache_dir):
    """GEBCO is time-invariant, so a week-old entry is still perfectly good.

    Sweeping it at the field TTL would refetch a global grid that cannot have
    changed — the exact cost `_scope_key` drops the date window to avoid.
    """
    request = _request()
    gebco_scope = grid_history._scope_key(catalog.PROVIDER_GEBCO, request, 1)
    physics_scope = grid_history._scope_key(catalog.PROVIDER_COPERNICUS_PHYSICS, request, 12)

    bathymetry = cache_dir / f"{gebco_scope}-dddddddddddd.nc"
    field = cache_dir / f"{physics_scope}-eeeeeeeeeeee.nc"
    _touch(bathymetry, age_hours=24 * 7)
    _touch(field, age_hours=24 * 7)

    assert grid_history.sweep_cache(request) == 1
    assert bathymetry.exists()
    assert not field.exists()

    # ...but not forever. Past 90 days it goes like anything else.
    _touch(bathymetry, age_hours=24 * 120)
    assert grid_history.sweep_cache(request) == 1
    assert not bathymetry.exists()


def test_sweep_removes_torn_writes(cache_dir):
    """A `.tmp` from a crashed `_cache_put` matches no glob in this module.

    Neither `_cache_get` nor `clear_cache` looks at `*.nc.tmp`, so without the
    sweep a torn write is permanent.
    """
    request = _request()
    scope = grid_history._scope_key(catalog.PROVIDER_COPERNICUS_PHYSICS, request, 12)
    torn = cache_dir / f"{scope}-ffffffffffff.nc.tmp"
    _touch(torn, age_hours=48)

    assert grid_history.sweep_cache(request) == 1
    assert not torn.exists()


def test_sweep_is_quiet_on_a_missing_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(grid_history, "CACHE_DIR", tmp_path / "absent")
    assert grid_history.sweep_cache(_request()) == 0
