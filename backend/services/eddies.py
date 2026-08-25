"""Mesoscale eddy detection from the live surface-current field.

The platform serves 32 variables and, until this module, said nothing about
*what is happening* in them. This is the first detector: it turns the surface
current field the map already draws into a list of named things — rotating
features with a position, a size, a polarity and an intensity.

**This module detects; it does not track, and that split is deliberate rather
than incomplete.** Age and trajectory are a frame-to-frame assignment problem
with its own failure modes (an eddy that flickers identity between two
timesteps produces a "track" that is an artefact of the matcher rather than an
observation), so `services/eddy_tracking.py` owns that as a separate module
built on top of `current_detection()` rather than a flag added here. Nothing
in *this* module holds state between refreshes — `detect()` stays a pure
snapshot-in, features-out function, which is what lets the tracker treat every
call here as one frame in a sequence it alone is responsible for stitching
together.

Design decisions worth keeping:

* **Okubo-Weiss over the velocity field, not closed SSH contours.** Both are
  standard. OW wins here on one practical ground: the surface currents cache is
  already warm, global and hourly (`services/copernicus_currents.py`), so
  detection costs a numpy pass over a grid that is in memory rather than a
  second global fetch of sea level. `sea_level_anomaly` exists as a *forecast*
  grid rather than a live observed field, which is the wrong footing for a
  detector that claims to say what is happening now.
* **The threshold is relative, and that is the method's known weakness.**
  W < -0.2 sigma_W is the conventional choice (Isern-Fontanet et al. 2003), but
  sigma is computed over whatever water is in the frame, so the same ocean can
  yield a different count under a different mask. The value and the sigma it was
  taken against are both reported, because a count without them is not
  reproducible.
* **The grid sets the smallest thing that can be found.** The currents cache is
  downsampled to ~0.25 degrees, so an eddy needs a few cells across to exist at
  all. `MIN_RADIUS_KM` is set from that, not from oceanography, and submesoscale
  features are simply invisible here. Reported as `min_resolvable_radius_km`
  rather than left for the reader to infer from an absence.
* **The equatorial band is excluded.** Polarity is defined relative to the
  Coriolis parameter — cyclonic means rotating the same way the planet does at
  that latitude — and f goes to zero at the equator. Within a few degrees the
  sign is meaningless and the geostrophic reading of the field breaks down
  entirely, so those cells are dropped rather than labelled with a coin flip.
* **Longitude wraps.** The field is global, so a feature sitting on the
  dateline arrives as two components on opposite edges of the array. Both the
  derivatives and the component labelling close that seam, and the centroid is
  a circular mean for the same reason — an arithmetic mean of +179 and -179 is
  0, which puts a Pacific eddy in the Gulf of Guinea.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
from loguru import logger
from scipy import ndimage

from services import copernicus_currents, field_sampling
from services.field_sampling import is_globally_periodic
from services.vector_source import VectorSnapshot, VectorSourceError

EARTH_RADIUS_M = 6_371_000.0

# W < -k * sigma_W. The conventional k, and the one the literature's counts are
# comparable against. Lowering it finds more, weaker features; raising it keeps
# only cores.
OW_THRESHOLD_FACTOR = 0.2

# Below this the Coriolis parameter is too small for "cyclonic" to mean
# anything. 5 degrees is the usual cut in eddy-census work.
EQUATORIAL_BAND_DEG = 5.0

# Set by the grid, not by oceanography: at ~0.25 degrees a feature needs several
# cells across before its rotation is resolved rather than interpolated. A
# 40 km equivalent radius is ~4 cells of area at mid-latitudes.
MIN_RADIUS_KM = 40.0

# Above this it is not an eddy — it is a gyre, a meander of a boundary current,
# or two features the threshold merged. Mesoscale eddies top out near 250 km.
MAX_RADIUS_KM = 300.0

# A component smaller than this is threshold noise however large its cells are
# at high latitude, where a cell is small in km but the count is what carries
# the shape.
MIN_CELLS = 6

# Aggregates over the polar caps are dominated by tiny cells and sea-ice
# artefacts in the velocity field, and this is the same 60-degree cut
# `services/crw.py` takes for the same class of reason.
MAX_LATITUDE_DEG = 60.0

# Most eddies returned by one request. The global ocean carries thousands at any
# moment; a map layer or a brief wants the strongest of them, and an unbounded
# list is a payload nobody reads.
DEFAULT_LIMIT = 200
MAX_LIMIT = 2000

METHOD = "Okubo-Weiss over surface geostrophic-scale velocity"

LIMITS = (
    "Detection only — these features are not tracked between refreshes, so no "
    "eddy here has an age or a trajectory.",
    "Okubo-Weiss thresholds are relative to the variance of the field in view; "
    "the count is sensitive to that threshold and is not an eddy census.",
    "Features smaller than the grid can resolve are absent, not zero.",
    "Coastal cells are lost where the derivative stencil meets the land mask, "
    "so nearshore eddies are under-detected.",
)


class EddyError(RuntimeError):
    """Eddy detection is unavailable — almost always because the surface
    currents cache it reads has not warmed up yet."""


@dataclass(frozen=True)
class Eddy:
    """One detected rotating feature."""

    latitude: float
    longitude: float
    polarity: str  # "cyclonic" | "anticyclonic"
    radius_km: float
    area_km2: float
    # Relative vorticity, 1/s. Signed: positive is counter-clockwise seen from
    # above, whichever hemisphere that happens to be cyclonic in.
    vorticity: float
    # Rotational speed scale, m/s — the fastest water in the feature, which is
    # what a reader means by "how strong".
    max_speed: float
    mean_speed: float
    cells: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "latitude": round(self.latitude, 4),
            "longitude": round(self.longitude, 4),
            "polarity": self.polarity,
            "radius_km": round(self.radius_km, 1),
            "area_km2": round(self.area_km2, 1),
            "vorticity_per_s": float(f"{self.vorticity:.3e}"),
            "max_speed_ms": round(self.max_speed, 3),
            "mean_speed_ms": round(self.mean_speed, 3),
            "cells": self.cells,
        }


@dataclass(frozen=True)
class Detection:
    """Everything one pass over one snapshot produced."""

    eddies: tuple[Eddy, ...]
    timestamp: datetime
    computed_at: datetime
    threshold: float
    sigma_w: float
    grid_spacing_deg: float
    min_resolvable_radius_km: float


_cache: Detection | None = None
_lock = threading.Lock()


# --------------------------------------------------------------- derivatives


# The grid geometry these detectors share now lives in `field_sampling`, so the
# derivative stencil and the metres-per-step arithmetic have exactly one
# definition. `services/upwelling.py` needs the identical maths, and two copies
# of a seam-closing stencil is precisely the kind of duplication that drifts
# without either field looking wrong.
_cell_spacing = field_sampling.cell_spacing_m
_d_dx = field_sampling.d_dx
_d_dy = field_sampling.d_dy


def okubo_weiss(
    u: np.ndarray, v: np.ndarray, lat: np.ndarray, lon: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """The Okubo-Weiss parameter and the relative vorticity behind it.

    W = Sn^2 + Ss^2 - zeta^2, so W < 0 is water where rotation beats strain —
    the interior of a coherent vortex. Returned together because the sign of
    zeta is what makes a detected patch cyclonic or anticyclonic, and
    recomputing it from a second pass is how the two would drift apart.
    """
    periodic = is_globally_periodic(lon)
    dx, dy = _cell_spacing(lat, lon)

    du_dx = _d_dx(u, dx, periodic)
    dv_dx = _d_dx(v, dx, periodic)
    du_dy = _d_dy(u, dy)
    dv_dy = _d_dy(v, dy)

    normal_strain = du_dx - dv_dy
    shear_strain = dv_dx + du_dy
    vorticity = dv_dx - du_dy

    w = normal_strain**2 + shear_strain**2 - vorticity**2
    return w, vorticity


# ------------------------------------------------------------------ labelling


def _label_with_wrap(mask: np.ndarray, periodic: bool) -> tuple[np.ndarray, int]:
    """Connected components, joined across the antimeridian when the grid wraps.

    `ndimage.label` sees a flat array, so a feature straddling the seam comes
    back as two. Rows touching both edges are unioned afterwards rather than by
    padding the array, which would double a 1440-column global grid to find a
    handful of joins.
    """
    labels, count = ndimage.label(mask)
    if not periodic or count == 0:
        return labels, count

    parent = list(range(count + 1))

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    west = labels[:, 0]
    east = labels[:, -1]
    for row in np.nonzero((west > 0) & (east > 0))[0]:
        union(int(west[row]), int(east[row]))

    remap = np.array([find(index) for index in range(count + 1)])
    # Compact the surviving ids so downstream code can still iterate 1..n.
    survivors = {value: rank for rank, value in enumerate(sorted(set(remap[1:])), start=1)}
    remap = np.array([0] + [survivors[remap[index]] for index in range(1, count + 1)])
    return remap[labels], len(survivors)


def _circular_mean_longitude(longitudes: np.ndarray, weights: np.ndarray) -> float:
    """Weighted mean longitude that survives the dateline.

    The arithmetic mean of +179 and -179 is 0. Same reasoning as the codebase's
    circular-variable handling everywhere else: interpolate sin/cos, recombine
    with atan2.
    """
    radians = np.radians(longitudes)
    sin_sum = float(np.sum(weights * np.sin(radians)))
    cos_sum = float(np.sum(weights * np.cos(radians)))
    if sin_sum == 0.0 and cos_sum == 0.0:
        return float(np.average(longitudes, weights=weights))
    return float(np.degrees(math.atan2(sin_sum, cos_sum)))


# ------------------------------------------------------------------ detection


def detect(snapshot: VectorSnapshot) -> Detection:
    """Every eddy in one current-field snapshot.

    Pure: no cache, no network, no state. `tests/test_eddies.py` drives it with
    a synthetic rotating field, which is the only way to assert that a detected
    polarity and radius are the ones that went in.
    """
    lat = np.asarray(snapshot.lat, dtype=np.float64)
    lon = np.asarray(snapshot.lon, dtype=np.float64)
    u = np.asarray(snapshot.u, dtype=np.float64)
    v = np.asarray(snapshot.v, dtype=np.float64)

    periodic = is_globally_periodic(lon)
    w, vorticity = okubo_weiss(u, v, lat, lon)

    # The band the detector is willing to speak about: away from the equator,
    # where polarity has a meaning, and off the polar caps, where the velocity
    # field carries ice artefacts and the cells are too small to mean much.
    usable_row = (np.abs(lat) >= EQUATORIAL_BAND_DEG) & (np.abs(lat) <= MAX_LATITUDE_DEG)
    usable = np.isfinite(w) & usable_row[:, None]
    if not usable.any():
        raise EddyError("the current field carries no usable cells between 5 and 60 degrees")

    sigma_w = float(np.std(w[usable]))
    if not math.isfinite(sigma_w) or sigma_w == 0.0:
        raise EddyError("the current field is uniform, so no rotation can be detected")
    threshold = -OW_THRESHOLD_FACTOR * sigma_w

    mask = usable & (w < threshold)
    labels, count = _label_with_wrap(mask, periodic)
    if count == 0:
        return _empty_detection(snapshot, threshold, sigma_w, lat, lon)

    speed = np.hypot(u, v)
    dlat = math.radians(float(np.abs(np.diff(lat)).mean()))
    dlon = math.radians(float(np.abs(np.diff(lon)).mean()))
    # Cell area on a sphere, by row. Not the flat dx*dy product: at 60 degrees
    # that is 15% wrong, which lands straight in the reported radius.
    row_area_m2 = EARTH_RADIUS_M**2 * dlat * dlon * np.cos(np.radians(lat))

    # Every component's cells in one pass. The obvious loop — `np.nonzero(labels
    # == index)` per component — rescans the whole grid once per feature, which
    # on a global field with ~2,000 detections is ~2 billion comparisons and
    # measured **37 s**. Sorting the labelled cells once and slicing costs 0.4 s
    # for the same answer.
    flat = labels.ravel()
    occupied = np.nonzero(flat)[0]
    order = occupied[np.argsort(flat[occupied], kind="stable")]
    starts = np.searchsorted(flat[order], np.arange(1, count + 2))
    all_rows, all_cols = np.unravel_index(order, labels.shape)

    eddies: list[Eddy] = []
    for index in range(1, count + 1):
        span = slice(starts[index - 1], starts[index])
        rows, cols = all_rows[span], all_cols[span]
        if rows.size < MIN_CELLS:
            continue

        areas = row_area_m2[rows]
        area_m2 = float(np.sum(areas))
        radius_km = math.sqrt(area_m2 / math.pi) / 1000.0
        if not MIN_RADIUS_KM <= radius_km <= MAX_RADIUS_KM:
            continue

        cell_vorticity = vorticity[rows, cols]
        finite = np.isfinite(cell_vorticity)
        if not finite.any():
            continue

        weights = np.where(finite, areas, 0.0)
        centre_lat = float(np.average(lat[rows], weights=weights))
        centre_lon = _circular_mean_longitude(lon[cols], weights)
        mean_vorticity = float(np.average(np.nan_to_num(cell_vorticity), weights=weights))

        cell_speed = speed[rows, cols]
        cell_speed = cell_speed[np.isfinite(cell_speed)]
        if cell_speed.size == 0:
            continue

        eddies.append(
            Eddy(
                latitude=centre_lat,
                longitude=centre_lon,
                # Cyclonic is rotation with the planet: counter-clockwise north
                # of the equator, clockwise south of it. Comparing the sign of
                # vorticity against the sign of latitude *is* comparing it
                # against the sign of f, without needing f itself.
                polarity=(
                    "cyclonic"
                    if mean_vorticity * centre_lat > 0
                    else "anticyclonic"
                ),
                radius_km=radius_km,
                area_km2=area_m2 / 1e6,
                vorticity=mean_vorticity,
                max_speed=float(np.max(cell_speed)),
                mean_speed=float(np.mean(cell_speed)),
                cells=int(rows.size),
            )
        )

    # Strongest first: |vorticity| is what "intense" means for a vortex, and it
    # is the ranking a reader keeping the top N wants.
    eddies.sort(key=lambda eddy: abs(eddy.vorticity), reverse=True)

    return Detection(
        eddies=tuple(eddies),
        timestamp=snapshot.timestamp,
        computed_at=datetime.now(UTC),
        threshold=threshold,
        sigma_w=sigma_w,
        grid_spacing_deg=float(np.abs(np.diff(lat)).mean()),
        min_resolvable_radius_km=MIN_RADIUS_KM,
    )


def _empty_detection(
    snapshot: VectorSnapshot,
    threshold: float,
    sigma_w: float,
    lat: np.ndarray,
    lon: np.ndarray,
) -> Detection:
    return Detection(
        eddies=(),
        timestamp=snapshot.timestamp,
        computed_at=datetime.now(UTC),
        threshold=threshold,
        sigma_w=sigma_w,
        grid_spacing_deg=float(np.abs(np.diff(lat)).mean()),
        min_resolvable_radius_km=MIN_RADIUS_KM,
    )


# --------------------------------------------------------------------- cache


def current_detection() -> Detection:
    """The detection for the currents cache's current timestep.

    Computed on demand rather than on a schedule: it costs a second of numpy
    over a grid that is already resident, and the currents cache it reads is
    refreshed hourly by a job that knows nothing about this module. Keying on
    that snapshot's timestamp means a refresh invalidates this without any
    wiring between the two.
    """
    try:
        snapshot = copernicus_currents.snapshot()
    except VectorSourceError as exc:
        raise EddyError(
            f"the surface currents field has no data yet, so eddies cannot be "
            f"detected ({exc})"
        ) from exc

    global _cache
    with _lock:
        cached = _cache
        if cached is not None and cached.timestamp == snapshot.timestamp:
            return cached

    detection = detect(snapshot)
    logger.info(
        "eddy detection: {count} features at {timestamp} "
        "(sigma_W={sigma:.3e}, threshold={threshold:.3e})",
        count=len(detection.eddies),
        timestamp=detection.timestamp.isoformat(),
        sigma=detection.sigma_w,
        threshold=detection.threshold,
    )

    with _lock:
        _cache = detection
    return detection


def _in_bbox(eddy: Eddy, bbox: tuple[float, float, float, float]) -> bool:
    """Whether an eddy centre falls inside (south, west, north, east).

    East < west means the box crosses the antimeridian, which is a real request
    over the Pacific rather than a malformed one.
    """
    south, west, north, east = bbox
    if not south <= eddy.latitude <= north:
        return False
    if west <= east:
        return west <= eddy.longitude <= east
    return eddy.longitude >= west or eddy.longitude <= east


def get_eddies(
    *,
    bbox: tuple[float, float, float, float] | None = None,
    polarity: str | None = None,
    min_radius_km: float | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Detected eddies, filtered, with everything needed to read the number.

    The response carries the threshold, the sigma it was taken against and the
    limitations of the method alongside the features, because a bare count of
    eddies reads as a measurement and is not one.
    """
    if polarity is not None and polarity not in ("cyclonic", "anticyclonic"):
        raise EddyError(
            f"unknown polarity {polarity!r}; expected 'cyclonic' or 'anticyclonic'"
        )
    limit = max(1, min(int(limit), MAX_LIMIT))

    detection = current_detection()
    selected = list(detection.eddies)
    if bbox is not None:
        selected = [eddy for eddy in selected if _in_bbox(eddy, bbox)]
    if polarity is not None:
        selected = [eddy for eddy in selected if eddy.polarity == polarity]
    if min_radius_km is not None:
        selected = [eddy for eddy in selected if eddy.radius_km >= min_radius_km]

    matched = len(selected)
    selected = selected[:limit]

    return {
        "timestamp": detection.timestamp.isoformat(),
        "computed_at": detection.computed_at.isoformat(),
        "source": copernicus_currents.SOURCE_LABEL,
        "method": METHOD,
        "threshold": {
            "okubo_weiss": float(f"{detection.threshold:.3e}"),
            "sigma_w": float(f"{detection.sigma_w:.3e}"),
            "factor": OW_THRESHOLD_FACTOR,
        },
        "coverage": {
            "grid_spacing_deg": round(detection.grid_spacing_deg, 4),
            "min_resolvable_radius_km": detection.min_resolvable_radius_km,
            "max_radius_km": MAX_RADIUS_KM,
            "latitude_band_deg": [EQUATORIAL_BAND_DEG, MAX_LATITUDE_DEG],
        },
        "detected": len(detection.eddies),
        "matched": matched,
        "returned": len(selected),
        "limits": list(LIMITS),
        "eddies": [eddy.as_dict() for eddy in selected],
    }


