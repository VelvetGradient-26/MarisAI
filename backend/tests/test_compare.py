"""Comparing two coordinates.

The whole output of this feature is a difference, so the failures worth pinning
are the ones that produce a *plausible* difference: a thousands separator eaten
by the number parser, a subtraction across mismatched units, and a row dropped
because only one point had it.
"""

from __future__ import annotations

import asyncio

import pytest

from services import compare


def _section(key, title, rows, available=True, note=None, reason=None):
    payload = {"key": key, "title": title, "available": available, "rows": rows}
    if note:
        payload["note"] = note
    if reason:
        payload["unavailable_reason"] = reason
    return payload


def test_a_thousands_separator_does_not_become_a_hundredfold_error():
    """"1,204 m" must parse as 1204, not as 1.

    Exactly the failure `agent._ungrounded_numbers` already records: a grouped
    number read as its first group. Here it would report a 1,200 m depth
    difference as 1 m, in the units the reader expects, with nothing raised.
    """
    assert compare._parse_quantity("1,204 m") == (1204.0, "m")
    assert compare._parse_quantity("28.4 °C") == (28.4, "°C")
    assert compare._parse_quantity("-3.5 m") == (-3.5, "m")


def test_a_sentinel_is_never_read_as_a_measurement():
    # Brief rows use these exact strings when a field has no data.
    assert compare._parse_quantity("unavailable") == (None, "")
    assert compare._parse_quantity("no data (land or outside coverage)") == (None, "")
    assert compare._parse_quantity(None) == (None, "")


def test_no_delta_is_computed_across_different_units():
    """A subtraction across mismatched units is the one output here that would
    be confidently wrong, so it is refused rather than approximated."""
    assert compare._delta("10 m", "12 m")["value"] == pytest.approx(2.0)
    assert compare._delta("10 m", "12 ft") is None
    assert compare._delta("10 m", "unavailable") is None


def test_deltas_run_b_minus_a():
    delta = compare._delta("20 °C", "23 °C")
    assert delta["value"] == pytest.approx(3.0)
    assert delta["unit"] == "°C"
    assert delta["percent"] == pytest.approx(15.0)


def test_a_row_only_one_point_has_is_kept_and_labelled():
    """The asymmetry is often the most informative part of the comparison —
    "suitability 0.71 here, outside the model's region there" is a real answer,
    and dropping it would report two points as more alike than they are."""
    a = _section("habitat", "Fish habitat", [{"label": "Yellowfin Tuna", "value": "0.71"}])
    b = _section("habitat", "Fish habitat", [], available=False, reason="outside the region")

    result = compare._compare_section(a, b)

    assert result["available"] is True
    assert result["a_available"] is True and result["b_available"] is False
    assert result["b_unavailable_reason"] == "outside the region"
    assert result["rows"][0]["only_at"] == "a"
    assert result["rows"][0]["b"] is None
    assert result["rows"][0]["delta"] is None


def test_the_section_note_travels_so_disclaimers_are_not_stripped():
    note = "MODEL OUTPUT. Relative habitat suitability on 0-1."
    a = _section("habitat", "Fish habitat", [], note=note)
    b = _section("habitat", "Fish habitat", [])
    assert compare._compare_section(a, b)["note"] == note


def test_forecast_rows_compare_per_horizon_without_parsing_text():
    a = _section(
        "forecast",
        "Forecast",
        [{"label": "Sea Surface Temperature", "unit": "°C", "last_observed": 28.0,
          "h1": 28.2, "h3": 28.5, "h7": 29.0}],
    )
    b = _section(
        "forecast",
        "Forecast",
        [{"label": "Sea Surface Temperature", "unit": "°C", "last_observed": 26.0,
          "h1": 26.1, "h3": None, "h7": 26.4}],
    )

    row = compare._compare_section(a, b)["rows"][0]

    assert row["unit"] == "°C"
    assert row["horizons"]["h1"]["delta"] == pytest.approx(-2.1)
    # A horizon one side is missing is reported, not silently zeroed.
    assert row["horizons"]["h3"]["delta"] is None
    assert row["horizons"]["h3"]["b"] is None


def test_the_coordinates_themselves_get_no_delta():
    """"Latitude +3.0°, +30.3%" parses perfectly and means nothing.

    It restates the user's own input as a finding, and a percent change in a
    coordinate is not a quantity. The separation a reader wants is a distance,
    which is a different row this does not claim to provide.
    """
    a = _section("location", "Location", [
        {"label": "Latitude", "value": "9.9000°"},
        {"label": "Seafloor depth", "value": "1,204 m"},
    ])
    b = _section("location", "Location", [
        {"label": "Latitude", "value": "12.9000°"},
        {"label": "Seafloor depth", "value": "42 m"},
    ])

    rows = {row["label"]: row for row in compare._compare_section(a, b)["rows"]}

    assert rows["Latitude"]["delta"] is None
    assert rows["Latitude"]["a"] == "9.9000°"
    # A real measurement in the same section still gets one.
    assert rows["Seafloor depth"]["delta"]["value"] == pytest.approx(-1162.0)


def test_compare_points_aligns_two_briefs(monkeypatch):
    briefs = {
        (1.0, 2.0): {
            "generated_at": "2026-08-14T00:00:00+00:00",
            "sections": [
                _section("location", "Location", [{"label": "Seafloor depth", "value": "1,204 m"}]),
                _section("conditions", "Observed", [{"label": "SST", "value": "28.4 °C"}]),
            ],
        },
        (3.0, 4.0): {
            "generated_at": "2026-08-14T00:00:00+00:00",
            "sections": [
                _section("location", "Location", [{"label": "Seafloor depth", "value": "42 m"}]),
                _section("conditions", "Observed", [{"label": "SST", "value": "26.9 °C"}]),
            ],
        },
    }

    async def fake_brief(lat, lon):
        return briefs[(lat, lon)]

    monkeypatch.setattr(compare, "build_brief", fake_brief)

    result = asyncio.run(compare.compare_points(1.0, 2.0, 3.0, 4.0))

    assert result["delta_direction"] == "b - a"
    depth = result["sections"][0]["rows"][0]
    assert depth["delta"]["value"] == pytest.approx(-1162.0)
    sst = result["sections"][1]["rows"][0]
    assert sst["delta"]["value"] == pytest.approx(-1.5)
    # No ranking, ever — see the module docstring.
    assert "better" not in result["note"].split(".")[0]
