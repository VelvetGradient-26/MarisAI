"""Coastal upwelling from Ekman transport — the platform's third detector.

What it computes
----------------
The Bakun coastal upwelling index: wind stress drives an Ekman transport 90
degrees to the right of the wind in the northern hemisphere and to the left in
the southern, and where that transport is directed **offshore** the water it
removes is replaced from below. So the index is a projection,

    upwelling = M . n_offshore

with `M` the Ekman transport (m^2/s) and `n_offshore` the coastal normal.
Positive is upwelling-favourable, negative is downwelling-favourable, and the
sign convention is the whole point — a detector that reported |M| would call a
coast that is being *piled up* an upwelling zone.

Why this is a live detector and not a forecast product
------------------------------------------------------
TODO.md records upwelling as "blocked on `wind_u`/`wind_v`", and that turned out
to be wrong once checked. What upwelling needs is wind *components*, because a
bearing cannot be projected onto a normal — and `copernicus_wind.snapshot()` has
exposed live `u`/`v` all along, for `services/drift.py` to sum. The
`wind_u`/`wind_v` training run produced *forecast* grids, which is a different
thing and the wrong footing for a detector claiming to say what is happening
now. This reads the live wind cache, exactly as `services/eddies.py` reads the
live currents cache, and costs a numpy pass over a grid already resident.

The three things that make this hard, and how each is handled
-------------------------------------------------------------
* **The coast has to have a direction.** An upwelling index is meaningless
  without knowing which way is offshore, and no service here supplies coastline
  geometry. It is derived instead from the ocean mask the currents field already
  carries (Copernicus physics is NaN over land): smooth the mask, take its
  gradient, and the gradient points from land into water by construction. That
  is a genuinely coarse normal at ~0.25 degrees — a fjord or a headland is below
  the grid — so `coastline_confidence` reports how sharply defined the local
  normal is, and a cell whose surroundings are ambiguous is dropped rather than
  given a made-up bearing.
* **Wind is defined over land and the ocean mask is not.** The mask therefore
  comes from the currents field and the wind is resampled onto that grid, rather
  than the other way round. Taking the wind field's own coverage would put the
  "coast" at the edge of the wind product, which is the whole globe.
* **f vanishes at the equator.** Ekman transport is `tau / (rho f)`, so the
  index diverges as f goes to zero and equatorial upwelling is a different
  mechanism (divergence, not coastal). The +/-5 degree band is excluded outright,
  the same cut and the same reason as `services/eddies.py`'s polarity band.

What it deliberately does not claim
-----------------------------------
**It is a wind-derived index, not an observation of upwelled water.** Bakun's
index says the wind is favourable, not that cold nutrient-rich water has
actually surfaced — stratification, topography and relaxation all intervene.

The SST corroboration, and why the two halves stay separable
------------------------------------------------------------
The second claim is now made, because the baseline it needs exists:
`services/climatology/` fits a per-cell, per-day-of-year percentile climatology,
and `services/heatwaves.py` already holds today's SST scored against it. A
favourable-wind cell with a *coincident cold anomaly* is a materially stronger
statement than either half alone, and it is the statement a user actually wants.

Three things keep it from becoming an overreach:

* **"Wind favourable" and "wind favourable and the water responded" are
  different findings and are reported as different fields.** `index` and its
  sign are untouched by any of this; corroboration rides in its own block with
  its own availability, its own timestamp and its own baseline. A cell with no
  SST is `sst_unavailable`, never "not corroborated" — the same distinction the
  dashboard draws between `unavailable` and a value.
* **Two tiers, because one of them needs a number chosen by hand.**
  `cool_anomaly` is SST at least `COOL_ANOMALY_C` below its seasonal mean, and
  that threshold is a judgement. `confirmed_below_p10` is SST below its own
  seasonal 10th percentile, which is defined by the local distribution and needs
  no chosen constant — it is the stronger claim and is labelled separately for
  exactly that reason.
* **The two halves are not simultaneous, and the lag is published rather than
  smoothed over.** The wind and current fields are hourly; OISST publishes daily
  with a lag of a week or more (16 days, measured 2026-08-17). So this is never
  "the water responded to *this* wind" — it is "the wind is favourable now, and
  at the most recent SST observation, N days ago, this coast was cool for the
  season". Past `MAX_SST_LAG_DAYS` even that is withheld with a reason.

Chlorophyll is the third leg and is still not done: there is no resident
chlorophyll grid and no long-record chlorophyll climatology to make an anomaly
out of.

**How strong the agreement actually is, measured.** On the live global field
2026-08-17: 19.9% of upwelling-favourable coastal cells were cool for the season
— against **17.2% of downwelling-favourable ones**, where cool water is not
expected at all. Below the seasonal p10 the two are indistinguishable (4.1% vs
3.9%), and the mean anomaly is *warmer* under favourable wind (+0.91 degC) than
under downwelling (+0.60). So a corroborated cell is a real observation of cool
water and a weak coincidence, not evidence that this wind drove it — with a
14.5-day-old SST field it could hardly be anything else. That control is
therefore computed and returned with every response (`control_cool_fraction`)
rather than left for a reader to think of, the same rule CLAUDE.md records for
HAB precision: a level is not a finding without its base rate.

**And the obvious fix for that lag does not work — do not reach for it again.**
Scoring the *live* hourly SST field instead of the lagged OISST record was built
and measured on 2026-08-17: the weak tier's contrast was unchanged (+0.022
against +0.026) and the strong tier **inverted** (-0.149), because the
climatology is fitted on OISST and a different product carries 0.76 degC of
per-cell disagreement across the coastal band — wider than `COOL_ANOMALY_C`
itself. Latency is not the binding constraint; the baseline's product is. The
numbers and the route back are in `services/sst_anomaly.py`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import xarray as xr
from loguru import logger
from scipy.ndimage import uniform_filter

from services import (
    copernicus_currents,
    copernicus_wind,
    field_sampling,
    heatwaves,
    sst_anomaly,
    vector_field,
)
from services.vector_source import VectorSnapshot, VectorSourceError

# Air density and the drag coefficient for the bulk stress formula
# `tau = rho_air * Cd * |U| * U`. Cd is the Large & Pond mid-range constant;
# it varies with wind speed and stability in reality, and a constant is the
# standard simplification for an index rather than a flux budget.
AIR_DENSITY = 1.225
DRAG_COEFFICIENT = 1.3e-3

SEAWATER_DENSITY = 1025.0

# Earth's rotation rate, rad/s.
OMEGA = 7.2921e-5

# Excluded outright: f -> 0 makes the transport diverge, and equatorial
# upwelling is driven by divergence rather than by a coast.
EQUATORIAL_BAND_DEG = 5.0

# How far from land a cell may be and still be "coastal". Upwelling is a coastal
# process and the index is per metre of coastline, so applying it mid-ocean
# would be projecting onto a normal that does not exist. Two cells at ~0.25
# degrees is ~55 km.
COASTAL_BAND_CELLS = 2

# The ocean mask is smoothed over this many cells before its gradient is taken.
# A raw 0/1 mask has a gradient only in the single cell adjacent to land, which
# makes the normal undefined for the rest of the band; smoothing spreads it
# across the band at the cost of resolution the grid does not have anyway.
NORMAL_SMOOTHING_CELLS = 3

# Below this, the local ocean-mask gradient is too weak or too ambiguous to call
# a direction — an enclosed sea, a cell between two coasts, a one-cell island.
# Such cells are dropped rather than assigned a bearing.
MIN_COASTLINE_CONFIDENCE = 0.05

# How far below its seasonal mean the water has to be before the anomaly counts
# as cool. A hand-chosen number, and named as one: OISST's daily 1-degree field
# carries real sub-tenth-degree wobble, so a test at "any negative anomaly"
# would corroborate half of every coast on any given day. The stronger tier
# below needs no such choice.
COOL_ANOMALY_C = 0.5

# Past this, the SST field is too old to say anything about today's wind and
# corroboration is withheld with a reason rather than quietly aged. OISST's own
# publication lag is a week or more — 16 days on 2026-08-17 — so this is a cap
# on *staleness beyond the product's normal lag*, not a promise of simultaneity.
MAX_SST_LAG_DAYS = 30

# Per-cell corroboration states. `sst_unavailable` is a distinct answer from
# `wind_only`, exactly as the dashboard's `unavailable` is distinct from a
# value: "we could not look" must never render as "we looked and found nothing".
CORROBORATION_STATES = (
    "confirmed_below_p10",
    "cool_anomaly",
    "wind_only",
    "not_applicable",
    "sst_unavailable",
)

METHOD = (
    "Bakun coastal upwelling index: Ekman transport from bulk wind stress, "
    "projected onto the offshore normal of the model land mask"
)

UNIT = "m^2/s per metre of coastline"

LIMITS = (
    "A wind-derived index, not an observation of upwelled water. It says the "
    "wind is favourable; stratification, topography and relaxation decide "
    "whether cold nutrient-rich water actually surfaces.",
    "The sea-surface temperature corroboration is a separate, later observation "
    "— OISST publishes daily with a lag of a week or more, so a corroborated "
    "cell means the wind is favourable now and the water was cool for the "
    "season at the most recent SST field, not that the water responded to this "
    "wind. The lag is reported with every response.",
    "Corroboration is at OISST's 1-degree resolution, which is coarser than the "
    "index's grid and cannot resolve an upwelling filament. It says the water in "
    "a ~110 km cell is cool for the season.",
    "Not corroborated against chlorophyll: there is no resident chlorophyll "
    "field and no long-record chlorophyll climatology to make an anomaly from.",
    "The coastal normal is derived from a ~0.25 degree land mask, so a "
    "headland, a bay or a fjord is below the grid. `coastline_confidence` "
    "reports how well-defined each normal is.",
    f"Cells within {EQUATORIAL_BAND_DEG} degrees of the equator are excluded: "
    "Ekman transport diverges as the Coriolis parameter goes to zero, and "
    "equatorial upwelling is driven by divergence rather than by a coast.",
    "Detection only — nothing is tracked between refreshes, so no upwelling "
    "cell here has an onset or a duration.",
)


class UpwellingError(RuntimeError):
    """Upwelling detection is unavailable — almost always a cold wind or
    currents cache, since this reads both rather than fetching."""


@dataclass(frozen=True)
class UpwellingField:
    """One pass over one pair of snapshots."""

    # (lat, lon) float32, m^2/s per metre of coastline. Positive is
    # upwelling-favourable. NaN away from the coastal band, over land, inside
    # the equatorial band, and where the normal is undefined.
    index: np.ndarray
    # (lat, lon) float32 in 0..1: how sharply the local normal is defined.
    coastline_confidence: np.ndarray
    # The offshore normal actually used, for a caller that wants to draw it.
    normal_east: np.ndarray
    normal_north: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    timestamp: datetime
    computed_at: datetime
    # (lat, lon) float32, degC: SST minus its seasonal mean, resampled onto this
    # grid. All-NaN when no SST field was available, which is a state the
    # response reports rather than a failure.
    sst_anomaly: np.ndarray
    # (lat, lon) float32, degC: SST minus its seasonal p10. Negative is the
    # strong cold claim.
    sst_cold_exceedance: np.ndarray
    # The SST observation's own day, which is *not* `timestamp`: see the module
    # docstring on why the lag is published instead of being folded into one
    # stamp the way `services/drift.py` folds its components.
    sst_timestamp: datetime | None
    sst_baseline: tuple[int, int] | None
    # Which observation the anomaly came from — the live hourly physics field or
    # the lagged OISST record. Published, because the two disagree per-cell at
    # the scale of `COOL_ANOMALY_C` (sd 0.50 degC, 17.1% of cells over 0.5,
    # measured 2026-08-01), so "which source" changes which cells are outlined.
    sst_source: str | None
    sst_unavailable_reason: str | None
    # Set only by `detect_from_history`: the trailing window this field's
    # transport was averaged over (`wind_history.MeanTransport.describe()`).
    # `None` means `index` came from one instantaneous wind snapshot, via
    # plain `detect` — the two must never look like the same claim.
    wind_window: dict[str, Any] | None = None

    def coverage(self) -> dict[str, Any]:
        scored = np.isfinite(self.index)
        cells = int(scored.sum())
        if cells == 0:
            return {
                "coastal_cells": 0,
                "unavailable_reason": (
                    "no cell in this field has both a defined coastal normal and "
                    "a usable Coriolis parameter"
                ),
            }
        favourable = int((self.index[scored] > 0).sum())
        return {
            "coastal_cells": cells,
            "upwelling_favourable_cells": favourable,
            "downwelling_favourable_cells": cells - favourable,
            "favourable_fraction": round(favourable / cells, 4),
            "max_index": round(float(np.nanmax(self.index)), 3),
            "band_cells": COASTAL_BAND_CELLS,
            "excluded_latitude_band_deg": EQUATORIAL_BAND_DEG,
        }

    def state_at(self, row: int, column: int) -> str:
        """One cell's corroboration state. See `CORROBORATION_STATES`."""
        index = float(self.index[row, column])
        anomaly = float(self.sst_anomaly[row, column])
        if not np.isfinite(anomaly):
            return "sst_unavailable"
        if not (index > 0):
            # The test is defined for upwelling-favourable wind only. A warm
            # anomaly under downwelling-favourable wind is not the symmetric
            # confirmation it looks like: downwelling suppresses a cold signal
            # rather than producing a warm one, and the surface warms for a
            # dozen reasons that have nothing to do with the coast.
            return "not_applicable"
        cold = float(self.sst_cold_exceedance[row, column])
        if np.isfinite(cold) and cold < 0:
            return "confirmed_below_p10"
        if anomaly <= -COOL_ANOMALY_C:
            return "cool_anomaly"
        return "wind_only"

    def corroboration(self) -> dict[str, Any]:
        """How much of the favourable coast the water agrees with.

        Kept out of `coverage`, which stays a description of the wind-derived
        index alone. The two are different findings and a caller has to be able
        to read one without the other coming along.
        """
        common: dict[str, Any] = {
            "source": (
                f"{self.sst_source} against the daily percentile climatology in "
                "services/climatology/"
                if self.sst_source
                else "the daily percentile climatology in services/climatology/"
            ),
            "cool_anomaly_threshold_c": COOL_ANOMALY_C,
            "states": list(CORROBORATION_STATES),
        }
        if self.sst_unavailable_reason is not None:
            return {
                **common,
                "available": False,
                "unavailable_reason": self.sst_unavailable_reason,
            }

        scored = np.isfinite(self.index)
        favourable = scored & (self.index > 0)
        with_sst = favourable & np.isfinite(self.sst_anomaly)
        below_p10 = with_sst & np.isfinite(self.sst_cold_exceedance)
        below_p10 &= self.sst_cold_exceedance < 0
        cool = with_sst & (self.sst_anomaly <= -COOL_ANOMALY_C)
        corroborated = cool | below_p10

        # The base rate the corroborated fraction has to be read against, and it
        # is not optional. Measured 2026-08-17 on the live global field: 19.9% of
        # favourable coastal cells were cool for the season against **17.2% of
        # downwelling-favourable ones** — so on a single snapshot the agreement
        # is barely better than chance, and a reader given only the first number
        # would take a weak coincidence for a confirmed mechanism. The same rule
        # CLAUDE.md records for HAB precision: quote the lift, not the level.
        control = scored & (self.index < 0) & np.isfinite(self.sst_anomaly)
        control_cool = control & (self.sst_anomaly <= -COOL_ANOMALY_C)
        control_n = int(control.sum())

        examined = int(with_sst.sum())
        assert self.sst_timestamp is not None  # set together with the arrays
        lag = self.timestamp - self.sst_timestamp
        return {
            **common,
            "available": True,
            "sst_timestamp": self.sst_timestamp.isoformat(),
            "lag_hours": round(lag.total_seconds() / 3600.0, 1),
            "baseline": (
                {"start": self.sst_baseline[0], "end": self.sst_baseline[1]}
                if self.sst_baseline
                else None
            ),
            "favourable_cells": int(favourable.sum()),
            # The denominator, stated. Coastal cells outside OISST's coverage
            # are not corroborated *and not refuted*, and a fraction taken over
            # all favourable cells would silently call them refuted.
            "favourable_cells_with_sst": examined,
            "corroborated_cells": int(corroborated.sum()),
            "below_p10_cells": int(below_p10.sum()),
            "corroborated_fraction": (
                round(float(corroborated.sum() / examined), 4) if examined else None
            ),
            # Named `control_*`, not `downwelling_*`: its job is to be the
            # denominator of belief, not another finding about downwelling.
            "control_cells": control_n,
            "control_cool_fraction": (
                round(float(control_cool.sum() / control_n), 4) if control_n else None
            ),
            "note": (
                "The wind is favourable now; the water was cool for the season "
                "at the most recent sea-surface temperature field, which is "
                "older. This is coincidence in space, not a causal link in time. "
                "Read the corroborated fraction against `control_cool_fraction` "
                "— the same fraction over downwelling-favourable coasts, where "
                "cool water is not expected. The two being close means this "
                "snapshot's agreement is weak, however many cells are outlined."
            ),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "computed_at": self.computed_at.isoformat(),
            "method": METHOD,
            "unit": UNIT,
            "sign_convention": (
                "positive is upwelling-favourable (Ekman transport directed "
                "offshore); negative is downwelling-favourable"
            ),
            "coverage": self.coverage(),
            "corroboration": self.corroboration(),
            "wind_window": self.wind_window,
            "limits": list(LIMITS),
        }


