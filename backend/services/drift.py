"""The combined drift field — what actually carries a floating object.

The map already draws three fields that each move water, and until now a reader
had to sum them by eye:

    u_total = u_current + u_stokes + alpha * u_wind

**The wind term is leeway, and `alpha` belongs to the object, not to the
ocean.** It is the fraction of the wind speed that a partly-submerged object
picks up directly from air drag on whatever stands above the waterline. A
swamped hull sitting almost flush carries ~1-2% of the wind; a person in the
water is a little more; a life raft with freeboard and no drogue is several
times that. So there is no correct constant to bake in — the same water drifts
a raft and a slick along measurably different tracks, and a field that picked
one value would be quietly answering a question the user did not ask.
`LEEWAY_PRESETS` names the choice instead, and `alpha = 0` gives the pure
water-borne field (current + Stokes) for anyone who wants it.

The presets are approximate, and are presented that way. Operational leeway
models use object-specific downwind *and* crosswind coefficients fitted to
field trials, and they carry a divergence angle this does not model at all;
these are order-of-magnitude values for orientation, not a substitute for one.

**Components are summed, never bearings.** This is the same trap that blocks a
forecast wind particle layer: a direction is circular, so averaging 359 and 1
gives 180 and the field flows backwards along every wrap. Every term here is a
u/v pair, and the bearing is derived once at the end.

**Coverage is the intersection, not the union.** A cell where the currents
product has data and the wave product does not is left empty rather than being
served as "current plus zero Stokes". That is the dashboard's rule — never
substitute a number for missing data — and the substituted number here would
not even be neutral: Stokes drift is largest exactly where it would be dropped
most often, in high-sea-state water. The intersection costs a thin coastal band
where the two products' land masks disagree.

**What this is not.** It is a field, not a trajectory. Every particle drawn from
it advects against a single snapshot, so it shows where the water is going *now*
everywhere — not where one object will be in 48 hours, which needs a
time-indexed stack and an integrator, and which must be shipped with an
uncertainty envelope rather than as a single line. See TODO.md; the two are
deliberately separate features and this is the cheap half.
"""

from __future__ import annotations

import asyncio
import math
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
from loguru import logger

from services import copernicus_currents, copernicus_wind, stokes_drift, vector_field
from services.vector_source import VectorSnapshot, VectorSourceError, compass_label

SOURCE_LABEL = (
    "Copernicus Marine Service — surface currents (GLOBAL_ANALYSISFORECAST_PHY_001_024) "
    "+ Stokes drift (GLOBAL_ANALYSISFORECAST_WAV_001_027) + leeway from the L4 wind "
    "blend (WIND_GLO_PHY_L4_NRT_012_004)"
)
UNIT = "m/s"

# Legend top. Currents alone reach 2 m/s in the western boundary currents; the
# two other terms add to that rather than averaging with it, so the combined
# field needs headroom the currents layer does not. 2.5 keeps a typical
# open-ocean 0.2 m/s drift off the floor of the ramp while leaving the Gulf
# Stream on-scale.
SPEED_MAX_LEGEND = 2.5


@dataclass(frozen=True)
class LeewayPreset:
    """One drifting object's wind coefficient."""

    key: str
    label: str
    alpha: float
    note: str


# Ordered lightest-to-heaviest windage. `water_only` is first because it is the
# honest default for "what is the water doing", and because a user who has not
# told us what is drifting has not given us an alpha.
LEEWAY_PRESETS: tuple[LeewayPreset, ...] = (
    LeewayPreset(
        key="water_only",
        label="Water only (no leeway)",
        alpha=0.0,
        note="Current + Stokes drift. What the water does, with nothing standing in the wind.",
    ),
    LeewayPreset(
        key="swamped_hull",
        label="Swamped hull / submerged debris",
        alpha=0.015,
        note="Almost nothing above the waterline, so almost no direct wind drag.",
    ),
    LeewayPreset(
        key="oil_slick",
        label="Oil slick",
        alpha=0.03,
        note="The long-standing 3% rule of thumb for surface slicks.",
    ),
    LeewayPreset(
        key="person_in_water",
        label="Person in the water",
        alpha=0.035,
        note="A head and shoulders of freeboard. Sensitive to whether a PFD holds the "
        "body higher in the water.",
    ),
    LeewayPreset(
        key="life_raft",
        label="Life raft, no drogue",
        alpha=0.06,
        note="Large freeboard and a canopy. Undrogued rafts are the classic case where "
        "leeway dominates the current entirely.",
    ),
)

_PRESETS_BY_KEY = {preset.key: preset for preset in LEEWAY_PRESETS}

