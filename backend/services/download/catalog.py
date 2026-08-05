"""The provider table for the Universal Ocean Data Downloader.

`registry.py` answers "which provider does this variable come from"; this
module answers "what *is* that provider" — dataset, grid, cadence, coverage,
citation, and how to fetch it.

It exists because the alternative doesn't scale. With three providers,
`service.py` could carry an if-block each and `limits.py` a couple of
hand-maintained dicts keyed by provider name; at fourteen that becomes a
dozen places to remember to edit in step. Everything that varies per provider
is a column here instead, so adding one is a single entry plus (if it speaks
a new protocol) a fetch function under `providers/`.

Every `fetch` has the same keyword-only signature and returns an
`xarray.Dataset`, whatever it actually talked to — Copernicus' zarr stores,
Open-Meteo's point JSON API, ERDDAP's CSV. That uniformity is what lets
`service.py` fetch all of them in one `asyncio.gather` and `cleaning.py` merge
them without knowing which is which.
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import date
from functools import partial
from typing import Protocol

import xarray as xr

from services.download.providers import copernicus, gebco, openmeteo


class FetchFn(Protocol):
    def __call__(
        self,
        *,
        fields: list[str],
        west: float,
        south: float,
        east: float,
        north: float,
        start_date: date,
        end_date: date,
        depth_m: float | None,
    ) -> Awaitable[xr.Dataset]: ...


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    # Citation string, reproduced in every export's metadata and the PDF's
    # sources page.
    source_label: str
    # Licence/attribution line for the PDF footer. Providers under the same
    # licence share a string.
    licence: str
    # Native grid spacing and cadence. Used *only* by limits.py to size a
    # request before it is sent; the fetch always uses the real native grid.
    grid_spacing_deg: float
    steps_per_day: float
    # First date the dataset actually carries data for, confirmed by reading
    # each dataset's real time axis rather than from the product docs. None
    # means no meaningful lower bound.
    coverage_start: date | None
    fetch: FetchFn
    # False for bathymetry, the one provider with no time dim.
    time_varying: bool = True
    # Point-API providers pay per grid point, not per fetched block, so they
    # need a tighter guardrail than the shared cell budget gives.
    max_points: int | None = None
    # Days past today the provider serves, when exceeding it is a hard error
    # rather than just an empty result. None = let the fetch decide.
    forecast_horizon_days: int | None = None


# --- Provider identifiers --------------------------------------------------
#
# One provider == one upstream dataset. Splitting the BGC suite into five
# rather than one "biogeochemistry" provider is deliberate: they have
# genuinely different coverage windows (optics starts two years later than the
# rest), and a per-dataset key means the coverage check, the size estimate and
# the citation all stay correct without special cases.
PROVIDER_COPERNICUS_PHYSICS = "copernicus_physics"
PROVIDER_COPERNICUS_WIND = "copernicus_wind"
PROVIDER_COPERNICUS_WAVES = "copernicus_waves"
PROVIDER_COPERNICUS_PHYSICS_DAILY = "copernicus_physics_daily"
PROVIDER_COPERNICUS_THETAO_DEPTH = "copernicus_thetao_depth"
PROVIDER_COPERNICUS_SO_DEPTH = "copernicus_so_depth"
PROVIDER_COPERNICUS_SEALEVEL = "copernicus_sealevel"
PROVIDER_COPERNICUS_BGC_BIO = "copernicus_bgc_bio"
PROVIDER_COPERNICUS_BGC_NUT = "copernicus_bgc_nut"
PROVIDER_COPERNICUS_BGC_CAR = "copernicus_bgc_car"
PROVIDER_COPERNICUS_BGC_PFT = "copernicus_bgc_pft"
PROVIDER_COPERNICUS_BGC_OPTICS = "copernicus_bgc_optics"
PROVIDER_OPENMETEO = "openmeteo"
PROVIDER_GEBCO = "gebco"


_COPERNICUS_LICENCE = (
    "Copernicus Marine Service, under the Copernicus Marine licence — free, open and "
    "full access (https://marine.copernicus.eu/user-corner-service/general-conditions-use)."
)
_OPENMETEO_LICENCE = (
    "Open-Meteo (https://open-meteo.com/), under CC BY 4.0, derived from ECMWF ERA5 "
    "reanalysis and forecast data."
)
_GEBCO_LICENCE = (
    "GEBCO Compilation Group, GEBCO_2021 Grid, served via Ifremer ERDDAP. "
    "GEBCO data are placed in the public domain (https://www.gebco.net/data-products/)."
)

# Copernicus coverage starts, each read off the dataset's own time axis.
_PHYSICS_START = date(2022, 6, 1)
_WIND_START = date(2024, 6, 13)
_WAVES_START = date(2022, 11, 1)
_SEALEVEL_START = date(2024, 7, 1)
_BGC_START = date(2021, 11, 1)
_BGC_OPTICS_START = date(2023, 11, 15)


def _copernicus_fetch(dataset_id: str, depth_mode: str = copernicus.DEPTH_NONE) -> FetchFn:
    return partial(copernicus.fetch, dataset_id=dataset_id, depth_mode=depth_mode)


def _copernicus_spec(
    key: str,
    dataset_id: str,
    product: str,
    coverage_start: date,
    *,
    grid_spacing_deg: float,
    steps_per_day: float,
    depth_mode: str = copernicus.DEPTH_NONE,
) -> ProviderSpec:
    return ProviderSpec(
        key=key,
        source_label=f"Copernicus Marine Service ({product})",
        licence=_COPERNICUS_LICENCE,
        grid_spacing_deg=grid_spacing_deg,
        steps_per_day=steps_per_day,
        coverage_start=coverage_start,
        fetch=_copernicus_fetch(dataset_id, depth_mode),
    )


def _bgc_spec(key: str, dataset_id: str, coverage_start: date = _BGC_START) -> ProviderSpec:
    # The five BGC datasets share a grid, a cadence, a product and a depth
    # story — only the id and (for optics) the coverage start differ.
    return _copernicus_spec(
        key,
        dataset_id,
        "GLOBAL_ANALYSISFORECAST_BGC_001_028",
        coverage_start,
        grid_spacing_deg=0.25,
        steps_per_day=1,
        depth_mode=copernicus.DEPTH_SURFACE,
    )


PROVIDERS: dict[str, ProviderSpec] = {
    spec.key: spec
    for spec in (
        _copernicus_spec(
            PROVIDER_COPERNICUS_PHYSICS,
            copernicus.PHYSICS_DATASET_ID,
            "GLOBAL_ANALYSISFORECAST_PHY_001_024",
            _PHYSICS_START,
            grid_spacing_deg=0.083,
            steps_per_day=24,
            depth_mode=copernicus.DEPTH_SURFACE,
        ),
        _copernicus_spec(
            PROVIDER_COPERNICUS_WIND,
            copernicus.WIND_DATASET_ID,
            "WIND_GLO_PHY_L4_NRT_012_004",
            _WIND_START,
            grid_spacing_deg=0.125,
            steps_per_day=24,
        ),
        _copernicus_spec(
            PROVIDER_COPERNICUS_WAVES,
            copernicus.WAVES_DATASET_ID,
            "GLOBAL_ANALYSISFORECAST_WAV_001_027",
            _WAVES_START,
            grid_spacing_deg=0.083,
            # 3-hourly, not hourly — assuming hourly would overstate a wave
            # request's cost threefold and reject areas that fetch fine.
            steps_per_day=8,
        ),
        _copernicus_spec(
            PROVIDER_COPERNICUS_PHYSICS_DAILY,
            copernicus.PHYSICS_DAILY_DATASET_ID,
            "GLOBAL_ANALYSISFORECAST_PHY_001_024",
            _PHYSICS_START,
            grid_spacing_deg=0.083,
            steps_per_day=1,
        ),
        _copernicus_spec(
            PROVIDER_COPERNICUS_THETAO_DEPTH,
            copernicus.THETAO_DEPTH_DATASET_ID,
            "GLOBAL_ANALYSISFORECAST_PHY_001_024",
            _PHYSICS_START,
            grid_spacing_deg=0.083,
            steps_per_day=1,
            depth_mode=copernicus.DEPTH_SELECT,
        ),
        _copernicus_spec(
            PROVIDER_COPERNICUS_SO_DEPTH,
            copernicus.SO_DEPTH_DATASET_ID,
            "GLOBAL_ANALYSISFORECAST_PHY_001_024",
            _PHYSICS_START,
            grid_spacing_deg=0.083,
            steps_per_day=1,
            depth_mode=copernicus.DEPTH_SELECT,
        ),
        _copernicus_spec(
            PROVIDER_COPERNICUS_SEALEVEL,
            copernicus.SEALEVEL_DATASET_ID,
            "SEALEVEL_GLO_PHY_L4_NRT_008_046",
            _SEALEVEL_START,
            grid_spacing_deg=0.125,
            steps_per_day=1,
        ),
        _bgc_spec(PROVIDER_COPERNICUS_BGC_BIO, copernicus.BGC_BIO_DATASET_ID),
        _bgc_spec(PROVIDER_COPERNICUS_BGC_NUT, copernicus.BGC_NUT_DATASET_ID),
        _bgc_spec(PROVIDER_COPERNICUS_BGC_CAR, copernicus.BGC_CAR_DATASET_ID),
        _bgc_spec(PROVIDER_COPERNICUS_BGC_PFT, copernicus.BGC_PFT_DATASET_ID),
        _bgc_spec(
            PROVIDER_COPERNICUS_BGC_OPTICS,
            copernicus.BGC_OPTICS_DATASET_ID,
            _BGC_OPTICS_START,
        ),
        ProviderSpec(
            key=PROVIDER_OPENMETEO,
            source_label="Open-Meteo (ECMWF ERA5 reanalysis / IFS forecast)",
            licence=_OPENMETEO_LICENCE,
            grid_spacing_deg=openmeteo.GRID_SPACING_DEG,
            steps_per_day=24,
            coverage_start=openmeteo.COVERAGE_START,
            fetch=openmeteo.fetch,
            # A point API: cost scales with grid points, and every 100 of them
            # is another HTTP round trip. 900 keeps the worst case at nine
            # batched requests.
            max_points=900,
            forecast_horizon_days=openmeteo.FORECAST_HORIZON_DAYS,
        ),
        ProviderSpec(
            key=PROVIDER_GEBCO,
            source_label="GEBCO_2021 Grid via Ifremer ERDDAP",
            licence=_GEBCO_LICENCE,
            grid_spacing_deg=gebco.GRID_SPACING_DEG,
            # Time-invariant: one value per cell for any date range.
            steps_per_day=0,
            coverage_start=None,
            fetch=gebco.fetch,
            time_varying=False,
        ),
    )
}


def get(provider_key: str) -> ProviderSpec:
    return PROVIDERS[provider_key]


def source_labels(provider_keys: set[str]) -> list[str]:
    return sorted({PROVIDERS[key].source_label for key in provider_keys})


def licences(provider_keys: set[str]) -> list[str]:
    return sorted({PROVIDERS[key].licence for key in provider_keys})
