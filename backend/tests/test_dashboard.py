"""Tests for the dashboard services.

Focused on the pure logic that was got wrong at least once while building it:
the NDBC fixed-width parse, the CRW masking that decides which cells count,
and the coverage gate that stops a chart requesting a range its product cannot
serve. Nothing here touches the network — the grids are synthetic.
"""

from datetime import datetime, timedelta, timezone

import httpx
import numpy as np
import pytest

from services import crw, ndbc
from services.dashboard import copernicus_series, health, history, trends
from services.dashboard.formatting import describe_location

# --------------------------------------------------------------------------
# NDBC parsing
# --------------------------------------------------------------------------

# Two real rows from the feed plus a deliberately malformed one. Column order
# is STN LAT LON YYYY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES PTDY
# ATMP WTMP DEWP VIS TIDE.
_FEED = """#STN       LAT      LON  YYYY MM DD hh mm WDIR WSPD   GST WVHT  DPD APD MWD   PRES  PTDY  ATMP  WTMP  DEWP  VIS   TIDE
#text      deg      deg   yr mo day hr mn degT  m/s   m/s   m   sec sec degT   hPa   hPa  degC  degC  degC  nmi     ft
14049   -12.000   65.000 2026 08 04 01 00 124  11.1  14.3   MM  MM   MM  MM 1015.5    MM  20.2  26.4    MM   MM     MM
41001    34.700  -72.200 2026 08 04 02 30 139   7.9   9.4  1.8  8   6.2 150 1017.1    MM  23.6  24.8  21.4   MM     MM
BADROW   1.0
"""


def test_parses_every_well_formed_row_and_skips_malformed():
    observations = ndbc.parse_latest_obs(_FEED)
    assert [o.station_id for o in observations] == ["14049", "41001"]


def test_missing_values_become_none_not_zero():
    """`MM` is "no reading". Turning it into 0.0 would invent a calm sea."""
    first = ndbc.parse_latest_obs(_FEED)[0]
    assert first.wave_height_m is None
    assert first.dewpoint_c is None
    assert first.water_temperature_c == 26.4
    assert first.wind_speed_ms == 11.1


def test_alphanumeric_station_ids_are_kept():
    feed = _FEED.replace("41001 ", "AAMC1")
    assert any(o.station_id == "AAMC1" for o in ndbc.parse_latest_obs(feed))


def test_relative_humidity_is_derived_only_when_both_inputs_exist():
    observations = ndbc.parse_latest_obs(_FEED)
    # No dewpoint reported -> no humidity, rather than a bogus 100%.
    assert observations[0].relative_humidity_pct is None
    # 23.6C air / 21.4C dewpoint is a humid but sub-saturated marine airmass.
    humidity = observations[1].relative_humidity_pct
    assert humidity is not None
    assert 85 < humidity < 95


