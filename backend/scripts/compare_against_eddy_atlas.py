"""Compare `services/eddies.py`'s own detections against AVISO+'s Mesoscale
Eddy Trajectory Atlas (META4.0 DT) — the validation TODO.md names and that
this platform's detector has never been checked against.

    python scripts/compare_against_eddy_atlas.py \\
        --cyclonic META4.0_DT_allsat_Cyclonic_19930101_20230908.nc \\
        --anticyclonic META4.0_DT_allsat_Anticyclonic_19930101_20230908.nc \\
        --date 2020-06-15 \\
        --bbox 0,30,90,120

**Requires two files this script cannot fetch itself.** The atlas needs a
registered AVISO+ account — checked live 2026-08-24 three ways (the product
page, its THREDDS catalog, and a direct `fileServer` request), and all three
end at the same login: the catalog listing is public, the data behind it is
not (`401 Unauthorized`, `WWW-Authenticate: Basic realm="Ldap
Authentification"`). The same shape of blocker as WDPA for
`services/geofencing.py`. Register at
https://www.aviso.altimetry.fr/en/data/data-access/registration-form.html
(select "Mesoscale Eddy Trajectory Atlas"), download the two NetCDF-4
"classic" files, and pass their paths here. **The product handbook itself
needs no account** — fetched openly from AVISO's own site
(`hdbk_eddytrajectory_META4.0_DT.pdf`) — and is where every variable name
and the polarity note below come from; nothing here is guessed.

**The atlas's own coverage (1993-01-01 to 2023-09-08, "updated every year")
is already years behind live operation**, so this can never be a same-instant
check against what `services/eddy_tracking.py` reports right now. What it
*can* check is `services/eddies.py`'s detector itself, reproducibly: this
script fetches one historical day's currents from the Copernicus reanalysis
(`services/climatology/copernicus_reanalysis.py::fetch_currents_day`, the
same product used to fit the corroboration climatology) and runs `detect()`
against it directly — `detect()` is pure, snapshot-in features-out, which is
exactly what makes this reproducible offline.

**Polarity needs no reconciliation between the two products, and that is
worth stating rather than assuming.** AVISO's algorithm labels an eddy
cyclonic/anticyclonic from the sign of the SSH extremum alone (low SSH is
cyclonic, in *both* hemispheres — see the handbook's detection section).
That is physically the same rule `services/eddies.py` uses
(`sign(vorticity) == sign(latitude)`, i.e. matching the Coriolis parameter's
own sign): geostrophic balance makes a low-pressure centre rotate the
hemisphere-correct "cyclonic" direction by construction, so both labels
already encode the same physics rather than needing a translation between
them. If the two products disagree on polarity for the same feature, that is
itself a finding worth reporting, not a bug in this comparison — matched
purely within same-polarity pairs below for exactly that reason.

**Matching is nearest-neighbour, gated, solved exactly per spatially-
independent cluster** — the same shape `services/eddy_tracking.py` uses for
frame-to-frame identity, reimplemented here rather than imported: that
module's matcher is typed around its own `Track`/`Eddy` objects mid-tracking,
and a one-shot spatial comparison between two independent detections is a
simpler, different problem (no history, no misses to tolerate) that does not
need that machinery's shape.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import eddies, vector_field  # noqa: E402
from services.climatology import copernicus_reanalysis  # noqa: E402
from services.vector_source import VectorSnapshot  # noqa: E402

logger = logging.getLogger("compare_against_eddy_atlas")

EARTH_RADIUS_KM = 6371.0088
# A comparison gate, not a detection one: the two methods resolve different
# minimum scales (Okubo-Weiss on a 0.25deg current grid vs. SSH contours from
# multi-satellite altimetry), so this is set to comfortably exceed either
# method's own position uncertainty rather than tuned to look good.
MATCH_GATE_KM = 150.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


@dataclass
class _Point:
    latitude: float
    longitude: float
    radius_km: float


# --------------------------------------------------------------------------
# Our own detector, run against a historical day
# --------------------------------------------------------------------------


async def _detect_for_day(target: date, bbox: tuple[float, float, float, float] | None) -> eddies.Detection:
    dataset = await copernicus_reanalysis.fetch_currents_day(target)
    lat = dataset["latitude"].values.astype("float64")
    lon = dataset["longitude"].values.astype("float64")
    u = dataset["uo"].isel(time=0).values.astype("float64")
    v = dataset["vo"].isel(time=0).values.astype("float64")

    if bbox is not None:
        south, west, north, east = bbox
        lat_mask = (lat >= south) & (lat <= north)
        lon_mask = (lon >= west) & (lon <= east)
        lat, u, v = lat[lat_mask], u[lat_mask][:, lon_mask], v[lat_mask][:, lon_mask]
        lon = lon[lon_mask]

    snapshot = VectorSnapshot(
        key="currents",
        lat=lat,
        lon=lon,
        u=u,
        v=v,
        u_interp=vector_field.build_interpolator(lat, lon, u),
        v_interp=vector_field.build_interpolator(lat, lon, v),
        lon_min=float(lon[0]),
        timestamp=datetime(target.year, target.month, target.day, tzinfo=UTC),
    )
    return eddies.detect(snapshot)


# --------------------------------------------------------------------------
# The atlas
# --------------------------------------------------------------------------


def _load_atlas_day(
    path: Path, target: date, bbox: tuple[float, float, float, float] | None
) -> list[_Point]:
    import xarray as xr

    with xr.open_dataset(path) as dataset:
        # `time` is CF-decoded ("days since 1950-01-01") by xarray automatically
        # when the file declares the standard `units`/`calendar` attributes the
        # handbook's own header dump shows it does — comparing as dates rather
        # than raw offsets is what makes this robust to that either way.
        times = dataset["time"].values.astype("datetime64[D]")
        mask = times == np.datetime64(target)
        idx = np.nonzero(mask)[0]
        if idx.size == 0:
            return []

        subset = dataset.isel(obs=idx)
        lat = subset["latitude"].values.astype("float64")
        lon = subset["longitude"].values.astype("float64")
        # Degrees_east per the handbook, but AVISO's own convention runs
        # 0..360 (its stated spatial coverage is "0deg to 360deg") — wrapped
        # to -180..180 to match every bbox and grid in this codebase.
        lon = ((lon + 180.0) % 360.0) - 180.0
        radius_km = subset["speed_radius"].values.astype("float64") / 1000.0

    points = [_Point(float(a), float(b), float(c)) for a, b, c in zip(lat, lon, radius_km, strict=True)]
    if bbox is not None:
        south, west, north, east = bbox
        points = [p for p in points if south <= p.latitude <= north and west <= p.longitude <= east]
    return points


# --------------------------------------------------------------------------
# Matching — nearest-neighbour, gated, exact within each spatial cluster
# --------------------------------------------------------------------------


def _candidate_pairs(a: list[_Point], b: list[_Point], gate_km: float) -> list[tuple[int, int, float]]:
    if not a or not b:
        return []
    ref_lat = radians(float(np.mean([p.latitude for p in b])))
    lon_scale = max(cos(ref_lat), 0.1)

    def project(p: _Point) -> tuple[float, float]:
        return (p.latitude * 111.32, p.longitude * 111.32 * lon_scale)

    tree = cKDTree(np.array([project(p) for p in b]))
    pairs: list[tuple[int, int, float]] = []
    for i, p in enumerate(a):
        for j in tree.query_ball_point(project(p), r=gate_km * 1.5):
            distance = _haversine_km(p.latitude, p.longitude, b[j].latitude, b[j].longitude)
            if distance <= gate_km:
                pairs.append((i, int(j), distance))
    return pairs


def _connected_components(n_a: int, n_b: int, pairs: list[tuple[int, int, float]]) -> list[tuple[list[int], list[int]]]:
    parent = list(range(n_a + n_b))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, j, _ in pairs:
        union(i, n_a + j)

    groups: dict[int, tuple[list[int], list[int]]] = {}
    for i in range(n_a):
        groups.setdefault(find(i), ([], []))[0].append(i)
    for j in range(n_b):
        groups.setdefault(find(n_a + j), ([], []))[1].append(j)
    return [g for g in groups.values() if g[0] and g[1]]


def _match(a: list[_Point], b: list[_Point], gate_km: float) -> dict[int, int]:
    pairs = _candidate_pairs(a, b, gate_km)
    matches: dict[int, int] = {}
    if not pairs:
        return matches
    lookup = {(i, j): d for i, j, d in pairs}
    for a_idx, b_idx in _connected_components(len(a), len(b), pairs):
        if len(a_idx) == 1 and len(b_idx) == 1:
            matches[a_idx[0]] = b_idx[0]
            continue
        cost = np.full((len(a_idx), len(b_idx)), gate_km * 10.0)
        for i, ai in enumerate(a_idx):
            for j, bj in enumerate(b_idx):
                d = lookup.get((ai, bj))
                if d is not None:
                    cost[i, j] = d
        row, col = linear_sum_assignment(cost)
        for i, j in zip(row, col, strict=True):
            if cost[i, j] <= gate_km:
                matches[a_idx[i]] = b_idx[j]
    return matches


def _compare_polarity(ours: list[_Point], atlas: list[_Point]) -> dict[str, Any]:
    matches = _match(ours, atlas, MATCH_GATE_KM)
    position_errors = []
    radius_ratios = []
    for our_idx, atlas_idx in matches.items():
        o, t = ours[our_idx], atlas[atlas_idx]
        position_errors.append(_haversine_km(o.latitude, o.longitude, t.latitude, t.longitude))
        if t.radius_km > 0:
            radius_ratios.append(o.radius_km / t.radius_km)

    return {
        "our_count": len(ours),
        "atlas_count": len(atlas),
        "matched": len(matches),
        # Recall against the atlas: what fraction of the atlas's eddies this
        # platform's detector also found. Not "accuracy" — the two methods
        # resolve different minimum scales, so a miss is not necessarily a
        # detector error, and this number alone should not be read as one.
        "recall_vs_atlas": round(len(matches) / len(atlas), 4) if atlas else None,
        "our_match_rate": round(len(matches) / len(ours), 4) if ours else None,
        "median_position_error_km": round(float(np.median(position_errors)), 1) if position_errors else None,
        "median_radius_ratio_ours_over_atlas": (
            round(float(np.median(radius_ratios)), 3) if radius_ratios else None
        ),
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _parse_bbox(raw: str | None) -> tuple[float, float, float, float] | None:
    if raw is None:
        return None
    south, west, north, east = (float(part) for part in raw.split(","))
    return south, west, north, east


async def run(args: argparse.Namespace) -> int:
    target = date.fromisoformat(args.date)
    if target < copernicus_reanalysis.COVERAGE_START:
        logger.error(f"{target} is before the reanalysis's coverage start ({copernicus_reanalysis.COVERAGE_START})")
        return 2

    bbox = _parse_bbox(args.bbox)

    logger.info(f"running services/eddies.py against the reanalysis currents for {target} ...")
    detection = await _detect_for_day(target, bbox)
    ours_cyclonic = [_Point(e.latitude, e.longitude, e.radius_km) for e in detection.eddies if e.polarity == "cyclonic"]
    ours_anticyclonic = [
        _Point(e.latitude, e.longitude, e.radius_km) for e in detection.eddies if e.polarity == "anticyclonic"
    ]

    logger.info(f"loading the atlas's own detections for {target} ...")
    atlas_cyclonic = _load_atlas_day(Path(args.cyclonic), target, bbox)
    atlas_anticyclonic = _load_atlas_day(Path(args.anticyclonic), target, bbox)

    if not atlas_cyclonic and not atlas_anticyclonic:
        logger.error(
            f"the atlas files have no observations on {target} — outside "
            "1993-01-01..2023-09-08, or the wrong files"
        )
        return 1

    print(f"\ndate: {target}  bbox: {bbox or 'global'}  gate: {MATCH_GATE_KM} km\n")
    print("cyclonic:")
    for key, value in _compare_polarity(ours_cyclonic, atlas_cyclonic).items():
        print(f"  {key}: {value}")
    print("anticyclonic:")
    for key, value in _compare_polarity(ours_anticyclonic, atlas_anticyclonic).items():
        print(f"  {key}: {value}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cyclonic", required=True, help="path to the atlas's *_Cyclonic_*.nc file")
    parser.add_argument("--anticyclonic", required=True, help="path to the atlas's *_Anticyclonic_*.nc file")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD, within 1993-01-01..2023-09-08")
    parser.add_argument("--bbox", default=None, help="south,west,north,east; omit for global")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "urllib3", "copernicusmarine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
