"""The dashboard's live feed — the freshest thing each source has.

Mixes genuine *observations* (buoys reporting minutes ago) with the newest
model and satellite products, because "what just landed" is the question the
panel answers and the answer legitimately comes from all three.

Everything is read from caches, so a one-minute poll costs nothing upstream.
Each entry carries its own `observed_at` and the feed reports its age, which
is the part that makes it read as live rather than merely recent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services import copernicus_sst, crw, gibs, ndbc, ocean_state


def _age_seconds(timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - parsed).total_seconds()
    # Date-only products (a daily satellite layer) are stamped at noon UTC,
    # so one published for today reads as future-dated before noon. A
    # negative age is never meaningful to display; floor it at zero.
    return round(max(age, 0.0), 1)


def _entry(
    *,
    kind: str,
    title: str,
    source: str,
    observed_at: str | None,
    available: bool = True,
    unavailable_reason: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "title": title,
        "source": source,
        "observed_at": observed_at,
        "age_seconds": _age_seconds(observed_at),
        "available": available,
        "unavailable_reason": unavailable_reason,
        **fields,
    }


def _buoys(
    limit: int,
    latitude: float | None,
    longitude: float | None,
) -> list[dict[str, Any]]:
    if not ndbc.is_available():
        return [
            _entry(
                kind="buoy",
                title="NOAA buoy network",
                source=ndbc.SOURCE_LABEL,
                observed_at=None,
                available=False,
                unavailable_reason="Buoy feed has not loaded yet.",
            )
        ]

    try:
        observations = ndbc.latest(limit=limit, latitude=latitude, longitude=longitude)
    except ndbc.NdbcError as exc:
        return [
            _entry(
                kind="buoy",
                title="NOAA buoy network",
                source=ndbc.SOURCE_LABEL,
                observed_at=None,
                available=False,
                unavailable_reason=str(exc),
            )
        ]

    return [
        _entry(
            kind="buoy",
            title=f"Station {observation['station_id']}",
            source=ndbc.SOURCE_LABEL,
            observed_at=observation["observed_at"],
            station_id=observation["station_id"],
            latitude=observation["latitude"],
            longitude=observation["longitude"],
            distance_km=observation.get("distance_km"),
            water_temperature_c=observation["water_temperature_c"],
            wave_height_m=observation["wave_height_m"],
            wind_speed_ms=observation["wind_speed_ms"],
            wind_gust_ms=observation["wind_gust_ms"],
            pressure_hpa=observation["pressure_hpa"],
            air_temperature_c=observation["air_temperature_c"],
            relative_humidity_pct=observation["relative_humidity_pct"],
        )
        for observation in observations
    ]


def _satellite() -> dict[str, Any]:
    if not gibs.is_available():
        return _entry(
            kind="satellite",
            title="NASA satellite products",
            source=gibs.SOURCE_LABEL,
            observed_at=None,
            available=False,
            unavailable_reason="Satellite product listing has not loaded yet.",
        )

    product = gibs.latest_product()
    if product is None:
        return _entry(
            kind="satellite",
            title="NASA satellite products",
            source=gibs.SOURCE_LABEL,
            observed_at=None,
            available=False,
            unavailable_reason="No tracked products are currently published.",
        )

    return _entry(
        kind="satellite",
        title=f"{product['satellite']} — {product['product']}",
        source=gibs.SOURCE_LABEL,
        # A daily product's date is a date, not an instant; noon UTC is used
        # so the age readout is not systematically off by half a day.
        observed_at=f"{product['latest_date']}T12:00:00+00:00"
        if product["latest_date"]
        else None,
        satellite=product["satellite"],
        product=product["product"],
        resolution=product["resolution"],
        cadence=product["cadence"],
        status=product["status"],
        coverage="Global",
    )


def _copernicus() -> dict[str, Any]:
    try:
        meta = copernicus_sst.get_meta()
    except copernicus_sst.CopernicusSstError as exc:
        return _entry(
            kind="model",
            title="Copernicus Marine — SST analysis",
            source=copernicus_sst.SOURCE_LABEL,
            observed_at=None,
            available=False,
            unavailable_reason=str(exc),
        )

    return _entry(
        kind="model",
        title="Copernicus Marine — SST analysis",
        source=meta["source"],
        observed_at=meta["timestamp"],
        dataset=copernicus_sst.DATASET_ID,
        depth_m=meta["depth_m"],
        coverage="Global, 0.083°",
    )


def _coral() -> dict[str, Any]:
    if not crw.is_available():
        return _entry(
            kind="satellite",
            title="NOAA Coral Reef Watch — heat stress",
            source=crw.SOURCE_LABEL,
            observed_at=None,
            available=False,
            unavailable_reason="Coral Reef Watch grid has not loaded yet.",
        )
    meta = crw.meta()
    return _entry(
        kind="satellite",
        title="NOAA Coral Reef Watch — heat stress",
        source=meta["source"],
        observed_at=meta["observed_at"],
        coverage=f"Global, {meta['grid_spacing_deg']}°",
        citation=meta["citation"],
    )


def _ocean_state() -> dict[str, Any]:
    if not ocean_state.is_available():
        return _entry(
            kind="model",
            title="Copernicus Marine — ocean state",
            source=ocean_state.SOURCE_LABEL,
            observed_at=None,
            available=False,
            unavailable_reason="Global ocean-state snapshot has not loaded yet.",
        )

    snapshot = ocean_state.summary()
    waves = snapshot["fields"].get("wave_height", {})
    return _entry(
        kind="model",
        title="Copernicus Marine — ocean state",
        source=ocean_state.SOURCE_LABEL,
        observed_at=waves.get("timestamp") or snapshot.get("fetched_at"),
        fields=sorted(snapshot["fields"]),
        coverage="Global",
    )


def build(
    limit: int = 6,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict[str, Any]:
    """The live feed. Pass a point to get the nearest buoys instead of the newest."""
    entries = [
        *_buoys(limit, latitude, longitude),
        _satellite(),
        _coral(),
        _copernicus(),
        _ocean_state(),
    ]

    return {
        "entries": entries,
        "buoy_count": sum(1 for entry in entries if entry["kind"] == "buoy" and entry["available"]),
        "near": {"latitude": latitude, "longitude": longitude}
        if latitude is not None and longitude is not None
        else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