def test_observation_timestamps_are_utc_aware():
    first = ndbc.parse_latest_obs(_FEED)[0]
    assert first.observed_at == datetime(2026, 8, 4, 1, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# NDBC station detail and raw feed — the click-through target's backend half
# --------------------------------------------------------------------------


def _install_ndbc_cache(monkeypatch):
    observations = ndbc.parse_latest_obs(_FEED)
    cache = ndbc._NdbcCache(
        observations=observations, fetched_at=datetime.now(timezone.utc), latency_ms=12.0
    )
    monkeypatch.setattr(ndbc, "_cache", cache)
    return cache


def test_station_looks_up_by_id_case_insensitively(monkeypatch):
    _install_ndbc_cache(monkeypatch)
    result = ndbc.station("41001")
    assert result["station_id"] == "41001"
    assert result["water_temperature_c"] == 24.8
    assert ndbc.station("41001") == result


def test_station_raises_for_an_unknown_id(monkeypatch):
    _install_ndbc_cache(monkeypatch)
    with pytest.raises(ndbc.NdbcError):
        ndbc.station("99999")


@pytest.mark.asyncio
async def test_raw_feed_returns_the_fetched_lines_as_provenance(monkeypatch):
    monkeypatch.setattr(ndbc, "_fetch_raw_feed", lambda url: "header line\nrow1\nrow2\n")
    result = await ndbc.raw_feed("41001")
    assert result["lines"] == ["header line", "row1", "row2"]
    assert result["total_lines"] == 3
    assert "41001" in result["url"]


@pytest.mark.asyncio
async def test_raw_feed_wraps_a_fetch_failure_rather_than_raising_raw(monkeypatch):
    def _boom(url):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(ndbc, "_fetch_raw_feed", _boom)
    with pytest.raises(ndbc.NdbcError) as excinfo:
        await ndbc.raw_feed("41001")
    # Never a raw exception repr leaked to whoever renders this — a
    # RetryError/Future repr was exactly what a live click-through surfaced
    # before this test existed.
    assert "RetryError" not in str(excinfo.value)
    assert "Future" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_raw_feed_reports_a_missing_file_plainly_and_does_not_retry(monkeypatch):
    """Not every station in `latest_obs.txt` is NDBC's own; a partner-network
    relay station legitimately has no `realtime2` file. That is routine, not
    a transient failure — exercised through the real decorated
    `_fetch_raw_feed` (not a monkeypatched stand-in) so the retry policy
    itself is under test, not just the error message: retrying it would
    waste three round trips for the same 404."""
    calls = 0

    class _FakeResponse:
        status_code = 404

    def fake_get(self, url, **kwargs):
        nonlocal calls
        calls += 1
        return _FakeResponse()

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    with pytest.raises(ndbc.NdbcError, match="does not publish a live feed"):
        await ndbc.raw_feed("41001")
    assert calls == 1


# --------------------------------------------------------------------------
# Coral Reef Watch masking
# --------------------------------------------------------------------------


def _synthetic_cache(**overrides):
    """A 1-degree global grid with everything finite and unremarkable."""
    latitudes = np.arange(-89.5, 90.5, 1.0)
    longitudes = np.arange(-179.5, 180.5, 1.0)
    shape = (latitudes.size, longitudes.size)

    fields = {
        "latitudes": latitudes,
        "longitudes": longitudes,
        "dhw": np.zeros(shape),
        "anomaly": np.zeros(shape),
        "hotspot": np.zeros(shape),
        "baa": np.zeros(shape),
        "seaice": np.full(shape, np.nan),
        "timestamp": datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
        "fetched_at": datetime(2026, 8, 4, tzinfo=timezone.utc),
        "latency_ms": 1.0,
    }
    fields.update(overrides)
    return crw._CrwCache(**fields)


@pytest.fixture
def crw_cache(monkeypatch):
    def install(cache):
        monkeypatch.setattr(crw, "_cache", cache)
        return cache

    return install


def test_polar_cells_are_excluded_from_aggregates(crw_cache):
    """The bug this guards: Arctic ice-margin cells carry anomalies above
    +15C because the climatology there expects ice, and including them roughly
    tripled the reported global mean."""
    anomaly = np.zeros((180, 360))
    anomaly[170:, :] = 12.0  # far northern rows
    crw_cache(_synthetic_cache(anomaly=anomaly))

    assert crw.sst_anomaly_summary()["mean_anomaly_c"] == 0.0


def test_out_of_range_cells_are_masked_at_parse_time():
    """NOAA publishes valid_min/valid_max; the live grid does violate them."""
    frame_text = (
        "time,latitude,longitude,CRW_DHW,CRW_SSTANOMALY,CRW_HOTSPOT,CRW_BAA,CRW_SEAICE\n"
        "UTC,degrees_north,degrees_east,Celsius weeks,Celsius,Celsius,1,1\n"
        "2026-08-02T12:00:00Z,10.0,20.0,1.0,17.44,2.0,1,NaN\n"
        "2026-08-02T12:00:00Z,10.0,21.0,1.0,2.0,2.0,1,NaN\n"
    )
    cache = crw._parse(frame_text, latency_ms=1.0)
    # 17.44 exceeds the +/-15C valid range and must not survive.
    assert np.isnan(cache.anomaly[0, 0])
    assert cache.anomaly[0, 1] == 2.0


def test_bleaching_uses_reef_latitudes_only(crw_cache):
    """DHW is computed on every water pixel including the Caspian and the
    Baltic, where 40+ C-weeks is meaningless and nowhere near a coral.

    Row 135 is ~45.5N: inside the 60-degree analysis band, so only the
    tighter reef mask can exclude it. Picking a polar row instead would let
    this pass on the analysis band alone and test nothing.
    """
    dhw = np.zeros((180, 360))
    dhw[135, 200] = 52.0
    cache = _synthetic_cache(dhw=dhw)
    assert abs(cache.latitudes[135]) > crw.CORAL_LAT_LIMIT
    assert abs(cache.latitudes[135]) < crw.ANALYSIS_LAT_LIMIT
    crw_cache(cache)

    assert crw.bleaching_summary()["max_dhw_c_weeks"] == 0.0


def test_heat_stress_regions_merge_across_the_antimeridian(crw_cache):
    """A patch straddling 180deg is one region, not two."""
    hotspot = np.zeros((180, 360))
    # A block touching both the first and last longitude columns.
    hotspot[90:95, :3] = 2.0
    hotspot[90:95, -3:] = 2.0
    crw_cache(_synthetic_cache(hotspot=hotspot))

    assert crw.marine_heatwave_summary()["region_count"] == 1


def test_speckle_below_the_minimum_size_is_not_a_region(crw_cache):
    hotspot = np.zeros((180, 360))
    hotspot[90, 180] = 5.0  # a single cell
    crw_cache(_synthetic_cache(hotspot=hotspot))

    assert crw.marine_heatwave_summary()["region_count"] == 0


def test_hotspots_are_declustered(crw_cache):
    """Adjacent cells of one warm pool are one alert, not six."""
    dhw = np.zeros((180, 360))
    dhw[90:93, 180:186] = 20.0  # one contiguous patch at the equator
    crw_cache(_synthetic_cache(dhw=dhw))

    assert len(crw.hotspots(limit=6)) == 1


# --------------------------------------------------------------------------
# KPI history
# --------------------------------------------------------------------------


def test_history_throttles_repeat_samples():
    history.reset()
    now = datetime.now(timezone.utc)
    history.record("k", 1.0, now=now)
    history.record("k", 2.0, now=now + timedelta(minutes=1))
    assert len(history.series("k")) == 1

    history.record("k", 3.0, now=now + history.MIN_SAMPLE_INTERVAL)
    assert len(history.series("k")) == 2


def test_history_reports_no_trend_from_a_single_point():
    """One reading is a value, not a trend; claiming 0% change would be a
    statement the data cannot support."""
    history.reset()
    history.record("k", 5.0)
    assert history.trend("k") is None


def test_history_ignores_non_numeric_values():
    history.reset()
    history.record("k", None)
    assert history.series("k") == []


def test_history_is_bounded():
    history.reset()
    start = datetime.now(timezone.utc)
    for index in range(history.MAX_POINTS + 25):
        history.record("k", float(index), now=start + index * history.MIN_SAMPLE_INTERVAL)
    assert len(history.series("k")) == history.MAX_POINTS


# --------------------------------------------------------------------------
# Data source detail — the click-through target's backend half
# --------------------------------------------------------------------------


def test_source_detail_reports_healthy_and_records_history(monkeypatch):
    """Exercises the real `noaa_ndbc` provider's probe closure end to end —
    it was bound to `ndbc.is_available`/`ndbc.health` at import time, so this
    has to drive it through `ndbc._cache` rather than monkeypatching those
    names directly, which the closure would no longer be looking at."""
    history.reset()
    _install_ndbc_cache(monkeypatch)

    result = health.detail("noaa_ndbc")

    assert result["key"] == "noaa_ndbc"
    assert result["connected"] is True
    assert result["health"] == "healthy"
    assert result["explanation"]
    assert len(result["recent_health"]) == 1
    assert result["recent_health"][0]["v"] == 1.0


def test_source_detail_reports_down_when_the_cache_is_empty(monkeypatch):
    history.reset()
    monkeypatch.setattr(ndbc, "_cache", None)

    result = health.detail("noaa_ndbc")

    assert result["connected"] is False
    assert result["health"] == "down"
    assert "no cache" in result["explanation"].lower()


def test_source_detail_raises_for_an_unregistered_key():
    with pytest.raises(health.HealthError):
        health.detail("not_a_real_provider")


# --------------------------------------------------------------------------
# Trend coverage gating
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_range_beyond_a_products_coverage_is_refused():
    """SST only reaches back to 2024, so a 10-year request must fail loudly
    rather than return a silently truncated series."""
    with pytest.raises(trends.TrendsError, match="only goes back to"):
        await trends.series("sea_surface_temperature", 15, 65, "10y")


@pytest.mark.asyncio
async def test_unknown_variable_is_refused():
    with pytest.raises(trends.TrendsError, match="Unknown variable"):
        await trends.series("unobtainium", 15, 65, "7d")


@pytest.mark.asyncio
async def test_daily_copernicus_products_refuse_the_hourly_range():
    """Chlorophyll, salinity and OHC are daily means. A 24-hour window would
    plot a single point, so it is refused rather than served as a "chart"."""
    for variable in ("chlorophyll_a", "sea_surface_salinity", "ocean_heat_content"):
        with pytest.raises(trends.TrendsError, match="daily product"):
            await trends.series(variable, 15, 65, "24h")


def test_catalog_only_offers_ranges_within_coverage():
    entries = {entry["key"]: entry for entry in trends.catalog()}

    # ERA5 reaches 1940, so every range is offered.
    assert "10y" in entries["wind_speed_10m"]["supported_ranges"]
    # The marine model's SST does not.
    assert "10y" not in entries["sea_surface_temperature"]["supported_ranges"]
    assert "7d" in entries["sea_surface_temperature"]["supported_ranges"]


def test_copernicus_backed_variables_are_chartable():
    """These three were briefly declared impossible; measuring showed a point
    series costs 8-13s, so they are served rather than refused."""
    entries = {entry["key"]: entry for entry in trends.catalog()}

    for key in ("chlorophyll_a", "sea_surface_salinity", "ocean_heat_content"):
        assert entries[key]["available"], f"{key} should be chartable"
        assert entries[key]["unavailable_reason"] is None
        # Daily products: the hourly ranges are withheld, longer ones offered.
        assert "24h" not in entries[key]["supported_ranges"]
        assert "1y" in entries[key]["supported_ranges"]


def test_ocean_heat_content_integral_matches_a_hand_calculation():
    """OHC = rho * cp * integral(T dz). A 700 m column at a uniform 15 C is
    1025 * 3985 * 15 * 700 = 42.9 GJ/m^2; the integral must land there."""
    depths = np.linspace(0.0, 700.0, 40)
    profile = np.full_like(depths, 15.0)

    result = copernicus_series._integrate_heat_content(profile, depths)
    assert result is not None
    assert abs(result - 42.88) < 0.1


def test_ocean_heat_content_needs_more_than_one_valid_level():
    """Below the seafloor the model is NaN; a column with one usable level
    cannot be integrated and must report nothing rather than a bogus zero."""
    depths = np.array([0.5, 10.0, 50.0])
    profile = np.array([20.0, np.nan, np.nan])

    assert copernicus_series._integrate_heat_content(profile, depths) is None


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("latitude", "longitude", "expected"),
    [
        # Negative zero is the case that reads as a bug: a region centred at
        # -0.03 must not render as "-0.0".
        (-0.03, -149.97, "0.0°N, 150.0°W"),
        (1.0, 143.0, "1.0°N, 143.0°E"),
        (-38.87, -2.5, "38.9°S, 2.5°W"),
        (0.0, 0.0, "0.0°N, 0.0°E"),
    ],
)
def test_location_labels(latitude, longitude, expected):
    assert describe_location(latitude, longitude) == expected


