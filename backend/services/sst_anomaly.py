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
not to reach for the live field again against this one.

The matched baseline was also tried, and also measured worse
--------------------------------------------------------------
`scripts/build_climatology_copernicus.py` built that climatology for real (30
years, 1993-2022, the reanalysis's full supported window) and
`scripts/measure_sst_corroboration.py --source copernicus_reanalysis` scored
the live Copernicus field against it, paired against the same script's OISST
arm over the identical wind/currents snapshot (2026-08-25):

| source (baseline) | cool contrast | below-p10 contrast |
| --- | --- | --- |
| OISST record (1991-2020 baseline) | +0.027 | -0.001 |
| live physics, GLORYS climatology (1993-2022 baseline) | +0.021 | **-0.051** |

Matching the product did not rescue the tail test — it made the weak tier
slightly worse and the strong tier newly and substantially inverted, the same
failure shape the mismatched live-field attempt above produced, not a
different one. So the product-mismatch diagnosis was itself incomplete: a
matched baseline removes the 0.76 degC product-disagreement term, but the
contrast still does not widen, which means what limits this control is the
wind/SST snapshots being instantaneous on both sides, not which SST product or
baseline scores them — see "a rolling wind history" in TODO.md, the lever this
result actually points at.

`copernicus_sst.anomaly_field()` and the built climatology stay — the
reanalysis fetch is shared with `scripts/compare_against_eddy_atlas.py`, and
`measure_sst_corroboration.py --source copernicus_reanalysis` is kept
runnable so this question can be re-asked once a wind history exists — but
`services/upwelling.py` stays on `heatwaves.sst_anomaly_field()` (OISST).
Wiring the reanalysis path into the live corroboration would be the same
mistake the deleted live-field path was: a switch that makes the detector
worse and looks like progress.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

# Source labels. Strings rather than an enum because they are published in the
# API response and read by a person deciding how much to believe a cell.
OISST_RECORD = "NOAA OISST v2.1 daily record"
# The live Copernicus physics field, scored against a climatology fitted on
# the Copernicus GLORYS reanalysis rather than OISST — tried as the fix for
# the measured 0.76 degC coastal disagreement, and itself measured not to
# widen the contrast (see this module's docstring). Not used by
# services/upwelling.py; kept for services/compare_against_eddy_atlas.py's
# shared fetch and for re-measuring this question later. See
# services/climatology/copernicus_reanalysis.py.
COPERNICUS_REANALYSIS = "Copernicus Marine physics, scored against its own reanalysis climatology"


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
