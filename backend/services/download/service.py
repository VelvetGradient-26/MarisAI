"""Orchestrates a download request end-to-end: validate -> resolve variables
-> check limits -> fetch concurrently -> merge -> clean -> export.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from services.download import limits
from services.download.cleaning import build_dataframe
from services.download.export.csv import to_csv_bytes
from services.download.export.json import to_json_bytes
from services.download.export.pdf import to_pdf_bytes
from services.download.models import (
    AreaTooLargeError,
    BboxArea,
    DownloadRequest,
    NoDataFoundError,
    OutputFormat,
    PointArea,
    ProviderUnavailableError,
    UnsupportedVariableError,
)
from services.download.providers import copernicus
from services.download.registry import (
    PROVIDER_COPERNICUS_PHYSICS,
    PROVIDER_COPERNICUS_WIND,
    VariableInfo,
    resolve_variables,
)

# A point request is widened to a small bbox before fetching (same idea as
# services/bathymetry.py's point-query pattern) so both area modes share one
# fetch/clean path; wide enough to reliably contain at least one native grid
# cell at both providers' resolutions (0.083deg / 0.125deg). The exact nearest
# cell is picked via .sel(method="nearest") after fetch, and the *original*
# point (not this widened window) is what limits.py sizes its guardrail on.
_POINT_HALF_WIDTH_DEG = 0.15


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


def _needed_physics_fields(variables: dict[str, VariableInfo]) -> list[str]:
    fields: set[str] = set()
    for info in variables.values():
        if info.provider != PROVIDER_COPERNICUS_PHYSICS:
            continue
        if info.source_field:
            fields.add(info.source_field)
        if info.derived_from:
            fields.update(info.derived_from)
    return sorted(fields)


def _check_coverage(request: DownloadRequest, providers_needed: set[str | None]) -> None:
    if (
        PROVIDER_COPERNICUS_PHYSICS in providers_needed
        and request.start_date < copernicus.PHYSICS_COVERAGE_START
    ):
        raise NoDataFoundError(
            f"Requested start date {request.start_date} is before the physics "
            f"dataset's coverage begins ({copernicus.PHYSICS_COVERAGE_START})."
        )
    if (
        PROVIDER_COPERNICUS_WIND in providers_needed
        and request.start_date < copernicus.WIND_COVERAGE_START
    ):
        raise NoDataFoundError(
            f"Requested start date {request.start_date} is before the wind "
            f"dataset's coverage begins ({copernicus.WIND_COVERAGE_START})."
        )


async def run_download(request: DownloadRequest) -> DownloadResult:
    try:
        variables = resolve_variables(request.variables)
    except ValueError as exc:
        raise UnsupportedVariableError(str(exc)) from exc

    providers_needed = {info.provider for info in variables.values()}
    _check_coverage(request, providers_needed)

    for provider in providers_needed:
        assert provider is not None
        limits.check_limits(request.area, request.start_date, request.end_date, provider)

    west, south, east, north = _area_to_bbox(request.area)

    fetch_tasks: dict[str, Any] = {}
    if PROVIDER_COPERNICUS_PHYSICS in providers_needed:
        physics_fields = _needed_physics_fields(variables)
        fetch_tasks["physics"] = copernicus.fetch_physics(
            west, south, east, north, request.start_date, request.end_date, physics_fields
        )
    if PROVIDER_COPERNICUS_WIND in providers_needed:
        fetch_tasks["wind"] = copernicus.fetch_wind(
            west, south, east, north, request.start_date, request.end_date
        )

    try:
        results = await asyncio.gather(*fetch_tasks.values())
    except Exception as exc:  # noqa: BLE001 - never leak a raw copernicusmarine/xarray traceback
        raise ProviderUnavailableError(f"Copernicus Marine request failed: {exc}") from exc

    fetched = dict(zip(fetch_tasks.keys(), results, strict=True))
    physics_ds = fetched.get("physics")
    wind_ds = fetched.get("wind")

    if isinstance(request.area, PointArea):
        if physics_ds is not None:
            physics_ds = physics_ds.sel(
                latitude=request.area.lat, longitude=request.area.lon, method="nearest"
            )
        if wind_ds is not None:
            wind_ds = wind_ds.sel(
                latitude=request.area.lat, longitude=request.area.lon, method="nearest"
            )

    df = build_dataframe(
        physics_ds=physics_ds, wind_ds=wind_ds, variables=variables, resolution=request.resolution
    )

    if df.empty:
        raise NoDataFoundError(
            "No data found for the requested area/date range — it may be entirely "
            "over land or outside the dataset's coverage."
        )

    metadata = _build_metadata(request, variables)
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


def _build_metadata(request: DownloadRequest, variables: dict[str, VariableInfo]) -> dict[str, Any]:
    sources = sorted(
        {
            "Copernicus Marine Service (GLOBAL_ANALYSISFORECAST_PHY_001_024)"
            if info.provider == PROVIDER_COPERNICUS_PHYSICS
            else "Copernicus Marine Service (WIND_GLO_PHY_L4_NRT_012_004)"
            for info in variables.values()
        }
    )
    return {
        "area": request.area.model_dump(),
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "resolution": request.resolution.value,
        "variables": list(variables.keys()),
        "sources": sources,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "MarisAI Universal Ocean Data Downloader",
    }
