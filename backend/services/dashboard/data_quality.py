"""What data this platform actually has, and how good it is.

`health.py` answers "are the live caches connected right now" — seven
in-process caches and their refresh times. This module answers the question
underneath it, which nothing surfaced before: **what are the datasets, at what
resolution, over what period, under what licence, and how well does the model
trained on each of them actually score?**

All of it already existed and none of it was reachable. `download/catalog.py`
carries every provider's dataset id, grid spacing, native cadence, coverage
start and citation, and was read only by the downloader's size estimator.
`download/registry.py` maps the 36 spec variables onto those providers.
`forecasting/model_store.py` holds 115 trained models with per-fold validation
metrics. Assembling them is this module; nothing here fetches, computes or
estimates anything.

Three rules it inherits, all load-bearing:

* **Never substitute a number for missing data.** Every entry carries
  `available` and, when false, an `unavailable_reason` in words. A dataset
  with no live cache is not "0% fresh" — freshness is `None` and the reason
  says the platform does not hold a warm copy of it. This is the same rule the
  rest of `services/dashboard/` is built around, and a data-quality panel that
  broke it would be self-refuting.
* **Report the fold spread, never the aggregate alone.** The shipping bar is
  skill > 0 *and* at most one of five folds negative, because six rejected
  horizons printed `beats persistence` on the mean. A model-health panel
  showing only the mean shows precisely the number that would have shipped
  them, so `negative_folds` travels beside every skill score and drives the
  grade.
* **Freshness is judged per source, against its own cadence.** These differ by
  two orders of magnitude — buoys every ten minutes, satellite capability
  documents every six hours — so one global threshold would permanently
  red-light the slow sources and green-light the dead fast ones. Same reason
  `health.py` gives, and the thresholds are read from there rather than
  restated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from forecasting import grid_history, model_store
from forecasting.config import load_config
from services import forecast_tiles
from services.dashboard import health
from services.download import catalog, registry


class DataQualityError(RuntimeError):
    """The quality report could not be assembled."""


# Live in-process caches, keyed by the download-catalog provider they hold a
# warm copy of. Only a few providers have one: the map layers and dashboard
# KPIs need a resident global field, the other datasets are fetched per
# request by the downloader and are correctly reported as having no cache
# rather than as being unhealthy.
_CACHE_BY_PROVIDER: dict[str, str] = {
    catalog.PROVIDER_COPERNICUS_PHYSICS: "copernicus_sst",
    catalog.PROVIDER_COPERNICUS_WIND: "copernicus_wind",
}


def _cadence_label(steps_per_day: float, *, time_varying: bool) -> str:
    if not time_varying or steps_per_day == 0:
        return "time-invariant"
    if steps_per_day >= 24:
        return "hourly"
    if steps_per_day > 1:
        # 8 steps/day is 3-hourly. Derived rather than tabulated so a new
        # cadence in the catalog does not silently fall through to "daily".
        return f"{round(24 / steps_per_day)}-hourly"
    if steps_per_day == 1:
        return "daily"
    return f"every {round(1 / steps_per_day)} days"


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _grade_from_skill(skill: float | None, negative_folds: int, n_folds: int) -> str:
    """Encode the shipping rule as a grade, not the headline number.

    Mirrors `passes_bar` in the ML tracking module deliberately: two places
    computing "is this model good enough" from different clauses is how the
    two answers drift apart.
    """
    if skill is None or n_folds == 0:
        return "unknown"
    if skill <= 0:
        return "poor"
    if negative_folds > 1:
        # Beats persistence on the mean, carried by a minority of folds. This
        # is the case the aggregate hides.
        return "fair"
    if negative_folds == 1:
        return "good"
    return "strong"


@dataclass(frozen=True)
class _CacheState:
    available: bool
    last_sync: str | None
    health: str
    unavailable_reason: str | None


def _cache_state(provider_key: str) -> _CacheState:
    """Freshness of the live cache backing a provider, if it has one."""
    cache_key = _CACHE_BY_PROVIDER.get(provider_key)
    if cache_key is None:
        return _CacheState(
            available=False,
            last_sync=None,
            health="not_cached",
            unavailable_reason=(
                "no resident copy — this dataset is fetched per request by the "
                "downloader rather than held warm in process"
            ),
        )

    status = next((p for p in health.PROVIDERS if p.key == cache_key), None)
    if status is None:
        return _CacheState(
            available=False,
            last_sync=None,
            health="unknown",
            unavailable_reason=f"no health probe registered for cache {cache_key!r}",
        )

    try:
        result = status.probe()
    except Exception as exc:  # noqa: BLE001 - one bad probe must not fail the report
        return _CacheState(
            available=False,
            last_sync=None,
            health="down",
            unavailable_reason=f"health probe failed: {exc}",
        )

    if not result.get("connected"):
        return _CacheState(
            available=False,
            last_sync=None,
            health="down",
            unavailable_reason="initial fetch has not completed, or the last one failed",
        )

    last_sync = result.get("last_sync")
    return _CacheState(
        available=True,
        last_sync=last_sync,
        # Reuses health.py's per-source staleness thresholds rather than
        # inventing a second definition of "fresh".
        health=health.timestamp_health(last_sync, status.stale_after_s),
        unavailable_reason=None,
    )


def _variables_by_provider() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for code, info in registry.VARIABLE_REGISTRY.items():
        if info.provider is None:
            continue
        grouped.setdefault(info.provider, []).append(
            {
                "code": code,
                "label": info.label,
                "unit": info.unit,
                "category": info.category,
                "available": info.available,
                "depth_resolved": info.depth_resolved,
                "circular": info.circular,
                "derived": info.derived_from is not None,
            }
        )
    for entries in grouped.values():
        entries.sort(key=lambda entry: entry["code"])
    return grouped


def datasets() -> list[dict[str, Any]]:
    """Every upstream dataset the platform reads, and what it is."""
    by_provider = _variables_by_provider()
    entries: list[dict[str, Any]] = []

    for key, spec in catalog.PROVIDERS.items():
        variables = by_provider.get(key, [])
        cache = _cache_state(key)
        entries.append(
            {
                "key": key,
                "source_label": spec.source_label,
                "licence": spec.licence,
                "grid_spacing_deg": spec.grid_spacing_deg,
                "cadence": _cadence_label(
                    spec.steps_per_day, time_varying=spec.time_varying
                ),
                "steps_per_day": spec.steps_per_day,
                "coverage_start": _iso(spec.coverage_start),
                "time_varying": spec.time_varying,
                "forecast_horizon_days": spec.forecast_horizon_days,
                "max_points": spec.max_points,
                "variable_count": len(variables),
                "variables": variables,
                "cache": {
                    "available": cache.available,
                    "last_sync": cache.last_sync,
                    "health": cache.health,
                    "unavailable_reason": cache.unavailable_reason,
                },
            }
        )

    entries.sort(key=lambda entry: entry["key"])
    return entries


def models() -> list[dict[str, Any]]:
    """Every trained forecasting model, with the fold spread beside the mean."""
    entries: list[dict[str, Any]] = []

    for variable, horizons in model_store.list_trained().items():
        for horizon in sorted(horizons):
            try:
                described = model_store.describe(variable, horizon)
            except model_store.ModelStoreError as exc:
                # A corrupt or version-mismatched artifact is reported as
                # itself, not omitted. Silently shrinking the model list is
                # how a failed retrain looks like a healthy platform.
                entries.append(
                    {
                        "variable": variable,
                        "horizon": horizon,
                        "available": False,
                        "unavailable_reason": str(exc),
                    }
                )
                continue

            metrics = described.validation_metrics
            skill = metrics.get("skill_score")
            negative = described.negative_folds
            n_folds = len(described.folds)
            fold_skills = [
                fold["skill_score"]
                for fold in described.folds
                if isinstance(fold.get("skill_score"), (int, float))
            ]
            skipped = described.metadata.get("skipped_points") or []

            entries.append(
                {
                    "variable": variable,
                    "label": described.metadata.get("label", variable),
                    "unit": described.metadata.get("unit"),
                    "horizon": horizon,
                    "available": True,
                    "unavailable_reason": None,
                    "model_type": described.metadata.get("model_type"),
                    "target_mode": described.metadata.get("target_mode"),
                    "trained_at": described.metadata.get("trained_at"),
                    "training_rows": described.metadata.get("training_rows"),
                    "training_started": described.metadata.get("training_started"),
                    "training_ended": described.metadata.get("training_ended"),
                    "feature_count": described.metadata.get("feature_count"),
                    "covariates": described.metadata.get("covariates", []),
                    "skill_score": skill,
                    "rmse": metrics.get("rmse"),
                    "mae": metrics.get("mae"),
                    "r2": metrics.get("r2"),
                    "persistence_rmse": metrics.get("persistence_rmse"),
                    "n_folds": n_folds,
                    "negative_folds": negative,
                    "fold_skill_min": min(fold_skills) if fold_skills else None,
                    "fold_skill_max": max(fold_skills) if fold_skills else None,
                    "grade": _grade_from_skill(skill, negative, n_folds),
                    # A global model that lost points has lost *geography*.
                    # TODO.md §2 records rainfall training on 10 of 24 points,
                    # every one northern-hemisphere, with perfect-looking
                    # metrics — partial success is the dangerous failure mode.
                    "points_used": len(described.metadata.get("training_points") or []),
                    "points_skipped": len(skipped),
                    "confidence_level": (
                        described.metadata.get("residual_quantiles", {}) or {}
                    ).get("confidence_level"),
                }
            )

    entries.sort(key=lambda entry: (entry["variable"], entry["horizon"]))
    return entries


def coverage() -> dict[str, Any]:
    """How far each stage of the pipeline actually reaches.

    The three counts differ, and the gaps between them are the useful part:
    a variable can be servable but never forecast, or forecast but not visible
    on the map because its grid was never built.
    """
    served = {code: info for code, info in registry.VARIABLE_REGISTRY.items() if info.available}
    unavailable = [
        {"code": code, "label": info.label}
        for code, info in registry.VARIABLE_REGISTRY.items()
        if not info.available
    ]

    trained = model_store.list_trained()
    try:
        gridded = set(forecast_tiles.available())
    except Exception as exc:  # noqa: BLE001 - a missing grid dir must not fail the report
        gridded = set()
        grid_error: str | None = str(exc)
    else:
        grid_error = None

    try:
        configured = set(load_config().variables)
    except Exception as exc:  # noqa: BLE001 - a bad YAML must not fail the report
        configured = set()
        config_error: str | None = str(exc)
    else:
        config_error = None

    # Configured to forecast but with no model on disk. Distinct from
    # "not configured": one is pending work, the other is a deliberate
    # omission, and collapsing them hides which.
    untrained = sorted(configured - set(trained))

    # Trained but never rendered — the gap TODO.md §3 opened a full grid build
    # to close. Split, because two very different things land here: a variable
    # whose grid has not been built *yet*, and one that can never have a grid
    # at all. Open-Meteo is a point API capped at 900 points, so
    # `air_temperature` is permanently ungriddable and listing it as a pending
    # build is a false gap — a panel reporting work that can never be done
    # trains people to ignore the list. The reason comes from
    # `grid_history.ungriddable_reason`, the same check the grid builder uses
    # to skip a target before paying for a fetch.
    ungridded: list[str] = []
    ungriddable: list[dict[str, str]] = []
    for variable in sorted(set(trained) - gridded):
        reason = grid_history.ungriddable_reason(variable)
        if reason is None:
            ungridded.append(variable)
        else:
            ungriddable.append({"code": variable, "reason": reason})

    return {
        "variables_total": len(registry.VARIABLE_REGISTRY),
        "variables_served": len(served),
        "variables_unavailable": unavailable,
        "variables_configured_for_forecast": len(configured),
        "variables_trained": len(trained),
        "models_trained": sum(len(h) for h in trained.values()),
        "variables_gridded": len(gridded),
        "configured_but_untrained": untrained,
        "trained_but_ungridded": ungridded,
        "trained_but_ungriddable": ungriddable,
        "grid_error": grid_error,
        "config_error": config_error,
    }


def build() -> dict[str, Any]:
    """The whole report: datasets, models, and the coverage rollup."""
    dataset_entries = datasets()
    model_entries = models()
    grades = [entry.get("grade") for entry in model_entries if entry.get("available")]

    return {
        "datasets": dataset_entries,
        "models": model_entries,
        "coverage": coverage(),
        "model_summary": {
            grade: sum(1 for value in grades if value == grade)
            for grade in ("strong", "good", "fair", "poor", "unknown")
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
