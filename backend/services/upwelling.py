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
Corroborating it against an SST drop and a chlorophyll rise is a genuinely
useful second step and is *not* done here: that is a second claim needing its
own baseline (an SST anomaly needs the climatology in `services/climatology/`,
and there is no resident chlorophyll grid at all). Reporting "upwelling
confirmed" from wind alone would be exactly the overreach this codebase avoids
elsewhere.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
from loguru import logger
from scipy.ndimage import uniform_filter

from services import copernicus_currents, copernicus_wind, field_sampling, vector_field
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

METHOD = (
    "Bakun coastal upwelling index: Ekman transport from bulk wind stress, "
    "projected onto the offshore normal of the model land mask"
)

UNIT = "m^2/s per metre of coastline"

LIMITS = (
    "A wind-derived index, not an observation of upwelled water. It says the "
    "wind is favourable; stratification, topography and relaxation decide "
    "whether cold nutrient-rich water actually surfaces.",
    "Not corroborated against sea-surface temperature or chlorophyll. That is a "
    "second claim needing its own baseline and is deliberately not made here.",
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


def detect(wind: VectorSnapshot, currents: VectorSnapshot) -> UpwellingField:
    """Detect upwelling-favourable coasts.

    Pure — two snapshots in, a field out, no fetching and no clock beyond the
    stamp. Same shape as `services/eddies.py::detect` and for the same reason:
    the science is then testable without a network.

    The **currents** snapshot supplies the grid and the land mask; the wind is
    resampled onto it. Not the other way round: the wind product covers the
    whole globe including land, so its coverage edge is not a coast.
    """
    lat = np.asarray(currents.lat, dtype="float64")
    lon = np.asarray(currents.lon, dtype="float64")
    ocean = np.isfinite(currents.u) & np.isfinite(currents.v)
    if not ocean.any():
        raise UpwellingError("the surface currents field has no ocean cells")

    periodic = field_sampling.is_globally_periodic(lon)
    dx, dy = field_sampling.cell_spacing_m(lat, lon)

    wind_u, wind_v = _resample(wind, lat, lon)
    tau_east, tau_north = wind_stress(wind_u, wind_v)
    f = coriolis(lat)
    m_east, m_north = ekman_transport(tau_east, tau_north, f)

    unit_east, unit_north, confidence = offshore_normal(ocean, dx, dy, periodic)

    index = m_east * unit_east + m_north * unit_north

    usable = (
        _coastal_band(ocean)
        & (confidence >= MIN_COASTLINE_CONFIDENCE)
        & np.isfinite(unit_east)
        & np.isfinite(index)
    )
    index = np.where(usable, index, np.nan).astype("float32")

    return UpwellingField(
        index=index,
        coastline_confidence=confidence.astype("float32"),
        normal_east=unit_east.astype("float32"),
        normal_north=unit_north.astype("float32"),
        latitude=lat,
        longitude=lon,
        # The stalest of the two inputs, for the same reason `services/drift.py`
        # reports the stalest term: a composite is only as current as its oldest
        # component, and the wind blend routinely lags the hourly currents.
        timestamp=min(wind.timestamp, currents.timestamp),
        computed_at=datetime.now(UTC),
    )


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

    stamp = min(wind.timestamp, currents.timestamp)
    global _cache
    with _lock:
        cached = _cache
        if cached is not None and cached.timestamp == stamp:
            return cached

    field = detect(wind, currents)
    coverage = field.coverage()
    logger.info(
        "upwelling detection at {timestamp}: {favourable} of {cells} coastal "
        "cells upwelling-favourable",
        timestamp=field.timestamp.isoformat(),
        favourable=coverage.get("upwelling_favourable_cells", 0),
        cells=coverage.get("coastal_cells", 0),
    )

    with _lock:
        _cache = field
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
        "note": (
            "A wind-derived index: the wind is favourable for upwelling, which "
            "is not the same as cold nutrient-rich water having surfaced."
        ),
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
            }
            for row, column in zip(rows.tolist(), columns.tolist(), strict=True)
        ],
    }
