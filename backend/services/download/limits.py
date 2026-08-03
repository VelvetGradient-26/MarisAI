"""Size guardrail for the download service — reject requests that would take
too long or use too much memory, before ever calling a provider.

Cap derived from live benchmarks taken while planning this feature: a ~5x5
degree bbox over one month of native hourly data (~2.7M cells) fetched in
~8-10s; a basin-scale bbox over a full year (~1.8B cells) took over 270s.
Starting at 3,000,000 cells per provider fetch keeps requests in roughly the
same ballpark as the fast case.

Grid spacing and native cadence are *not* duplicated here — they are columns
on the provider's `catalog.ProviderSpec`, so a new provider cannot be added
with a working fetch but a silently missing guardrail entry.
"""

from __future__ import annotations

from datetime import date

from services.download.catalog import ProviderSpec
from services.download.models import AreaTooLargeError, BboxArea, PointArea

MAX_CELLS_PER_PROVIDER = 3_000_000


def grid_points(area: PointArea | BboxArea, spacing_deg: float) -> int:
    """How many grid cells of this size the area covers."""
    if isinstance(area, PointArea):
        return 1
    lat_points = max(1, round((area.north - area.south) / spacing_deg))
    lon_points = max(1, round((area.east - area.west) / spacing_deg))
    return lat_points * lon_points


def estimate_cells(
    area: PointArea | BboxArea, start_date: date, end_date: date, provider: ProviderSpec
) -> int:
    # Fetch always pulls the dataset's native cadence regardless of the
    # requested output resolution — resampling to daily/weekly/monthly
    # happens after fetch, in cleaning.py, so the guardrail must account for
    # the fetch cost, not the (potentially much smaller) requested output.
    # A time-invariant provider fetches its grid once, whatever the range.
    days = (end_date - start_date).days + 1
    steps = max(1, round(days * provider.steps_per_day)) if provider.time_varying else 1
    return grid_points(area, provider.grid_spacing_deg) * steps


def check_limits(
    area: PointArea | BboxArea, start_date: date, end_date: date, provider: ProviderSpec
) -> None:
    cells = estimate_cells(area, start_date, end_date, provider)
    if cells > MAX_CELLS_PER_PROVIDER:
        raise AreaTooLargeError(
            f"~{cells:,} cells requested (area x days x cadence) for one of the "
            f"requested variables, limit is {MAX_CELLS_PER_PROVIDER:,} — try "
            "a smaller area or a shorter date range."
        )

    # A point API charges per coordinate and needs one HTTP round trip per
    # batch of them, so a box that is cheap by cell count can still be far too
    # many requests. Checked separately rather than folded into the cell cap
    # because the two limits are about genuinely different costs.
    if provider.max_points is not None:
        points = grid_points(area, provider.grid_spacing_deg)
        if points > provider.max_points:
            raise AreaTooLargeError(
                f"~{points:,} grid points requested for one of the requested "
                f"variables, whose source is queried point-by-point and is "
                f"limited to {provider.max_points:,} — try a smaller area."
            )
