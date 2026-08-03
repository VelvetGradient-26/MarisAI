"""Orchestrates a download request end-to-end: validate -> resolve variables
-> check limits -> fetch concurrently -> merge -> clean -> export.

Provider-specific knowledge lives in `catalog.py`, not here. This module only
knows that a request resolves to some set of providers, that every provider
fetches the same way, and that the results merge into one frame — so it did
not need to change when the provider count went from three to fourteen.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import xarray as xr

from services.download import catalog, limits
from services.download.catalog import ProviderSpec
from services.download.cleaning import build_dataframe
from services.download.export.csv import to_csv_bytes
from services.download.export.json import to_json_bytes
from services.download.export.pdf import to_pdf_bytes
from services.download.models import (
    BboxArea,
    DownloadRequest,
    NoDataFoundError,
    OutputFormat,
    PointArea,
    ProviderUnavailableError,
    UnsupportedVariableError,
)
from services.download.registry import VariableInfo, resolve_variables

# A point request is widened to a small bbox before fetching (same idea as
# services/bathymetry.py's point-query pattern) so both area modes share one
# fetch/clean path. The window must exceed the *coarsest* provider grid
# (0.25deg, for biogeochemistry and meteorology) or a point could fall between
# cell centres and return nothing. The exact nearest cell is picked via
# .sel(method="nearest") after fetch, and the *original* point (not this
# widened window) is what limits.py sizes its guardrail on.
_POINT_HALF_WIDTH_DEG = 0.3


@dataclass(frozen=True)
class DownloadResult:
    content: bytes
    filename: str
    media_type: str


def _area_to_bbox(area: PointArea | BboxArea) -> tuple[float, float, float, float]:
    if isinstance(area, PointArea):
        return (
            area.lon - _POINT_HALF_WIDTH_DEG,
            area.lat - _POINT_HALF_WIDTH_DEG,
            area.lon + _POINT_HALF_WIDTH_DEG,
            area.lat + _POINT_HALF_WIDTH_DEG,
        )
    return area.west, area.south, area.east, area.north


def _needed_fields(variables: dict[str, VariableInfo], provider_key: str) -> list[str]:
    fields: set[str] = set()
    for info in variables.values():
        if info.provider != provider_key:
            continue
        if info.source_field:
            fields.add(info.source_field)
        if info.derived_from:
            fields.update(info.derived_from)
    return sorted(fields)


def _check_coverage(request: DownloadRequest, specs: dict[str, ProviderSpec]) -> None:
    """Fast, friendly preflight before any network call.

    The fetch itself remains the source of truth, so a coverage window that
    drifts slightly stale only means a slower error (an empty result) rather
    than a wrong one. The forward check is different in kind: Open-Meteo
    rejects an out-of-range end date with an HTTP 400, so catching it here
    turns a provider error into a clear explanation.
    """
    today = date.today()
    for spec in specs.values():
        if spec.coverage_start is not None and request.start_date < spec.coverage_start:
            raise NoDataFoundError(
                f"Requested start date {request.start_date} is before coverage begins "
                f"({spec.coverage_start}) for {spec.source_label}."
            )
        if spec.forecast_horizon_days is not None:
            horizon = today + timedelta(days=spec.forecast_horizon_days)
            if request.end_date > horizon:
                raise NoDataFoundError(
                    f"Requested end date {request.end_date} is beyond the forecast "
                    f"horizon ({horizon}) for {spec.source_label}."
                )


def _resolved_depth(
    fetched: dict[str, tuple[ProviderSpec, xr.Dataset]],
    variables: dict[str, VariableInfo],
) -> float | None:
    """The model level a depth-resolved request actually landed on.

    Reported instead of the requested depth because the two differ: the 50
    levels are geometrically spaced, so asking for 100m gets you 92.3m.
    Returns None when nothing depth-resolved was requested — the surface-only
    providers also carry a scalar depth coord, and reporting theirs would be
    misleading.
    """
    depth_providers = {info.provider for info in variables.values() if info.depth_resolved}
    for key in depth_providers:
        entry = fetched.get(key or "")
        if entry is not None and "depth" in entry[1].coords:
            return round(float(entry[1]["depth"].values), 3)
    return None


async def run_download(request: DownloadRequest) -> DownloadResult:
    try:
        variables = resolve_variables(request.variables)
    except ValueError as exc:
        raise UnsupportedVariableError(str(exc)) from exc

    provider_keys = {info.provider for info in variables.values()}
    specs = {key: catalog.get(key) for key in provider_keys if key is not None}
    assert len(specs) == len(provider_keys), "every available variable must name a provider"

    _check_coverage(request, specs)
    for spec in specs.values():
        limits.check_limits(request.area, request.start_date, request.end_date, spec)

    west, south, east, north = _area_to_bbox(request.area)

    tasks = {
        key: spec.fetch(
            fields=_needed_fields(variables, key),
            west=west,
            south=south,
            east=east,
            north=north,
            start_date=request.start_date,
            end_date=request.end_date,
            depth_m=request.depth_m,
        )
        for key, spec in specs.items()
    }

    try:
        results = await asyncio.gather(*tasks.values())
    except Exception as exc:  # noqa: BLE001 - never leak a raw provider traceback
        raise ProviderUnavailableError(f"Data provider request failed: {exc}") from exc

    fetched: dict[str, tuple[ProviderSpec, xr.Dataset]] = {
        key: (specs[key], ds) for key, ds in zip(tasks.keys(), results, strict=True)
    }

    if isinstance(request.area, PointArea):
        fetched = {
            key: (
                spec,
                ds.sel(latitude=request.area.lat, longitude=request.area.lon, method="nearest"),
            )
            for key, (spec, ds) in fetched.items()
        }

    df = build_dataframe(
        fetched=fetched,
        variables=variables,
        resolution=request.resolution,
        start_date=request.start_date,
    )

    resolved_depth_m = _resolved_depth(fetched, variables)

    if df.empty:
        reason = (
            "it may be entirely over land or outside the dataset's coverage"
            if resolved_depth_m is None
            # The ocean model is NaN below the seafloor, so asking for 3000m
            # somewhere 1600m deep returns nothing — a far more likely mistake
            # than picking a landlocked area, and worth naming.
            else f"the requested depth ({resolved_depth_m}m) may be below the seafloor there, "
            "or the area may be over land"
        )
        raise NoDataFoundError(f"No data found for the requested area/date range — {reason}.")

    metadata = _build_metadata(request, variables, resolved_depth_m)
    filename_stem = f"marisai_ocean_data_{request.start_date}_{request.end_date}"

    if request.format == OutputFormat.csv:
        return DownloadResult(
            content=to_csv_bytes(df), filename=f"{filename_stem}.csv", media_type="text/csv"
        )
    if request.format == OutputFormat.pdf:
        return DownloadResult(
            content=await asyncio.to_thread(to_pdf_bytes, df, metadata, variables),
            filename=f"{filename_stem}.pdf",
            media_type="application/pdf",
        )
    return DownloadResult(
        content=to_json_bytes(df, metadata, variables),
        filename=f"{filename_stem}.json",
        media_type="application/json",
    )


def _build_metadata(
    request: DownloadRequest,
    variables: dict[str, VariableInfo],
    resolved_depth_m: float | None,
) -> dict[str, Any]:
    provider_keys = {info.provider for info in variables.values() if info.provider}
    metadata: dict[str, Any] = {
        "area": request.area.model_dump(),
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "resolution": request.resolution.value,
        "variables": list(variables.keys()),
        "sources": catalog.source_labels(provider_keys),
        "licences": catalog.licences(provider_keys),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "MarisAI Universal Ocean Data Downloader",
    }
    if resolved_depth_m is not None:
        metadata["requested_depth_m"] = request.depth_m
        metadata["resolved_depth_m"] = resolved_depth_m
    return metadata
