"""Frame-to-frame identity for detected eddies — the half `services/eddies.py`
deliberately left out.

`eddies.py` says why tracking is its own module rather than a flag on
detection: "an eddy that flickers identity between two timesteps produces a
'track' that is an artefact of the matcher rather than an observation."
Everything below exists to make that artefact rare, and to be honest about
the one thing that would actually prove it isn't happening.

**Matching, not tracking, is the hard part, and it does not scale the naive
way.** A global detection pass can carry up to `eddies.MAX_LIMIT` (2000)
features. A dense every-track-against-every-eddy distance matrix, or a
Hungarian solve over it, is `O(n^2)`/`O(n^3)` in a number that large — and
almost all of those pairs are on opposite sides of the planet. `_candidate_pairs`
shortlists with a `scipy.spatial.cKDTree` instead (a flat-earth approximation,
good enough for a radius query at the gate's own scale of tens of km — every
shortlisted pair is re-scored with exact haversine before it counts), then
`_connected_components` splits the shortlist into independent clusters via
union-find. Almost every cluster is one track and one eddy — a trivial direct
match — and only a genuinely crowded patch of ocean (two eddies passing close
together, one splitting) pays for an actual `linear_sum_assignment` solve,
over that cluster's own small sub-matrix rather than the whole ocean's.

**The match gate is sized from the detection grid, not from eddy physics, and
that is deliberate.** Mesoscale eddies propagate at a few km/day; at this
module's hourly cadence that is not the dominant source of apparent movement
between two frames — the detection's own centroid jitter at ~0.25° grid
resolution is. `GATE_CELLS * grid_spacing_deg` sizes the gate off the
detector's actual resolution instead of a propagation speed that would be
smaller than the noise floor it needs to survive.

**State does not survive a restart** — an in-process dict, for the same
reason `services/wind_history.py` accepts it: there is no upstream that can
answer "what did this eddy look like six hours ago" for this to fall back to,
and a database record implies a durability guarantee this does not need to
make for a computed, re-derivable-from-history-if-ever-needed series.
(`services/dashboard/history.py`'s KPI buffer used to be cited here as the
same shape; it now persists to Postgres, since a dashboard card's sparkline —
unlike this tracker's own working state — is worth surviving a restart.)

**What is validated, and what is still open.** The matcher's own correctness
(a track never breaks continuity when it shouldn't; two crossing eddies never
swap identity; polarity never flips mid-track; a missed frame or two does not
fork a new identity) is checked directly against synthetic, controlled
scenarios in `tests/test_eddy_tracking.py` — real validation of the
algorithm, not a demo that looks plausible. **Accuracy against a real,
published eddy atlas is not validated, and could not be within this pass**:
AVISO+'s Mesoscale Eddy Trajectory Atlas (META, the standard reference
product built from altimetry) needs a registered AVISO+ account — checked
2026-08-24, the product page states registration is required and gives no
keyless download — the same shape of blocker as WDPA for
`services/geofencing.py`'s Marine Protected Areas. That comparison is the
next step once such an account exists; this module is honest that it has not
been taken.
"""

from __future__ import annotations

import itertools
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
from loguru import logger
from scipy.optimize import linear_sum_assignment
from scipy.spatial import cKDTree

from services.eddies import Detection, Eddy, EddyError, current_detection

EARTH_RADIUS_KM = 6371.0088
KM_PER_DEGREE = 111.32

# Consecutive missed frames a track tolerates before it is retired. At the
# hourly cadence this runs on, 2 misses is a 2-3 hour gap — enough to survive
# one transient dip below the detection threshold without the same physical
# eddy reappearing under a brand new identity.
MAX_MISSES = 2

# History kept per track, bounding memory on a long-running process — the
# same ring-buffer reasoning as services/dashboard/history.py. 72 hourly
# fixes is 3 days, comfortably longer than this method resolves a track
# reliably anyway.
MAX_HISTORY = 72