# --------------------------------------------------------------------------
# Router: the two "click for detail" endpoints
# --------------------------------------------------------------------------


def test_the_station_and_source_endpoints_serve_detail(monkeypatch):
    """Thin-router check, same shape as `test_data_quality.py`'s: 200 with
    the full payload on the happy path, 404 (not a 500) on an unknown id."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import dashboard as dashboard_router

    _install_ndbc_cache(monkeypatch)
    # No real network call: a router test staying off the network is this
    # file's own stated rule (see its module docstring).
    monkeypatch.setattr(ndbc, "_fetch_raw_feed", lambda url: "header\nrow1\n")

    app = FastAPI()
    app.include_router(dashboard_router.router)
    client = TestClient(app)

    response = client.get("/api/dashboard/stations/41001")
    assert response.status_code == 200
    payload = response.json()
    assert payload["station"]["station_id"] == "41001"
    assert payload["raw_feed"]["lines"] == ["header", "row1"]
    assert payload["raw_feed_error"] is None

    missing_station = client.get("/api/dashboard/stations/00000")
    assert missing_station.status_code == 404

    source = client.get("/api/dashboard/sources/noaa_ndbc")
    assert source.status_code == 200
    assert source.json()["key"] == "noaa_ndbc"

    missing_source = client.get("/api/dashboard/sources/not_a_real_provider")
    assert missing_source.status_code == 404
