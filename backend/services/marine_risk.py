"""Deterministic "is it safe to venture out" verdict — fixed rules over live checks.

sihtodo.md item 10: answering "is it safe to go out" today means the model
independently calls `get_current_conditions` + `get_severe_weather_alerts` +
`get_cyclone_alerts` + `check_geofence` itself and synthesises a verdict in
prose — so the same underlying conditions can read as reassuring or alarming
depending on how the model happened to phrase that turn. This module runs the
same four live checks but reduces them through a fixed rule table, so a given
set of conditions always produces the same `risk_level`.

**Escalation only ever goes up, and only from a check that actually
returned data.** A failed sub-check (a dead upstream, a timeout) is recorded
in `could_not_verify` rather than silently treated as "no hazard found" —
the same discipline the rest of this codebase applies to missing data
(CLAUDE.md's "never substitute a number for missing data"). It is also never
used to *inflate* the verdict: a check that could not be confirmed is a gap
in the answer, not evidence of danger.

**Boundary/Marine Protected Area proximity is a legal and navigational
caution, not a weather hazard**, so on its own it can only push the verdict
to "moderate" — it never combines with a calm-sea reading to read as
"extreme" the way an active cyclone does.

Not a substitute for an official marine forecast or a coast guard advisory —
every response says so, the same posture every other detector-style module
here takes (`services/eddies.py`, `services/upwelling.py`, `services/pfz.py`).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from services import cyclones, geofencing, openmeteo, severe_weather

logger = logging.getLogger(__name__)

RiskLevel = Literal["low", "moderate", "high", "extreme"]

_LEVEL_RANK: dict[RiskLevel, int] = {"low": 0, "moderate": 1, "high": 2, "extreme": 3}

# Matches services/routing.py's own `_WAVE_CAUTION_M` / `_WAVE_HAZARD_M` —
# one definition of "rough water" rather than a second one invented here.
_WAVE_CAUTION_M = 1.5
_WAVE_HAZARD_M = 2.5

# Beaufort 6 ("strong breeze", small craft warnings routinely start here) and
# Beaufort 8 ("gale") in km/h, rounded.
_WIND_CAUTION_KMH = 40.0
_WIND_HAZARD_KMH = 62.0

# CAP's own severity vocabulary (IMD's feed uses it directly — see
# services/severe_weather.py). Anything not in this table — Moderate, Minor,
# Unknown — still escalates to "moderate": an *active* alert covering this
# exact point is never nothing, even at IMD's lowest severity tier.
_SEVERE_ALERT_ESCALATION: dict[str, RiskLevel] = {
    "extreme": "extreme",
    "severe": "high",
}


def _escalate(current: RiskLevel, candidate: RiskLevel) -> RiskLevel:
    return candidate if _LEVEL_RANK[candidate] > _LEVEL_RANK[current] else current


def _assess_conditions(level: RiskLevel, conditions: dict[str, Any]) -> tuple[RiskLevel, list[str]]:
    reasons: list[str] = []
    current = conditions.get("current") or {}
    wave_m = current.get("wave_height")
    wind_kmh = current.get("wind_speed")

    if wave_m is not None:
        if wave_m >= _WAVE_HAZARD_M:
            level = _escalate(level, "high")
            reasons.append(
                f"wave height {wave_m} m is at or above the {_WAVE_HAZARD_M} m hazard threshold"
            )
        elif wave_m >= _WAVE_CAUTION_M:
            level = _escalate(level, "moderate")
            reasons.append(
                f"wave height {wave_m} m is at or above the {_WAVE_CAUTION_M} m caution threshold"
            )

    if wind_kmh is not None:
        if wind_kmh >= _WIND_HAZARD_KMH:
            level = _escalate(level, "high")
            reasons.append(
                f"wind speed {wind_kmh} km/h is at or above the {_WIND_HAZARD_KMH} km/h hazard threshold"
            )
        elif wind_kmh >= _WIND_CAUTION_KMH:
            level = _escalate(level, "moderate")
            reasons.append(
                f"wind speed {wind_kmh} km/h is at or above the {_WIND_CAUTION_KMH} km/h caution threshold"
            )

    return level, reasons


def _assess_severe_weather(level: RiskLevel, severe: dict[str, Any]) -> tuple[RiskLevel, list[str]]:
    reasons: list[str] = []
    for alert in severe.get("alerts") or []:
        severity = str(alert.get("severity") or "").strip().lower()
        escalated = _SEVERE_ALERT_ESCALATION.get(severity, "moderate")
        level = _escalate(level, escalated)
        reasons.append(f"IMD alert: {alert.get('event')} ({alert.get('severity') or 'unspecified'} severity)")
    return level, reasons


def _assess_cyclone(level: RiskLevel, cyclone: dict[str, Any]) -> tuple[RiskLevel, list[str]]:
    reasons: list[str] = []
    nearest = cyclone.get("nearest")
    if cyclone.get("within_watch_radius") and nearest:
        level = _escalate(level, "extreme")
        reasons.append(
            f"cyclone {nearest.get('name')} is {nearest.get('distance_km')} km away, "
            f"within the {cyclone.get('watch_radius_km')} km watch radius"
        )
    return level, reasons


def _assess_geofence(level: RiskLevel, geofence: dict[str, Any]) -> tuple[RiskLevel, list[str]]:
    notes: list[str] = []
    if geofence["india_sri_lanka_imbl"]["near"]:
        level = _escalate(level, "moderate")
        notes.append(
            f"within {geofence['india_sri_lanka_imbl']['distance_km']} km of the "
            "India-Sri Lanka maritime boundary"
        )
    inside_areas = [area for area in geofence["nearby_protected_areas"] if area["inside"]]
    if inside_areas:
        level = _escalate(level, "moderate")
        notes.append(
            "inside a Marine Protected Area: " + ", ".join(area["name"] for area in inside_areas)
        )
    return level, notes


async def assess(latitude: float, longitude: float) -> dict[str, Any]:
    """Combine live sea conditions, IMD alerts, active cyclones and
    boundary/MPA proximity into one deterministic risk verdict for a point.

    Never raises: each live check is isolated, so one dead upstream degrades
    that one input (recorded in `could_not_verify`) rather than failing the
    whole assessment.
    """
    conditions_result, severe_result, cyclone_result = await asyncio.gather(
        openmeteo.get_realtime_ocean_conditions(latitude, longitude),
        severe_weather.check_point(latitude, longitude),
        cyclones.check_point(latitude, longitude),
        return_exceptions=True,
    )
    # Pure local geometry — never raises, touches no network.
    geofence = geofencing.check(latitude, longitude)

    level: RiskLevel = "low"
    reasons: list[str] = []
    checked: list[str] = []
    could_not_verify: list[str] = []

    if isinstance(conditions_result, BaseException):
        logger.warning(f"assess_marine_risk: current conditions check failed: {conditions_result}")
        could_not_verify.append(f"current sea/weather conditions ({conditions_result})")
        conditions_result = None
    else:
        checked.append("current sea/weather conditions")
        level, condition_reasons = _assess_conditions(level, conditions_result)
        reasons.extend(condition_reasons)

    if isinstance(severe_result, BaseException):
        logger.warning(f"assess_marine_risk: severe-weather check failed: {severe_result}")
        could_not_verify.append(f"IMD severe-weather alerts ({severe_result})")
        severe_result = None
    else:
        checked.append("IMD severe-weather alerts")
        level, severe_reasons = _assess_severe_weather(level, severe_result)
        reasons.extend(severe_reasons)

    if isinstance(cyclone_result, BaseException):
        logger.warning(f"assess_marine_risk: cyclone check failed: {cyclone_result}")
        could_not_verify.append(f"active cyclone tracks ({cyclone_result})")
        cyclone_result = None
    else:
        checked.append("active cyclone tracks")
        level, cyclone_reasons = _assess_cyclone(level, cyclone_result)
        reasons.extend(cyclone_reasons)

    checked.append("maritime boundary / Marine Protected Area proximity")
    level, geofence_reasons = _assess_geofence(level, geofence)
    reasons.extend(geofence_reasons)

    if not reasons:
        reasons.append("no hazard condition crossed a fixed threshold in the checks that ran")

    return {
        "latitude": latitude,
        "longitude": longitude,
        "risk_level": level,
        "reasons": reasons,
        "checked": checked,
        "could_not_verify": could_not_verify,
        "conditions": conditions_result,
        "severe_weather": severe_result,
        "cyclone": cyclone_result,
        "geofence": geofence,
        "note": (
            "risk_level is computed by a fixed rule table over live checks, not "
            "generated text — the same conditions always produce the same level. "
            f"Thresholds: wave height {_WAVE_CAUTION_M}/{_WAVE_HAZARD_M} m "
            f"(caution/hazard), wind speed {_WIND_CAUTION_KMH:.0f}/{_WIND_HAZARD_KMH:.0f} "
            "km/h (caution/hazard), any active IMD severe-weather alert covering this "
            "point, an active cyclone within its watch radius, or being inside/near a "
            "boundary or Marine Protected Area. Escalation only ever goes up, and only "
            "from a check that actually returned data — see could_not_verify for "
            "anything that could not be confirmed this call. Not a substitute for an "
            "official marine forecast or coast guard advisory."
        ),
    }
