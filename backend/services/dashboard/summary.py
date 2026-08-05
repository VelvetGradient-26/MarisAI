"""The dashboard's KPI row — six headline numbers about the global ocean.

Every card is assembled from a cached global field, so this module does no
network I/O: it reads what `copernicus_sst`, `ocean_state`, `crw` and
`predictions` already hold and shapes it for display.

The rule this module exists to enforce is that **a card whose source has not
loaded reports itself unavailable rather than substituting a number.** Each
KPI carries `available`, a `source`, and — where the underlying product is
regional or proxy-based — a `scope` note, so the UI never has to guess how
much to trust a figure. `_card` is the single place that shape is built.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services import copernicus_sst, crw, ocean_state, predictions
from services.dashboard import history
from services.dashboard.formatting import describe_location

# Habitat suitability is a regional model (see the manifest's `region`), so
# the card names the species and month it is reporting rather than implying a
# global index.
_DEFAULT_HABITAT_SPECIES = "yellowfin_tuna"


# Roughly how long each source's first fetch takes, measured on a warm
# network. Used only to drive a progress indicator — the UI needs something to
# animate against, and an honest estimate beats a spinner that says nothing.
WARMUP_SECONDS = {
    "sea_surface_temperature": 25,
    "chlorophyll_a": 90,
    "current_speed": 90,
    "marine_heatwaves": 90,
    "coral_bleaching": 90,
    "habitat_suitability": 5,
}


def _card(
    key: str,
    label: str,
    *,
    value: Any = None,
    unit: str | None = None,
    available: bool,
    source: str | None = None,
    observed_at: str | None = None,
    detail: str | None = None,
    scope: str | None = None,
    unavailable_reason: str | None = None,
    warming: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    """One KPI card.

    `status` is three-way on purpose. "Still fetching" and "this failed" look
    identical if both render as an error, and on a cold start every Copernicus
    card is the former for a minute or so — showing six failures for a system
    that is simply starting up is both alarming and wrong.
    """
    status = "ready" if available else ("warming" if warming else "unavailable")
    card: dict[str, Any] = {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "available": available,
        "status": status,
        "expected_warmup_seconds": WARMUP_SECONDS.get(key) if status == "warming" else None,
        "source": source,
        "observed_at": observed_at,
        "detail": detail,
        "scope": scope,
        "unavailable_reason": unavailable_reason,
    }
    card.update(extra)
    return card


def _sst_card() -> dict[str, Any]:
    try:
        stats = copernicus_sst.global_stats()
    except copernicus_sst.CopernicusSstError as exc:
        return _card(
            "sea_surface_temperature",
            "Global Mean SST",
            available=False,
            warming=copernicus_sst.is_refreshing(),
            unavailable_reason=str(exc),
        )

    # The anomaly comes from CRW, which carries a real 1985-2012 climatology.
    # Without it the card still shows the absolute temperature and simply has
    # no comparison to make — inventing a baseline would be worse.
    anomaly: float | None = None
    baseline: str | None = None
    if crw.is_available():
        try:
            anomaly_summary = crw.sst_anomaly_summary()
            anomaly = anomaly_summary["mean_anomaly_c"]
            baseline = anomaly_summary["baseline"]
        except crw.CrwError:
            anomaly = None

    return _card(
        "sea_surface_temperature",
        "Global Mean SST",
        value=stats["mean_c"],
        unit="°C",
        available=True,
        source=stats["source"],
        observed_at=stats["timestamp"],
        detail=f"Range {stats['min_c']}°C to {stats['max_c']}°C",
        scope="Area-weighted global mean, surface (0.49 m)",
        anomaly_c=anomaly,
        anomaly_baseline=baseline,
    )


def _field_card(
    key: str,
    label: str,
    *,
    field_key: str,
    unit: str,
    scope: str,
    decimals: int = 3,
    detail_from_percentiles: bool = False,
) -> dict[str, Any]:
    """A KPI backed by one of the cached global ocean-state fields."""
    stats = ocean_state.get_field(field_key)
    if stats is None:
        return _card(
            key,
            label,
            available=False,
            warming=ocean_state.is_refreshing(),
            unavailable_reason=(
                "The global ocean-state snapshot has not loaded this field yet."
            ),
        )

    detail = f"Max {stats['max']} {unit}"
    if detail_from_percentiles and "p99" in stats:
        detail = f"99th percentile {stats['p99']} {unit} · max {stats['max']} {unit}"

    return _card(
        key,
        label,
        value=round(float(stats["mean"]), decimals),
        unit=unit,
        available=True,
        source=ocean_state.SOURCE_LABEL,
        observed_at=stats.get("timestamp"),
        detail=detail,
        scope=scope,
        minimum=stats.get("min"),
        maximum=stats.get("max"),
    )


def _heatwave_card() -> dict[str, Any]:
    if not crw.is_available():
        return _card(
            "marine_heatwaves",
            "Marine Heat Stress Regions",
            available=False,
            warming=crw.is_refreshing(),
            unavailable_reason="The Coral Reef Watch grid has not loaded yet.",
        )
    try:
        summary = crw.marine_heatwave_summary()
    except crw.CrwError as exc:
        return _card(
            "marine_heatwaves",
            "Marine Heat Stress Regions",
            available=False,
            warming=crw.is_refreshing(),
            unavailable_reason=str(exc),
        )

    largest = summary["largest_regions"][0] if summary["largest_regions"] else None
    detail = (
        f"{summary['ocean_fraction'] * 100:.1f}% of tracked ocean under heat stress"
    )
    if largest:
        location = largest["peak_location"]
        detail += (
            f" · largest {largest['area_km2']:,} km² "
            f"peaking {largest['peak_hotspot_c']}°C at "
            f"{describe_location(location['latitude'], location['longitude'])}"
        )

    return _card(
        "marine_heatwaves",
        "Marine Heat Stress Regions",
        value=summary["region_count"],
        unit="regions",
        available=True,
        source=summary["source"],
        observed_at=summary["observed_at"],
        detail=detail,
        # The card states its own definition — this is a NOAA heat-stress
        # criterion, not the formal marine-heatwave definition.
        scope=summary["definition"],
        ocean_fraction=summary["ocean_fraction"],
        largest_regions=summary["largest_regions"],
    )


def _bleaching_card() -> dict[str, Any]:
    if not crw.is_available():
        return _card(
            "coral_bleaching",
            "Coral Bleaching Risk",
            available=False,
            warming=crw.is_refreshing(),
            unavailable_reason="The Coral Reef Watch grid has not loaded yet.",
        )
    try:
        summary = crw.bleaching_summary()
    except crw.CrwError as exc:
        return _card(
            "coral_bleaching",
            "Coral Bleaching Risk",
            available=False,
            warming=crw.is_refreshing(),
            unavailable_reason=str(exc),
        )

    return _card(
        "coral_bleaching",
        "Coral Bleaching Risk",
        value=summary["risk"],
        unit=None,
        available=True,
        source=summary["source"],
        observed_at=summary["observed_at"],
        detail=(
            f"{summary['bleaching_likely_fraction'] * 100:.1f}% of reef water at "
            f"DHW ≥ {summary['thresholds']['bleaching_likely_dhw']} °C-weeks "
            f"· peak {summary['max_dhw_c_weeks']} °C-weeks"
        ),
        scope=summary["coverage"],
        max_dhw_c_weeks=summary["max_dhw_c_weeks"],
        alert_categories=summary["alert_categories"],
        bleaching_likely_fraction=summary["bleaching_likely_fraction"],
    )


def _habitat_card() -> dict[str, Any]:
    """Fish habitat suitability from the offline ML export.

    Deliberately *not* presented as a global index: the model covers the north
    Indian Ocean only, so the card reports that region, the species and the
    month, plus the model's measured skill.
    """
    if not predictions.available():
        return _card(
            "habitat_suitability",
            "Fish Habitat Suitability",
            available=False,
            unavailable_reason=(
                "No prediction export present — run the offline ML pipeline to "
                "generate habitat_suitability.nc."
            ),
        )

    try:
        manifest = predictions.manifest()
        habitat = manifest["products"]["habitat"]
        month = datetime.now(timezone.utc).month
        field = predictions.habitat_slice(_DEFAULT_HABITAT_SPECIES, month)
    except (predictions.PredictionError, KeyError) as exc:
        return _card(
            "habitat_suitability",
            "Fish Habitat Suitability",
            available=False,
            unavailable_reason=str(exc),
        )

    import numpy as np

    values = np.asarray(field.values, dtype=float)
    valid = np.isfinite(values)
    if not valid.any():
        return _card(
            "habitat_suitability",
            "Fish Habitat Suitability",
            available=False,
            unavailable_reason="Habitat grid holds no valid cells for this month.",
        )

    species_label = next(
        (
            entry["label"]
            for entry in habitat.get("species", [])
            if entry["key"] == _DEFAULT_HABITAT_SPECIES
        ),
        _DEFAULT_HABITAT_SPECIES,
    )
    region = habitat.get("region", {})
    metrics = habitat.get("metrics", {}).get("lightgbm", {})
    month_name = datetime(2000, month, 1).strftime("%B")

    return _card(
        "habitat_suitability",
        "Fish Habitat Suitability",
        value=round(float(np.mean(values[valid])), 3),
        unit="index",
        available=True,
        source="MarisAI habitat model (presence-only SDM)",
        observed_at=manifest.get("generated"),
        detail=(
            f"{species_label}, {month_name} · "
            f"{float(np.mean(values[valid] >= 0.5)) * 100:.0f}% of cells above 0.5"
        ),
        scope=(
            f"{region.get('name', 'regional').replace('_', ' ').title()} "
            f"({region.get('west')}–{region.get('east')}°E, "
            f"{region.get('south')}–{region.get('north')}°N) — regional model, "
            f"not a global index"
        ),
        species=_DEFAULT_HABITAT_SPECIES,
        species_label=species_label,
        month=month,
        roc_auc=metrics.get("roc_auc"),
        tss=metrics.get("tss"),
    )


def build() -> dict[str, Any]:
    """The six KPI cards, plus which sources were reachable.

    Each numeric card is recorded into `history` and carries back whatever
    sparkline has accumulated. On a freshly started server that is empty, and
    the card says so rather than drawing a line from one point.
    """
    cards = [
        _sst_card(),
        _field_card(
            "chlorophyll_a",
            "Mean Chlorophyll-a",
            field_key="chlorophyll_a",
            unit="mg/m³",
            scope="Area-weighted global mean, surface",
        ),
        _field_card(
            "current_speed",
            "Mean Current Speed",
            field_key="current_speed",
            unit="m/s",
            scope="Area-weighted global mean of √(u²+v²), surface",
            detail_from_percentiles=True,
        ),
        _heatwave_card(),
        _bleaching_card(),
        _habitat_card(),
    ]

    for card in cards:
        if card["available"] and isinstance(card["value"], (int, float)):
            history.record(card["key"], float(card["value"]))
        card["sparkline"] = history.series(card["key"])
        card["trend"] = history.trend(card["key"])

    return {
        "cards": cards,
        "available_count": sum(1 for card in cards if card["available"]),
        "history_note": (
            "Sparklines show values observed since this server started; they are "
            "not persisted across restarts."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
