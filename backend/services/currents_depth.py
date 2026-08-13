"""Ocean currents below the surface — the same field, at a chosen depth.

A different product from the surface layer, and necessarily so: the hourly
physics dataset `copernicus_currents` reads carries **one** singleton surface
level, so there is nothing below the surface in it. The depth-resolved currents
live in `cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m` — `uo`/`vo` on 50 levels,
verified live 2026-08-13 — which is daily rather than hourly. That trade is the
whole design of this module and is stated in the meta rather than hidden: the
surface layer answers "what is the water doing right now", this one answers
"what is the water doing at 200 m today".

**One cache per depth, and the ladder is short on purpose.** Each depth is an
independent whole-globe fetch of ~70 MB per timestep; caching all 50 levels is
not a slow version of this feature, it is a different one that does not fit in
memory. `DEPTH_LADDER` is six levels chosen for what they show rather than for
even spacing:

    0 m     the surface, so the layer can be compared against the live one
    50 m    typically within the mixed layer
    100 m   around the thermocline in the tropics
    200 m   below it — where the flow often reverses relative to the surface
    500 m   intermediate water
    1000 m  the Argo park depth, and where the deep western boundary currents
            are the interesting signal

**Warming is lazy and honest.** Only the surface and 200 m are refreshed on the
schedule; the rest are fetched on first request and then kept warm. A depth that
has never been asked for reports itself as unavailable *with a reason* rather
than blocking a tile request behind a multi-minute global fetch — the rule the
dashboard already holds everywhere, that a missing reading is never replaced by
a number, and that "still warming" and "failed" must not look alike.
"""

from __future__ import annotations

import asyncio
from typing import Any

from services.vector_source import VectorSource, VectorSourceError, VectorSourceSpec

DATASET_ID = "cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m"
SOURCE_LABEL = "Copernicus Marine Service (GLOBAL_ANALYSISFORECAST_PHY_001_024, daily)"
U_VARIABLE = "uo"
V_VARIABLE = "vo"
UNIT = "m/s"

# The offered levels. See the module docstring for why these six.
DEPTH_LADDER: tuple[float, ...] = (0.0, 50.0, 100.0, 200.0, 500.0, 1000.0)

# Refreshed on the schedule. The rest warm on demand: six global fetches every
# cycle to serve levels nobody has opened is most of the cost of the feature for
# none of its value.
_SCHEDULED_DEPTHS: tuple[float, ...] = (0.0, 200.0)

# Legend top. Subsurface flow is weaker than the surface almost everywhere, but
# the scale is deliberately shared with the surface currents layer: the entire
# point of a depth selector is comparing one level against another, and a legend
# that rescaled per level would make the comparison meaningless.
SPEED_MAX_LEGEND = 2.0

_DOWNSAMPLE = 3

# Daily product, so this is a fortnight of walk-back. Generous because a daily
# analysis publishes later in the day than an hourly one and a missed step costs
# a whole day rather than an hour.
_MAX_LOOKBACK_STEPS = 3

REFRESH_INTERVAL_HOURS = 6


class CurrentsDepthError(VectorSourceError):
    pass


def _spec(depth_m: float) -> VectorSourceSpec:
    return VectorSourceSpec(
        key=f"currents_{depth_m:g}m",
        dataset_id=DATASET_ID,
        u_field=U_VARIABLE,
        v_field=V_VARIABLE,
        source_label=SOURCE_LABEL,
        unit=UNIT,
        speed_max_legend=SPEED_MAX_LEGEND,
        convention="toward",
        downsample=_DOWNSAMPLE,
        depth_m=depth_m,
        max_lookback_steps=_MAX_LOOKBACK_STEPS,
        error_type=CurrentsDepthError,
    )


_sources: dict[float, VectorSource] = {depth: VectorSource(_spec(depth)) for depth in DEPTH_LADDER}
# Depths a request has already triggered a fetch for. Distinct from "has data":
# a fetch in flight is neither available nor absent, and conflating the two is
# how a warming layer gets reported as broken.
_requested: set[float] = set(_SCHEDULED_DEPTHS)


def resolve_depth(depth_m: float) -> float:
    """The offered level nearest `depth_m`.

    Snapped rather than rejected, so a caller can pass a real depth and be told
    which level answered — the same contract the downloader's depth-resolved
    variables have. `meta()` reports both the requested and the model level.
    """
    return min(DEPTH_LADDER, key=lambda level: abs(level - depth_m))


def _source(depth_m: float) -> VectorSource:
    return _sources[resolve_depth(depth_m)]


async def refresh_cache() -> None:
    """Refresh every depth that has been asked for at least once.

    Sequential, not gathered: these are whole-globe reads of the same product,
    and issuing six at once is how a scheduled refresh turns into a rate limit.
    """
    for depth in sorted(_requested):
        await _sources[depth].refresh()


def _ensure_warming(depth: float) -> None:
    """Start a fetch for a depth nobody has opened yet, and return immediately.

    Fire-and-forget on purpose: awaiting it would hold a tile request open for
    the length of a global fetch, which is exactly what this codebase's
    "cached, scheduled, never fetched per request" rule exists to prevent. The
    caller still gets an unavailable-with-reason answer for this request.
    """
    if depth in _requested:
        return
    _requested.add(depth)
    try:
        asyncio.get_running_loop().create_task(_sources[depth].refresh())
    except RuntimeError:
        # No running loop (a synchronous caller, e.g. a test). The depth stays
        # marked as requested so the next scheduled refresh picks it up.
        pass


def catalog() -> list[dict[str, Any]]:
    """Every offered depth and whether it can be drawn right now.

    `available` plus a reason, never a silent omission: a level that is warming
    and a level that failed are different answers, and both differ from "this
    level does not exist".
    """
    entries: list[dict[str, Any]] = []
    for depth in DEPTH_LADDER:
        source = _sources[depth]
        entry: dict[str, Any] = {
            "depth_m": depth,
            "label": "Surface" if depth == 0 else f"{depth:g} m",
            "available": source.is_available(),
            "unit": UNIT,
            "speed_max_legend": SPEED_MAX_LEGEND,
        }
        if not source.is_available():
            entry["unavailable_reason"] = (
                "fetching now — a whole-globe read takes a few minutes"
                if source.is_refreshing()
                else (
                    "not fetched yet; open this level once to start it"
                    if depth not in _requested
                    else "the last fetch for this level failed"
                )
            )
        entries.append(entry)
    return entries


def is_refreshing(depth_m: float) -> bool:
    return _source(depth_m).is_refreshing()


def is_available(depth_m: float) -> bool:
    return _source(depth_m).is_available()


def get_meta(depth_m: float) -> dict[str, Any]:
    depth = resolve_depth(depth_m)
    _ensure_warming(depth)
    return {**_sources[depth].meta(), "depth_ladder": list(DEPTH_LADDER)}


def get_point(latitude: float, longitude: float, depth_m: float) -> dict[str, Any]:
    depth = resolve_depth(depth_m)
    _ensure_warming(depth)
    return _sources[depth].point(latitude, longitude)


def get_field_png(depth_m: float) -> bytes:
    depth = resolve_depth(depth_m)
    _ensure_warming(depth)
    return _sources[depth].field_png()
