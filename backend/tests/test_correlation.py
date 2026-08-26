"""services/correlation.py: the alignment + statistics, not the trends fetch
itself (already covered by test_dashboard.py). `trends.multi_series` is
monkeypatched to return controlled per-variable series so each test isolates
one behaviour of the correlation/alignment logic.
"""

from __future__ import annotations

import pytest

from services import correlation


def _daily_points(start_day: int, values: list[float]) -> list[dict]:
    return [{"t": f"2026-01-{start_day + i:02d}", "v": v} for i, v in enumerate(values)]


def _series_payload(points: list[dict]) -> dict:
    return {"points": points}


def _error_payload(message: str) -> dict:
    return {"variable": "x", "error": message, "points": []}


async def test_rejects_fewer_than_two_variables():
    with pytest.raises(correlation.CorrelationError, match="at least"):
        await correlation.analyze(["sea_surface_temperature"], 10.0, 75.0, "1y")


async def test_rejects_more_than_four_variables():
    with pytest.raises(correlation.CorrelationError, match="At most"):
        await correlation.analyze(["a", "b", "c", "d", "e"], 10.0, 75.0, "1y")


async def test_rejects_an_hourly_only_range():
    with pytest.raises(correlation.CorrelationError, match="daily-aggregated"):
        await correlation.analyze(["a", "b"], 10.0, 75.0, "7d")


async def test_a_perfectly_correlated_pair_is_reported_strong_and_positive(monkeypatch):
    n = 20
    values_a = [10.0 + i * 0.5 for i in range(n)]
    values_b = [20.0 + i * 1.0 for i in range(n)]  # a perfect linear function of a

    async def fake_multi_series(variables, latitude, longitude, range_key):
        return {
            "series": {
                "a": _series_payload(_daily_points(1, values_a)),
                "b": _series_payload(_daily_points(1, values_b)),
            }
        }

    monkeypatch.setattr(correlation.trends, "multi_series", fake_multi_series)

    result = await correlation.analyze(["a", "b"], 10.0, 75.0, "1y")

    assert result["variables_unavailable"] == {}
    pair = result["pairs"][0]
    assert pair["available"] is True
    assert pair["correlation_r"] == pytest.approx(1.0, abs=1e-6)
    assert pair["strength"] == "strong"
    assert pair["direction"] == "positive"
    assert pair["overlapping_days"] == n


async def test_an_inversely_correlated_pair_reports_negative_direction(monkeypatch):
    n = 15
    values_a = [float(i) for i in range(n)]
    values_b = [float(n - i) for i in range(n)]

    async def fake_multi_series(variables, latitude, longitude, range_key):
        return {
            "series": {
                "a": _series_payload(_daily_points(1, values_a)),
                "b": _series_payload(_daily_points(1, values_b)),
            }
        }

    monkeypatch.setattr(correlation.trends, "multi_series", fake_multi_series)

    result = await correlation.analyze(["a", "b"], 10.0, 75.0, "1y")

    pair = result["pairs"][0]
    assert pair["correlation_r"] < 0
    assert pair["direction"] == "negative"


async def test_a_fetch_failure_is_reported_inline_not_raised(monkeypatch):
    async def fake_multi_series(variables, latitude, longitude, range_key):
        return {
            "series": {
                "a": _series_payload(_daily_points(1, [1.0, 2.0, 3.0])),
                "b": _error_payload("upstream unavailable"),
            }
        }

    monkeypatch.setattr(correlation.trends, "multi_series", fake_multi_series)

    result = await correlation.analyze(["a", "b"], 10.0, 75.0, "1y")

    assert result["variables_unavailable"] == {"b": "upstream unavailable"}
    assert result["pairs"] == []  # only one usable variable, no pair to form


async def test_too_little_overlap_is_reported_unavailable_not_raised(monkeypatch):
    async def fake_multi_series(variables, latitude, longitude, range_key):
        return {
            "series": {
                # Only 3 shared days — below MIN_OVERLAPPING_DAYS.
                "a": _series_payload(_daily_points(1, [1.0, 2.0, 3.0])),
                "b": _series_payload(_daily_points(1, [4.0, 5.0, 6.0])),
            }
        }

    monkeypatch.setattr(correlation.trends, "multi_series", fake_multi_series)

    result = await correlation.analyze(["a", "b"], 10.0, 75.0, "1y")

    pair = result["pairs"][0]
    assert pair["available"] is False
    assert "overlapping days" in pair["reason"]


async def test_a_constant_series_is_reported_unavailable_not_nan(monkeypatch):
    n = 12
    constant = [5.0] * n
    varying = [float(i) for i in range(n)]

    async def fake_multi_series(variables, latitude, longitude, range_key):
        return {
            "series": {
                "a": _series_payload(_daily_points(1, constant)),
                "b": _series_payload(_daily_points(1, varying)),
            }
        }

    monkeypatch.setattr(correlation.trends, "multi_series", fake_multi_series)

    result = await correlation.analyze(["a", "b"], 10.0, 75.0, "1y")

    pair = result["pairs"][0]
    assert pair["available"] is False
    assert "did not vary" in pair["reason"]


async def test_multiple_hourly_points_on_the_same_day_are_averaged(monkeypatch):
    """Two same-day readings for one variable and one for the other must
    collapse to a single daily mean before correlating — the alignment step
    this module exists for."""
    async def fake_multi_series(variables, latitude, longitude, range_key):
        return {
            "series": {
                "a": _series_payload(
                    [
                        {"t": "2026-01-01T00:00", "v": 10.0},
                        {"t": "2026-01-01T12:00", "v": 20.0},  # day-1 mean: 15.0
                        *_daily_points(2, [float(i) for i in range(2, 15)]),
                    ]
                ),
                "b": _series_payload(_daily_points(1, [float(i) for i in range(15)])),
            }
        }

    monkeypatch.setattr(correlation.trends, "multi_series", fake_multi_series)

    result = await correlation.analyze(["a", "b"], 10.0, 75.0, "1y")

    pair = result["pairs"][0]
    assert pair["available"] is True
    assert pair["overlapping_days"] == 14


async def test_the_disclaimer_never_implies_causation(monkeypatch):
    async def fake_multi_series(variables, latitude, longitude, range_key):
        return {
            "series": {
                "a": _series_payload(_daily_points(1, [float(i) for i in range(12)])),
                "b": _series_payload(_daily_points(1, [float(i) for i in range(12)])),
            }
        }

    monkeypatch.setattr(correlation.trends, "multi_series", fake_multi_series)

    result = await correlation.analyze(["a", "b"], 10.0, 75.0, "1y")

    assert "not evidence that one caused the other" in result["note"]
    assert "causes" not in result["note"].lower()  # only the negated form is allowed


async def test_deduplicates_a_repeated_variable(monkeypatch):
    async def fake_multi_series(variables, latitude, longitude, range_key):
        assert variables == ["a", "b"]  # deduped before the fetch
        return {
            "series": {
                "a": _series_payload(_daily_points(1, [float(i) for i in range(12)])),
                "b": _series_payload(_daily_points(1, [float(i) for i in range(12)])),
            }
        }

    monkeypatch.setattr(correlation.trends, "multi_series", fake_multi_series)

    result = await correlation.analyze(["a", "b", "a"], 10.0, 75.0, "1y")

    assert result["variables_requested"] == ["a", "b"]
