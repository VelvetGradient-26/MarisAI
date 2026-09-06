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


class ForecastTrendArgs(PointArgs):
    variable: str = Field(
        ...,
        description=(
            "Variable key to forecast, e.g. 'sea_surface_temperature'. "
            "Call list_available_variables first if unsure."
        ),
    )
    horizons: list[int] | None = Field(
        None,
        description=(
            "Horizons in days ahead to plot. Only a fixed set is actually trained "
            "per variable — check list_available_variables' trained_horizons if "
            "unsure; an untrained horizon here is silently dropped rather than "
            "failing the call. Omit entirely to use every horizon this variable "
            "has a trained model for."
        ),
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


class CycloneArgs(PointArgs):
    radius_km: float = Field(
        500.0,
        ge=50,
        le=2000,
        description="How far from the point counts as 'nearby' for a tropical cyclone, in km.",
    )


class DocumentationArgs(BaseModel):
    query: str = Field(
        ...,
        description=(
            "What the user wants to know about the MarisAI platform itself, "
            "in their own words, e.g. 'how do I read the map colours' or "
            "'what does grounded mean'. Not for ocean data or forecasts."
        ),
    )


class CorrelationArgs(PointArgs):
    variables: list[str] = Field(
        ...,
        min_length=2,
        max_length=4,
        description=(
            "2-4 variable keys to correlate at this point, e.g. "
            "['sea_surface_temperature', 'chlorophyll_a']. Call "
            "list_available_variables or get_historical_series first if unsure "
            "of a key. Not every ocean variable is available here — only ones "
            "with a point historical series (fishing effort and the upwelling "
            "index have none in this codebase and cannot be requested)."
        ),
    )
    range_key: str = Field(
        "1y",
        description=(
            "Named daily-resolution time range: '30d', '6mo', '1y', '5y' or "
            "'10y'. Hourly ranges ('24h', '7d') are not supported — a "
            "correlation needs a shared daily cadence."
        ),
    )


class RouteArgs(BaseModel):
    start_latitude: float = Field(..., ge=-90, le=90, description="Start latitude in degrees north.")
    start_longitude: float = Field(..., ge=-180, le=180, description="Start longitude in degrees east.")
    end_latitude: float = Field(..., ge=-90, le=90, description="Destination latitude in degrees north.")
    end_longitude: float = Field(..., ge=-180, le=180, description="Destination longitude in degrees east.")
    vessel_draft_m: float | None = Field(
        None,
        gt=0,
        description=(
            "Vessel draft in metres, if given. Water too shallow to clear it is excluded from the "
            "route outright, so the path may detour around a shoal it would otherwise cross."
        ),
    )
    vessel_speed_kmh: float | None = Field(
        None,
        gt=0,
        description="Vessel speed in km/h, if given. Only used to estimate travel time; never changes the route.",
    )
    vessel_fuel_range_km: float | None = Field(
        None,
        gt=0,
        description=(
            "Vessel fuel range in km, if given. Checked against the found route's own distance "
            "to say whether it fits within range; never changes the route."
        ),
    )


class WebSearchArgs(BaseModel):
    query: str = Field(..., description="What to search for on the open web.")
    max_results: int = Field(5, ge=1, le=10, description="Maximum number of results to return.")


class FetchWebpageArgs(BaseModel):
    url: str = Field(
        ...,
        description=(
            "A specific http(s) URL to fetch and read, e.g. one returned by "
            "web_search. Not a search query."
        ),
    )


class LiteratureArgs(BaseModel):
    query: str = Field(..., description="Topic, species, or research question to search for.")
    max_results: int = Field(5, ge=1, le=10, description="Maximum number of papers to return.")


class TideArgs(PointArgs):
    radius_km: float = Field(
        200.0,
        ge=10,
        le=500,
        description="How far from the point to look for an INCOIS tide-gauge station, in km.",
    )


class ArgoArgs(PointArgs):
    radius_km: float = Field(300.0, ge=10, le=1000, description="How far from the point to look for an ARGO float.")
    lookback_days: int = Field(
        30, ge=1, le=120, description="How many days back to look for a profile (a float reports roughly every 10 days)."
    )


class DriftTrajectoryArgs(PointArgs):
    preset: str = Field(
        "life_raft",
        description=(
            "What is drifting, which sets how much of the wind it picks up "
            "directly (leeway) on top of the current and waves. One of: "
            "water_only (no leeway — a slick or larva), swamped_hull, "
            "oil_slick, person_in_water, life_raft (default — the common "
            "person-overboard/SAR case)."
        ),
    )
    horizon_hours: float = Field(48.0, ge=6, le=96, description="How far ahead to forecast, in hours.")


# --------------------------------------------------------------------------
# Tool implementations
# --------------------------------------------------------------------------


async def _list_variables() -> dict[str, Any]:
    from forecasting.config import get_config
    from forecasting.registry import catalog as forecast_catalog

    config = get_config()
    entries = [
        {
            "key": entry.key,
            "label": entry.label,
            "unit": entry.unit,
            # The distinction the model must not blur: a variable can be
            # configured and downloadable while having no trained model, in
            # which case it can be charted but not forecast. `catalog()` is
            # the source of truth for this (it also handles derived
            # variables, trained from two component models rather than one)
            # — re-deriving it here from a bare `list_trained()` lookup, as
            # this tool used to, drifted out of sync with that logic and
            # crashed outright once VariableEntry stopped being a dict.
            "forecast_available": entry.available,
            "trained_horizons": sorted(entry.trained_horizons),
        }
        for entry in forecast_catalog(config)
    ]
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


async def _forecast_trend(
    variable: str, latitude: float, longitude: float, horizons: list[int] | None
) -> dict[str, Any]:
    """Several horizons plus recent history — the one place in this file the
    `_history` tool's own trimming reasoning inverts: there, the full series
    is thrown away because "the model is answering a question, not drawing
    the chart"; here, the array *is* what gets drawn, so it is kept rather
    than collapsed to first/last/statistics.
    """
    from forecasting.config import get_config
    from forecasting.registry import catalog as forecast_catalog
    from forecasting.predictor import predict_many

    config = get_config()
    entry = next((e for e in forecast_catalog(config) if e.key == variable), None)
    trained = sorted(entry.trained_horizons) if entry and entry.trained_horizons else None

    # A model asking for "the next week" naturally reaches for daily
    # horizons (1, 2, 3, ...), most of which are not trained — only a fixed
    # set is (e.g. 1/3/7/14/30/90/365). predict_many fails the *entire* call
    # on the first untrained horizon it hits, which would otherwise throw
    # away every valid horizon the model also asked for along with the
    # invalid ones. Silently keep only the trained subset of what was asked
    # for, and fall back to every trained horizon if none of them were.
    if trained is not None:
        if horizons:
            horizons = [h for h in horizons if h in trained] or trained
        else:
            horizons = trained
    elif not horizons:
        horizons = [1, 3, 7, 30]

    # Sequential inside predict_many, reusing the first call's history-fetch
    # cache for every later horizon — the same reason get_historical_series's
    # caller doesn't need to worry about N separate upstream fetches here.
    forecasts = await predict_many(variable, latitude, longitude, horizons, history_window=30)
    first = forecasts[0]
    return {
        "variable": first.variable,
        "label": first.label,
        "unit": first.unit,
        "latitude": first.latitude,
        "longitude": first.longitude,
        "history": first.history,
        "points": [
            {
                "horizon_days": f.horizon,
                # .isoformat() explicitly (unlike _point_forecast's bare
                # valid_at, left to json.dumps's default=str) — the frontend
                # chart parses this with Date.parse, and history[].t is
                # already pd.Timestamp(...).isoformat() a few lines up in
                # this same file, so this keeps both timestamps in the one
                # format that's actually proven to parse correctly.
                "target_time": f.target_time.isoformat(),
                "prediction": round(float(f.prediction), 3),
                "interval_low": round(float(f.interval.lower), 3),
                "interval_high": round(float(f.interval.upper), 3),
            }
            for f in forecasts
        ],
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


async def _cyclone_alerts(latitude: float, longitude: float, radius_km: float) -> dict[str, Any]:
    from services.cyclones import check_point

    return await check_point(latitude, longitude, radius_km)


async def _severe_weather_alerts(latitude: float, longitude: float) -> dict[str, Any]:
    from services.severe_weather import check_point

    return await check_point(latitude, longitude)


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


async def _get_documentation(query: str) -> dict[str, Any]:
    from services import docs

    results = docs.search(query)
    return {
        "query": query,
        "results": results,
        "note": (
            "No documentation chapter matched this query."
            if not results
            else "Each result names a real /docs?c=<id> route — link to it rather "
            "than inventing a path."
        ),
    }


async def _safe_route(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
    vessel_draft_m: float | None = None,
    vessel_speed_kmh: float | None = None,
    vessel_fuel_range_km: float | None = None,
) -> dict[str, Any]:
    from services.routing import plan_route

    return await plan_route(
        start_latitude,
        start_longitude,
        end_latitude,
        end_longitude,
        vessel_draft_m=vessel_draft_m,
        vessel_speed_kmh=vessel_speed_kmh,
        vessel_fuel_range_km=vessel_fuel_range_km,
    )


async def _assess_risk(latitude: float, longitude: float) -> dict[str, Any]:
    from services.marine_risk import assess

    return await assess(latitude, longitude)


async def _correlate(
    variables: list[str], latitude: float, longitude: float, range_key: str
) -> dict[str, Any]:
    from services.correlation import analyze

    return await analyze(variables, latitude, longitude, range_key)


async def _web_search(query: str, max_results: int) -> dict[str, Any]:
    from services.web_search import search

    return await search(query, max_results)


async def _fetch_webpage(url: str) -> dict[str, Any]:
    from services.webpage import fetch

    return await fetch(url)


async def _search_literature(query: str, max_results: int) -> dict[str, Any]:
    from services.literature import search_literature

    return await search_literature(query, max_results)


async def _tide_level(latitude: float, longitude: float, radius_km: float) -> dict[str, Any]:
    from services.tides import nearest_station

    return await nearest_station(latitude, longitude, radius_km)


async def _argo_profile(latitude: float, longitude: float, radius_km: float, lookback_days: int) -> dict[str, Any]:
    from services.argo import nearest_profile

    return await nearest_profile(latitude, longitude, radius_km, lookback_days)


async def _drift_trajectory(
    latitude: float, longitude: float, preset: str, horizon_hours: float
) -> dict[str, Any]:
    """A trimmed view of `drift_trajectory.plan_trajectory`'s ensemble: the
    100 raw member tracks would swamp the model's context for no benefit, so
    this reports the median path at a 12-hourly cadence plus one spread
    number — how far the 90th-percentile member sits from the median at the
    end of the horizon, which is the "how big is the search area" question a
    SAR-style answer actually needs."""
    import math

    from services.drift import resolve_alpha
    from services.drift_trajectory import plan_trajectory

    alpha = resolve_alpha(None, preset)
    result = await plan_trajectory(latitude, longitude, alpha, True, horizon_hours=horizon_hours)

    median = result["median_track"]
    final_hour = median[-1]["hour"]
    final_median = median[-1]

    distances_km = []
    for member in result["members"]:
        point = member["track"][-1]
        dlat_km = (point["lat"] - final_median["lat"]) * 111.32
        dlon_km = (point["lon"] - final_median["lon"]) * 111.32 * math.cos(math.radians(final_median["lat"]))
        distances_km.append(math.hypot(dlat_km, dlon_km))
    distances_km.sort()
    p90_index = min(len(distances_km) - 1, round(0.9 * (len(distances_km) - 1)))

    return {
        "start": result["start"],
        "object": preset,
        "leeway_alpha": result["leeway_alpha"],
        "median_track": [p for p in median if p["hour"] % 12 == 0 or p["hour"] == final_hour],
        "search_radius_90th_percentile_km_at_horizon": round(distances_km[p90_index], 1),
        # A plain value, not just the number above's field *name* — found
        # live: the grounding checker's own identifier guard (a digit run
        # preceded by a letter/underscore is a serial, not a quantity — see
        # agent._QUANTITY) means "90" inside "_90th_percentile" is never
        # credited as shown, so a model explaining the figure as "a 90%
        # confidence radius" got flagged on every single drift-trajectory
        # answer, deterministically, since this field name never changes.
        "search_radius_percentile": 90,
        "provenance": result["provenance"],
        "degraded_terms": result["degraded_terms"],
        "note": result["note"],
    }


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
        "get_forecast_trend",
        "Forecast one variable at one coordinate across multiple horizons, with "
        "recent observed history, so the trend can be plotted as a chart. Use "
        "this instead of get_point_forecast when the user wants to see how a "
        "value changes over time, a trend, a trajectory, or asks for a graph. "
        "Only works for variables whose forecast_available is true.",
        ForecastTrendArgs,
        _forecast_trend,
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
        "get_cyclone_alerts",
        "Active tropical cyclones worldwide, and whether one is within a "
        "given radius of a coordinate. From GDACS (aggregating JTWC and "
        "national warning centres), not a live track — position is the most "
        "recently reported fix.",
        CycloneArgs,
        _cyclone_alerts,
    ),
    (
        "get_severe_weather_alerts",
        "India Meteorological Department severe-weather warnings (heavy "
        "rain, heatwave, cold wave, thunderstorm/lightning, ...) whose "
        "warned area covers a coordinate. Nationwide coverage, not scoped to "
        "the coast; not a cyclone-track bulletin — use get_cyclone_alerts "
        "for that.",
        PointArgs,
        _severe_weather_alerts,
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
        "Check a coordinate against India's EEZ (mainland, including "
        "Lakshadweep, and the Andaman & Nicobar Islands as a separate zone), "
        "the India-Sri Lanka maritime boundary (IMBL), and nearby Marine "
        "Protected Areas. The EEZ/IMBL geometry is real (Marine Regions and "
        "the India-Sri Lanka treaty line); the Marine Protected Area list is "
        "still a hand-curated set of named sites, not a surveyed footprint.",
        PointArgs,
        _geofence,
    ),
    (
        "plan_safe_route",
        "Plan a route between two coordinates with an A* search over a live "
        "hazard grid — land, the IMBL and Marine Protected Areas are "
        "excluded from the search outright (the route cannot cross them, "
        "not merely flagged after the fact) and the path prefers lower wave "
        "height when a calmer detour exists. May report that no route could "
        "be planned if the points are too enclosed or a detour would exceed "
        "the search area.",
        RouteArgs,
        _safe_route,
    ),
    (
        "get_documentation",
        "Look up MarisAI's own documentation for questions about the "
        "platform itself — how to use a feature, where a page lives, what a "
        "term or badge means (e.g. 'how do I read the map colours', 'what "
        "does grounded mean', 'where's the download page'). Returns "
        "matching doc chapters with an excerpt and a /docs link. Not for "
        "ocean data — this is about the product, not the ocean.",
        DocumentationArgs,
        _get_documentation,
    ),
    (
        "assess_marine_risk",
        "Deterministic 'is it safe to go out' verdict for a coordinate: a "
        "fixed rule table over live sea conditions, IMD severe-weather "
        "alerts, active cyclones and boundary/Marine Protected Area "
        "proximity, producing a risk_level (low/moderate/high/extreme) that "
        "does not vary with how the model phrases it. Prefer this over "
        "combining the individual condition/alert tools yourself when the "
        "question is explicitly about safety.",
        PointArgs,
        _assess_risk,
    ),
    (
        "analyze_variable_correlation",
        "Align 2-4 ocean variables in time at one coordinate and measure "
        "whether they moved together (Pearson correlation on a shared daily "
        "cadence). Use for 'why has X changed' questions that need more than "
        "one variable, e.g. does chlorophyll track sea surface temperature "
        "here. Reports strength and statistical significance, never a causal "
        "claim — correlation is not causation.",
        CorrelationArgs,
        _correlate,
    ),
    (
        "web_search",
        "Search the open web for current information MarisAI's own ocean "
        "data cannot provide — news, explanations of an unusual event, "
        "context beyond a measured number. Returns a ranked list of "
        "{title, url, snippet, published_date}. Always attribute what you "
        "relay to its source; a web result is a claim someone made, not a "
        "MarisAI measurement.",
        WebSearchArgs,
        _web_search,
    ),
    (
        "fetch_webpage",
        "Fetch one specific webpage (e.g. a URL web_search returned, or one "
        "the user gave you) and return its title and readable text. Only "
        "plain public http(s) HTML/text pages can be fetched — not a search "
        "query, and not a PDF or image.",
        FetchWebpageArgs,
        _fetch_webpage,
    ),
    (
        "search_scientific_literature",
        "Search published, peer-reviewed scientific literature (via "
        "CrossRef) for a topic, species or research question. Returns "
        "{title, authors, journal, published, doi, url} per paper — use the "
        "DOI/URL to cite it, never restate a finding as MarisAI's own.",
        LiteratureArgs,
        _search_literature,
    ),
    (
        "get_tide_level",
        "Current measured sea level at the nearest INCOIS tide-gauge station "
        "to a coordinate (~50 Indian coastal stations), with a rising/"
        "falling/steady trend. This is a real-time gauge reading — it folds "
        "in storm surge and wave setup along with the astronomical tide — "
        "not a predicted tide table; no keyless Indian tide-prediction feed "
        "exists. Reports if the nearest station is out of range or not "
        "currently reporting rather than guessing a value.",
        TideArgs,
        _tide_level,
    ),
    (
        "get_argo_profile",
        "The nearest real ARGO float's measured temperature and salinity by "
        "depth (roughly surface to 2000 m) near a coordinate — the only "
        "in-situ, instrument-measured check on subsurface conditions this "
        "platform has. ARGO floats profile on a ~10-day cycle and are "
        "sparse (about one per 3 degrees globally), so report if none is "
        "within range rather than guessing; a profile found may be several "
        "days old, and its own timestamp says how old.",
        ArgoArgs,
        _argo_profile,
    ),
    (
        "plan_drift_trajectory",
        "Forecast where a drifting object (a person overboard, a life raft, "
        "an oil slick) will be over the next 6-96 hours, starting from a "
        "coordinate — a probability envelope from a 100-member ensemble, "
        "not one predicted position. Use for 'where will X end up' or "
        "search-and-rescue-shaped questions; get_current_conditions and "
        "get_active_alerts answer 'what is happening now', not this.",
        DriftTrajectoryArgs,
        _drift_trajectory,
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
