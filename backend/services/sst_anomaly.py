"""What "today's SST against its seasonal baseline" is, as one shape.

Why this is its own module
--------------------------
More than one observation can be scored against the single fitted climatology in
`services/climatology/`, and more than one consumer wants the answer:
`services/heatwaves.py` produces it from the OISST record it already fetches,
and `services/upwelling.py` consumes it to corroborate a wind index against cold
water. Keeping the shape here means the producers cannot drift into two
definitions of what an anomaly is — the failure would be silent, because both
would still be plausible fields on the right grid.

The live SST field cannot be used here, and that is measured
-------------------------------------------------------------
The obvious improvement is to score the *live* Copernicus physics field that
`services/copernicus_sst.py` caches for the map layer — hours old, against
OISST's week-or-more publication lag. It was built and measured on 2026-08-17
and **it is worse**, so it does not ship. Both arms over the identical
wind/currents field, contrast = upwelling-favourable minus downwelling-favourable
(the control):

| source | cool contrast | below-p10 contrast |
| --- | --- | --- |
| OISST record (14.5 d old) | +0.026 | +0.002 |
| live physics field (current) | +0.022 | **-0.149** |

Closing a fortnight of latency bought nothing on the weak tier and *inverted*
the strong one — downwelling-favourable coasts came out below their seasonal
10th percentile three times as often as favourable ones.

**The cause is a product mismatch, not latency, and it concentrates on exactly
the water this scores.** The climatology is fitted on OISST, so scoring a
different product against it carries that product's own difference into every
anomaly. Measured 2026-08-01, a full day of hourly physics daily-averaged and
coarsened onto the OISST grid:

| water | mean | median | sd | \\|d\\|>0.5 degC | \\|d\\|>1.0 degC |
| --- | --- | --- | --- | --- | --- |
| open ocean | +0.033 | +0.011 | 0.467 | 14.3% | 3.9% |
| **coastal band** | +0.131 | -0.002 | **0.758** | **24.9%** | **10.0%** |

There is no systematic offset to correct — the medians are ~0, so a constant
bias term would be a fudge with nothing to fix. What there is instead is
per-cell noise of **0.76 degC on the coast**, wider than the whole 0.5 degC
`upwelling.COOL_ANOMALY_C` threshold, and a below-p10 test is a *tail* test that
cannot survive noise the width of its own signal. Every coastal cell is a 1
degree average of a coastline that the two products resolve differently, which is
why the coast is twice as bad as open water.

**The route back is to fit the baseline on the product being scored** — a
climatology from the Copernicus physics reanalysis, whose record reaches 1993 —
not to reach for the live field again against this one. See TODO.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

# Source labels. Strings rather than an enum because they are published in the
# API response and read by a person deciding how much to believe a cell.
OISST_RECORD = "NOAA OISST v2.1 daily record"


@dataclass(frozen=True)
class SstAnomalyField:
    """An SST field scored against its seasonal baseline.

    Deliberately narrow: the only consumers corroborate a cold anomaly, and an
    object that also carried heatwave categories and run lengths would sooner or
    later be reached into for them. Both arrays are on the *baseline's* grid,
    which is coarser than most callers' — resampling is the caller's problem,
    because the honest handling of a cell the baseline does not cover belongs to
    whoever knows what that cell is for.
    """

    # (lat, lon) float32, degC: observed minus the day's climatological mean.
    anomaly: np.ndarray
    # (lat, lon) float32, degC: observed minus the day's p10. Negative means
    # below the seasonal 10th percentile, which is the strong cold claim.
    cold_exceedance: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    # The observation's own time. A week or more behind real time for the OISST
    # record, so a consumer must report the gap rather than implying
    # simultaneity with whatever it is corroborating.
    timestamp: datetime
    baseline: tuple[int, int]
    # Which observation this came from. Published rather than assumed: the
    # module docstring's measurement is precisely that swapping the source
    # changes which cells are called cold.
    source: str

    def describe(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "baseline": {"start": self.baseline[0], "end": self.baseline[1]},
        }