def wind_stress(u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Bulk wind stress in Pa, as (east, north) components."""
    speed = np.hypot(u, v)
    factor = AIR_DENSITY * DRAG_COEFFICIENT * speed
    return factor * u, factor * v


def coriolis(latitude: np.ndarray) -> np.ndarray:
    """f = 2 Omega sin(lat), with the equatorial band blanked to NaN."""
    f = 2.0 * OMEGA * np.sin(np.radians(latitude))
    return np.where(np.abs(latitude) < EQUATORIAL_BAND_DEG, np.nan, f)


def ekman_transport(
    tau_east: np.ndarray, tau_north: np.ndarray, f: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Depth-integrated Ekman transport, m^2/s, as (east, north).

    `M = (tau_north / (rho f), -tau_east / (rho f))` — 90 degrees to the *right*
    of the stress where f is positive (northern hemisphere) and to the left
    where it is negative, which the sign of f delivers without a hemisphere
    branch. Writing it as an explicit `if latitude > 0` is the version that is
    wrong in one hemisphere and confidently plausible in both.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        denominator = SEAWATER_DENSITY * f[:, None]
        return tau_north / denominator, -tau_east / denominator


def offshore_normal(
    ocean: np.ndarray, dx: np.ndarray, dy: float, periodic: bool
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The unit vector pointing from land into water, and its confidence.

    Derived from the ocean mask rather than from a coastline dataset, because
    none is available here. The mask is smoothed first: a raw 0/1 mask has a
    gradient only in the one cell touching land, so the rest of the coastal band
    would have no normal at all.

    Confidence is the *magnitude* of the smoothed gradient, normalised — it is
    high on a straight open coast and low where land lies on two sides, which is
    exactly where a single normal is not a meaningful description.
    """
    smoothed = uniform_filter(ocean.astype("float64"), size=NORMAL_SMOOTHING_CELLS)
    # Gradient of "how much ocean is nearby" points away from land, i.e.
    # offshore, which is the direction wanted.
    east = field_sampling.d_dx(smoothed, dx, periodic)
    north = field_sampling.d_dy(smoothed, dy)

    magnitude = np.hypot(east, north)
    # Scale to 0..1 against the steepest gradient the grid can produce, so the
    # number means "how coast-like is this cell" rather than carrying units.
    finite = magnitude[np.isfinite(magnitude)]
    peak = float(finite.max()) if finite.size else 0.0
    confidence = magnitude / peak if peak > 0 else np.zeros_like(magnitude)

    with np.errstate(divide="ignore", invalid="ignore"):
        unit_east = np.where(magnitude > 0, east / magnitude, np.nan)
        unit_north = np.where(magnitude > 0, north / magnitude, np.nan)
    return unit_east, unit_north, confidence


def _coastal_band(ocean: np.ndarray) -> np.ndarray:
    """Ocean cells within `COASTAL_BAND_CELLS` of land."""
    size = 2 * COASTAL_BAND_CELLS + 1
    # Mean of the land mask in a neighbourhood: > 0 means land is within reach.
    near_land = uniform_filter((~ocean).astype("float64"), size=size) > 0
    return ocean & near_land


def detect(
    wind: VectorSnapshot,
    currents: VectorSnapshot,
    sst: sst_anomaly.SstAnomalyField | None = None,
) -> UpwellingField:
    """Detect upwelling-favourable coasts, optionally corroborated by SST.

    Pure — snapshots in, a field out, no fetching and no clock beyond the
    stamp. Same shape as `services/eddies.py::detect` and for the same reason:
    the science is then testable without a network.

    The **currents** snapshot supplies the grid and the land mask; the wind is
    resampled onto it. Not the other way round: the wind product covers the
    whole globe including land, so its coverage edge is not a coast.

    `sst` is optional throughout, and the index is identical with and without
    it. Corroboration adds a claim; it never edits or filters the wind-derived
    one, so a cold SST cache degrades this to what it always was rather than
    failing it.
    """
    lat = np.asarray(currents.lat, dtype="float64")
    lon = np.asarray(currents.lon, dtype="float64")
    wind_u, wind_v = _resample(wind, lat, lon)
    tau_east, tau_north = wind_stress(wind_u, wind_v)
    f = coriolis(lat)
    m_east, m_north = ekman_transport(tau_east, tau_north, f)

    # The stalest of the two live inputs, for the same reason `services/drift.py`
    # reports the stalest term: a composite is only as current as its oldest
    # component, and the wind blend routinely lags the hourly currents. The SST
    # field is deliberately *not* folded in — it is a separate observation of a
    # separate quantity, and averaging it into one stamp would hide the very lag
    # the corroboration has to disclose.
    stamp = min(wind.timestamp, currents.timestamp)
    return _assemble_field(m_east, m_north, currents, sst, stamp)


def detect_from_history(
    mean_transport: Any,
    currents: VectorSnapshot,
    sst: sst_anomaly.SstAnomalyField | None = None,
) -> UpwellingField:
    """The same detection, against a trailing multi-day mean transport
    (`services/wind_history.py::MeanTransport`) instead of one instantaneous
    wind snapshot — the untried lever TODO.md and this file's own docstring
    point at: upwelling responds to wind integrated over days, and every
    control run so far has scored an instantaneous snapshot on both sides.

    `mean_transport` is resampled from its own (coarser, fixed) grid onto
    `currents`'s grid exactly the way `sst.anomaly` already is — the same
    `_resample_scalar` helper, since a mean transport component is just
    another holed scalar field at this point, not a vector needing a
    direction-aware resample (its two components are averaged and resampled
    independently, which is valid because averaging is linear and resampling
    each Cartesian component separately is the same operation
    `services/drift.py` already relies on elsewhere in this codebase).
    """
    lat = np.asarray(currents.lat, dtype="float64")
    lon = np.asarray(currents.lon, dtype="float64")
    m_east = _resample_scalar(mean_transport.m_east, mean_transport.latitude, mean_transport.longitude, lat, lon)
    m_north = _resample_scalar(mean_transport.m_north, mean_transport.latitude, mean_transport.longitude, lat, lon)

    return _assemble_field(
        m_east, m_north, currents, sst, currents.timestamp, wind_window=mean_transport.describe()
    )


def _assemble_field(
    m_east: np.ndarray,
    m_north: np.ndarray,
    currents: VectorSnapshot,
    sst: sst_anomaly.SstAnomalyField | None,
    timestamp: datetime,
    *,
    wind_window: dict[str, Any] | None = None,
) -> UpwellingField:
    """Coastal normal, band/equator exclusion and SST corroboration — the
    half of detection that does not care whether `m_east`/`m_north` came from
    one instantaneous snapshot (`detect`) or a trailing mean
    (`detect_from_history`). Kept as one function so the two paths cannot
    silently diverge in how "upwelling-favourable" is decided, which would
    make any comparison between them meaningless.
    """
    lat = np.asarray(currents.lat, dtype="float64")
    lon = np.asarray(currents.lon, dtype="float64")
    ocean = np.isfinite(currents.u) & np.isfinite(currents.v)
    if not ocean.any():
        raise UpwellingError("the surface currents field has no ocean cells")

    periodic = field_sampling.is_globally_periodic(lon)
    dx, dy = field_sampling.cell_spacing_m(lat, lon)

    unit_east, unit_north, confidence = offshore_normal(ocean, dx, dy, periodic)

    index = m_east * unit_east + m_north * unit_north

    usable = (
        _coastal_band(ocean)
        & (confidence >= MIN_COASTLINE_CONFIDENCE)
        & np.isfinite(unit_east)
        & np.isfinite(index)
    )
    index = np.where(usable, index, np.nan).astype("float32")

    anomaly, cold, sst_reason = _corroborating_sst(sst, lat, lon, timestamp)

    return UpwellingField(
        index=index,
        coastline_confidence=confidence.astype("float32"),
        normal_east=unit_east.astype("float32"),
        normal_north=unit_north.astype("float32"),
        latitude=lat,
        longitude=lon,
        timestamp=timestamp,
        computed_at=datetime.now(UTC),
        sst_anomaly=anomaly,
        sst_cold_exceedance=cold,
        sst_timestamp=sst.timestamp if sst_reason is None and sst else None,
        sst_baseline=sst.baseline if sst_reason is None and sst else None,
        sst_source=sst.source if sst_reason is None and sst else None,
        sst_unavailable_reason=sst_reason,
        wind_window=wind_window,
    )


def _corroborating_sst(
    sst: sst_anomaly.SstAnomalyField | None,
    lat: np.ndarray,
    lon: np.ndarray,
    stamp: datetime,
) -> tuple[np.ndarray, np.ndarray, str | None]:
    """The SST anomaly on this field's grid, or a reason there is none.

    Returns all-NaN arrays alongside the reason rather than `None`, so every
    downstream read is the same shape regardless — a per-cell branch on "is
    there an SST field at all" is how a cell with no data starts rendering as a
    cell with no anomaly.
    """
    empty = np.full((lat.size, lon.size), np.nan, dtype="float32")
    if sst is None:
        return (
            empty,
            empty.copy(),
            "no sea-surface temperature anomaly is loaded — the marine heatwave "
            "detector, which computes it, has not run or has no climatology "
            "built (see `scripts/build_climatology.py`)",
        )

    # Signed, then compared on magnitude. The gap is normally large and
    # positive (OISST is weeks behind), but it can go *negative*: the wind blend
    # lagged the currents by 1.3 days on 2026-08-17, so a fresher SST field than
    # the wind is a real state rather than an impossible one. A bare `>` would
    # wave through an SST field arbitrarily far in the future of the wind.
    lag_days = (stamp - sst.timestamp).total_seconds() / 86400.0
    if abs(lag_days) > MAX_SST_LAG_DAYS:
        return (
            empty,
            empty.copy(),
            f"the most recent sea-surface temperature field is "
            f"{abs(lag_days):.1f} days "
            f"{'older' if lag_days > 0 else 'newer'} than the wind, past the "
            f"{MAX_SST_LAG_DAYS}-day limit for saying anything about today's "
            "coast",
        )

    return (
        _resample_scalar(sst.anomaly, sst.latitude, sst.longitude, lat, lon),
        _resample_scalar(sst.cold_exceedance, sst.latitude, sst.longitude, lat, lon),
        None,
    )


def _resample_scalar(
    values: np.ndarray,
    source_lat: np.ndarray,
    source_lon: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
) -> np.ndarray:
    """A NaN-holed scalar field onto this grid, via the shared sampler.

    `field_sampling.build_sampler` rather than a bare interpolator, because that
    is where the two properties this needs already live: coverage is resampled
    separately from values, so a coastal cell beside OISST's land mask keeps its
    own value instead of being poisoned to NaN by a land neighbour; and the
    longitude wrap is *measured* from the cell edges, which OISST's global grid
    needs and a regional field must not get.
    """
    field = xr.DataArray(
        np.asarray(values, dtype="float64"),
        dims=("latitude", "longitude"),
        coords={"latitude": source_lat, "longitude": source_lon},
    )
    sampler = field_sampling.build_sampler(field)
    # Into the sampler's own frame. The physics grid and OISST need not share a
    # longitude origin, and a query outside the axis silently returns NaN, which
    # would present as "no SST anywhere" rather than as a frame mismatch.
    # `vector_field.wrap_longitude`'s arithmetic, over a whole axis at once.
    origin = float(source_lon[0])
    query = origin + (np.asarray(lon, dtype="float64") - origin) % 360.0
    return sampler(query, lat).astype("float32")


def _resample(
    snapshot: VectorSnapshot, lat: np.ndarray, lon: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """One field's u/v on another field's grid.

    Same construction as `services/drift.py::_resample`, including the
    longitude wrap into the snapshot's own frame — the wind product and the
    physics product do not share an origin, and sampling with the wrong frame
    still returns a plausible field.
    """
    lon_query = np.asarray(
        [vector_field.wrap_longitude(float(value), snapshot.lon_min) for value in lon]
    )
    mesh_lat, mesh_lon = np.meshgrid(lat, lon_query, indexing="ij")
    points = np.column_stack([mesh_lat.ravel(), mesh_lon.ravel()])
    return (
        snapshot.u_interp(points).reshape(mesh_lat.shape),
        snapshot.v_interp(points).reshape(mesh_lat.shape),
    )


# --------------------------------------------------------------------- cache

_cache: UpwellingField | None = None
_cache_key: tuple[datetime, datetime | None] | None = None
_lock = threading.Lock()


def _current_field() -> UpwellingField:
    """The field for the current wind/currents timesteps.

    Computed on demand and keyed on the pair of snapshot timestamps, so the
    hourly refreshes of either input invalidate it with no wiring between the
    modules — the same trick `services/eddies.py` uses against the currents
    cache alone.
    """
    try:
        wind = copernicus_wind.snapshot()
        currents = copernicus_currents.snapshot()
    except (VectorSourceError, RuntimeError) as exc:
        raise UpwellingError(
            f"upwelling needs both the wind and surface-current fields, and one "
            f"of them has no data yet ({exc})"
        ) from exc

    # Read, never fetched: an absent anomaly is a missing corroboration, not a
    # failure of the index.
    #
    # **The lagged OISST record, deliberately, and not the live SST field.**
    # Scoring the live hourly physics field against this OISST-fitted baseline
    # was built and measured and is worse: see `services/sst_anomaly.py` for the
    # numbers. Freshness is not the binding constraint here.
    sst = heatwaves.sst_anomaly_field()

    stamp = min(wind.timestamp, currents.timestamp)
    sst_stamp = sst.timestamp if sst is not None else None
    # Keyed on *both* inputs' stamps. Keyed on the wind alone, a corroboration
    # computed against a fortnight-old SST field would survive every OISST
    # publication until the wind happened to move. The key is held separately
    # rather than read back off the field, because a field whose SST was refused
    # for age records no SST stamp at all and would never match itself.
    key = (stamp, sst_stamp)
    global _cache, _cache_key
    with _lock:
        cached = _cache
        if cached is not None and _cache_key == key:
            return cached

    field = detect(wind, currents, sst)
    coverage = field.coverage()
    corroboration = field.corroboration()
    logger.info(
        "upwelling detection at {timestamp}: {favourable} of {cells} coastal "
        "cells upwelling-favourable, {corroborated} corroborated by SST",
        timestamp=field.timestamp.isoformat(),
        favourable=coverage.get("upwelling_favourable_cells", 0),
        cells=coverage.get("coastal_cells", 0),
        corroborated=corroboration.get("corroborated_cells", "none (no SST)"),
    )

    with _lock:
        _cache = field
        _cache_key = key
    return field


def get_upwelling() -> dict[str, Any]:
    """The current field's summary."""
    return _current_field().as_dict()


def at_point(latitude: float, longitude: float) -> dict[str, Any]:
    """Upwelling state at one coordinate, for the point brief.

    Answers for open ocean as readily as for a coast — "this point is not
    coastal" is a result, and an omitted row reads as "no upwelling anywhere",
    the same rule `services/eddies.py::nearest` records.
    """
    field = _current_field()

    row = int(np.abs(field.latitude - latitude).argmin())
    delta = np.abs((field.longitude - longitude + 180.0) % 360.0 - 180.0)
    column = int(delta.argmin())

    value = float(field.index[row, column])
    common = {
        "latitude": float(field.latitude[row]),
        "longitude": float(field.longitude[column]),
        "timestamp": field.timestamp.isoformat(),
        "unit": UNIT,
    }
    if not np.isfinite(value):
        reason = "this point is not within the coastal band where the index is defined"
        if abs(field.latitude[row]) < EQUATORIAL_BAND_DEG:
            reason = (
                f"within {EQUATORIAL_BAND_DEG} degrees of the equator, where "
                "Ekman transport diverges and coastal upwelling is not the "
                "relevant mechanism"
            )
        return {**common, "available": False, "unavailable_reason": reason}

    return {
        **common,
        "available": True,
        "index": round(value, 3),
        "favourable": value > 0,
        "regime": "upwelling-favourable" if value > 0 else "downwelling-favourable",
        "coastline_confidence": round(float(field.coastline_confidence[row, column]), 3),
        "offshore_bearing_deg": round(
            float(
                np.degrees(
                    np.arctan2(
                        field.normal_east[row, column], field.normal_north[row, column]
                    )
                )
                % 360.0
            ),
            1,
        ),
        "corroboration": _point_corroboration(field, row, column),
        "note": (
            "A wind-derived index: the wind is favourable for upwelling, which "
            "is not the same as cold nutrient-rich water having surfaced."
        ),
    }


# What each state means, in the words a brief or a tooltip can print unedited.
# The wording is deliberately about *what was observed*, never "confirmed" or
# "no upwelling": the wind index and the water are two observations that can
# agree, and neither one settles the other.
_STATE_NOTES = {
    "confirmed_below_p10": (
        "The wind is favourable and the water is below its seasonal 10th "
        "percentile — the strongest agreement available here."
    ),
    "cool_anomaly": (
        f"The wind is favourable and the water is at least {COOL_ANOMALY_C} degC "
        "below its seasonal mean, though not below its 10th percentile."
    ),
    "wind_only": (
        "The wind is favourable but the water is not cool for the season. That "
        "is a real reading, not a missing one: upwelling can be suppressed by "
        "stratification, or the wind may not have blown long enough yet."
    ),
    "not_applicable": (
        "The wind is downwelling-favourable, and a warm surface would not "
        "corroborate that the way a cold one corroborates upwelling."
    ),
    "sst_unavailable": (
        "No sea-surface temperature anomaly covers this cell, so the wind index "
        "here is uncorroborated — which is not the same as contradicted."
    ),
}


def _point_corroboration(field: UpwellingField, row: int, column: int) -> dict[str, Any]:
    """The corroboration block for one cell."""
    if field.sst_unavailable_reason is not None:
        return {"available": False, "unavailable_reason": field.sst_unavailable_reason}

    state = field.state_at(row, column)
    anomaly = float(field.sst_anomaly[row, column])
    cold = float(field.sst_cold_exceedance[row, column])
    assert field.sst_timestamp is not None  # set together with the arrays
    return {
        "available": True,
        "state": state,
        "corroborated": state in ("confirmed_below_p10", "cool_anomaly"),
        "sst_anomaly_c": round(anomaly, 3) if np.isfinite(anomaly) else None,
        "below_seasonal_p10": bool(np.isfinite(cold) and cold < 0),
        "sst_timestamp": field.sst_timestamp.isoformat(),
        "lag_hours": round(
            (field.timestamp - field.sst_timestamp).total_seconds() / 3600.0, 1
        ),
        "baseline": (
            {"start": field.sst_baseline[0], "end": field.sst_baseline[1]}
            if field.sst_baseline
            else None
        ),
        "note": _STATE_NOTES[state],
    }


def is_available() -> bool:
    try:
        _current_field()
    except UpwellingError:
        return False
    return True


def cells() -> dict[str, Any]:
    """Coastal cells with a defined index, as drawable rectangles.

    Every scored cell is sent, not just the favourable ones: the sign is the
    measurement here, and a layer showing only upwelling would answer "where is
    upwelling" with a map that cannot distinguish "downwelling" from "not
    coastal". Both are drawn, on a diverging ramp about zero.
    """
    field = _current_field()

    south, north = field_sampling.cell_edges(field.latitude)
    west, east = field_sampling.cell_edges(field.longitude)
    rows, columns = np.nonzero(np.isfinite(field.index))

    return {
        **field.as_dict(),
        "cells": [
            {
                "west": round(float(west[column]), 4),
                "south": round(float(south[row]), 4),
                "east": round(float(east[column]), 4),
                "north": round(float(north[row]), 4),
                "index": round(float(field.index[row, column]), 3),
                "favourable": bool(field.index[row, column] > 0),
                "confidence": round(float(field.coastline_confidence[row, column]), 3),
                # Both travel per cell so the layer can draw agreement without
                # a second request. `null` is the anomaly's absence, never 0 —
                # a zero anomaly means the water is exactly average, which is a
                # measurement.
                "sst_anomaly_c": (
                    round(float(field.sst_anomaly[row, column]), 3)
                    if np.isfinite(field.sst_anomaly[row, column])
                    else None
                ),
                "corroboration": field.state_at(row, column),
            }
            for row, column in zip(rows.tolist(), columns.tolist(), strict=True)
        ],
    }
