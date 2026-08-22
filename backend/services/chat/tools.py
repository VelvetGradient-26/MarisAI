"""The agent's tool surface: real MarisAI services, wrapped for a model.

Two rules shape everything here.

**Tools call services directly, never the HTTP API.** A tool that issued a
request back into our own uvicorn worker would deadlock the moment the loop is
busy serving the chat request itself, and it would pay JSON serialisation twice
for data that is already in the process. The router stays the browser's entry
point; the agent uses the same service functions the router does.

**A tool never raises.** An exception inside the loop kills the whole
conversation, so every tool catches its service's error type and returns a
sentence the model can actually act on ("no model is trained for X, here is
what is trained"). That is also why the failure text names alternatives where
it can — a model told only "not found" tends to retry the same call.

The surface is deliberately small. Every tool is another thing the model can
choose wrongly, and a handful of well-described tools beats twenty overlapping
ones. `test_chat.py` pins the count, so adding one is a deliberate act.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class Ledger:
    """Everything the tools actually returned during one conversation turn.

    The agent's grounding check reads this: a number in the final answer that
    appears nowhere in any tool result was invented by the model rather than
    measured by a provider. Kept per-request rather than module-level, because
    two concurrent chats must not be able to launder each other's numbers.
    """

    def __init__(self) -> None:
        self.observations: list[dict[str, Any]] = []

    def record(
        self,
        tool: str,
        arguments: dict[str, Any],
        result: Any,
        *,
        agent: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {"tool": tool, "arguments": arguments, "result": result}
        # Only present for a specialist's own tool calls, so the top-level
        # loop's calls (before the multi-agent split existed) keep the exact
        # same observation shape as before — additive, not a breaking change.
        if agent is not None:
            entry["agent"] = agent
        self.observations.append(entry)

    def as_text(self) -> str:
        return json.dumps(self.observations, default=str)

    def sources(self) -> list[str]:
        """Provider/citation strings seen in any result, for attribution."""
        found: set[str] = set()

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in {"source", "source_label", "sources", "citation"}:
                        if isinstance(value, str):
                            found.add(value)
                        elif isinstance(value, list):
                            found.update(str(item) for item in value)
                    else:
                        walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(self.observations)
        return sorted(found)


# --------------------------------------------------------------------------
# Argument schemas
# --------------------------------------------------------------------------
#
# Explicit pydantic models rather than inferred signatures: the `description`
# on each field is what the model reads to decide what to pass, and bounds are
# what stop a hallucinated longitude of 400 from reaching a provider.


class PointArgs(BaseModel):
    latitude: float = Field(..., ge=-90, le=90, description="Latitude in degrees north.")
    longitude: float = Field(
        ..., ge=-180, le=180, description="Longitude in degrees east, -180 to 180."
    )


class ForecastArgs(PointArgs):
    variable: str = Field(
        ...,
        description=(
            "Variable key to forecast, e.g. 'sea_surface_temperature'. "
            "Call list_available_variables first if unsure."
        ),
    )
    horizon_days: int = Field(
        7, ge=1, le=365, description="Days ahead to forecast. Must be at least 1."
    )


class SeriesArgs(PointArgs):
    variable: str = Field(..., description="Variable key, e.g. 'sst' or 'wave_height'.")
    range_key: str = Field(
        "7d",
        description=(
            "Named time range such as '24h', '7d', '30d', '1y'. Coverage genuinely "
            "differs per variable — if a range is unsupported the tool says so "
            "rather than returning a truncated series."
        ),
    )


class HabitatArgs(PointArgs):
    species: str = Field(
        ...,
        description=(
            "One of: yellowfin_tuna, skipjack_tuna, bigeye_tuna, "
            "indian_mackerel, oil_sardine."
        ),
    )
    month: int = Field(..., ge=1, le=12, description="Calendar month, 1-12.")


class BloomArgs(PointArgs):
    horizon_days: int = Field(
        3, description="Forecast horizon in days. Trained horizons are 3, 5 and 7."
    )


class Empty(BaseModel):
    pass


class FishingZoneArgs(PointArgs):
    radius_km: float = Field(
        100.0, ge=10, le=300, description="How far around the point to scan, in km."
    )


class RouteArgs(BaseModel):
    start_latitude: float = Field(..., ge=-90, le=90, description="Start latitude in degrees north.")
    start_longitude: float = Field(..., ge=-180, le=180, description="Start longitude in degrees east.")
    end_latitude: float = Field(..., ge=-90, le=90, description="Destination latitude in degrees north.")
    end_longitude: float = Field(..., ge=-180, le=180, description="Destination longitude in degrees east.")


# --------------------------------------------------------------------------
# Tool implementations
# --------------------------------------------------------------------------


async def _list_variables() -> dict[str, Any]:
    from forecasting.config import get_config
    from forecasting.model_store import list_trained
    from forecasting.registry import catalog as forecast_catalog

    config = get_config()
    trained = list_trained()
    entries = []
    for entry in forecast_catalog(config):
        key = entry.get("key") or entry.get("variable")
        entries.append(
            {
                "key": key,
                "label": entry.get("label"),
                "unit": entry.get("unit"),
                # The distinction the model must not blur: a variable can be
                # configured and downloadable while having no trained model, in
                # which case it can be charted but not forecast.
                "forecast_available": key in trained,
                "trained_horizons": sorted(trained.get(key, [])),
            }
        )
    return {
        "variables": entries,
        "note": (
            "forecast_available=false means the variable has data but no trained "
            "model; it can be charted and downloaded but not forecast."
        ),
    }


async def _point_forecast(variable: str, latitude: float, longitude: float, horizon_days: int) -> dict[str, Any]:
    from forecasting.predictor import predict

    forecast = await predict(
        variable, latitude, longitude, horizon_days, include_history=False
    )
    return {
        "variable": forecast.variable,
        "label": forecast.label,
        "unit": forecast.unit,
        "latitude": forecast.latitude,
        "longitude": forecast.longitude,
        "horizon_days": forecast.horizon,
        "valid_at": forecast.target_time,
        "prediction": round(float(forecast.prediction), 3),
        "interval_low": round(float(forecast.interval.lower), 3),
        "interval_high": round(float(forecast.interval.upper), 3),
    }


async def _current_conditions(latitude: float, longitude: float) -> dict[str, Any]:
    from services.openmeteo import get_realtime_ocean_conditions

    return await get_realtime_ocean_conditions(latitude=latitude, longitude=longitude)


async def _seafloor_depth(latitude: float, longitude: float) -> dict[str, Any]:
    from services.bathymetry import get_elevation

    return await get_elevation(latitude=latitude, longitude=longitude)


async def _global_summary() -> dict[str, Any]:
    from services.dashboard import summary

    return summary.build()


async def _active_alerts() -> dict[str, Any]:
    from services.dashboard import alerts

    return alerts.build()


async def _history(variable: str, latitude: float, longitude: float, range_key: str) -> dict[str, Any]:
    from services.dashboard import trends

    payload = await trends.series(variable, latitude, longitude, range_key)
    # The full series is thousands of points and would swamp the context for no
    # gain — the model is answering a question, not drawing the chart. Summary
    # statistics plus the endpoints are what a sentence actually needs.
    points = payload.get("points") or []
    return {
        "variable": payload.get("variable"),
        "label": payload.get("label"),
        "unit": payload.get("unit"),
        "range": range_key,
        "statistics": payload.get("statistics"),
        "point_count": len(points),
        "first": points[0] if points else None,
        "last": points[-1] if points else None,
        "source": payload.get("source"),
    }


async def _habitat(species: str, month: int, latitude: float, longitude: float) -> dict[str, Any]:
    from services.predictions import habitat_point

    return habitat_point(species, month, latitude, longitude)


async def _bloom_risk(horizon_days: int, latitude: float, longitude: float) -> dict[str, Any]:
    from services.predictions import hab_point

    return hab_point(horizon_days, latitude, longitude)


async def _fishing_zones(latitude: float, longitude: float, radius_km: float) -> dict[str, Any]:
    from services.pfz import find_zones

    return find_zones(latitude, longitude, radius_km)


async def _geofence(latitude: float, longitude: float) -> dict[str, Any]:
    from services import geofencing

    return geofencing.check(latitude, longitude)


async def _safe_route(
    start_latitude: float, start_longitude: float, end_latitude: float, end_longitude: float
) -> dict[str, Any]:
    from services.routing import plan_route

    return await plan_route(start_latitude, start_longitude, end_latitude, end_longitude)


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------

_SPECS: list[tuple[str, str, type[BaseModel], Any]] = [
    (
        "list_available_variables",
        "List every ocean variable MarisAI serves and whether a trained forecast "
        "model exists for it. Call this before forecasting an unfamiliar variable.",
        Empty,
        _list_variables,
    ),
    (
        "get_point_forecast",
        "Forecast one variable at one coordinate, N days ahead, with an "
        "uncertainty interval. Only works for variables whose forecast_available "
        "is true.",
        ForecastArgs,
        _point_forecast,
    ),
    (
        "get_current_conditions",
        "Present-day marine and weather conditions at a coordinate: temperature, "
        "wind, waves. Use for 'right now' questions.",
        PointArgs,
        _current_conditions,
    ),
    (
        "get_seafloor_depth",
        "Seafloor depth (bathymetry) at a coordinate, from GEBCO.",
        PointArgs,
        _seafloor_depth,
    ),
    (
        "get_global_ocean_summary",
        "Global ocean state: mean sea-surface temperature, heat-stress extent, "
        "coral bleaching risk and related indicators. No coordinate needed.",
        Empty,
        _global_summary,
    ),
    (
        "get_active_alerts",
        "Current threshold-based alerts over real fields (heat stress, waves, "
        "blooms). These are computed rules, not issued marine warnings.",
        Empty,
        _active_alerts,
    ),
    (
        "get_historical_series",
        "Summary statistics for one variable at a coordinate over a past time "
        "range. Use for 'how has X changed' and comparisons against the past.",
        SeriesArgs,
        _history,
    ),
    (
        "get_fishing_habitat",
        "Habitat suitability (potential fishing zone) for one of five species in "
        "a given month. Covers the North Indian Ocean only.",
        HabitatArgs,
        _habitat,
    ),
    (
        "get_bloom_risk",
        "Harmful algal bloom risk at a coordinate for a 3, 5 or 7 day horizon. "
        "Covers the Arabian Sea only.",
        BloomArgs,
        _bloom_risk,
    ),
    (
        "find_fishing_zones",
        "Scan the water around a coordinate for potentially favourable fishing "
        "conditions (chlorophyll + SST), ranked. A heuristic screening aid, "
        "not a validated PFZ model or an official advisory.",
        FishingZoneArgs,
        _fishing_zones,
    ),
    (
        "check_geofence",
        "Check a coordinate against India's EEZ (mainland coastal waters), the "
        "India-Sri Lanka maritime boundary (IMBL), and nearby Marine Protected "
        "Areas. Reference geometry, not a surveyed nautical chart.",
        PointArgs,
        _geofence,
    ),
    (
        "plan_safe_route",
        "Plan a route between two coordinates, comparing wave/wind hazard "
        "along a direct line against two lateral alternatives, and flagging "
        "any candidate that crosses the IMBL or a Marine Protected Area.",
        RouteArgs,
        _safe_route,
    ),
]

# name -> (description, schema, function), for lookup by the specialist
# tool-name allowlists in `services/chat/specialists.py`.
_BY_NAME: dict[str, tuple[str, type[BaseModel], Any]] = {
    name: (description, schema, function) for name, description, schema, function in _SPECS
}

ALL_TOOL_NAMES: list[str] = [name for name, *_ in _SPECS]


def build_tools(
    ledger: Ledger, names: list[str] | None = None, *, agent: str | None = None
) -> list[StructuredTool]:
    """Bind a tool set to one conversation's ledger.

    Built per request rather than once at import, because the ledger has to be
    per-conversation — see `Ledger`. The wrapper is also the single place tool
    failures are turned into text, so no individual tool has to remember to.

    `names=None` returns every tool (the pre-multi-agent behaviour, and what
    `test_every_tool_declares_a_description_and_schema` still exercises).
    `agent` tags every observation this tool set records, so a specialist's
    calls carry which specialist made them — see `Ledger.record`.
    """
    selected = _SPECS if names is None else [(n, *_BY_NAME[n]) for n in names]
    tools: list[StructuredTool] = []

    for name, description, schema, function in selected:
        def make(name: str, function: Any):
            async def run(**kwargs: Any) -> str:
                try:
                    result = await function(**kwargs)
                except Exception as exc:  # noqa: BLE001 - a raise would end the turn
                    logger.warning(f"chat tool {name} failed: {exc}")
                    return json.dumps(
                        {
                            "error": str(exc)[:400],
                            "tool": name,
                            "hint": (
                                "This data is unavailable. Say so plainly; do not "
                                "estimate or substitute a value."
                            ),
                        }
                    )
                ledger.record(name, kwargs, result, agent=agent)
                return json.dumps(result, default=str)

            return run

        tools.append(
            StructuredTool.from_function(
                coroutine=make(name, function),
                name=name,
                description=description,
                args_schema=schema,
            )
        )

    return tools