# The matching gate as a multiple of the detection grid's own cell size —
# see the module docstring for why this is sized from grid resolution
# (centroid jitter) rather than eddy propagation speed.
GATE_CELLS = 3.0

DEFAULT_LIMIT = 200
MAX_LIMIT = 2000


class TrackingError(RuntimeError):
    """Tracking could not advance — currently only when the detector itself
    has no data yet."""


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class _Fix:
    """One track's state at one timestamp — the fields that matter for
    continuity and reporting, copied out of the `Eddy` rather than holding a
    reference to it (a `Detection` is not kept alive once processed)."""

    timestamp: datetime
    latitude: float
    longitude: float
    radius_km: float
    area_km2: float
    max_speed_ms: float
    mean_speed_ms: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "radius_km": self.radius_km,
        }


def _fix_from(eddy: Eddy, timestamp: datetime) -> _Fix:
    return _Fix(
        timestamp=timestamp,
        latitude=eddy.latitude,
        longitude=eddy.longitude,
        radius_km=eddy.radius_km,
        area_km2=eddy.area_km2,
        max_speed_ms=eddy.max_speed,
        mean_speed_ms=eddy.mean_speed,
    )


@dataclass
class Track:
    track_id: str
    polarity: str
    history: list[_Fix] = field(default_factory=list)
    misses: int = 0

    @property
    def latest(self) -> _Fix:
        return self.history[-1]

    @property
    def age_hours(self) -> float:
        span = self.history[-1].timestamp - self.history[0].timestamp
        return span.total_seconds() / 3600.0

    def as_dict(self, *, include_path: bool = True) -> dict[str, Any]:
        latest = self.latest
        payload = {
            "track_id": self.track_id,
            "polarity": self.polarity,
            "latitude": latest.latitude,
            "longitude": latest.longitude,
            "radius_km": latest.radius_km,
            "area_km2": latest.area_km2,
            "max_speed_ms": latest.max_speed_ms,
            "mean_speed_ms": latest.mean_speed_ms,
            "hits": len(self.history),
            "age_hours": round(self.age_hours, 1),
            "first_seen": self.history[0].timestamp.isoformat(),
            "last_seen": latest.timestamp.isoformat(),
        }
        if include_path:
            payload["path"] = [fix.as_dict() for fix in self.history]
        return payload


_tracks: dict[str, Track] = {}
_last_processed_timestamp: datetime | None = None
_track_counter = itertools.count(1)
_lock = threading.Lock()


def _new_track_id(polarity: str) -> str:
    prefix = "C" if polarity == "cyclonic" else "A"
    return f"{prefix}{next(_track_counter):06d}"


def _project(lat: float, lon: float, lon_scale: float) -> tuple[float, float]:
    """A flat-earth (lat, lon) -> (km, km) projection, accurate only at the
    gate's own scale of tens of km — used solely to shortlist KD-tree
    candidates. Every shortlisted pair is re-scored with exact haversine
    distance before it is trusted for anything."""
    return (lat * KM_PER_DEGREE, lon * KM_PER_DEGREE * lon_scale)


def _candidate_pairs(
    tracks: list[Track], eddies_list: list[Eddy], gate_km: float
) -> list[tuple[int, int, float]]:
    """(track_index, eddy_index, distance_km) for every pair within the gate."""
    if not tracks or not eddies_list:
        return []

    ref_lat = math.radians(float(np.mean([e.latitude for e in eddies_list])))
    lon_scale = max(math.cos(ref_lat), 0.1)

    eddy_points = np.array([_project(e.latitude, e.longitude, lon_scale) for e in eddies_list])
    tree = cKDTree(eddy_points)

    # Generous over the gate to absorb the flat-earth approximation's error;
    # the exact haversine check below is what actually enforces the gate.
    search_radius_km = gate_km * 1.5

    pairs: list[tuple[int, int, float]] = []
    for t_idx, track in enumerate(tracks):
        point = _project(track.latest.latitude, track.latest.longitude, lon_scale)
        for e_idx in tree.query_ball_point(point, r=search_radius_km):
            eddy = eddies_list[e_idx]
            distance = _haversine_km(track.latest.latitude, track.latest.longitude, eddy.latitude, eddy.longitude)
            if distance <= gate_km:
                pairs.append((t_idx, int(e_idx), distance))
    return pairs


