"""Dashboard alerts, derived from thresholds on real fields.

Every alert here is a *rule applied to observed data*, not a feed of curated
incidents. That distinction matters for how they read: this is not NOAA's
warning service, and an alert saying "high seas" means "the wave model's 99th
percentile is above 7m somewhere", not "a marine warning has been issued".
Each alert therefore carries the rule that produced it in `basis`.

Rules and their sources:
  * Coral heat stress   — CRW degree heating weeks past NOAA's own thresholds.
  * Marine heat stress  — CRW HotSpot regions above the stress criterion.
  * High seas           — global wave-height percentiles from `ocean_state`.
  * Harmful algal bloom — the Arabian Sea HAB model's own forecast grid.

An alert is only raised from a source that actually loaded; a missing source
produces no alert rather than a reassuring absence, and `sources_unavailable`
reports which rules could not be evaluated so the panel can say so.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal

from services import crw, ocean_state, predictions
from services.dashboard.formatting import describe_location

Severity = Literal["critical", "warning", "advisory"]

# Ordering for display — most severe first.
_SEVERITY_RANK: dict[str, int] = {"critical": 0, "warning": 1, "advisory": 2}

# Significant wave height thresholds. 9m is a phenomenal/very high sea by the
# Douglas scale and 6m is "very rough"; both are widely used marine cut-offs.
_WAVE_CRITICAL_M = 9.0
_WAVE_WARNING_M = 6.0

# Bloom probability from the HAB model above which the forecast is worth
# surfacing. The model's own reliability curve shows predictions above ~0.5
# verifying near or above their stated probability at the 3-day horizon.
_HAB_ALERT_PROBABILITY = 0.5
_HAB_HORIZON_DAYS = 3


def _alert_id(*parts: Any) -> str:
    """Stable id so the UI can dismiss an alert and have it stay dismissed.

    Derived from the alert's content rather than a counter: the same stress at
    the same place keeps its id across refreshes, and a genuinely new one gets
    a new id.
    """
    digest = hashlib.sha1("|".join(str(part) for part in parts).encode()).hexdigest()
    return digest[:12]


def _alert(
    *,
    kind: str,
    title: str,
    severity: Severity,
    region: str,
    basis: str,
    observed_at: str | None,
    source: str,
    latitude: float | None = None,
    longitude: float | None = None,
    **extra: Any,
) -> dict[str, Any]:
    alert = {
        "id": _alert_id(kind, region, round(latitude or 0, 2), round(longitude or 0, 2)),
        "kind": kind,
        "title": title,
        "severity": severity,
        "region": region,
        "basis": basis,
        "observed_at": observed_at,
        "source": source,
        "latitude": latitude,
        "longitude": longitude,
        "status": "active",
    }
    alert.update(extra)
    return alert


def _coral_alerts() -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    try:
        summary = crw.bleaching_summary()
        spots = crw.hotspots(limit=5)
    except crw.CrwError:
        return alerts

    for spot in spots:
        dhw = spot["dhw_c_weeks"]
        if dhw >= crw.DHW_MORTALITY_LIKELY:
            severity: Severity = "critical"
            title = "Coral mortality risk"
        elif dhw >= crw.DHW_BLEACHING_LIKELY:
            severity = "warning"
            title = "Coral bleaching likely"
        else:
            continue

        alerts.append(
            _alert(
                kind="coral_bleaching",
                title=title,
                severity=severity,
                region=describe_location(spot["latitude"], spot["longitude"]),
                basis=(
                    f"Degree heating weeks {dhw} °C-weeks "
                    f"(NOAA {spot['alert_label']}); bleaching is expected above "
                    f"{crw.DHW_BLEACHING_LIKELY} and mortality above "
                    f"{crw.DHW_MORTALITY_LIKELY}."
                ),
                observed_at=summary["observed_at"],
                source=crw.SOURCE_LABEL,
                latitude=spot["latitude"],
                longitude=spot["longitude"],
                dhw_c_weeks=dhw,
                alert_level=spot["alert_level"],
            )
        )
    return alerts


def _heat_stress_alerts() -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    try:
        summary = crw.marine_heatwave_summary()
    except crw.CrwError:
        return alerts

    for region in summary["largest_regions"][:3]:
        location = region["peak_location"]
        # Only the genuinely large features are worth an alert; the count
        # itself is already on the KPI card.
        if region["area_km2"] < 1_000_000:
            continue
        alerts.append(
            _alert(
                kind="marine_heat_stress",
                title="Large marine heat-stress region",
                severity="warning" if region["peak_hotspot_c"] >= 2 else "advisory",
                region=describe_location(location["latitude"], location["longitude"]),
                basis=(
                    f"{region['area_km2']:,} km² above the "
                    f"{crw.HOTSPOT_STRESS_C}°C HotSpot criterion, peaking at "
                    f"{region['peak_hotspot_c']}°C above the maximum monthly mean."
                ),
                observed_at=summary["observed_at"],
                source=crw.SOURCE_LABEL,
                latitude=location["latitude"],
                longitude=location["longitude"],
                area_km2=region["area_km2"],
                peak_hotspot_c=region["peak_hotspot_c"],
            )
        )
    return alerts


def _wave_alerts() -> list[dict[str, Any]]:
    stats = ocean_state.get_field("wave_height")
    if stats is None:
        return []

    peak = float(stats.get("max", 0.0))
    if peak < _WAVE_WARNING_M:
        return []

    severity: Severity = "critical" if peak >= _WAVE_CRITICAL_M else "warning"
    return [
        _alert(
            kind="high_seas",
            title="High seas in the global wave field",
            severity=severity,
            # The peak's coordinates are not retained (only statistics are
            # kept from the grid), so this alert is explicitly global.
            region="Global maximum",
            basis=(
                f"Peak significant wave height {peak} m; 99th percentile "
                f"{stats.get('p99')} m. Warning above {_WAVE_WARNING_M} m, "
                f"critical above {_WAVE_CRITICAL_M} m."
            ),
            observed_at=stats.get("timestamp"),
            source=ocean_state.SOURCE_LABEL,
            peak_wave_height_m=peak,
            p99_wave_height_m=stats.get("p99"),
        )
    ]


def _bloom_alerts() -> list[dict[str, Any]]:
    if not predictions.available():
        return []

    try:
        import numpy as np

        manifest = predictions.manifest()
        field = predictions.hab_slice(_HAB_HORIZON_DAYS)
        values = np.asarray(field.values, dtype=float)
    except (predictions.PredictionError, KeyError):
        return []

    valid = np.isfinite(values)
    if not valid.any():
        return []

    peak = float(np.nanmax(values))
    if peak < _HAB_ALERT_PROBABILITY:
        return []

    index = np.unravel_index(np.nanargmax(np.where(valid, values, np.nan)), values.shape)
    latitude = float(np.asarray(field.latitude.values)[index[0]])
    longitude = float(np.asarray(field.longitude.values)[index[1]])

    hab = manifest["products"].get("hab", {})
    horizon = next(
        (
            entry
            for entry in hab.get("horizons", [])
            if entry.get("horizon_days") == _HAB_HORIZON_DAYS
        ),
        {},
    )
    region = hab.get("region", {})

    return [
        _alert(
            kind="algal_bloom",
            title="Elevated harmful algal bloom probability",
            severity="warning" if peak >= 0.7 else "advisory",
            region=(
                f"{region.get('name', 'model region').replace('_', ' ').title()} — "
                f"{describe_location(latitude, longitude)}"
            ),
            basis=(
                f"Modelled bloom probability {peak:.2f} at a {_HAB_HORIZON_DAYS}-day "
                f"horizon (PR-AUC {horizon.get('pr_auc')} vs persistence baseline "
                f"{horizon.get('persistence_pr_auc')})."
            ),
            observed_at=manifest.get("generated"),
            source="MarisAI HAB early-warning model",
            latitude=latitude,
            longitude=longitude,
            probability=round(peak, 3),
            horizon_days=_HAB_HORIZON_DAYS,
        )
    ]


def build() -> dict[str, Any]:
    """Evaluate every rule against whatever data is currently loaded."""
    unavailable: list[str] = []

    if crw.is_available():
        alerts = _coral_alerts() + _heat_stress_alerts()
    else:
        alerts = []
        unavailable.append("NOAA Coral Reef Watch (coral and heat-stress rules)")

    if ocean_state.get_field("wave_height") is not None:
        alerts += _wave_alerts()
    else:
        unavailable.append("Copernicus wave field (high-seas rule)")

    if predictions.available():
        alerts += _bloom_alerts()
    else:
        unavailable.append("HAB early-warning export (algal-bloom rule)")

    alerts.sort(key=lambda alert: _SEVERITY_RANK.get(alert["severity"], 9))

    return {
        "alerts": alerts,
        "counts": {
            severity: sum(1 for alert in alerts if alert["severity"] == severity)
            for severity in ("critical", "warning", "advisory")
        },
        "sources_unavailable": unavailable,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": (
            "Derived from thresholds applied to model and satellite fields. "
            "Not an official marine warning service and not suitable for navigation."
        ),
    }
