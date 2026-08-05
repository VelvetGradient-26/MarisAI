"""Data-source health for the dashboard's provider panel.

Reports what each integration's *cache* looks like — connected, how long its
last refresh took, when it last succeeded — rather than pinging each provider
on request. Polling seven upstreams every five minutes to render status lights
would generate more traffic than the dashboard's actual data, and would report
a provider as down whenever a probe raced a refresh.

Staleness is judged against each source's own refresh interval, because these
differ by two orders of magnitude: buoy observations every ten minutes,
satellite capabilities every six hours. A single global threshold would
permanently red-light the slow sources or permanently green-light the dead
fast ones.

**`last_sync` is when the cache last refreshed, not the timestep it holds.**
Those are different questions and conflating them was wrong: the Copernicus
wind product routinely publishes a step ~30 hours behind real time, so judging
on the timestep reported a provider as `down` two minutes after a completely
successful fetch. The data's own age travels separately as `data_timestamp`,
which is information about the product rather than about the connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from services import copernicus_sst, copernicus_wind, crw, gibs, ndbc, ocean_state, predictions


@dataclass(frozen=True)
class ProviderStatus:
    key: str
    name: str
    category: str
    # Seconds after which the last successful sync counts as stale. Derived
    # from each service's own refresh cadence, with headroom for one missed
    # cycle before the panel turns amber.
    stale_after_s: float
    probe: Callable[[], dict[str, Any]]
    notes: str | None = None


def _timestamp_health(fetched_at: str | None, stale_after_s: float) -> str:
    if fetched_at is None:
        return "down"
    try:
        parsed = datetime.fromisoformat(fetched_at)
    except ValueError:
        return "unknown"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    age = (datetime.now(timezone.utc) - parsed).total_seconds()
    if age <= stale_after_s:
        return "healthy"
    # One missed cycle is degraded; several is down. A source that refreshes
    # every six hours should not read as failed twenty minutes late.
    if age <= stale_after_s * 3:
        return "degraded"
    return "down"


def _cache_probe(
    is_available: Callable[[], bool],
    health: Callable[[], dict[str, Any]],
) -> Callable[[], dict[str, Any]]:
    def probe() -> dict[str, Any]:
        if not is_available():
            return {"connected": False, "latency_ms": None, "last_sync": None, "records": 0}
        return health()

    return probe


def _sst_probe() -> dict[str, Any]:
    if not copernicus_sst.is_available():
        return {"connected": False, "latency_ms": None, "last_sync": None, "records": 0}
    meta = copernicus_sst.get_meta()
    return {
        "connected": True,
        "latency_ms": None,
        "last_sync": meta["fetched_at"],
        "data_timestamp": meta["timestamp"],
        "records": 1,
    }


def _wind_probe() -> dict[str, Any]:
    if not copernicus_wind.is_available():
        return {"connected": False, "latency_ms": None, "last_sync": None, "records": 0}
    meta = copernicus_wind.get_meta()
    return {
        "connected": True,
        "latency_ms": None,
        "last_sync": meta["fetched_at"],
        "data_timestamp": meta["timestamp"],
        "records": 1,
    }


def _predictions_probe() -> dict[str, Any]:
    if not predictions.available():
        return {"connected": False, "latency_ms": None, "last_sync": None, "records": 0}
    try:
        manifest = predictions.manifest()
    except predictions.PredictionError:
        return {"connected": False, "latency_ms": None, "last_sync": None, "records": 0}
    return {
        "connected": True,
        "latency_ms": None,
        "last_sync": manifest.get("generated"),
        "records": len(manifest.get("products", {})),
    }


_HOUR = 3600.0

PROVIDERS: tuple[ProviderStatus, ...] = (
    ProviderStatus(
        key="copernicus_sst",
        name="Copernicus Marine — SST",
        category="Model",
        stale_after_s=4 * _HOUR,
        probe=_sst_probe,
        notes="Global thetao grid refreshed every 3 hours.",
    ),
    ProviderStatus(
        key="copernicus_wind",
        name="Copernicus Marine — Wind",
        category="Model",
        stale_after_s=2 * _HOUR,
        probe=_wind_probe,
        notes="Global wind field refreshed hourly.",
    ),
    ProviderStatus(
        key="copernicus_ocean_state",
        name="Copernicus Marine — Ocean State",
        category="Model",
        stale_after_s=4 * _HOUR,
        probe=_cache_probe(ocean_state.is_available, ocean_state.health),
        notes="Currents, salinity, chlorophyll, oxygen and waves.",
    ),
    ProviderStatus(
        key="noaa_crw",
        name="NOAA Coral Reef Watch",
        category="Satellite",
        stale_after_s=8 * _HOUR,
        probe=_cache_probe(crw.is_available, crw.health),
        notes="Daily 5km heat-stress suite via ERDDAP.",
    ),
    ProviderStatus(
        key="noaa_ndbc",
        name="NOAA NDBC Buoys",
        category="Observation",
        stale_after_s=30 * 60,
        probe=_cache_probe(ndbc.is_available, ndbc.health),
        notes="Latest report from every active station.",
    ),
    ProviderStatus(
        key="nasa_gibs",
        name="NASA GIBS",
        category="Satellite",
        stale_after_s=8 * _HOUR,
        probe=_cache_probe(gibs.is_available, gibs.health),
        notes="Satellite product availability and freshness.",
    ),
    ProviderStatus(
        key="marisai_ml",
        name="MarisAI ML Exports",
        category="Model",
        # An offline export; it is current until the pipeline is re-run, so
        # only a very old manifest is worth flagging.
        stale_after_s=90 * 24 * _HOUR,
        probe=_predictions_probe,
        notes="Habitat suitability and HAB early-warning grids.",
    ),
)


def build() -> dict[str, Any]:
    """Status for every provider the dashboard depends on."""
    entries = []
    for provider in PROVIDERS:
        try:
            result = provider.probe()
        except Exception as exc:  # noqa: BLE001 - one bad probe must not 500 the panel
            result = {
                "connected": False,
                "latency_ms": None,
                "last_sync": None,
                "records": 0,
                "error": str(exc),
            }

        connected = bool(result.get("connected"))
        health_state = (
            _timestamp_health(result.get("last_sync"), provider.stale_after_s)
            if connected
            else "down"
        )

        entries.append(
            {
                "key": provider.key,
                "name": provider.name,
                "category": provider.category,
                "connected": connected,
                "health": health_state,
                "latency_ms": result.get("latency_ms"),
                "last_sync": result.get("last_sync"),
                # The age of the data itself, where it differs meaningfully
                # from the refresh time. Shown, but never used to judge health.
                "data_timestamp": result.get("data_timestamp"),
                "records": result.get("records", 0),
                "notes": provider.notes,
                "error": result.get("error"),
            }
        )

    summary = {
        state: sum(1 for entry in entries if entry["health"] == state)
        for state in ("healthy", "degraded", "down", "unknown")
    }

    return {
        "providers": entries,
        "summary": summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
