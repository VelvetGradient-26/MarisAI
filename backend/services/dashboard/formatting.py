"""Shared display helpers for the dashboard aggregates.

Small on purpose: `summary` and `alerts` both name locations, and two
independent formatters drifted apart immediately — one printed "-0.0, -150.0"
for a point on the equator while the other printed "0.0°S, 150.0°W".
"""

from __future__ import annotations


def describe_location(latitude: float, longitude: float, *, decimals: int = 1) -> str:
    """A coarse hemisphere-qualified label, e.g. "1.0°N, 143.0°W".

    Adding 0.0 to each rounded value normalises negative zero: a heat-stress
    region centred at -0.03°N would otherwise render as "-0.0", which reads
    like a formatting bug even though the number is right.

    No reverse-geocoding: these are produced per alert from cached grids, and
    a lookup each would put a network round trip behind a 30-second poll.
    """
    lat = round(latitude, decimals) + 0.0
    lon = round(longitude, decimals) + 0.0
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{abs(lat):.{decimals}f}°{ns}, {abs(lon):.{decimals}f}°{ew}"
