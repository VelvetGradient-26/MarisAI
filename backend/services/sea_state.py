"""One definition of "rough water", shared by the risk verdict and the router.

`services/marine_risk.py` and `services/routing.py` used to carry their own
copies of the wave thresholds, and only the risk verdict knew about wind, so
a gale with small waves could be "high" risk at a point and "calm" along a
route through it. Both now read these.

Wave thresholds: 1.5 m is where small-craft caution is usually advised and
2.5 m is rough sea for a small fishing boat. Wind: Beaufort 6 ("strong
breeze", where small-craft warnings routinely start) and Beaufort 8 ("gale"),
in km/h, rounded.
"""

from __future__ import annotations

from typing import Literal

WAVE_CAUTION_M = 1.5
WAVE_HAZARD_M = 2.5
WIND_CAUTION_KMH = 40.0
WIND_HAZARD_KMH = 62.0

HazardLevel = Literal["calm", "caution", "hazardous", "unknown"]

_RANK: dict[str, int] = {"calm": 0, "caution": 1, "hazardous": 2}


def _level(value: float, caution: float, hazard: float) -> HazardLevel:
    if value >= hazard:
        return "hazardous"
    if value >= caution:
        return "caution"
    return "calm"


def hazard_level(wave_m: float | None, wind_kmh: float | None) -> HazardLevel:
    """The worst of the known inputs; "unknown" only when neither is known."""
    levels = []
    if wave_m is not None:
        levels.append(_level(wave_m, WAVE_CAUTION_M, WAVE_HAZARD_M))
    if wind_kmh is not None:
        levels.append(_level(wind_kmh, WIND_CAUTION_KMH, WIND_HAZARD_KMH))
    if not levels:
        return "unknown"
    return max(levels, key=_RANK.__getitem__)
