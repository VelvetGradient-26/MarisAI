"""What changes when a region is the whole planet.

Every source in `marine_ml.sources` was written for a bounded box, and each one
fails differently at global extent rather than merely getting slower:

* Copernicus physics is 1/12 degree, so 168 monthly timesteps of six variables
  is ~35 GB in a single array — an OOM, not a long wait.
* GEBCO's griddap at native 1 arc-minute is 233M cells worldwide, which ERDDAP
  refuses.
* The OBIS target group is 21,789,311 records worldwide against 10,051 over
  NORTH_INDIAN_OCEAN, and the pager would have returned a truncated frame that
  looks complete.

These tests pin the fixes, and — the part that matters most — pin that the
**regional path is untouched**, because the regional model is the baseline the
global one has to beat. A coarsened or strided regional fetch would silently
change the features under the existing models.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from marine_ml import config
from marine_ml.sources import copernicus, gebco, obis


# --------------------------------------------------------------------------
# Coarsening
# --------------------------------------------------------------------------


def _global_field(spacing: float, times: int = 3) -> xr.Dataset:
    latitudes = np.arange(-80.0, 90.0, spacing)
    longitudes = np.arange(-180.0, 180.0, spacing)
    shape = (times, latitudes.size, longitudes.size)
    return xr.Dataset(
        {"thetao": (("time", "latitude", "longitude"), np.ones(shape, dtype="float32"))},
        coords={
            "time": pd.date_range("2000-01-01", periods=times, freq="MS"),
            "latitude": latitudes,
            "longitude": longitudes,
        },
    )


def test_coarsening_lands_on_the_requested_spacing() -> None:
    coarse = copernicus._coarsen_to(_global_field(1 / 12), config.GRID_RESOLUTION)
    spacing = float(np.diff(coarse["latitude"].values).mean())
    assert spacing == pytest.approx(config.GRID_RESOLUTION, rel=0.02)


def test_coarsening_a_grid_already_at_resolution_is_a_no_op() -> None:
    """BGC is natively 0.25 degrees, and a global caller passes the same
    arguments to both products rather than tracking which needs it."""
    native = _global_field(config.GRID_RESOLUTION)
    coarse = copernicus._coarsen_to(native, config.GRID_RESOLUTION)
    assert coarse.sizes == native.sizes


def test_coarsening_averages_rather_than_strides() -> None:
    """A block mean, not every Nth cell.

    Striding discards 8 of every 9 cells and its answer depends on which one
    it happened to keep. Here one cell of a 3x3 block carries a spike: the mean
    retains a ninth of it, a stride either returns it whole or loses it
    entirely.
    """
    dataset = _global_field(config.GRID_RESOLUTION / 3, times=1)
    values = dataset["thetao"].values
    values[0, 1, 1] = 10.0  # centre of the first 3x3 block

    coarse = copernicus._coarsen_to(dataset, config.GRID_RESOLUTION)
    first = float(coarse["thetao"].values[0, 0, 0])
    assert first == pytest.approx((8 * 1.0 + 10.0) / 9)


# --------------------------------------------------------------------------
# Cache identity
# --------------------------------------------------------------------------


def test_a_coarsened_cache_file_is_distinct_from_a_native_one() -> None:
    """Same region, same dates, different grids — they must not collide.

    Sharing a path would serve 0.25 degree data to a caller that asked for
    1/12, which is invisible in the returned object.
    """
    args = ("physics", "monthly", config.NORTH_INDIAN_OCEAN, date(2000, 1, 1), date(2000, 12, 31))
    assert copernicus._cache_path(*args) != copernicus._cache_path(*args, 0.25)


def test_year_chunks_cover_the_window_exactly() -> None:
    chunks = copernicus._year_chunks(config.HABITAT_START, config.HABITAT_END)
    assert len(chunks) == 14
    assert chunks[0] == (config.HABITAT_START, date(2000, 12, 31))
    assert chunks[-1] == (date(2013, 1, 1), config.HABITAT_END)
    # No gaps and no overlaps.
    for (_, previous_end), (next_start, _) in zip(chunks, chunks[1:]):
        assert (next_start - previous_end).days == 1


def test_a_partial_year_is_not_padded_out() -> None:
    chunks = copernicus._year_chunks(date(2005, 6, 1), date(2006, 2, 15))
    assert chunks == [
        (date(2005, 6, 1), date(2005, 12, 31)),
        (date(2006, 1, 1), date(2006, 2, 15)),
    ]


# --------------------------------------------------------------------------
# Bathymetry
# --------------------------------------------------------------------------


def test_the_regional_bathymetry_request_is_unchanged() -> None:
    """Stride 1 by default, so existing caches and features still match."""
    assert gebco._stride_for(None) == 1
    assert gebco._cache_path(config.NORTH_INDIAN_OCEAN, 1).name == (
        "bathymetry_north_indian_ocean.nc"
    )


def test_a_global_request_is_thinned_to_the_common_grid() -> None:
    stride = gebco._stride_for(config.GRID_RESOLUTION)
    assert stride == 15  # 0.25 degrees / (1/60)

    cells = (360 / (stride / 60)) * (170 / (stride / 60))
    assert cells < 2_000_000  # against ~233M at native resolution


def test_a_strided_bathymetry_cache_is_distinct() -> None:
    assert gebco._cache_path(config.GLOBAL_OCEAN, 15) != gebco._cache_path(
        config.GLOBAL_OCEAN, 1
    )


# --------------------------------------------------------------------------
# OBIS paging and effort-weighted sampling
# --------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.ok = True
        self.status_code = 200
        self.text = ""

    def json(self) -> dict:
        return self._payload


def test_the_pager_raises_rather_than_truncating(monkeypatch) -> None:
    """The failure this replaces returned a spatially-ordered prefix.

    Pages follow the `after` cursor, so a truncated result is not a random
    subsample — it is the first N by id. For a pool whose whole job is to
    represent where people sampled, that is worse than no pool.
    """
    full_page = {"results": [{"id": str(i)} for i in range(obis._PAGE_SIZE)]}
    monkeypatch.setattr(
        obis.requests, "get", lambda *a, **k: _FakeResponse(full_page)
    )

    with pytest.raises(obis.ObisError, match="truncated"):
        list(obis._paged_request({"taxonid": 10194}))


def test_effort_weighted_sampling_follows_the_effort_surface(monkeypatch) -> None:
    """Cells are chosen with probability proportional to their record count.

    That proportionality is the entire methodological claim of target-group
    background sampling: background points must inherit the survey bias of the
    presences to cancel it. Uniform cell choice would draw as heavily from an
    unsurveyed cell as from a 2.15M-record one.
    """
    # One cell holds 90% of the effort, nine share the rest.
    effort = pd.DataFrame(
        {
            "records": [9000] + [111] * 9,
            "west": np.arange(10.0), "east": np.arange(10.0) + 1,
            "south": np.zeros(10), "north": np.ones(10),
            "longitude": np.arange(10.0) + 0.5, "latitude": np.full(10, 0.5),
        }
    )
    monkeypatch.setattr(obis, "fetch_effort_grid", lambda *a, **k: effort)

    chosen: list[int] = []

    def fake_query(cache_name, params, refresh, max_records=None):
        chosen.append(int(cache_name.rsplit("_c", 1)[1]))
        return pd.DataFrame(
            {
                "latitude": [0.5], "longitude": [0.5],
                "observation_date": [pd.Timestamp("2005-01-01")],
                "dataset_id": ["d"],
            }
        )

    monkeypatch.setattr(obis, "_cached_query", fake_query)

    # Drawing 1 cell repeatedly, the dominant cell should win most of the time.
    hits = 0
    for seed in range(40):
        chosen.clear()
        obis.sample_target_group(config.GLOBAL_OCEAN, n_cells=1, seed=seed)
        hits += chosen[0] == 0
    assert hits > 28  # ~90% expected; a uniform draw would give ~4


def test_sampling_without_replacement_bounds_any_single_cell(monkeypatch) -> None:
    """The largest real cell holds 2.15M of 21.8M records worldwide.

    With replacement it could be drawn repeatedly and dominate the pool
    outright; without, it contributes one quota like any other chosen cell.
    """
    effort = pd.DataFrame(
        {
            "records": [10_000_000] + [1] * 4,
            "west": np.arange(5.0), "east": np.arange(5.0) + 1,
            "south": np.zeros(5), "north": np.ones(5),
            "longitude": np.arange(5.0) + 0.5, "latitude": np.full(5, 0.5),
        }
    )
    monkeypatch.setattr(obis, "fetch_effort_grid", lambda *a, **k: effort)

    seen: list[int] = []

    def fake_query(cache_name, params, refresh, max_records=None):
        seen.append(int(cache_name.rsplit("_c", 1)[1]))
        return pd.DataFrame(
            {
                "latitude": [0.5], "longitude": [0.5],
                "observation_date": [pd.Timestamp("2005-01-01")],
                "dataset_id": ["d"],
            }
        )

    monkeypatch.setattr(obis, "_cached_query", fake_query)
    obis.sample_target_group(config.GLOBAL_OCEAN, n_cells=4, seed=0)

    assert len(seen) == len(set(seen)) == 4


# --------------------------------------------------------------------------
# Per-region artifact naming
# --------------------------------------------------------------------------


def test_the_default_region_keeps_its_historic_artifact_names() -> None:
    """The baseline must not be renamed out from under itself.

    Each problem's existing store, model and reports are the control a new
    region is judged against — the Arabian Sea HAB store is 1.59 GB and the
    regional habitat model is what the global one has to beat. Suffixing the
    default would orphan both.
    """
    from fish_habitat_prediction.src import pipeline as habitat
    from hab_early_warning.src import pipeline as hab

    assert habitat._store_name(config.NORTH_INDIAN_OCEAN) == "fish_habitat_points"
    assert habitat._artifact_name(config.NORTH_INDIAN_OCEAN) == "fish_habitat"
    assert hab._store_name(config.ARABIAN_SEA) == "hab_gridded"
    assert hab._artifact_name(config.ARABIAN_SEA) == "hab_early_warning"


def test_every_other_region_gets_its_own_artifacts() -> None:
    """Otherwise the second region's run silently destroys the first's."""
    from fish_habitat_prediction.src import pipeline as habitat
    from hab_early_warning.src import pipeline as hab

    names = {hab._store_name(region) for region in config.HAB_REGIONS.values()}
    assert len(names) == len(config.HAB_REGIONS)

    assert habitat._store_name(config.GLOBAL_OCEAN) == "fish_habitat_points_global_ocean"
    assert habitat._artifact_name(config.GLOBAL_OCEAN) == "fish_habitat_global_ocean"


# --------------------------------------------------------------------------
# Year-batched sampling
# --------------------------------------------------------------------------


def _synthetic_fields(region: config.Region, months: int = 36):
    """Monthly fields stamped mid-month, as the real products are."""
    from marine_ml import fusion

    latitudes, longitudes = fusion.common_grid(region, config.GRID_RESOLUTION)
    times = pd.date_range("2000-01-15", periods=months, freq="MS") + pd.Timedelta(days=14)
    shape = (times.size, latitudes.size, longitudes.size)
    rng = np.random.default_rng(0)

    physics = xr.Dataset(
        {
            name: (("time", "latitude", "longitude"), rng.normal(size=shape).astype("float32"))
            for name in ("thetao", "so", "uo", "vo", "zos", "mlotst")
        },
        coords={"time": times, "latitude": latitudes, "longitude": longitudes},
    )
    bgc = xr.Dataset(
        {
            name: (("time", "latitude", "longitude"), rng.normal(size=shape).astype("float32"))
            for name in ("chl", "no3", "nppv")
        },
        coords={"time": times, "latitude": latitudes, "longitude": longitudes},
    )
    depth = rng.uniform(10, 4000, size=(latitudes.size, longitudes.size))
    bathymetry = xr.Dataset(
        {
            "depth": (("latitude", "longitude"), depth),
            # As `gebco.fetch_bathymetry` returns it: positive up, so ocean
            # is negative.
            "elevation": (("latitude", "longitude"), -depth),
        },
        coords={"latitude": latitudes, "longitude": longitudes},
    )
    return physics, bgc, bathymetry


def test_year_batched_sampling_matches_the_unbatched_path() -> None:
    """The whole licence for the batched path.

    A memory optimisation that quietly changed feature values would be far
    worse than the OOM it avoids, so this compares the two paths column for
    column on identical inputs. It is the same argument the backend makes for
    `test_grid_matches_the_point_path`.

    Two things would break it and are what the batching handles explicitly:
    points near a year boundary (nearest-in-time selection reaching into the
    adjacent year, hence the pad) and eddy kinetic energy (an anomaly against
    the *record* mean, hence passing it in).
    """
    from marine_ml import fusion

    region = config.ARABIAN_SEA
    physics, bgc, bathymetry = _synthetic_fields(region)

    rng = np.random.default_rng(7)

    # Year-boundary dates are listed explicitly rather than left to the random
    # draw. The products are stamped mid-month, so a 31 December point's
    # nearest timestep is the *next* year's 15 January — that is the exact case
    # `_BATCH_PAD_DAYS` exists for, and 300 uniform draws over three years will
    # almost never land on it. Verified to fail with the pad set to 0.
    boundaries = pd.to_datetime(
        [
            "2000-12-31", "2001-01-01", "2001-12-31", "2002-01-01",
            "2000-12-28", "2001-01-03", "2001-12-25", "2002-01-07",
        ]
    )
    n = 300
    dates = pd.to_datetime("2000-01-01") + pd.to_timedelta(
        rng.integers(0, 365 * 3, n - len(boundaries)), unit="D"
    )
    points = pd.DataFrame(
        {
            "latitude": rng.uniform(region.south, region.north, n),
            "longitude": rng.uniform(region.west, region.east, n),
            "observation_date": dates.append(boundaries),
        }
    )

    plain = fusion.sample_at_points(points, physics, bgc, bathymetry, region=region)
    batched = fusion.sample_at_points(
        points, physics, bgc, bathymetry, region=region, batch_years=True
    )

    assert list(plain.columns) == list(batched.columns)
    assert len(plain) == len(batched) == n
    for column in plain.columns:
        if pd.api.types.is_numeric_dtype(plain[column]):
            np.testing.assert_allclose(
                plain[column].to_numpy(), batched[column].to_numpy(),
                rtol=1e-6, atol=1e-6, err_msg=f"column {column!r} diverged",
            )
        else:
            assert plain[column].equals(batched[column]), column


def test_eddy_kinetic_energy_uses_the_record_mean_when_given_one() -> None:
    """Without this, a one-year batch measures anomalies against its own mean.

    A cell whose flow is steady within each year but differs between years has
    zero EKE per-year and non-zero EKE over the record. That is the silent
    divergence the `flow_mean` argument exists to prevent.
    """
    from marine_ml import fusion

    times = pd.date_range("2000-01-15", periods=4, freq="YS")
    # 3x3 in space: the other derived fields here take spatial gradients, which
    # need a neighbourhood to exist at all.
    steady = np.tile(
        np.array([1.0, 1.0, 3.0, 3.0], dtype="float32").reshape(4, 1, 1), (1, 3, 3)
    )
    dataset = xr.Dataset(
        {
            "uo": (("time", "latitude", "longitude"), steady),
            "vo": (("time", "latitude", "longitude"), np.zeros((4, 3, 3), dtype="float32")),
        },
        coords={
            "time": times,
            "latitude": [10.0, 10.25, 10.5],
            "longitude": [70.0, 70.25, 70.5],
        },
    )

    record_mean = dataset[["uo", "vo"]].mean("time")
    first_half = dataset.isel(time=slice(0, 2))

    # Against its own (constant) mean the first half has no eddy energy at all.
    own = fusion.add_derived_fields(first_half)
    assert float(own["eddy_kinetic_energy"].max()) == pytest.approx(0.0)

    # Against the record mean of 2.0 it correctly has some.
    shared = fusion.add_derived_fields(first_half, flow_mean=record_mean)
    assert float(shared["eddy_kinetic_energy"].max()) == pytest.approx(0.5)
