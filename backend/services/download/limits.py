"""Size guardrail for the download service — reject requests that would take
too long or use too much memory, before ever calling Copernicus.

Cap derived from live benchmarks taken while planning this feature: a ~5x5
degree bbox over one month of native hourly data (~2.7M cells) fetched in
~8-10s; a basin-scale bbox over a full year (~1.8B cells) took over 270s.
Starting at 3,000,000 cells per provider fetch keeps requests in roughly the
same ballpark as the fast case.
"""

from __future__ import annotations

from datetime import date

from services.download.models import AreaTooLargeError, BboxArea, PointArea

MAX_CELLS_PER_PROVIDER = 3_000_000

# Native grid spacing of each provider's dataset — used only to *estimate*
# request size for this guardrail. The actual fetch always uses the
# dataset's real native grid, this is just a fast pre-flight check.
GRID_SPACING_DEG = {
    "copernicus_physics": 0.083,
    "copernicus_wind": 0.125,
}


def estimate_cells(
    area: PointArea | BboxArea, start_date: date, end_date: date, provider: str
) -> int:
    spacing = GRID_SPACING_DEG[provider]
    if isinstance(area, PointArea):
        lat_points = lon_points = 1
    else:
        lat_points = max(1, round((area.north - area.south) / spacing))
        lon_points = max(1, round((area.east - area.west) / spacing))

    # Fetch always pulls native hourly data regardless of the requested
    # output resolution — resampling to daily/weekly/monthly happens after
    # fetch, in cleaning.py, so the guardrail must account for the fetch
    # cost, not the (potentially much smaller) requested output size.
    hours = (end_date - start_date).days * 24 + 24
    return lat_points * lon_points * hours


def check_limits(
    area: PointArea | BboxArea, start_date: date, end_date: date, provider: str
) -> None:
    cells = estimate_cells(area, start_date, end_date, provider)
    if cells > MAX_CELLS_PER_PROVIDER:
        raise AreaTooLargeError(
            f"~{cells:,} cells requested (area x days x 24h) for one of the "
            f"requested variables, limit is {MAX_CELLS_PER_PROVIDER:,} — try "
            "a smaller area or a shorter date range."
        )