def _connected_components(
    n_tracks: int, n_eddies: int, pairs: list[tuple[int, int, float]]
) -> list[tuple[list[int], list[int]]]:
    """Group tracks and eddies into independent clusters via union-find, so
    each cluster's assignment problem is solved on its own rather than
    building one dense matrix for the whole ocean."""
    parent = list(range(n_tracks + n_eddies))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for t_idx, e_idx, _distance in pairs:
        union(t_idx, n_tracks + e_idx)

    groups: dict[int, tuple[list[int], list[int]]] = {}
    for t_idx in range(n_tracks):
        groups.setdefault(find(t_idx), ([], []))[0].append(t_idx)
    for e_idx in range(n_eddies):
        groups.setdefault(find(n_tracks + e_idx), ([], []))[1].append(e_idx)

    return [group for group in groups.values() if group[0] and group[1]]


def _match(tracks: list[Track], eddies_list: list[Eddy], gate_km: float) -> dict[int, int]:
    """track_index -> eddy_index for every match found, solved optimally
    within each independent spatial cluster rather than greedily."""
    pairs = _candidate_pairs(tracks, eddies_list, gate_km)
    matches: dict[int, int] = {}
    if not pairs:
        return matches

    pair_lookup = {(t, e): d for t, e, d in pairs}
    for track_indices, eddy_indices in _connected_components(len(tracks), len(eddies_list), pairs):
        if len(track_indices) == 1 and len(eddy_indices) == 1:
            matches[track_indices[0]] = eddy_indices[0]
            continue

        # A genuinely ambiguous cluster (more than one candidate on either
        # side) — solved exactly, but only over this cluster's own small
        # sub-matrix. Unset pairs cost more than the gate so they are never
        # chosen when a real candidate is available, without needing a
        # ragged/sparse cost matrix.
        cost = np.full((len(track_indices), len(eddy_indices)), gate_km * 10.0)
        for i, t_idx in enumerate(track_indices):
            for j, e_idx in enumerate(eddy_indices):
                distance = pair_lookup.get((t_idx, e_idx))
                if distance is not None:
                    cost[i, j] = distance

        row_idx, col_idx = linear_sum_assignment(cost)
        for i, j in zip(row_idx, col_idx, strict=True):
            if cost[i, j] <= gate_km:
                matches[track_indices[i]] = eddy_indices[j]

    return matches


def update(detection: Detection | None = None) -> None:
    """Advance tracking state by one detection frame.

    Idempotent on a repeated or stale timestamp — the scheduler and an
    on-demand caller can both invoke this without double-counting a frame
    the currents cache has not actually refreshed since.

    Matching is polarity-separated (a cyclonic eddy can never become
    anticyclonic — the same physical fact `eddies.py` uses to define
    polarity in the first place) and gated at `GATE_CELLS` times the
    detection's own grid spacing.
    """
    global _last_processed_timestamp
    if detection is None:
        detection = current_detection()

    with _lock:
        if _last_processed_timestamp is not None and detection.timestamp <= _last_processed_timestamp:
            return

        gate_km = GATE_CELLS * detection.grid_spacing_deg * KM_PER_DEGREE

        for polarity in ("cyclonic", "anticyclonic"):
            active_ids = [track_id for track_id, track in _tracks.items() if track.polarity == polarity]
            active_tracks = [_tracks[track_id] for track_id in active_ids]
            polarity_eddies = [eddy for eddy in detection.eddies if eddy.polarity == polarity]

            matches = _match(active_tracks, polarity_eddies, gate_km)
            matched_eddy_indices = set(matches.values())

            for t_idx, track_id in enumerate(active_ids):
                track = _tracks[track_id]
                if t_idx in matches:
                    track.history.append(_fix_from(polarity_eddies[matches[t_idx]], detection.timestamp))
                    del track.history[:-MAX_HISTORY]
                    track.misses = 0
                else:
                    track.misses += 1

            for e_idx, eddy in enumerate(polarity_eddies):
                if e_idx not in matched_eddy_indices:
                    track_id = _new_track_id(polarity)
                    _tracks[track_id] = Track(
                        track_id=track_id,
                        polarity=polarity,
                        history=[_fix_from(eddy, detection.timestamp)],
                    )

        for track_id in [tid for tid, track in _tracks.items() if track.misses > MAX_MISSES]:
            del _tracks[track_id]

        _last_processed_timestamp = detection.timestamp