# Alpha is rounded to this many decimals before it becomes a cache key, so a
# slider dragged across a range does not mint a texture per pixel.
_ALPHA_DECIMALS = 3
_ALPHA_MAX = 0.15

# Composed textures held at once. Small: the presets are five, and a texture is
# ~1 MB. Evicted oldest-first.
_TEXTURE_CACHE_MAX = 8

# Downsample is 1 because the terms arrive already downsampled — currents and
# Stokes at /3 of 0.083deg, wind at /2 of 0.125deg. Downsampling again here
# would blur a field that is already at texture resolution.
_DOWNSAMPLE = 1

# Recompose cadence. Matched to the *fastest* term (hourly currents and wind)
# rather than the slowest, because this job does not fetch — it re-reads three
# caches and adds them, so running it when only one has moved still costs
# seconds and keeps the composite from lagging its own inputs.
REFRESH_INTERVAL_HOURS = 1


class DriftError(VectorSourceError):
    """The combined drift field is unavailable — usually because one of the three
    fields it sums has not warmed up yet. The message names which."""


@dataclass
class _Composed:
    """The two alpha-independent halves, on one grid.

    Split this way because alpha is a *UI parameter*: recomposing the whole sum
    for every slider position would repeat three interpolations onto a million
    cells to change one multiplier. `water` is current + Stokes; `wind` is the
    resampled wind field, waiting to be scaled.
    """

    lat: np.ndarray
    lon: np.ndarray
    water_u: np.ndarray
    water_v: np.ndarray
    wind_u: np.ndarray
    wind_v: np.ndarray
    # The three upstream timesteps, which are the cache key. They genuinely
    # differ — hourly currents, 3-hourly Stokes, and a wind blend that is often
    # hours behind — so the composite's own "timestamp" is a range, reported as
    # one rather than collapsed to a single reassuring value.
    stamps: dict[str, datetime]
    composed_at: datetime


_composed: _Composed | None = None
_textures: dict[float, vector_field.FieldTexture] = {}
_lock = threading.Lock()
_compose_lock = asyncio.Lock()


# ----------------------------------------------------------------- resampling


