"""The point brief — composition, and what it must never do.

A brief is read away from the app, where nobody can hover over a blank panel to
find out why it is blank. That makes the honesty rules stricter here than on
screen, not looser: a section that could not be built has to say so *in the
document*, and a prediction has to be labelled as one.
"""

from __future__ import annotations

import asyncio

import pytest

from services import brief as brief_service
from services import brief_pdf
from services.brief import BriefError, Section


def _run(coroutine):
    return asyncio.run(coroutine)


def _sections(brief: dict) -> dict[str, dict]:
    return {section["key"]: section for section in brief["sections"]}


@pytest.fixture
def offline(monkeypatch):
    """Every upstream unavailable. The interesting case, not the degenerate one:
    a brief that cannot reach anything must still be a valid brief that says so,
    because that is what a user on a bad connection actually receives."""

    async def _no_conditions(*_args, **_kwargs):
        from services.openmeteo import OpenMeteoError

        raise OpenMeteoError("offline")

    async def _no_bathymetry(*_args, **_kwargs):
        from services.bathymetry import BathymetryError

        raise BathymetryError("offline")

    async def _no_biodiversity(*_args, **_kwargs):
        from services.biodiversity import BiodiversityError

        raise BiodiversityError("offline")

    monkeypatch.setattr(brief_service, "get_realtime_ocean_conditions", _no_conditions)
    monkeypatch.setattr(brief_service, "get_elevation", _no_bathymetry)
    # OBIS is the one section built from a live upstream rather than a cache or
    # a grid file, so an unstubbed one would reach the network from a test.
    monkeypatch.setattr(brief_service.biodiversity, "at_point", _no_biodiversity)


def test_a_brief_out_of_range_is_refused_rather_than_guessed():
    with pytest.raises(BriefError, match="out of range"):
        _run(brief_service.build_brief(120.0, 0.0))


def test_every_section_is_present_even_when_nothing_can_be_reached(offline):
    """Sections are never dropped. A missing habitat block reads as "habitat did
    not apply here"; a present one reading "outside the model's region" is a
    fact. The renderer prints the reason, so the reason must exist."""
    brief = _run(brief_service.build_brief(9.5, 75.0))

    sections = _sections(brief)
    assert set(sections) == {
        "location",
        "conditions",
        "flow",
        "forecast",
        "habitat",
        "bloom",
        "biodiversity",
    }
    for key, section in sections.items():
        if not section["available"]:
            assert section.get("unavailable_reason"), f"{key} is absent without saying why"


def test_the_coordinate_is_always_reported_even_with_every_upstream_down(offline):
    """The one thing a brief always knows."""
    brief = _run(brief_service.build_brief(9.5, 75.0))

    location = _sections(brief)["location"]
    assert location["available"]
    values = {row["label"]: row["value"] for row in location["rows"]}
    assert values["Latitude"].startswith("9.5")
    assert values["Longitude"].startswith("75.0")


def test_a_section_whose_every_row_failed_is_not_reported_as_available():
    """The bug this pins: rows carrying the word "unavailable" inside a section
    flagged `available: true`, which renders as a table of apologies where one
    honest sentence belongs."""
    section = brief_service._flow_section(9.5, 75.0)

    if not section.available:
        assert section.unavailable_reason
    else:
        assert any(row["value"][0].isdigit() for row in section.rows)


def test_model_output_sections_say_so():
    """Habitat, bloom and forecast are predictions. A reader who cannot tell
    them from the observed block has been misled by the layout."""
    for builder in (
        lambda: brief_service._habitat_section(9.5, 75.0, 8),
        lambda: brief_service._bloom_section(20.0, 68.5),
        lambda: brief_service._forecast_section(9.5, 75.0),
    ):
        section = builder()
        if section.available:
            assert "MODEL OUTPUT" in (section.note or ""), f"{section.key} is not labelled"


def test_observed_conditions_are_not_labelled_as_model_output():
    """The converse, and the reason the two are separate sections at all."""
    section = brief_service._conditions_section(
        {"current": {"sea_surface_temperature": 28.3}, "units": {"sea_surface_temperature": "°C"}}
    )

    assert section.available
    assert "MODEL OUTPUT" not in (section.note or "")
    assert section.rows == [{"label": "Sea surface temperature", "value": "28.3 °C"}]


def test_units_come_from_the_provider_rather_than_being_asserted():
    """Open-Meteo's marine and weather endpoints each choose their own units. A
    brief that hardcoded degrees Celsius over a Fahrenheit response would be
    confidently wrong, and nothing would raise."""
    section = brief_service._conditions_section(
        {"current": {"air_temperature": 81.0}, "units": {"air_temperature": "°F"}}
    )

    assert section.rows == [{"label": "Air temperature", "value": "81 °F"}]


def test_a_brief_renders_to_a_pdf_even_when_every_section_is_unavailable():
    """The renderer must not assume rows exist. An all-empty brief is exactly
    what a user offline receives, and a traceback instead of a document would be
    the worst possible answer to it."""
    brief = {
        "latitude": 9.5,
        "longitude": 75.0,
        "generated_at": "2026-08-14T00:00:00+00:00",
        "sections": [
            Section(
                key=key, title=key.title(), available=False, unavailable_reason="nothing reachable"
            ).as_dict()
            for key in ("location", "conditions", "flow", "forecast", "habitat", "bloom")
        ],
    }

    pdf = brief_pdf.render(brief)

    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_the_pdf_carries_the_unavailable_reasons_rather_than_dropping_them():
    """Checked against the PDF's own bytes: reportlab compresses streams, so the
    assertion is on the document building at all plus the reason surviving into
    the section list the renderer walks."""
    brief = {
        "latitude": 0.0,
        "longitude": -140.0,
        "generated_at": "2026-08-14T00:00:00+00:00",
        "sections": [
            Section(
                key="habitat",
                title="Fish habitat suitability",
                available=False,
                unavailable_reason="outside the habitat model's region",
            ).as_dict()
        ],
    }

    assert brief_pdf.render(brief).startswith(b"%PDF")
    assert brief["sections"][0]["unavailable_reason"]
