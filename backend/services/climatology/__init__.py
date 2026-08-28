"""Gridded percentile climatology — the baseline the platform did not have.

**This is not `forecasting/climatology.py`.** That module is an *evaluation
baseline*: a per-location day-of-year mean over the engine's 24 configured
points, fitted on a CV fold's training rows, used to answer "did the model learn
to forecast, or only learn what month it is". This package is a *global gridded
threshold artifact*: per-cell, per-day-of-year percentiles over a 30-year
record, used to answer "is what is happening here unusual". Different question,
different data, different lifetime. They are not merge candidates.

Why it exists
-------------
`services/crw.py` carried the only climatology in this codebase and it is SST
only *and* a climatology of **means**. That is enough for an anomaly and not
enough for an event: the Hobday marine-heatwave definition is a 90th-percentile
threshold exceeded for at least five days, and a mean cannot express it. Four
proposed features stall on this one artifact — marine heatwaves, an anomaly
explorer, polygon seasonal anomalies, and every percentile-relative event
(cold spells, extreme waves, low oxygen).

Why the source is NOAA OISST and not Copernicus, for this first climatology
-----------------------------------------------------------------------------
Measured against `services/download/catalog.py` rather than assumed: every
*near-real-time* Copernicus provider in this codebase starts recently —
physics 2022-06-01, waves 2022-11-01, wind 2024-06-13, BGC 2021-11-01. A
30-year baseline is not expensive on that path, it is **impossible**. NOAA
OISST v2.1 is daily 0.25 degree SST from 1981-09-01 to the present, served by
the same CoastWatch ERDDAP `services/crw.py` already uses, and one year of it
strided to 1 degree is ~95 MB in a single griddap request.

So the framing recorded in TODO.md — "an offline job against the expensive
global fetch path" — was wrong twice over, and this package is cheap.

**This was correct for a near-real-time product and incomplete about
Copernicus as a whole.** Copernicus also publishes a *reanalysis* — a
different product family, "my" (multi-year) rather than "anfc" (analysis-
forecast) in its dataset id — and that one reaches back to 1993.
`services/climatology/copernicus_reanalysis.py` fits a second climatology on
it, not to replace this OISST one (`services/heatwaves.py`'s detection stays
OISST's own answer) but to give `services/upwelling.py`'s SST corroboration a
baseline actually fitted on the live Copernicus field it scores — see
`services/sst_anomaly.py` for why scoring that live field against *this*
OISST-fitted climatology measurably made the corroboration worse, not better.
"""

from __future__ import annotations

from services.climatology.build import (
    ClimatologyBuildError,
    apply_percentiles,
    build_climatology,
    fit_percentiles,
)
from services.climatology.store import (
    ClimatologyNotBuilt,
    available,
    climatology_path,
    load,
    save,
)

__all__ = [
    "ClimatologyBuildError",
    "ClimatologyNotBuilt",
    "apply_percentiles",
    "available",
    "build_climatology",
    "climatology_path",
    "fit_percentiles",
    "load",
    "save",
]