def _resample(snapshot: VectorSnapshot, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """One field's u/v on another field's grid.

    Necessary because the three products are not on one grid: physics and waves
    run 0.083 degrees over latitude -80 to 90, the wind blend 0.125 over the
    full globe. Sampling through the cached interpolators rather than
    re-fetching means the resample sees exactly the values the field's own
    layer draws.
    """
    lon_query = np.asarray(
        [vector_field.wrap_longitude(float(value), snapshot.lon_min) for value in lon]
    )
    mesh_lat, mesh_lon = np.meshgrid(lat, lon_query, indexing="ij")
    points = np.column_stack([mesh_lat.ravel(), mesh_lon.ravel()])
    u = snapshot.u_interp(points).reshape(mesh_lat.shape)
    v = snapshot.v_interp(points).reshape(mesh_lat.shape)
    return u, v


def _same_grid(snapshot: VectorSnapshot, lat: np.ndarray, lon: np.ndarray) -> bool:
    """Whether a field is already on the base grid, to within float noise.

    Worth checking rather than always interpolating: Stokes drift and the
    surface currents come off the same 0.083-degree Copernicus grid at the same
    downsample, so they usually match exactly, and interpolating a field onto
    its own grid is both wasted work and a coastline eroder — a bilinear read of
    a NaN-holed field is poisoned by the hole, the defect
    `services/field_sampling.py` exists to document.
    """
    return (
        snapshot.lat.shape == lat.shape
        and snapshot.lon.shape == lon.shape
        and bool(np.allclose(snapshot.lat, lat, atol=1e-6))
        and bool(np.allclose(snapshot.lon, lon, atol=1e-6))
    )


def _build_composed() -> _Composed:
    """Sum the water terms and resample wind, on the currents grid.

    The currents grid is the base for two reasons: it is the dominant term
    almost everywhere, so it is the one field that should not be resampled at
    all; and it is the finest of the three.
    """
    currents = _snapshot_or_raise(copernicus_currents, "surface currents")
    stokes = _snapshot_or_raise(stokes_drift, "Stokes drift")
    wind = _snapshot_or_raise(copernicus_wind, "wind")

    lat, lon = currents.lat, currents.lon

    if _same_grid(stokes, lat, lon):
        stokes_u, stokes_v = stokes.u, stokes.v
    else:
        stokes_u, stokes_v = _resample(stokes, lat, lon)

    wind_u, wind_v = _resample(wind, lat, lon)

    # Intersection, not union — see the module docstring. Wind is defined over
    # land too, so it is deliberately *not* part of the coverage test: a cell is
    # drawable when the two water terms are, and the leeway term only ever adds
    # to a cell that already has water in it.
    water_u = currents.u + stokes_u
    water_v = currents.v + stokes_v

    return _Composed(
        lat=lat,
        lon=lon,
        water_u=water_u,
        water_v=water_v,
        wind_u=wind_u,
        wind_v=wind_v,
        stamps={
            "currents": currents.timestamp,
            "stokes_drift": stokes.timestamp,
            "wind": wind.timestamp,
        },
        composed_at=datetime.now(UTC),
    )


def _snapshot_or_raise(module: Any, label: str) -> VectorSnapshot:
    try:
        return module.snapshot()
    except VectorSourceError as exc:
        raise DriftError(
            f"the {label} field has no data yet, so a combined drift field cannot be "
            f"computed ({exc})"
        ) from exc


# ------------------------------------------------------------------- caching


def resolve_alpha(alpha: float | None, preset: str | None) -> float:
    """The leeway coefficient a request means, from either form of the parameter.

    A named preset wins over a raw number when both arrive, because a client
    that sent a name asked for whatever this codebase currently believes that
    object's coefficient to be.
    """
    if preset is not None:
        entry = _PRESETS_BY_KEY.get(preset)
        if entry is None:
            raise DriftError(
                f"unknown leeway preset {preset!r}. Expected one of: "
                f"{', '.join(_PRESETS_BY_KEY)}"
            )
        return entry.alpha
    if alpha is None:
        return 0.0
    if not 0.0 <= alpha <= _ALPHA_MAX:
        raise DriftError(
            f"leeway coefficient must be between 0 and {_ALPHA_MAX}; got {alpha}. "
            "Values above a few per cent belong to objects with large freeboard, and "
            "beyond 15% nothing floats that way."
        )
    return round(alpha, _ALPHA_DECIMALS)


def _texture_for(alpha: float) -> vector_field.FieldTexture:
    """The encoded combined field at one alpha, composed on first request."""
    with _lock:
        composed = _composed
        hit = _textures.get(alpha)
        if hit is not None:
            return hit

    if composed is None:
        raise DriftError(
            "the combined drift field has not been composed yet — it is built from the "
            "currents, Stokes drift and wind caches, which warm in the background after "
            "a restart"
        )

    texture = vector_field.encode(
        composed.water_u + alpha * composed.wind_u,
        composed.water_v + alpha * composed.wind_v,
        composed.lat,
        composed.lon,
        downsample=_DOWNSAMPLE,
    )

    with _lock:
        _textures[alpha] = texture
        if len(_textures) > _TEXTURE_CACHE_MAX:
            _textures.pop(next(iter(_textures)), None)
    return texture


async def refresh_cache() -> None:
    """Recompose from whatever the three upstream caches now hold.

    Never raises and never clears a good composite, for the reason every cached
    service here documents: this runs as a fire-and-forget scheduler task, so an
    escaping exception is swallowed by asyncio and the field stays empty forever
    with nothing actionable logged.

    Scheduled *after* the three it reads, and cheaply tolerant of running before
    them: a cold upstream is a warning and a skipped cycle, not a failure.
    """
    global _composed
    async with _compose_lock:
        try:
            composed = await asyncio.to_thread(_build_composed)
        except DriftError as exc:
            logger.info(f"drift field not composed yet: {exc}")
            return
        except Exception:  # noqa: BLE001 - keep the previous composite
            logger.opt(exception=True).warning(
                "drift field compose failed, keeping previous composite if any"
            )
            return

        with _lock:
            _composed = composed
            # The alpha textures describe the old timestep, so they go with it.
            _textures.clear()

        stamps = ", ".join(
            f"{name} {stamp.isoformat()}" for name, stamp in sorted(composed.stamps.items())
        )
        logger.info(f"drift field composed ({stamps})")


def is_refreshing() -> bool:
    return _compose_lock.locked()


def is_available() -> bool:
    with _lock:
        return _composed is not None


# --------------------------------------------------------------------- reads


def _require() -> _Composed:
    with _lock:
        composed = _composed
    if composed is None:
        raise DriftError(
            "the combined drift field is not available yet — it is composed from the "
            "currents, Stokes drift and wind caches after all three have warmed"
        )
    return composed


def presets() -> list[dict[str, Any]]:
    """The named objects, for a UI that offers a choice rather than a number."""
    return [
        {"key": p.key, "label": p.label, "alpha": p.alpha, "note": p.note}
        for p in LEEWAY_PRESETS
    ]


def get_meta(alpha: float = 0.0) -> dict[str, Any]:
    composed = _require()
    texture = _texture_for(alpha)
    return {
        # The oldest of the three, not the newest. A composite is only as
        # current as its stalest term, and reporting the freshest would
        # overstate how recent the field is by however far the wind blend lags.
        "timestamp": min(composed.stamps.values()).isoformat(),
        "component_timestamps": {
            name: stamp.isoformat() for name, stamp in composed.stamps.items()
        },
        "fetched_at": composed.composed_at.isoformat(),
        "source": SOURCE_LABEL,
        "unit": UNIT,
        "speed_max_legend": SPEED_MAX_LEGEND,
        "direction_convention": "toward",
        "leeway_alpha": alpha,
        "u_min": texture.u_min,
        "u_max": texture.u_max,
        "v_min": texture.v_min,
        "v_max": texture.v_max,
        **texture.bounds(),
    }


def get_field_png(alpha: float = 0.0) -> bytes:
    return _texture_for(alpha).png


def get_point(latitude: float, longitude: float, alpha: float = 0.0) -> dict[str, Any]:
    """The drift at one point, with each term reported beside the total.

    Sampled from the three sources directly rather than off the composed grid.
    That is both more precise (their native interpolators, not a downsampled
    sum) and more useful: the question a drift number provokes is always "which
    of the three put it there", and a lone total cannot answer it.
    """
    terms: dict[str, dict[str, Any]] = {}
    total_u = 0.0
    total_v = 0.0
    missing: list[str] = []

    for name, module, weight in (
        ("current", copernicus_currents, 1.0),
        ("stokes_drift", stokes_drift, 1.0),
        ("wind_leeway", copernicus_wind, alpha),
    ):
        try:
            point = module.get_point(latitude, longitude)
        except VectorSourceError as exc:
            missing.append(f"{name} ({exc})")
            continue
        except Exception as exc:  # noqa: BLE001 - one cold cache, not a failed request
            missing.append(f"{name} ({exc})")
            continue

        if point.get("is_land_or_no_data"):
            missing.append(f"{name} (no data at this point)")
            continue

        # The wind service reports speed and a "from" bearing rather than
        # components, so its u/v are reconstructed here. Reconstructing from the
        # *from* convention is the one place a sign error would be invisible:
        # the field would still animate, at the right speed, in the wrong
        # direction. `direction_from_deg` is where the air comes from, so the
        # velocity points the opposite way.
        if name == "wind_leeway":
            speed = float(point["speed_ms"])
            bearing_toward = math.radians((float(point["direction_from_deg"]) + 180.0) % 360.0)
            u = speed * math.sin(bearing_toward)
            v = speed * math.cos(bearing_toward)
        else:
            u = float(point["u_ms"])
            v = float(point["v_ms"])

        total_u += weight * u
        total_v += weight * v
        terms[name] = {
            "speed_ms": round(math.hypot(u, v), 3),
            "u_ms": round(u, 3),
            "v_ms": round(v, 3),
            "weight": weight,
            "contribution_ms": round(weight * math.hypot(u, v), 3),
            "timestamp": point.get("timestamp"),
        }

    # The two water terms are required; leeway at alpha=0 contributes nothing
    # and its absence must not blank a point the water terms can answer.
    water_present = {"current", "stokes_drift"} <= terms.keys()
    if not water_present:
        return {
            "latitude": latitude,
            "longitude": longitude,
            "leeway_alpha": alpha,
            "speed_ms": None,
            "direction_toward_deg": None,
            "direction_compass": None,
            "is_land_or_no_data": True,
            "terms": terms,
            "unavailable_reason": "; ".join(missing) or "no data at this point",
            "source": SOURCE_LABEL,
        }

    direction = (90.0 - math.degrees(math.atan2(total_v, total_u))) % 360.0
    payload: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "leeway_alpha": alpha,
        "speed_ms": round(math.hypot(total_u, total_v), 3),
        "u_ms": round(total_u, 3),
        "v_ms": round(total_v, 3),
        "direction_toward_deg": round(direction, 1),
        "direction_compass": compass_label(direction),
        "is_land_or_no_data": False,
        "terms": terms,
        "source": SOURCE_LABEL,
        "note": (
            "Instantaneous drift velocity, not a trajectory. Leeway is an approximate "
            "coefficient for the chosen object and carries no divergence angle; a real "
            "search plan needs an ensemble, not one vector."
        ),
    }
    if missing:
        payload["degraded_reason"] = "; ".join(missing)
    return payload