async def refresh() -> None:
    """Scheduler entry point (see `main.py`).

    Wrapped `async` only for consistency with every other scheduled job
    there; the work itself is synchronous — it reads the currents cache
    `eddies.py` already holds resident, the same on-demand-cost compute that
    module's own callers pay, not a new fetch.
    """
    try:
        update()
    except EddyError:
        # The currents cache has not warmed up yet (e.g. at boot). Nothing to
        # track this cycle; the next scheduled run tries again once it has,
        # same as eddies.py's own on-demand path degrading rather than raising
        # into the scheduler.
        logger.info("eddy tracking skipped this cycle: currents cache not ready yet")


def _in_bbox(track: Track, bbox: tuple[float, float, float, float]) -> bool:
    south, west, north, east = bbox
    lat, lon = track.latest.latitude, track.latest.longitude
    if not south <= lat <= north:
        return False
    if west <= east:
        return west <= lon <= east
    return lon >= west or lon <= east


def get_tracks(
    *,
    bbox: tuple[float, float, float, float] | None = None,
    polarity: str | None = None,
    min_age_hours: float | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Every currently active track, filtered — mirrors `eddies.get_eddies`'s
    shape so a caller already reading that endpoint recognises this one.

    A track with `hits == 1` is a detection that has not yet been confirmed
    by a second frame — reported, not hidden, but `age_hours == 0` says so
    plainly rather than implying a lifespan that has not been observed yet.
    """
    if polarity is not None and polarity not in ("cyclonic", "anticyclonic"):
        raise TrackingError(f"unknown polarity {polarity!r}; expected 'cyclonic' or 'anticyclonic'")
    limit = max(1, min(int(limit), MAX_LIMIT))

    with _lock:
        selected = list(_tracks.values())

    if bbox is not None:
        selected = [track for track in selected if _in_bbox(track, bbox)]
    if polarity is not None:
        selected = [track for track in selected if track.polarity == polarity]
    if min_age_hours is not None:
        selected = [track for track in selected if track.age_hours >= min_age_hours]

    selected.sort(key=lambda track: track.age_hours, reverse=True)
    matched = len(selected)
    selected = selected[:limit]

    return {
        "last_processed_timestamp": _last_processed_timestamp.isoformat() if _last_processed_timestamp else None,
        "active_tracks": len(_tracks),
        "matched": matched,
        "returned": len(selected),
        "gate_cells": GATE_CELLS,
        "max_misses": MAX_MISSES,
        "note": (
            "Frame-to-frame identity assigned by nearest-neighbour matching "
            "(gated, polarity-separated, solved exactly within each locally "
            "ambiguous cluster) over services/eddies.py's own hourly "
            "detection passes. Not validated against a published eddy atlas "
            "(AVISO+ META needs a registered account) — see the module "
            "docstring. State does not survive a server restart."
        ),
        "tracks": [track.as_dict(include_path=False) for track in selected],
    }


def get_track(track_id: str) -> dict[str, Any] | None:
    """One track's full position history, or `None` if it does not exist —
    retired tracks are not distinguished from ones that never existed, since
    nothing here keeps a closed-track record to tell the two apart."""
    with _lock:
        track = _tracks.get(track_id)
        if track is None:
            return None
        return track.as_dict(include_path=True)
