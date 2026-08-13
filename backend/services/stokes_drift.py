"""Stokes drift, as a live particle field.

The wave-induced mean transport of a water parcel — what actually carries a
floating object, as distinct from the Eulerian current the currents layer draws.
That distinction is the reason this is worth a layer of its own rather than a
second opinion about the same thing: a drifting hull, a slick or a larva moves
with the *sum*, and the two fields routinely disagree in direction. In the
Southern Ocean and the trade-wind belts Stokes drift is a large fraction of the
total, which the currents layer alone does not show at all.

It comes from `GLOBAL_ANALYSISFORECAST_WAV_001_027`, already integrated by the
downloader as `copernicus_waves`, and is served through `vector_source` like
every other live field. Three things specific to it:

* **It is a genuine vector in the product** (`VSDX`/`VSDY`, verified live
  2026-08-13), which is why it can be a particle field at all. The wave
  *direction* fields beside it (`VMDR`, `VPED`) are bearings on 0-360, and a
  field composed from a bearing flows backwards wherever it wraps through north
  — the same trap that blocks forecast wind particles. Components or nothing.
* **It is slower than the currents it accompanies**, typically 0-0.3 m/s with
  storm maxima near 1, so the legend tops out at 1 m/s rather than currents' 2.
  Sharing currents' scale would push a typical Stokes field into the bottom
  eighth of the ramp.
* **3-hourly, not hourly.** The product publishes eight steps a day, so the
  refresh cadence gains nothing from running more often than that.

Convention: **toward**, like currents and unlike wind. Stokes drift is a
transport — it is named for where the water goes.
"""

from __future__ import annotations

from typing import Any

from services.download.providers.copernicus import WAVES_DATASET_ID
from services.vector_source import VectorSource, VectorSourceError, VectorSourceSpec

SOURCE_LABEL = "Copernicus Marine Service (GLOBAL_ANALYSISFORECAST_WAV_001_027)"
U_VARIABLE = "VSDX"
V_VARIABLE = "VSDY"
UNIT = "m/s"

# Legend top. Open-ocean Stokes drift is 0.05-0.3 m/s; 1.0 leaves headroom for
# a storm sea without flattening the ordinary case against the ramp's floor.
SPEED_MAX_LEGEND = 1.0

# Same 0.083deg grid as the physics product, and the same reasoning as there:
# the shader samples with GPU bilinear filtering, so native resolution costs the
# client megabytes and buys nothing.
_DOWNSAMPLE = 3

# 3-hourly product, so four steps is half a day of walk-back — the same margin
# currents gets in hours.
_MAX_LOOKBACK_STEPS = 4

# Publication cadence, for the scheduler. Matching the product rather than
# guessing: refreshing hourly would fetch the same three-hourly field three
# times.
REFRESH_INTERVAL_HOURS = 3


class StokesDriftError(VectorSourceError):
    pass


SPEC = VectorSourceSpec(
    key="stokes_drift",
    dataset_id=WAVES_DATASET_ID,
    u_field=U_VARIABLE,
    v_field=V_VARIABLE,
    source_label=SOURCE_LABEL,
    unit=UNIT,
    speed_max_legend=SPEED_MAX_LEGEND,
    convention="toward",
    downsample=_DOWNSAMPLE,
    max_lookback_steps=_MAX_LOOKBACK_STEPS,
    error_type=StokesDriftError,
)

_source = VectorSource(SPEC)


async def refresh_cache() -> None:
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
