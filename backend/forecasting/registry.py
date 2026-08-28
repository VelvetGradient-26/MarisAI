"""The resolver everything else asks "what is this variable, and can we
forecast it?".

Three sources of truth meet here and none of them is duplicated:

* `services/download/registry.py` — what the platform can *fetch* (label,
  unit, category, provider).
* `forecasting/config/forecasting.yaml` — what the engine is *configured* to
  forecast (covariates, horizons, transforms, bounds).
* `forecasting/model_store.py` — what has actually been *trained*.

A variable can be fetchable but unconfigured, configured but untrained, or
fully ready, and those are three genuinely different answers. Collapsing them
into a boolean is how a UI ends up offering a forecast that 404s. Following
the pattern the dashboard already uses in this codebase, every entry carries
`available` plus an `unavailable_reason` naming which of the three stages it
fell out of.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forecasting import ForecastingError
from forecasting.config import ForecastingConfig, VariableConfig, get_config
from forecasting import derived
from forecasting.model_store import list_trained
from services.download.registry import VARIABLE_REGISTRY


class UnknownVariableError(ForecastingError):
    """The requested variable is not configured for forecasting."""


class UnsupportedHorizonError(ForecastingError):
    """The horizon is outside what the engine will accept at all."""


@dataclass(frozen=True)
class VariableEntry:
    """One row of the forecast catalog."""

    key: str
    code: str
    label: str
    unit: str
    category: str
    covariates: list[str]
    configured_horizons: list[int]
    trained_horizons: list[int]
    circular: bool
    log_transform: bool
    available: bool
    unavailable_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "code": self.code,
            "label": self.label,
            "unit": self.unit,
            "category": self.category,
            "covariates": self.covariates,
            "configured_horizons": self.configured_horizons,
            "trained_horizons": self.trained_horizons,
            "circular": self.circular,
            "log_transform": self.log_transform,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
        }


def resolve(key: str, config: ForecastingConfig | None = None) -> VariableConfig:
    """The config block for a variable, or a message naming what went wrong.

    Deliberately distinguishes "we can fetch this but nobody configured it"
    from "we have never heard of it" — the first is a one-block YAML fix and
    the message says so.
    """
    config = config or get_config()
    variable = config.variables.get(key)

    if variable is None:
        if key in VARIABLE_REGISTRY:
            raise UnknownVariableError(
                f"{key!r} is a known ocean variable but is not configured for "
                f"forecasting. Add a block for it in forecasting/config/forecasting.yaml."
            )
        raise UnknownVariableError(
            f"Unknown variable {key!r}. Forecastable variables: "
            f"{', '.join(sorted(config.enabled_variables()))}"
        )

    if not variable.enabled:
        raise UnknownVariableError(f"Forecasting for {key!r} is disabled in configuration.")

    return variable


def validate_horizon(
    horizon: int, config: ForecastingConfig | None = None
) -> int:
    """Reject a horizon the engine does not accept at all.

    A horizon that is *supported but untrained* deliberately passes here and
    fails later in the model store, with a message that says to train it. The
    difference matters: 90 days is a thing this engine will one day do, and a
    422 saying "invalid" would wrongly imply otherwise.
    """
    config = config or get_config()
    if horizon in config.defaults.supported_horizons:
        return horizon
    raise UnsupportedHorizonError(
        f"Horizon {horizon} is not supported. Supported horizons: "
        f"{', '.join(map(str, config.defaults.supported_horizons))}."
    )


def catalog(
    config: ForecastingConfig | None = None, root: Path | None = None
) -> list[VariableEntry]:
    """Every configured variable with its training state.

    This is what the dashboard reads to decide which variables get a forecast
    panel and which horizons that panel offers.
    """
    config = config or get_config()
    trained = list_trained(root)

    entries = []
    for key, variable in config.enabled_variables().items():
        configured = config.horizons_for(key)
        trained_horizons = trained.get(key, [])

        # A derived bearing has no model of its own: it is assembled from two
        # component forecasts, so it is available exactly where both components
        # are trained. See `forecasting/derived.py` for why a circular target is
        # not modelled directly.
        spec = derived.spec_for(key)
        if spec is not None:
            east, north = spec.components
            trained_horizons = sorted(set(trained.get(east, [])) & set(trained.get(north, [])))
            if trained_horizons:
                available, reason = True, None
            else:
                available = False
                reason = (
                    f"{variable.label} is derived from {east} and {north}; train "
                    f"both (`python scripts/train_forecasting.py --variable {east}`) "
                    f"to make it available."
                )
        elif trained_horizons:
            available, reason = True, None
        else:
            available = False
            reason = (
                f"No model has been trained for {variable.label} yet. Run "
                f"`python scripts/train_forecasting.py --variable {key}`."
            )

        entries.append(
            VariableEntry(
                key=key,
                code=variable.code,
                label=variable.label,
                unit=variable.unit,
                category=variable.category,
                covariates=list(variable.covariates),
                configured_horizons=configured,
                trained_horizons=trained_horizons,
                circular=variable.circular,
                log_transform=variable.log_transform,
                available=available,
                unavailable_reason=reason,
            )
        )
    return entries


def grouped_catalog(
    config: ForecastingConfig | None = None, root: Path | None = None
) -> list[dict[str, Any]]:
    """The catalog grouped by category, matching how the downloader's registry
    presents itself to the frontend — so the forecast picker can reuse the
    same grouped-list rendering."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in catalog(config, root):
        groups.setdefault(entry.category, []).append(entry.as_dict())
    return [
        {"category": category, "variables": variables}
        for category, variables in groups.items()
    ]


def fetch_codes(variable: VariableConfig, *, include_static: bool = True) -> tuple[str, ...]:
    """Every registry code the engine must fetch to build this variable's features.

    The target, its covariates, and (unless disabled) `ocean_depth` — which is
    a time-invariant GEBCO field and therefore arrives as a static feature
    column for free, with no separate lookup path to maintain.
    """
    codes = [variable.code, *variable.covariates]
    if include_static and "ocean_depth" not in codes:
        codes.append("ocean_depth")
    # Deduplicated but order-stable, so the cache key is deterministic.
    seen: list[str] = []
    for code in codes:
        if code not in seen:
            seen.append(code)
    return tuple(seen)
