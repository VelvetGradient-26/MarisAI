"""Compare `services/drift_trajectory.py`'s ensemble forecast against real
ocean drifter buoy tracks from NOAA's Global Drifter Program (GDP) — the
validation TODO.md names and that this platform's trajectory integrator has
never been checked against.

    python scripts/compare_against_drifter_tracks.py \\
        --bbox -10,30,30,100 --start-date 2020-06-01 --end-date 2020-06-30 \\
        --segment-hours 48 --n-segments 20 --seed 0

**Needs no account, unlike the eddy atlas / WDPA validations.** GDP is fully
public: `https://erddap.aoml.noaa.gov/gdp/erddap/`, dataset
`drifter_6hour_qc`, confirmed live to answer with real 6-hourly buoy fixes
with no login of any kind. Historical current and Stokes-drift fields come
from Copernicus's own multi-year reanalyses
(`cmems_mod_glo_phy_my_0.083deg_P1D-m`, `cmems_mod_glo_wav_my_0.2deg_PT3H-i`)
via the same account this backend already holds for its live products.

**Scope: current + Stokes drift only (`alpha=0.0`), against drogued
segments.** GDP's standard drogued-buoy design specifically minimizes wind
slip to track near-surface currents — a drifter with `drogue_lost_date`
still in the future (or never set) is a defensible proxy for exactly the
physics this comparison can test. Wind/leeway is not validated here: its
only source anywhere in `drift_trajectory.py` is today's operational ML
forecast grid, with no historical counterpart at all, so even a future
attempt needs new plumbing, not a flag on this script.

**Two real, stated resolution mismatches between what is validated here and
what the live tool actually serves**, not swept under the rug:
* Current: the reanalysis is a *daily mean*; the live product is far
  finer-grained. A good result here is evidence the physics/integrator are
  sound, not proof the live product's finer cadence performs identically.
* Stokes: matched cadence (3-hourly, both here and live) but coarser space
  (0.2deg reanalysis vs. 0.083deg live).

**The RK4/ensemble core is reused unmodified.**
`drift_trajectory._run_ensemble` takes already-built `_LiveField` interpolators
rather than fetching them itself, so this script builds its own from a
historical reanalysis fetch (via `_build_live_field`, extracted from
`_fetch_live_field` for exactly this reuse) and calls the same integrator
`plan_trajectory` calls in production — the same "pure, snapshot-in
features-out" reuse `compare_against_eddy_atlas.py` makes of `eddies.detect()`.

**`allow_present_day_fallback=False` is passed on every call.** Without it, a
historical field with any gap (a member drifting outside the fetched
bbox/window) would silently fall back to *today's* real operational ML grid
or wave nowcast — wrong for a run set in the past. With it, a gap is reported
in `degraded_terms` instead, and this script excludes any segment where that
happened from the headline numbers rather than trusting a result that quietly
mixed in the wrong decade.

**A drogued buoy is a proxy for the current+Stokes engine, not a stand-in for
every object the live tool serves.** Life rafts, vessels and other
`alpha != 0` presets are materially more wind-driven; this comparison says
nothing about them. GDP's regional/seasonal coverage is also uneven — the
printed roster states exactly which drifters/dates were actually sampled,
rather than implying uniform coverage. With `--n-segments 20` at 48h this is
a first real measurement (on the order of 100-150 scored points), not a
statistically powered one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import drift_trajectory  # noqa: E402
from services.climatology import copernicus_reanalysis  # noqa: E402
from services.download.providers import copernicus as copernicus_provider  # noqa: E402

logger = logging.getLogger("compare_against_drifter_tracks")

EARTH_RADIUS_KM = 6371.0088

GDP_BASE_URL = "https://erddap.aoml.noaa.gov/gdp/erddap/tabledap/drifter_6hour_qc.json"
GDP_COLUMNS = ("ID", "latitude", "longitude", "time", "drogue_lost_date")
GDP_FIX_CADENCE_HOURS = 6.0
_MAX_FIX_GAP_HOURS = GDP_FIX_CADENCE_HOURS + 1.0  # one step + slack, not a data hole

# The multi-year wave reanalysis carrying VSDX/VSDY — confirmed live this
# session (1980-01-01..2026-05-31, global). No `fetch_*` wrapper needed in
# copernicus_reanalysis.py: `copernicus_provider.fetch()` is already
# dataset-ID-agnostic and this is a small bounded-bbox fetch per segment, the
# same access pattern the live trajectory tool already uses for its own
# (non-historical) sources.
WAVES_REANALYSIS_DATASET_ID = "cmems_mod_glo_wav_my_0.2deg_PT3H-i"

# The bulk of the ensemble (P90), not the outlier fringe (P100, which a
# 100-member continuous draw would satisfy almost trivially). P50 is a
# stricter secondary check.
CONTAINMENT_PERCENTILES = (50.0, 90.0)

DEFAULT_BBOX = (-10.0, 30.0, 30.0, 100.0)  # south, west, north, east: broad Indian Ocean


class DrifterTrackError(RuntimeError):
    """The GDP feed could not be reached or answered with something unusable."""


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


# --------------------------------------------------------------------------
# GDP fetch
# --------------------------------------------------------------------------


def _build_gdp_url(bbox: tuple[float, float, float, float], start: datetime, end: datetime) -> str:
    """ERDDAP's own query grammar: `>`/`<` percent-encoded, everything else
    literal. Built by hand rather than via `httpx`'s `params=`, which would
    double-encode the already-encoded operators into something ERDDAP
    rejects — verified against the real server with exactly this shape."""
    south, west, north, east = bbox
    columns = ",".join(GDP_COLUMNS)
    constraints = "&".join(
        [
            f"time%3E={start.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            f"time%3C={end.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            f"latitude%3E={south}",
            f"latitude%3C={north}",
            f"longitude%3E={west}",
            f"longitude%3C={east}",
        ]
    )
    return f"{GDP_BASE_URL}?{columns}&{constraints}"


async def _get_json(client: httpx.AsyncClient, url: str) -> dict[str, Any] | None:
    """`None` for ERDDAP's convention of answering a zero-row query with a
    404 ("Your query produced no matching results") — standard ERDDAP
    behaviour, not itself part of the query shape confirmed live this
    session, so treated defensively rather than assumed load-bearing."""
    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise DrifterTrackError(f"GDP ERDDAP returned {exc.response.status_code} for {url}") from exc
    except httpx.HTTPError as exc:
        raise DrifterTrackError(f"GDP ERDDAP could not be reached: {exc}") from exc
    return response.json()


async def _fetch_gdp_rows(
    client: httpx.AsyncClient, bbox: tuple[float, float, float, float], start: datetime, end: datetime
) -> list[dict[str, Any]]:
    payload = await _get_json(client, _build_gdp_url(bbox, start, end))
    if payload is None:
        return []
    table = payload["table"]
    return [dict(zip(table["columnNames"], row, strict=True)) for row in table["rows"]]


# --------------------------------------------------------------------------
# Fixes and segments
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _DrifterFix:
    drifter_id: str
    time: datetime
    latitude: float
    longitude: float
    drogue_lost_date: datetime | None


def _as_time(raw: Any) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


def _as_id(value: Any) -> str:
    return str(int(value)) if isinstance(value, float) else str(value)


def _parse_fixes(rows: list[dict[str, Any]]) -> list[_DrifterFix]:
    return [
        _DrifterFix(
            drifter_id=_as_id(row["ID"]),
            time=_as_time(row["time"]),
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            drogue_lost_date=_as_time(row.get("drogue_lost_date")),
        )
        for row in rows
    ]


@dataclass(frozen=True)
class _DrifterSegment:
    drifter_id: str
    fixes: list[_DrifterFix]  # sorted by time, contiguous real 6-hourly cadence, entirely drogued

    @property
    def start(self) -> _DrifterFix:
        return self.fixes[0]

    @property
    def duration_hours(self) -> float:
        return (self.fixes[-1].time - self.fixes[0].time).total_seconds() / 3600.0


def _still_drogued(fix: _DrifterFix) -> bool:
    return fix.drogue_lost_date is None or fix.time < fix.drogue_lost_date


def _extract_segments(fixes: list[_DrifterFix], min_hours: float) -> list[_DrifterSegment]:
    """Contiguous, real 6-hourly runs at least `min_hours` long, entirely
    before the drifter's own `drogue_lost_date` (or from a drifter that never
    lost it) — see the module docstring for why that population is the right
    one for a current+Stokes-only comparison."""
    by_drifter: dict[str, list[_DrifterFix]] = {}
    for fix in fixes:
        by_drifter.setdefault(fix.drifter_id, []).append(fix)

    def _flush(run: list[_DrifterFix], drifter_id: str, out: list[_DrifterSegment]) -> None:
        if run and (run[-1].time - run[0].time).total_seconds() / 3600.0 >= min_hours:
            out.append(_DrifterSegment(drifter_id, list(run)))

    segments: list[_DrifterSegment] = []
    for drifter_id, drifter_fixes in by_drifter.items():
        drifter_fixes.sort(key=lambda f: f.time)
        run: list[_DrifterFix] = []
        for fix in drifter_fixes:
            gap_ok = not run or (fix.time - run[-1].time) <= timedelta(hours=_MAX_FIX_GAP_HOURS)
            if _still_drogued(fix) and gap_ok:
                run.append(fix)
            else:
                _flush(run, drifter_id, segments)
                run = [fix] if _still_drogued(fix) else []
        _flush(run, drifter_id, segments)
    return segments


def _trim_to_segment_hours(segment: _DrifterSegment, segment_hours: float) -> _DrifterSegment:
    start_time = segment.start.time
    trimmed = [
        fix for fix in segment.fixes
        if (fix.time - start_time).total_seconds() / 3600.0 <= segment_hours + 1e-6
    ]
    return _DrifterSegment(segment.drifter_id, trimmed)


def _sample_segments(
    segments: list[_DrifterSegment], n: int, rng: np.random.Generator
) -> list[_DrifterSegment]:
    if len(segments) <= n:
        return segments
    indices = sorted(rng.choice(len(segments), size=n, replace=False))
    return [segments[i] for i in indices]


# --------------------------------------------------------------------------
# Historical fields
# --------------------------------------------------------------------------


async def _fetch_historical_field(
    label: str,
    dataset_id: str,
    u_field: str,
    v_field: str,
    depth_mode: str,
    center_lat: float,
    center_lon: float,
    half_width_deg: float,
    start_time: datetime,
    horizon_hours: float,
) -> drift_trajectory._LiveField | None:
    """Mirrors `drift_trajectory._fetch_live_field`'s shape exactly, against
    a historical reanalysis dataset ID instead of a live one. `None` means
    "exclude this segment" to the caller — never "fall back", since there is
    no historical fallback path to fall back to."""
    try:
        dataset = await copernicus_provider.fetch(
            dataset_id=dataset_id,
            fields=[u_field, v_field],
            west=center_lon - half_width_deg,
            east=center_lon + half_width_deg,
            south=center_lat - half_width_deg,
            north=center_lat + half_width_deg,
            start_date=(start_time - timedelta(hours=6)).date(),
            end_date=(start_time + timedelta(hours=horizon_hours + 6)).date(),
            depth_mode=depth_mode,
        )
    except Exception:  # noqa: BLE001 - any upstream failure excludes the segment, never degrades it
        logger.warning(f"{label} historical fetch failed for the segment starting {start_time}", exc_info=True)
        return None

    field = drift_trajectory._build_live_field(dataset, u_field, v_field)
    if field is None:
        logger.warning(f"{label} historical fetch returned no timesteps for the segment starting {start_time}")
    return field


# --------------------------------------------------------------------------
# Per-segment validation
# --------------------------------------------------------------------------


async def _validate_segment(
    segment: _DrifterSegment, *, n_members: int, start_uncertainty_km: float, rng: np.random.Generator
) -> dict[str, Any] | None:
    start_fix = segment.start
    horizon_hours = segment.duration_hours
    half_width = drift_trajectory._half_width_deg(horizon_hours)

    current_field, stokes_field = await asyncio.gather(
        _fetch_historical_field(
            "current", copernicus_reanalysis.DATASET_ID, "uo", "vo", copernicus_provider.DEPTH_SURFACE,
            start_fix.latitude, start_fix.longitude, half_width, start_fix.time, horizon_hours,
        ),
        _fetch_historical_field(
            "stokes", WAVES_REANALYSIS_DATASET_ID, "VSDX", "VSDY", copernicus_provider.DEPTH_NONE,
            start_fix.latitude, start_fix.longitude, half_width, start_fix.time, horizon_hours,
        ),
    )
    if current_field is None or stokes_field is None:
        return None

    result = await asyncio.to_thread(
        drift_trajectory._run_ensemble,
        start_fix.latitude, start_fix.longitude, 0.0, False,  # alpha=0.0, preset_used=False: water-only scope
        start_fix.time, horizon_hours, n_members, start_uncertainty_km,
        current_field, stokes_field, rng,
        allow_present_day_fallback=False,
    )
    excluded = bool(result["degraded_terms"])
    return {
        "segment": segment,
        "result": result,
        "excluded": excluded,
        "exclusion_reason": "; ".join(result["degraded_terms"]) if excluded else None,
    }


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def _score_segment(segment: _DrifterSegment, result: dict[str, Any]) -> list[dict[str, Any]]:
    """Scores each real subsequent fix against the model's output at the same
    elapsed hour, looked up by hour value on both the median track and every
    member's own track — not by list position. In real `_run_ensemble`
    output the two happen to coincide (reports are exactly hourly, from 0),
    but scoring by an hour-keyed lookup rather than assuming that shape keeps
    this correct even if the reporting cadence ever changes."""
    start_time = segment.start.time
    median_by_hour = {round(pt["hour"]): (pt["lat"], pt["lon"]) for pt in result["median_track"]}
    member_by_hour = [
        {round(pt["hour"]): (pt["lat"], pt["lon"]) for pt in member["track"]}
        for member in result["members"]
    ]

    rows = []
    for fix in segment.fixes[1:]:  # skip index 0: the seed, not a prediction
        lead_hours = (fix.time - start_time).total_seconds() / 3600.0
        idx = round(lead_hours)
        if abs(idx - lead_hours) > 1e-3 or idx not in median_by_hour:
            continue
        median_lat, median_lon = median_by_hour[idx]
        position_error_km = _haversine_km(fix.latitude, fix.longitude, median_lat, median_lon)
        spread_km = sorted(
            _haversine_km(median_lat, median_lon, *member_hours[idx])
            for member_hours in member_by_hour
            if idx in member_hours
        )
        if not spread_km:
            continue
        envelope = {p: float(np.percentile(spread_km, p)) for p in CONTAINMENT_PERCENTILES}
        rows.append(
            {
                "drifter_id": segment.drifter_id,
                "lead_hours": idx,
                "position_error_km": round(position_error_km, 2),
                "envelope_radius_km": {p: round(r, 2) for p, r in envelope.items()},
                "contained": {p: position_error_km <= r for p, r in envelope.items()},
            }
        )
    return rows


def _aggregate(all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not all_rows:
        return {"n_scored_points": 0, "overall_median_position_error_km": None,
                "overall_containment_rate": {}, "by_lead_hours": {}}

    by_lead: dict[int, list[dict[str, Any]]] = {}
    for row in all_rows:
        by_lead.setdefault(row["lead_hours"], []).append(row)

    def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        summary = {
            "n": len(rows),
            "median_position_error_km": round(float(np.median([r["position_error_km"] for r in rows])), 1),
        }
        for p in CONTAINMENT_PERCENTILES:
            summary[f"containment_rate_p{int(p)}"] = round(
                sum(r["contained"][p] for r in rows) / len(rows), 3
            )
        return summary

    return {
        "n_scored_points": len(all_rows),
        "overall_median_position_error_km": round(
            float(np.median([r["position_error_km"] for r in all_rows])), 1
        ),
        "overall_containment_rate": {
            f"p{int(p)}": round(sum(r["contained"][p] for r in all_rows) / len(all_rows), 3)
            for p in CONTAINMENT_PERCENTILES
        },
        "by_lead_hours": {lead: _summary(rows) for lead, rows in sorted(by_lead.items())},
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _parse_bbox(raw: str) -> tuple[float, float, float, float]:
    south, west, north, east = (float(part) for part in raw.split(","))
    return south, west, north, east


async def run(args: argparse.Namespace) -> int:
    from datetime import date as date_cls

    start_date = date_cls.fromisoformat(args.start_date)
    end_date = date_cls.fromisoformat(args.end_date)
    if start_date < copernicus_reanalysis.COVERAGE_START:
        logger.error(f"{start_date} is before the currents reanalysis's coverage start "
                     f"({copernicus_reanalysis.COVERAGE_START})")
        return 2

    segment_hours = min(drift_trajectory.MAX_HORIZON_HOURS, max(drift_trajectory.MIN_HORIZON_HOURS, args.segment_hours))
    bbox = _parse_bbox(args.bbox)
    start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=UTC)
    end_dt = datetime(end_date.year, end_date.month, end_date.day, tzinfo=UTC) + timedelta(days=1)

    logger.info(f"fetching GDP fixes for bbox={bbox} {start_date}..{end_date} ...")
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        rows = await _fetch_gdp_rows(client, bbox, start_dt, end_dt)
    if not rows:
        logger.error("GDP returned no fixes for this bbox/date range")
        return 1
    fixes = _parse_fixes(rows)

    all_segments = _extract_segments(fixes, segment_hours)
    all_segments = [_trim_to_segment_hours(s, segment_hours) for s in all_segments]
    if not all_segments:
        logger.error(f"no drogued segment at least {segment_hours}h long found in this bbox/date range")
        return 1

    rng = np.random.default_rng(args.seed)
    sampled = _sample_segments(all_segments, args.n_segments, rng)
    logger.info(f"{len(all_segments)} candidate segments found; validating {len(sampled)}")

    all_rows: list[dict[str, Any]] = []
    roster: list[dict[str, Any]] = []
    for segment in sampled:
        outcome = await _validate_segment(
            segment, n_members=args.n_members, start_uncertainty_km=args.start_uncertainty_km, rng=rng
        )
        if outcome is None:
            roster.append({
                "drifter_id": segment.drifter_id, "start": segment.start.time.isoformat(),
                "status": "excluded", "reason": "historical field fetch failed or had no timesteps",
            })
            continue
        if outcome["excluded"]:
            roster.append({
                "drifter_id": segment.drifter_id, "start": segment.start.time.isoformat(),
                "status": "excluded", "reason": outcome["exclusion_reason"],
            })
            continue
        rows = _score_segment(segment, outcome["result"])
        all_rows.extend(rows)
        roster.append({
            "drifter_id": segment.drifter_id, "start": segment.start.time.isoformat(),
            "status": "scored", "n_points": len(rows),
        })

    print(f"\nbbox: {bbox}  window: {start_date}..{end_date}  segment_hours: {segment_hours}\n")
    print("segments:")
    for entry in roster:
        print(f"  {entry}")

    summary = _aggregate(all_rows)
    print("\nsummary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({"roster": roster, "summary": summary}, indent=2))
        print(f"\nwrote {args.json_out}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bbox", default=",".join(str(v) for v in DEFAULT_BBOX),
                         help="south,west,north,east; defaults to a broad Indian Ocean box")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--segment-hours", type=float, default=48.0)
    parser.add_argument("--n-segments", type=int, default=20)
    parser.add_argument("--n-members", type=int, default=drift_trajectory.DEFAULT_N_MEMBERS)
    parser.add_argument("--start-uncertainty-km", type=float,
                         default=drift_trajectory.DEFAULT_START_POSITION_UNCERTAINTY_KM)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--json-out", default=None)
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
