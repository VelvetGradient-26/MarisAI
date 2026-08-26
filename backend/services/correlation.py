"""Cross-variable correlation: does X actually move with Y at this point.

sihtodo.md item 7: `get_historical_series` (`services/dashboard/trends.py`)
only ever answers "how has one variable changed" — nothing aligns several of
them in time and measures how they move together, which is what "why has
fish productivity declined in this region?" actually needs (SST, chlorophyll
and currents looked at together, not one at a time).

**Aggregate to a common daily cadence before comparing, never after** — the
same ordering `services/download/cleaning.py` had to get right for the same
reason. `trends.series` can return each variable at a different native
resolution (hourly Open-Meteo vs. daily-only Copernicus), so pairing raw
points by list position would line up an hourly instantaneous reading against
a different variable's daily mean under no shared clock. Every series is
therefore reduced to a daily mean here — unconditionally, regardless of what
resolution actually came back — before any correlation is computed, and only
daily-resolution ranges are accepted in the first place (see
`_ALLOWED_RANGES`) so an hourly request can never reach this code at all.

**Correlation is not causation, and this module never implies otherwise.**
Every response carries a fixed disclaimer, and the tool-facing language
throughout is "moved together" / "no evidence of association", never "caused"
or "led to" — the model is a far more effective source of over-claiming than
any user, per this codebase's existing grounding discipline
(`services/chat/agent.py`'s `_ungrounded_numbers`), and nothing downstream
would catch a causal sentence this tool's own output invited.

**Fishing effort and the upwelling index are deliberately not offered as
variables here**, even though sihtodo.md's own example query names both.
Neither has a point-based historical series anywhere in this codebase to
align against: `services/gfw.py` is a raster tile proxy with no per-point
time-series endpoint wired up, and `services/upwelling.py` computes its index
live from the current wind field with no historical archive behind it.
Building either into a real time series is a separate, larger piece of work,
not a shortcut available here — stated rather than silently done less than
the example implied.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np
from scipy import stats as scipy_stats

from services.dashboard import trends

MIN_VARIABLES = 2
MAX_VARIABLES = 4
MIN_OVERLAPPING_DAYS = 10

# Ranges short enough to be served hourly are refused outright, structurally
# sidestepping the mixed-cadence bug `cleaning.py` documents rather than
# trying to detect it per pair: every range accepted here is already daily
# resolution (or aggregated to daily below regardless).
_ALLOWED_RANGES = ("30d", "6mo", "1y", "5y", "10y")

_STRENGTH_BANDS: tuple[tuple[float, str], ...] = (
    (0.7, "strong"),
    (0.4, "moderate"),
    (0.2, "weak"),
)

_SIGNIFICANCE_P = 0.05


class CorrelationError(RuntimeError):
    """The request itself cannot be answered — too few/many variables, or an
    hourly-only range. Per-variable *fetch* failures are not this: those are
    reported inline via `variables_unavailable`, the same
    available/unavailable_reason convention used everywhere else."""


def _strength(abs_r: float) -> str:
    for threshold, label in _STRENGTH_BANDS:
        if abs_r >= threshold:
            return label
    return "negligible"


def _daily_means(payload: dict[str, Any]) -> dict[str, float]:
    """date-string -> mean value, collapsing whatever native resolution came
    back. Unconditional, even for an already-daily series, so every variable
    goes through the identical reduction rather than two code paths that
    could quietly drift apart."""
    buckets: dict[str, list[float]] = {}
    for point in payload.get("points") or []:
        day = str(point["t"])[:10]
        buckets.setdefault(day, []).append(float(point["v"]))
    return {day: sum(values) / len(values) for day, values in buckets.items()}


async def analyze(
    variables: list[str],
    latitude: float,
    longitude: float,
    range_key: str = "1y",
) -> dict[str, Any]:
    """Pairwise Pearson correlation between 2-4 variables at one point, over
    a shared daily-aggregated window.

    Raises `CorrelationError` only for a malformed request (too few/many
    variables, an hourly-only range). An individual variable that fails to
    fetch, or a pair with too little overlapping coverage, is reported inline
    rather than failing the whole call.
    """
    unique = list(dict.fromkeys(variables))
    if len(unique) < MIN_VARIABLES:
        raise CorrelationError(
            f"Need at least {MIN_VARIABLES} distinct variables to correlate; got {unique}."
        )
    if len(unique) > MAX_VARIABLES:
        raise CorrelationError(
            f"At most {MAX_VARIABLES} variables at once, to keep the fetch and the "
            f"pairwise matrix readable; got {len(unique)}."
        )
    if range_key not in _ALLOWED_RANGES:
        raise CorrelationError(
            f"range must be one of {list(_ALLOWED_RANGES)} — correlation needs a "
            "daily-aggregated series, not raw hourly readings mixed across "
            "variables with different native cadences."
        )

    fetched = await trends.multi_series(unique, latitude, longitude, range_key)
    series_by_variable = fetched["series"]

    daily: dict[str, dict[str, float]] = {}
    unavailable: dict[str, str] = {}
    for variable in unique:
        payload = series_by_variable.get(variable) or {}
        if payload.get("error"):
            unavailable[variable] = payload["error"]
            continue
        values = _daily_means(payload)
        if not values:
            unavailable[variable] = "No data points were returned for this range."
            continue
        daily[variable] = values

    usable = [variable for variable in unique if variable in daily]
    pairs: list[dict[str, Any]] = []
    for var_a, var_b in combinations(usable, 2):
        common_days = sorted(set(daily[var_a]) & set(daily[var_b]))
        if len(common_days) < MIN_OVERLAPPING_DAYS:
            pairs.append(
                {
                    "variable_a": var_a,
                    "variable_b": var_b,
                    "available": False,
                    "reason": (
                        f"Only {len(common_days)} overlapping days of data — need at "
                        f"least {MIN_OVERLAPPING_DAYS} to compute a meaningful correlation."
                    ),
                }
            )
            continue

        a_values = np.array([daily[var_a][day] for day in common_days])
        b_values = np.array([daily[var_b][day] for day in common_days])
        # `a_values`/`b_values` can each be constant (e.g. a flat calm-season
        # window) — pearsonr returns NaN for a zero-variance input rather than
        # raising, so that is reported as unavailable rather than as a
        # spurious "correlation_r": NaN in the payload.
        if np.std(a_values) == 0 or np.std(b_values) == 0:
            pairs.append(
                {
                    "variable_a": var_a,
                    "variable_b": var_b,
                    "available": False,
                    "reason": (
                        "One of these variables did not vary at all over the "
                        "overlapping window, so a correlation is undefined."
                    ),
                }
            )
            continue

        r, p_value = scipy_stats.pearsonr(a_values, b_values)
        r_float, p_float = float(r), float(p_value)

        pairs.append(
            {
                "variable_a": var_a,
                "variable_b": var_b,
                "available": True,
                "correlation_r": round(r_float, 3),
                "p_value": round(p_float, 4),
                "strength": _strength(abs(r_float)),
                "direction": "positive" if r_float > 0 else "negative" if r_float < 0 else "none",
                "statistically_significant": p_float < _SIGNIFICANCE_P,
                "overlapping_days": len(common_days),
                "window": {"start": common_days[0], "end": common_days[-1]},
            }
        )

    return {
        "latitude": latitude,
        "longitude": longitude,
        "range": range_key,
        "variables_requested": unique,
        "variables_unavailable": unavailable,
        "pairs": pairs,
        "note": (
            "correlation_r is Pearson's r on daily-aggregated values over each "
            "pair's overlapping window, from -1 to 1. This measures whether two "
            "variables moved together — it is not evidence that one caused the "
            "other. A 'statistically significant' correlation (p < 0.05) with few "
            "overlapping_days can still be a coincidence; check overlapping_days "
            "before trusting a 'strong' label. A shared seasonal cycle routinely "
            "produces a strong correlation between two variables with no direct "
            "relationship — a confounder, not evidence either one drives the other."
        ),
    }
