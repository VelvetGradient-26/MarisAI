"""Shared Hobday-definition arithmetic between `services/heatwaves.py` (the
pure, window-censored snapshot detector) and `services/heatwave_tracking.py`
(persistent per-cell onset/duration/intensity across refreshes).

Kept in its own module rather than either one importing the other — the two
would otherwise import each other (`heatwaves.refresh_cache` calls
`heatwave_tracking.advance`, which needs the same per-day exceedance/category
arithmetic `detect` uses) — and, more importantly, so "what counts as a
heatwave" is computed exactly one way. Same reason `services/sst_anomaly.py`
holds `SstAnomalyField` instead of `heatwaves.py` and `services/upwelling.py`
each defining their own version of the same shape.
"""

from __future__ import annotations

import numpy as np

# Hobday's minimum duration. Five days is the published definition, not a
# knob — it is exposed as a constant so a response can state it, not so it
# can be tuned down until something shows up.
MIN_DURATION_DAYS = 5

# Category boundaries as multiples of (p90 - mean). Hobday et al. 2018.
CATEGORY_NAMES = ("none", "moderate", "strong", "severe", "extreme")


def day_state(values: np.ndarray, p90: np.ndarray, mean: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """`(exceedance, multiple)` for one day's field against its own seasonal
    threshold — pure arithmetic, no run-length dependency, so a caller can
    combine it with its own notion of "how many days" (a window-trailing
    count in `heatwaves.detect`, a persistent one in
    `heatwave_tracking.advance`) via `categorize` without computing the
    Hobday formula two different ways.
    """
    exceedance = (values - p90).astype("float32")
    gap = p90 - mean
    with np.errstate(divide="ignore", invalid="ignore"):
        multiple = np.where(gap > 0, (values - mean) / gap, np.nan)
    return exceedance, multiple


def categorize(multiple: np.ndarray, qualifies: np.ndarray) -> np.ndarray:
    """Hobday's category scale (multiples of the mean-to-p90 gap), restricted
    to cells `qualifies` says have actually met the duration clause. A
    degenerate or undefined multiple never counts as "extreme" — dividing by
    a near-zero gap must not make the most featureless cell on the map the
    most alarming one.
    """
    category = np.zeros(np.broadcast(multiple, qualifies).shape, dtype="int8")
    for index in (1, 2, 3, 4):
        lower = index
        upper = index + 1
        band = qualifies & np.isfinite(multiple) & (multiple >= lower)
        if index < 4:
            band &= multiple < upper
        category[band] = index
    return category
