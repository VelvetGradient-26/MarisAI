"""Tests for the metric intelligence services.

No network — every test builds a synthetic series, so a failure means a code
defect rather than a provider outage.

The two that matter most are the decimation envelope test and the story
verifier tests. Both protect against the same class of failure: a number
reaching the user that the data does not support. Decimation can silently erase
a marine heatwave from a ten-year chart; the story generator can silently
invent one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from forecasting.history import HistoryError, ProviderUnavailableError
from forecasting.preprocessing import TIMESTAMP
from forecasting.registry import UnknownVariableError
from routers.metrics import _raise_for
from services.metrics import MetricsError
from services.metrics.series import RANGES, _resolve_window, decimate
from services.metrics.statistics import compute
from services.metrics.story import StoryFacts, _verify, render_template


@pytest.fixture
def series() -> pd.DataFrame:
    """Two years of daily values with a seasonal cycle."""
    n = 730
    index = np.arange(n)
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            TIMESTAMP: pd.date_range("2024-08-04", periods=n, freq="D"),
            "sea_surface_temperature": 28.0
            + 2.5 * np.sin(2 * np.pi * index / 365.25)
            + rng.normal(0, 0.2, n),
        }
    )


# --------------------------------------------------------------------------
# Decimation
# --------------------------------------------------------------------------


def test_decimation_preserves_the_extremes():
    """Stride sampling erases spikes; the min/max envelope must not.

    This is the test that justifies the implementation. A three-day marine
    heatwave inside a ten-year series is exactly the event a user opens the
    chart to find, and exactly what every Nth point would drop.
    """
    n = 50_000
    frame = pd.DataFrame(
        {
            TIMESTAMP: pd.date_range("2020-01-01", periods=n, freq="h"),
            "v": np.sin(np.arange(n) / 500) * 2 + 20,
        }
    )
    frame.loc[31_337, "v"] = 99.0
    frame.loc[12_345, "v"] = -5.0

    reduced = decimate(frame, "v", 2000)

    assert len(reduced) <= 2000
    assert reduced["v"].max() == 99.0
    assert reduced["v"].min() == -5.0

    # The naive alternative loses both, which is why this is not that.
    stride = frame.iloc[:: len(frame) // 2000]
    assert stride["v"].max() < 99.0
    assert stride["v"].min() > -5.0


def test_decimation_keeps_timestamps_increasing():
    """uPlot renders nothing at all given an x series that jumps backwards."""
    n = 10_000
    frame = pd.DataFrame(
        {
            TIMESTAMP: pd.date_range("2020-01-01", periods=n, freq="h"),
            "v": np.random.default_rng(1).normal(20, 3, n),
        }
    )
    reduced = decimate(frame, "v", 500)
    assert reduced[TIMESTAMP].is_monotonic_increasing


def test_decimation_is_a_no_op_below_the_threshold(series):
    assert decimate(series, "sea_surface_temperature", 4000) is series


def test_an_all_nan_bucket_still_contributes_a_point():
    """A genuine outage must stay visible as a gap, not close up."""
    n = 4000
    frame = pd.DataFrame(
        {
            TIMESTAMP: pd.date_range("2020-01-01", periods=n, freq="h"),
            "v": np.linspace(0, 100, n),
        }
    )
    frame.loc[1000:1800, "v"] = np.nan
    reduced = decimate(frame, "v", 200)
    assert reduced["v"].isna().any(), "the outage must survive decimation"


# --------------------------------------------------------------------------
# Ranges
# --------------------------------------------------------------------------


def test_named_ranges_resolve_to_days():
    assert _resolve_window("30d", None) == 30
    assert _resolve_window("1y", None) == 365
    assert _resolve_window(None, None) == RANGES["1y"]


def test_explicit_days_wins_over_a_named_range():
    assert _resolve_window("30d", 90) == 90


def test_an_unknown_range_names_the_valid_ones():
    with pytest.raises(MetricsError, match="Expected one of"):
        _resolve_window("forever", None)


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------


def test_statistics_match_hand_computed_values():
    frame = pd.DataFrame(
        {
            TIMESTAMP: pd.date_range("2025-01-01", periods=5, freq="D"),
            "v": [10.0, 20.0, 30.0, 40.0, 50.0],
        }
    )
    stats = {item.key: item for item in compute(frame, "v", "degC")}

    assert stats["current"].value == 50.0
    assert stats["mean"].value == 30.0
    assert stats["median"].value == 30.0
    assert stats["min"].value == 10.0
    assert stats["max"].value == 50.0
    # Sample standard deviation (ddof=1) of 10..50 is 15.81, not 14.14.
    assert stats["std"].value == pytest.approx(15.8114, abs=1e-3)
    assert stats["percentile"].value == 100.0


def test_a_change_that_the_record_cannot_support_says_so(series):
    """The rule the whole module exists for: absent, not zero."""
    stats = {item.key: item for item in compute(series, "sea_surface_temperature", "degC")}

    thirty = stats["change_30d"]
    assert thirty.available and thirty.value is not None

    # The two-year fixture can answer a 365-day question, so the negative case
    # needs a deliberately short record — 40 days, as a young product would be.
    short = series.iloc[:40]
    short_stats = {item.key: item for item in compute(short, "sea_surface_temperature", "degC")}
    annual = short_stats["change_365d"]
    assert not annual.available
    assert annual.value is None
    assert "365" in (annual.unavailable_reason or "")
    assert "begins" in (annual.unavailable_reason or "")


def test_change_is_measured_against_a_date_not_a_row_offset():
    """With gaps, positional lookback silently measures the wrong window."""
    stamps = list(pd.date_range("2025-01-01", periods=10, freq="D")) + [
        pd.Timestamp("2025-03-01")
    ]
    frame = pd.DataFrame({TIMESTAMP: stamps, "v": [1.0] * 10 + [5.0]})

    stats = {item.key: item for item in compute(frame, "v", "u")}
    change = stats["change_30d"]
    # 30 days before 1 March is 30 January; the nearest earlier observation is
    # 10 January at 1.0, so the change is +4, not the +0 a 30-row offset gives.
    assert change.available
    assert change.value == pytest.approx(4.0)


def test_distribution_statistics_are_withheld_on_a_small_sample():
    frame = pd.DataFrame(
        {
            TIMESTAMP: pd.date_range("2025-01-01", periods=12, freq="D"),
            "v": np.linspace(1, 12, 12),
        }
    )
    stats = {item.key: item for item in compute(frame, "v", "u")}
    assert not stats["skewness"].available
    assert not stats["kurtosis"].available
    assert "noise" in (stats["skewness"].unavailable_reason or "")


def test_an_empty_record_is_an_error_not_a_row_of_zeroes():
    frame = pd.DataFrame(
        {
            TIMESTAMP: pd.date_range("2025-01-01", periods=5, freq="D"),
            "v": [np.nan] * 5,
        }
    )
    with pytest.raises(MetricsError, match="no usable observations"):
        compute(frame, "v", "u")


# --------------------------------------------------------------------------
# Ocean Story — the anti-hallucination contract
# --------------------------------------------------------------------------


@pytest.fixture
def facts() -> StoryFacts:
    return StoryFacts(
        label="Sea Surface Temperature",
        unit="degC",
        current=27.75,
        mean=27.87,
        minimum=25.47,
        maximum=31.36,
        percentile=54.0,
        trend_word="falling",
        trend_days=30,
        change_recent=-0.90,
        change_365d=1.20,
        observation_count=366,
        start="2025-08-04",
        end="2026-08-04",
        forecast={
            "horizon": 7, "value": 27.75, "lower": 26.41,
            "upper": 29.14, "delta": -0.03, "drivers": ["Air Temperature"],
        },
        drivers=["Air Temperature"],
    )


def test_a_faithful_narrative_passes_verification(facts):
    text = (
        "Sea Surface Temperature is 27.75 degC, just below the 27.87 degC average "
        "of 366 observations. It sits at the 54th percentile of a record running "
        "from 2025-08-04 to 2026-08-04, which ranged 25.47 to 31.36 degC. It has "
        "fallen 0.90 degC over 30 days but risen 1.20 degC over 365 days."
    )
    assert _verify(text, facts) == (True, None)


def test_a_fabricated_number_is_caught(facts):
    """The failure this whole design exists to prevent."""
    text = "Sea Surface Temperature is 27.75 degC, a full 3.42 degC above average."
    ok, offender = _verify(text, facts)
    assert not ok
    assert offender == "3.42"


def test_window_sizes_quoted_from_the_facts_block_are_allowed(facts):
    """Regression: the first verifier rejected '365 days'.

    Its permitted set was built from a hand-listed set of *values* and missed
    the window sizes appearing in the block's own labels, so a sentence that
    faithfully quoted the facts was thrown away. The permitted set is now
    derived from the block itself.
    """
    assert "365" in facts.as_block()
    ok, offender = _verify("Over 365 days it rose 1.20 degC.", facts)
    assert ok, f"rejected {offender!r}, which appears in the facts block"


def test_the_template_renders_every_fact_without_an_llm(facts):
    text = render_template(facts)
    for figure in ("27.75", "27.87", "25.47", "31.36", "0.90", "1.20", "26.41", "29.14"):
        assert figure in text, f"template omitted {figure}"
    # And it must satisfy its own verifier, or the fallback would be rejected.
    assert _verify(text, facts) == (True, None)


def test_the_template_handles_a_missing_forecast(facts):
    facts.forecast = None
    facts.drivers = []
    text = render_template(facts)
    assert "forecast" not in text.lower()
    assert "27.75" in text


# --------------------------------------------------------------------------
# Error mapping
# --------------------------------------------------------------------------


def test_a_provider_outage_is_503_with_retry_after():
    with pytest.raises(HTTPException) as caught:
        _raise_for(ProviderUnavailableError("Copernicus timed out"))
    assert caught.value.status_code == 503
    assert caught.value.headers.get("Retry-After")


def test_missing_data_is_404():
    with pytest.raises(HTTPException) as caught:
        _raise_for(HistoryError("point is over land"))
    assert caught.value.status_code == 404


def test_an_unknown_variable_is_404():
    with pytest.raises(HTTPException) as caught:
        _raise_for(UnknownVariableError("no such variable"))
    assert caught.value.status_code == 404
