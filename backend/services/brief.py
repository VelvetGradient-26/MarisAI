"""One coordinate, as a document — the platform's answer to "what is here?".

Composition, not computation. Every number in a brief already has an endpoint;
what does not exist is the act of putting them on one page, which is the form
someone actually takes to a meeting, a skipper or a regulator. So this module
calls the same services the map calls and lays the answers out.

Two rules it inherits and must not break:

* **Never substitute a number for missing data.** Each section carries
  `available` and, when absent, a reason — the dashboard's rule, and it matters
  more in a document than on screen, because a PDF is read away from the app
  where nobody can hover to find out why a panel was blank. A brief for a
  landlocked coordinate is a legitimate brief that says so in six places.
* **Model output is labelled as model output.** Habitat suitability and bloom
  risk are predictions, the forecast fields are predictions, and the observed
  conditions are not. A document that renders them in one uniform table is
  exactly how a reader stops being able to tell.

The forecast half reads the **grid files**, not the live predictor. That is a
deliberate downgrade in precision for an upgrade in honesty and speed: the grids
are nearest-cell at 1 degree, but they are what the map shows, and a brief whose
numbers disagreed with the layer the user was looking at when they clicked
"brief" would be worse than one that is coarse and consistent. It is also the
difference between a request that returns now and one that runs inference for 30
seconds per variable.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from services import (
    biodiversity,
    copernicus_currents,
    eddies,
    heatwaves,
    forecast_tiles,
    predictions,
    stokes_drift,
    upwelling,
)
from services.bathymetry import BathymetryError, get_elevation
from services.biodiversity import BiodiversityError
from services.openmeteo import OpenMeteoError, get_realtime_ocean_conditions

# Forecast variables a brief reports, in the order they are laid out. Not every
# trained variable — a brief that ran to thirty rows would be a data dump rather
# than a briefing. These are the ones that answer "should I go, and what will it
# be like": sea state, temperature, and the two biological fields.
BRIEF_VARIABLES: tuple[str, ...] = (
    "sea_surface_temperature",
    "significant_wave_height",
    "wind_speed",
    "current_speed",
    "chlorophyll_a",
    "dissolved_oxygen",
)

# Horizons reported per variable. Three, not four: +1/+3/+7 is the window a
# planning decision actually spans, and +30 on a six-variable table doubles the
# page for a horizon almost nothing ships skill at.
BRIEF_HORIZONS: tuple[int, ...] = (1, 3, 7)

# Species carried in the habitat section, matching the map's own list.
BRIEF_SPECIES: tuple[str, ...] = (
    "yellowfin_tuna",
    "skipjack_tuna",
    "bigeye_tuna",
    "indian_mackerel",
    "oil_sardine",
)


class BriefError(RuntimeError):
    """A brief could not be assembled at all — as distinct from a section of one
    being unavailable, which is a normal, reportable outcome."""


@dataclass
class Section:
    """One block of a brief. `available` plus a reason, never a silent gap."""

    key: str
    title: str
    available: bool
    rows: list[dict[str, Any]] = field(default_factory=list)
    unavailable_reason: str | None = None
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": self.key,
            "title": self.title,
            "available": self.available,
            "rows": self.rows,
        }
        if self.unavailable_reason:
            payload["unavailable_reason"] = self.unavailable_reason
        if self.note:
            payload["note"] = self.note
        return payload


async def _location_section(latitude: float, longitude: float) -> tuple[Section, dict[str, Any]]:
    """Where this is, and how deep. Also returns the raw conditions payload, so
    the caller does not pay for a second Open-Meteo round trip."""
    conditions: dict[str, Any] = {}
    rows: list[dict[str, Any]] = [
        {"label": "Latitude", "value": f"{latitude:.4f}°"},
        {"label": "Longitude", "value": f"{longitude:.4f}°"},
    ]

    try:
        conditions = await get_realtime_ocean_conditions(latitude, longitude)
        context = conditions.get("location_context") or {}
        for key, label in (
            ("ocean_name", "Ocean / sea"),
            ("nearest_port", "Nearest port"),
            ("locality", "Nearest locality"),
        ):
            value = context.get(key)
            # `nearest_port` is a dict of its own; everything else is a string.
            if isinstance(value, dict):
                value = value.get("name")
            # Offshore, the reverse geocoder returns the sea itself as the
            # locality, so the two rows print the same words twice. Deduplicated
            # rather than dropped: inshore they are genuinely different answers.
            if value and not any(row["value"] == str(value) for row in rows):
                rows.append({"label": label, "value": str(value)})
    except OpenMeteoError as exc:
        logger.warning(f"brief: location context unavailable: {exc}")

    try:
        elevation = await get_elevation(latitude, longitude)
        metres = elevation.get("elevation_m")
        if metres is not None:
            # GEBCO reports elevation, so the seafloor is negative. Stated as a
            # depth for a marine reader, and land is named as land rather than
            # reported as a negative depth.
            rows.append(
                {
                    "label": "Seafloor depth" if metres < 0 else "Land elevation",
                    "value": f"{abs(metres):,.0f} m",
                }
            )
    except BathymetryError as exc:
        logger.warning(f"brief: bathymetry unavailable: {exc}")

    return Section(key="location", title="Location", available=True, rows=rows), conditions


def _conditions_section(conditions: dict[str, Any]) -> Section:
    """Observed now. Kept separate from the forecast table on purpose — these
    are measurements and those are predictions, and one table would blur that."""
    if not conditions:
        return Section(
            key="conditions",
            title="Observed conditions",
            available=False,
            unavailable_reason=(
                "the live conditions provider did not answer for this point; it is a "
                "point API and does not cover every coordinate"
            ),
        )

    # The readings are nested under `current`, with the provider's own unit
    # strings beside them under `units`. Taking the units from the response
    # rather than hardcoding them is the point: Open-Meteo's marine and weather
    # endpoints each choose their own, and a brief that asserted °C over a
    # response in °F would be confidently wrong.
    current = conditions.get("current") or {}
    units = conditions.get("units") or {}
    labels = {
        "sea_surface_temperature": "Sea surface temperature",
        "wave_height": "Significant wave height",
        "wave_period": "Wave period",
        "wave_direction": "Wave direction (from)",
        "ocean_current_velocity": "Surface current (point API)",
        "wind_speed": "Wind speed",
        "wind_direction": "Wind direction (from)",
        "air_temperature": "Air temperature",
    }
    rows = [
        {
            "label": label,
            "value": f"{current[key]:g} {units.get(key, '')}".strip(),
        }
        for key, label in labels.items()
        if isinstance(current.get(key), (int, float))
    ]

    if not rows:
        return Section(
            key="conditions",
            title="Observed conditions",
            available=False,
            unavailable_reason="the provider answered but carried no readings for this point",
        )
    return Section(key="conditions", title="Observed conditions", available=True, rows=rows)


def _flow_section(latitude: float, longitude: float) -> Section:
    """Surface currents and Stokes drift, which is what actually moves things.

    Both or neither is the wrong framing, so each is reported independently —
    the drift of a floating object is their sum, and a brief that showed only
    one would be answering a different question than the reader's.
    """
    rows: list[dict[str, Any]] = []
    for label, service in (
        ("Surface current", copernicus_currents),
        ("Stokes drift", stokes_drift),
    ):
        try:
            point = service.get_point(latitude, longitude)
        except Exception as exc:  # noqa: BLE001 - one field must not sink the brief
            rows.append({"label": label, "value": "unavailable", "note": str(exc)[:120]})
            continue

        if point.get("is_land_or_no_data"):
            rows.append({"label": label, "value": "no data (land or outside coverage)"})
            continue

        rows.append(
            {
                "label": label,
                "value": f"{point['speed_ms']:g} m/s toward {point['direction_compass']} "
                f"({point['direction_toward_deg']:g}°)",
            }
        )

    # A section whose every row failed is an unavailable section, not an
    # available one full of the word "unavailable". The distinction is what the
    # renderer keys on, and getting it wrong prints a table of apologies where a
    # single honest sentence belongs.
    if not any(row.get("value", "").startswith(("0", "1", "2", "3", "4", "5", "6", "7", "8", "9"))
               for row in rows):
        return Section(
            key="flow",
            title="Water movement",
            available=False,
            unavailable_reason=(
                "neither the surface currents nor the Stokes drift cache has data yet — "
                "both warm in the background after a restart, and a whole-globe fetch "
                "takes a few minutes"
            ),
        )
    # What the water is *doing* here, as opposed to which way it is going. A
    # point inside an eddy has a circulation, a retention time and a distinct
    # water mass that a bare velocity vector does not reveal — and a point well
    # outside every detection is a real answer too, so the distance is reported
    # rather than the row omitted.
    try:
        closest = eddies.nearest(latitude, longitude)
    except eddies.EddyError:
        closest = None
    if closest is not None:
        if closest["inside"]:
            article = "an" if closest["polarity"].startswith("a") else "a"
            value = (
                f"inside {article} {closest['polarity']} eddy, "
                f"{closest['radius_km']:g} km equivalent radius"
            )
        else:
            value = (
                f"nearest detected eddy {closest['distance_km']:g} km away "
                f"({closest['polarity']}, {closest['radius_km']:g} km)"
            )
        rows.append({"label": "Eddies", "value": value})

    # Vertical movement, which the horizontal vector above cannot show. Reported
    # for open ocean too — "not coastal" is a real answer, and an omitted row
    # reads as "no upwelling anywhere", the same rule the eddy row follows.
    try:
        up = upwelling.at_point(latitude, longitude)
    except upwelling.UpwellingError:
        up = None
    if up is not None:
        if up["available"]:
            value = (
                f"{up['regime']}, index {up['index']:g} {up['unit']} "
                f"(offshore {up['offshore_bearing_deg']:g}°)"
            )
        else:
            value = up["unavailable_reason"]
        rows.append({"label": "Coastal upwelling", "value": value})

    return Section(
        key="flow",
        title="Water movement",
        available=True,
        rows=rows,
        note=(
            "A floating object is carried by the sum of the current and the Stokes "
            "drift, not by the current alone. Directions are the direction the water "
            "travels toward. Eddies are detected from the current field by the "
            "Okubo-Weiss method and are not tracked, so none of them has an age; the "
            "radius is the equivalent radius of the rotating core. The upwelling "
            "index is wind-derived — it says the wind is favourable for upwelling, "
            "not that cold nutrient-rich water has actually surfaced."
        ),
    )


def _events_section(latitude: float, longitude: float) -> Section:
    """Detected events — currently marine heatwaves.

    Its own section rather than a row among the observed conditions, because a
    detection is a different kind of claim from a measurement: it carries a
    definition, a baseline and a threshold, and burying it beside a temperature
    reading invites it to be read as one. The note states the baseline, since a
    heatwave is meaningless without saying "relative to what".
    """
    try:
        state = heatwaves.at_point(latitude, longitude)
    except heatwaves.HeatwaveError as exc:
        return Section(
            key="events",
            title="Detected events",
            available=False,
            unavailable_reason=str(exc),
        )

    if not state["available"]:
        return Section(
            key="events",
            title="Detected events",
            available=False,
            unavailable_reason=state["unavailable_reason"],
        )

    if state["in_heatwave"]:
        run = f"{state['run_days']} consecutive day{'s' if state['run_days'] != 1 else ''}"
        if state["run_days_censored"]:
            # The window bounds what can be claimed. Saying "12 days" when the
            # record only reaches back 12 days states a duration the data cannot
            # support — and a marine heatwave's duration is one of its defining
            # properties, so the overstatement would matter.
            run += " or more (the record examined does not reach further back)"
        value = (
            f"{state['category']} marine heatwave — {run} above the seasonal "
            f"90th percentile, currently {state['exceedance_c']:g} °C above it"
        )
    else:
        value = (
            "no marine heatwave — sea-surface temperature is not above its "
            "seasonal 90th percentile for five consecutive days"
        )

    baseline = state["baseline"]
    return Section(
        key="events",
        title="Detected events",
        available=True,
        rows=[{"label": "Marine heatwave", "value": value}],
        note=(
            f"Hobday definition: sea-surface temperature above the "
            f"seasonally-varying 90th percentile of the {baseline['start']}-"
            f"{baseline['end']} baseline for at least five consecutive days. "
            "Events are not tracked between refreshes, so this carries no onset "
            "date or total duration."
        ),
    )


def _forecast_section(latitude: float, longitude: float) -> Section:
    """The forecast table, read off the same grids the map paints.

    A variable with no grid built is omitted from the rows and named in the
    note, rather than shown as blank — an empty cell in a forecast table reads
    as "we predict nothing here", which is a different claim from "this variable
    has no global grid yet".
    """
    rows: list[dict[str, Any]] = []
    missing: list[str] = []

    for variable in BRIEF_VARIABLES:
        values: dict[str, Any] = {}
        label = variable.replace("_", " ").title()
        unit = ""
        anchor: float | None = None

        for horizon in BRIEF_HORIZONS:
            try:
                point = forecast_tiles.point(variable, horizon, latitude, longitude)
            except Exception:  # noqa: BLE001 - an unbuilt grid is expected, not exceptional
                continue
            label = point.get("label", label)
            unit = point.get("unit", "")
            anchor = point.get("last_observed", anchor)
            values[f"h{horizon}"] = point.get("forecast")

        if not values:
            missing.append(variable.replace("_", " "))
            continue

        rows.append({"label": label, "unit": unit, "last_observed": anchor, **values})

    if not rows:
        return Section(
            key="forecast",
            title="Forecast",
            available=False,
            unavailable_reason=(
                "no forecast grid covers this point yet — grids are built offline and "
                "each takes about an hour"
            ),
        )

    note = (
        "MODEL OUTPUT, not observation. Read off the same 1° grids the forecast map "
        "paints, nearest cell, so these agree with the layer rather than with a more "
        "precise number the grid does not carry."
    )
    if missing:
        note += f" No grid built yet for: {', '.join(missing)}."
    return Section(key="forecast", title="Forecast", available=True, rows=rows, note=note)


def _habitat_section(latitude: float, longitude: float, month: int) -> Section:
    rows: list[dict[str, Any]] = []
    for species in BRIEF_SPECIES:
        try:
            point = predictions.habitat_point(species, month, latitude, longitude)
        except Exception:  # noqa: BLE001 - outside the model's region is normal
            continue
        value = point.get("suitability")
        if value is None:
            continue
        rows.append({"label": species.replace("_", " ").title(), "value": f"{value:.2f}"})

    if not rows:
        return Section(
            key="habitat",
            title="Fish habitat suitability",
            available=False,
            unavailable_reason=(
                "this point is outside the habitat model's region (northern Indian Ocean, "
                "55–95°E / 5°S–25°N)"
            ),
        )
    return Section(
        key="habitat",
        title="Fish habitat suitability",
        available=True,
        rows=rows,
        note=(
            "MODEL OUTPUT. Relative habitat suitability on 0–1 for the current calendar "
            "month's climatology — not a probability of catch, and the model is "
            "presence-only (no verified absences exist). TSS 0.76–0.90 across five spatial "
            "folds."
        ),
    )


def _bloom_section(latitude: float, longitude: float) -> Section:
    rows: list[dict[str, Any]] = []
    for horizon in (3, 5, 7):
        try:
            point = predictions.hab_point(horizon, latitude, longitude)
        except Exception:  # noqa: BLE001 - outside the region is normal
            continue
        risk = point.get("risk")
        if risk is None:
            continue
        rows.append({"label": f"+{horizon} days", "value": f"{risk:.2f}"})

    if not rows:
        return Section(
            key="bloom",
            title="Harmful algal bloom risk",
            available=False,
            unavailable_reason=(
                "this point is outside the bloom model's region (Arabian Sea, "
                "68–78°E / 6–23°N)"
            ),
        )
    return Section(
        key="bloom",
        title="Harmful algal bloom risk",
        available=True,
        rows=rows,
        note=(
            "MODEL OUTPUT, and a screening tool. A 'bloom' here is model chlorophyll above "
            "the local seasonal 90th percentile — a proxy, not a verified bloom, and it says "
            "nothing about toxicity. At the +7 day lead four in five alerts are false "
            "(precision 0.202 at 80% recall); +3 days is the usable one at 0.449."
        ),
    )


async def _biodiversity_section(latitude: float, longitude: float) -> Section:
    """What has been recorded here, from OBIS.

    The one section built from a *live* upstream rather than from a cache or a
    grid file, so it is the one that can make a brief slow; it is gathered with
    the rest rather than awaited in line for that reason.

    The bias note is not optional and is not a footnote. These counts measure
    survey effort — a well-studied bay outscores an unsurveyed one regardless of
    what lives in either — and the habitat model in this same document exists
    partly to correct that bias. Printing an uncorrected headline beside it
    without saying so would be the one genuinely indefensible thing in the
    brief.
    """
    try:
        report = await biodiversity.at_point(latitude, longitude)
    except BiodiversityError as exc:
        return Section(
            key="biodiversity",
            title="Recorded biodiversity",
            available=False,
            unavailable_reason=f"OBIS could not be queried for this area ({exc})",
        )

    totals = report["totals"]
    if not totals["records"]:
        return Section(
            key="biodiversity",
            title="Recorded biodiversity",
            available=False,
            unavailable_reason=report.get(
                "empty_reason", "no OBIS records within 0.5° of this point"
            ),
        )

    box = report["search_box"]
    rows = [
        {"label": "Occurrence records", "value": f"{totals['records']:,}"},
        {"label": "Species recorded", "value": f"{totals['species']:,}"},
        {"label": "Ray-finned fish species", "value": f"{totals['fish_species']:,}"},
        {"label": "Contributing datasets", "value": f"{totals['datasets']:,}"},
    ]
    if totals["first_year"] and totals["last_year"]:
        rows.append(
            {
                "label": "Years covered",
                "value": f"{totals['first_year']}–{totals['last_year']}",
            }
        )

    top = [entry for entry in report["species"] if entry.get("scientific_name")][:5]
    if top:
        rows.append(
            {
                "label": "Most recorded taxa",
                "value": ", ".join(entry["scientific_name"] for entry in top),
            }
        )

    return Section(
        key="biodiversity",
        title="Recorded biodiversity",
        available=True,
        rows=rows,
        note=(
            f"Within a {box['radius_deg']:g}° box (~{box['approx_area_km2']:,} km²). "
            + biodiversity.BIAS_NOTE
        ),
    )


async def build_brief(latitude: float, longitude: float) -> dict[str, Any]:
    """Everything known about one coordinate, as ordered sections.

    Sections are gathered rather than awaited in sequence where they touch the
    network, and the synchronous ones run in a thread — reading a grid file is
    milliseconds but there are eighteen of them, and this is called from a
    request handler.
    """
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        raise BriefError(f"coordinate out of range: {latitude}, {longitude}")

    generated = datetime.now(UTC)
    location, conditions = await _location_section(latitude, longitude)

    forecast, habitat, bloom, flow, events, biology = await asyncio.gather(
        asyncio.to_thread(_forecast_section, latitude, longitude),
        asyncio.to_thread(_habitat_section, latitude, longitude, generated.month),
        asyncio.to_thread(_bloom_section, latitude, longitude),
        asyncio.to_thread(_flow_section, latitude, longitude),
        asyncio.to_thread(_events_section, latitude, longitude),
        # Already a coroutine — it is a live HTTP call, not a grid read.
        _biodiversity_section(latitude, longitude),
    )

    sections = [
        location,
        _conditions_section(conditions),
        # Directly after the conditions it qualifies: "27.4 °C" and "that is a
        # severe marine heatwave" are the same reader's question one step apart.
        events,
        flow,
        forecast,
        habitat,
        bloom,
        # Last, deliberately. It is observation history rather than a condition
        # or a prediction, and it is the section most likely to be misread as a
        # richness measurement — so it sits after the model output it helps
        # contextualise rather than above it.
        biology,
    ]

    return {
        "latitude": latitude,
        "longitude": longitude,
        "generated_at": generated.isoformat(),
        "sections": [section.as_dict() for section in sections],
    }