def nearest(latitude: float, longitude: float) -> dict[str, Any] | None:
    """The detected eddy nearest a point, and whether the point is inside it.

    For `services/brief.py`, which asks a different question from the map's: not
    "what is in view" but "is this coordinate in one". Returns None when nothing
    was detected at all, which the caller must distinguish from an eddy being
    far away — `distance_km` says how far, and no answer says nothing.

    Distance is great-circle from the centre. "Inside" compares it against the
    equivalent radius, so it is as round as the detection is: a point just
    outside a lopsided feature can read as outside while sitting in its water.
    """
    detection = current_detection()
    if not detection.eddies:
        return None

    lat_rad = math.radians(latitude)
    lon_rad = math.radians(longitude)

    def separation(eddy: Eddy) -> float:
        other_lat = math.radians(eddy.latitude)
        other_lon = math.radians(eddy.longitude)
        # Haversine rather than a flat approximation: the nearest eddy to a
        # high-latitude point can be several degrees of longitude away, where
        # a degree is a third of what it is at the equator.
        sin_lat = math.sin((other_lat - lat_rad) / 2) ** 2
        sin_lon = math.sin((other_lon - lon_rad) / 2) ** 2
        inner = sin_lat + math.cos(lat_rad) * math.cos(other_lat) * sin_lon
        return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(inner)) / 1000.0

    closest = min(detection.eddies, key=separation)
    distance_km = separation(closest)

    return {
        **closest.as_dict(),
        "distance_km": round(distance_km, 1),
        "inside": distance_km <= closest.radius_km,
        "timestamp": detection.timestamp.isoformat(),
    }


def is_available() -> bool:
    return copernicus_currents.is_available()
