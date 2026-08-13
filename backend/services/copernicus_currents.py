"""Copernicus Marine surface currents, as a live particle field.

Now a *binding* rather than an implementation: everything about fetching,
caching, encoding and point lookup lives in `services/vector_source.py`, which
exists because this file and `copernicus_wind` were two copies of the same 250
lines and Stokes drift and currents-at-depth would have made four. The module
keeps its own name, error type and function names because routers and
`main.py`'s scheduler import them, and because a per-field error type is what
lets a thin router map one service's failure to one status code.

What is specific to this field, and why:

* **The dataset is the one `copernicus_sst` already uses.**
  `cmems_mod_glo_phy_anfc_0.083deg_PT1H-m` carries `thetao`, `so`, `uo`, `vo`
  and `zos` on one singleton surface level, so the currents field costs a second
  fetch of a product this codebase already knows how to open quickly rather than
  a new integration with its own failure modes.
* **The grid is not the global frame.** This product runs latitude **-80 to 90**.
  The wind product covers the full -90 to 90, and the particle shader used to
  assume that of every field. Bounds travel in the meta and the shader treats a
  particle below 80degS as off-field, rather than sampling the -80 row and
  advecting the Southern Ocean with Antarctic coastal water.
* **Currents are an order of magnitude slower than wind** — a typical open-ocean
  0.1-0.4 m/s against wind's 5-10 — so the legend tops out at 2 m/s and the layer
  asks the particle engine for its own visual speed scale.
* **Named for where the water goes**, not where it comes from: the field is
  `direction_toward_deg`. Wind's convention is the opposite one.

See `services/currents_depth.py` for the same field below the surface, which is
a different product because this one carries only the surface level.
"""

from __future__ import annotations

from typing import Any

from services.copernicus_sst import DATASET_ID
from services.vector_source import (
    VectorSource,
    VectorSourceError,
    VectorSourceSpec,
    compass_label as _compass_label,  # re-exported: tests and siblings use it
)

SOURCE_LABEL = "Copernicus Marine Service (GLOBAL_ANALYSISFORECAST_PHY_001_024)"
U_VARIABLE = "uo"
V_VARIABLE = "vo"
UNIT = "m/s"

# Legend top. Open ocean sits at 0.1-0.4 m/s; the western boundary currents —
# Gulf Stream, Kuroshio, Agulhas — are the reason the scale has to reach 2.
SPEED_MAX_LEGEND = 2.0

# 0.083deg native is 2041x4320. /3 -> 680x1440, matching the wind texture's
# 720x1440 on the wire for the same reason: the particle system samples with GPU
# bilinear filtering, so native resolution buys nothing visually and costs the
# client megabytes on every layer activation. 2041 does not divide by 3 —
# `vector_field.block_mean` crops the odd row and reports the axis that
# survives, so the declared bounds stay exact.
_DOWNSAMPLE = 3

# Short, unlike wind's 30: this is an analysis product rather than a gap-filled
# L4 blend, so the first step is expected to work and each step costs a global
# load. Not zero, because "the latest timestep exists" and "the latest timestep
# has data" are different claims and this codebase has been caught by that.
_MAX_LOOKBACK_STEPS = 4

_COMPASS_LABELS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


class CopernicusCurrentsError(VectorSourceError):
    pass


SPEC = VectorSourceSpec(
    key="currents",
    dataset_id=DATASET_ID,
    u_field=U_VARIABLE,
    v_field=V_VARIABLE,
    source_label=SOURCE_LABEL,
    unit=UNIT,
    speed_max_legend=SPEED_MAX_LEGEND,
    convention="toward",
    downsample=_DOWNSAMPLE,
    max_lookback_steps=_MAX_LOOKBACK_STEPS,
    error_type=CopernicusCurrentsError,
)

_source = VectorSource(SPEC)


async def refresh_currents_cache() -> None:
    await _source.refresh()


def is_refreshing() -> bool:
    return _source.is_refreshing()


def is_available() -> bool:
    return _source.is_available()


def get_meta() -> dict[str, Any]:
    return _source.meta()


def get_point(latitude: float, longitude: float) -> dict[str, Any]:
    return _source.point(latitude, longitude)


def get_field_png() -> bytes:
    return _source.field_png()
