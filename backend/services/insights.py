"""Turns a snapshot of dashboard ocean/atmospheric metrics into an LLM prompt."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.llm import LLMError, get_llm_provider

METRIC_LABELS: dict[str, str] = {
    "sea_surface_temperature": "Sea surface temperature",
    "wave_height": "Wave height",
    "wave_direction": "Wave direction",
    "wave_period": "Wave period",
    "ocean_current_velocity": "Ocean current speed",
    "ocean_current_direction": "Ocean current direction",
    "sea_level_height_msl": "Sea level (MSL)",
    "wind_speed": "Wind speed",
    "wind_direction": "Wind direction",
    "air_temperature": "Air temperature",
    "relative_humidity": "Relative humidity",
    "surface_pressure": "Surface pressure",
    "visibility": "Visibility",
    "cloud_cover": "Cloud cover",
    "precipitation": "Precipitation",
}


class InsightsError(RuntimeError):
    pass


def _build_prompt(
    current: dict[str, Any],
    units: dict[str, Any],
    location_context: dict[str, Any] | None,
    requested: dict[str, Any] | None,
) -> str:
    lines: list[str] = []
    for key, label in METRIC_LABELS.items():
        value = current.get(key)
        if value is None:
            continue
        unit = units.get(key) or ""
        lines.append(f"- {label}: {value} {unit}".rstrip())

    if not lines:
        raise InsightsError("No metrics available to analyze")

    location_bits = []
    if location_context:
        for field in ("ocean_name", "locality", "continent"):
            value = location_context.get(field)
            if value:
                location_bits.append(value)
    location_desc = ", ".join(location_bits) if location_bits else "an open-ocean coordinate"

    nearest_port = location_context.get("nearest_port") if location_context else None
    if nearest_port:
        location_desc += (
            f" (nearest port: {nearest_port['name']}, {nearest_port['country']}, "
            f"{nearest_port['distance_km']} km away)"
        )

    coord_desc = ""
    if requested and requested.get("latitude") is not None and requested.get("longitude") is not None:
        coord_desc = f" ({requested['latitude']:.4f}°, {requested['longitude']:.4f}°)"

    metrics_block = "\n".join(lines)

    return (
        "You are a marine conditions analyst embedded in an ocean intelligence dashboard. "
        f"Analyze the live readings below for {location_desc}{coord_desc} and produce a short, "
        "actionable brief for someone monitoring this location.\n\n"
        f"Current readings:\n{metrics_block}\n\n"
        "Respond in 3-5 short bullet points covering: notable conditions, any risk or safety "
        "flags, and a one-line outlook. Be concise and avoid restating raw numbers that were "
        "already listed unless interpreting them. Do not use markdown headings."
    )


async def generate_ocean_insights(
    current: dict[str, Any],
    units: dict[str, Any],
    location_context: dict[str, Any] | None = None,
    requested: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt = _build_prompt(current, units, location_context, requested)

    provider = get_llm_provider()
    try:
        text = await provider.generate(prompt)
    except LLMError:
        raise
    except Exception as exc:  # unexpected transport/provider failure
        raise LLMError(f"LLM insight generation failed: {exc}") from exc

    if not text:
        raise InsightsError("LLM returned an empty response")

    return {
        "insights": text,
        "provider": type(provider).__name__.replace("Provider", "").lower(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
