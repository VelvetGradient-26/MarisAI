"""Variable -> provider -> dataset mapping for the Universal Ocean Data
Downloader — the "dataset resolver" from the spec, as an in-code registry
rather than the (real, migrated, but currently unused) `app/models/core`
DB schema. Matches how `copernicus_sst.py`/`copernicus_wind.py` are already
built: no DB session needed to serve this feature.

This module owns *variables*; `catalog.py` owns the providers they name.
Adding a real provider for a currently-`available=False` variable is still
purely a backend change: implement the adapter under `providers/`, add its
row to `catalog.PROVIDERS`, then flip that entry's `available`/`provider`/
`source_field` here. The frontend renders whatever this file says.
"""

from __future__ import annotations

from dataclasses import dataclass

from services.download.catalog import (
    PROVIDER_COPERNICUS_BGC_BIO,
    PROVIDER_COPERNICUS_BGC_CAR,
    PROVIDER_COPERNICUS_BGC_NUT,
    PROVIDER_COPERNICUS_BGC_OPTICS,
    PROVIDER_COPERNICUS_BGC_PFT,
    PROVIDER_COPERNICUS_PHYSICS,
    PROVIDER_COPERNICUS_PHYSICS_DAILY,
    PROVIDER_COPERNICUS_SEALEVEL,
    PROVIDER_COPERNICUS_SO_DEPTH,
    PROVIDER_COPERNICUS_THETAO_DEPTH,
    PROVIDER_COPERNICUS_WAVES,
    PROVIDER_COPERNICUS_WIND,
    PROVIDER_GEBCO,
    PROVIDER_OPENMETEO,
)


@dataclass(frozen=True)
class VariableInfo:
    label: str
    category: str
    unit: str
    available: bool
    # Provider identifier this variable is fetched from, or None if unavailable.
    provider: str | None = None
    # Name of the variable inside the provider's xarray Dataset, for variables
    # fetched directly (not derived).
    source_field: str | None = None
    # Source fields inside the provider's Dataset, for variables computed
    # rather than fetched directly. Two for the vector pairs (currents, wind),
    # one for the single-field conversions (water clarity from attenuation).
    derived_from: tuple[str, ...] | None = None
    # Key into cleaning.py's _DERIVATIONS, paired with derived_from.
    derivation: str | None = None
    # True when the value depends on the request's `depth_m`. The frontend
    # shows its depth control only while one of these is selected.
    depth_resolved: bool = False
    # True for a compass bearing on 0-360, where 359 and 1 are neighbours.
    # Every downstream stage — interpolation, subtraction, colour ramp, legend
    # bounds — is linear by default and gets these wrong in a way that looks
    # entirely plausible: the mean of 359 and 1 is 180, the exact opposite
    # heading. Consumers that treat a value as a number rather than as an angle
    # must check this. See `services/field_sampling.py`.
    circular: bool = False


# Ordered to match the spec's own category grouping, so the frontend can
# render grouped checkboxes by iterating this registry directly.
VARIABLE_REGISTRY: dict[str, VariableInfo] = {
    # --- Temperature ---
    "sea_surface_temperature": VariableInfo(
        label="Sea Surface Temperature",
        category="Temperature",
        unit="degC",
        available=True,
        provider=PROVIDER_COPERNICUS_PHYSICS,
        source_field="thetao",
    ),
    "bottom_temperature": VariableInfo(
        label="Bottom Temperature",
        category="Temperature",
        unit="degC",
        available=True,
        # Only the *daily* physics dataset carries the bottom fields; the
        # hourly one this product family also publishes does not.
        provider=PROVIDER_COPERNICUS_PHYSICS_DAILY,
        source_field="tob",
    ),
    "water_temperature": VariableInfo(
        label="Water Temperature",
        category="Temperature",
        unit="degC",
        available=True,
        provider=PROVIDER_COPERNICUS_THETAO_DEPTH,
        source_field="thetao",
        depth_resolved=True,
    ),
    # --- Salinity ---
    "sea_surface_salinity": VariableInfo(
        label="Sea Surface Salinity",
        category="Salinity",
        unit="PSU",
        available=True,
        provider=PROVIDER_COPERNICUS_PHYSICS,
        source_field="so",
    ),
    "bottom_salinity": VariableInfo(
        label="Bottom Salinity",
        category="Salinity",
        unit="PSU",
        available=True,
        provider=PROVIDER_COPERNICUS_PHYSICS_DAILY,
        source_field="sob",
    ),
    "water_salinity": VariableInfo(
        label="Water Salinity",
        category="Salinity",
        unit="PSU",
        available=True,
        provider=PROVIDER_COPERNICUS_SO_DEPTH,
        source_field="so",
        depth_resolved=True,
    ),
    # --- Ocean Currents ---
    "current_u": VariableInfo(
        label="Current U Component",
        category="Ocean Currents",
        unit="m/s",
        available=True,
        provider=PROVIDER_COPERNICUS_PHYSICS,
        source_field="uo",
    ),
    "current_v": VariableInfo(
        label="Current V Component",
        category="Ocean Currents",
        unit="m/s",
        available=True,
        provider=PROVIDER_COPERNICUS_PHYSICS,
        source_field="vo",
    ),
    "current_speed": VariableInfo(
        label="Current Speed",
        category="Ocean Currents",
        unit="m/s",
        available=True,
        provider=PROVIDER_COPERNICUS_PHYSICS,
        derived_from=("uo", "vo"),
        derivation="speed",
    ),
    "current_direction": VariableInfo(
        label="Current Direction",
        category="Ocean Currents",
        unit="deg",
        available=True,
        provider=PROVIDER_COPERNICUS_PHYSICS,
        derived_from=("uo", "vo"),
        # Oceanographic convention: direction the current flows TOWARD.
        # Different from wind_direction below (meteorological "from"
        # convention) — see cleaning.py's derive_direction for the formulas.
        derivation="direction_to",
        circular=True,
    ),
    # --- Waves ---
    "significant_wave_height": VariableInfo(
        label="Significant Wave Height",
        category="Waves",
        unit="m",
        available=True,
        provider=PROVIDER_COPERNICUS_WAVES,
        source_field="VHM0",
    ),
    "maximum_wave_height": VariableInfo(
        label="Maximum Wave Height",
        category="Waves",
        unit="m",
        available=True,
        provider=PROVIDER_COPERNICUS_WAVES,
        # Crest-to-trough maximum, not the dataset's similarly-named VMXL
        # (highest crest only, roughly half the wave).
        source_field="VCMX",
    ),
    "mean_wave_period": VariableInfo(
        label="Mean Wave Period",
        category="Waves",
        unit="s",
        available=True,
        provider=PROVIDER_COPERNICUS_WAVES,
        # Tm02, the spectral moments (0,2) period.
        source_field="VTM02",
    ),
    "peak_wave_period": VariableInfo(
        label="Peak Wave Period",
        category="Waves",
        unit="s",
        available=True,
        provider=PROVIDER_COPERNICUS_WAVES,
        source_field="VTPK",
    ),
    "wave_direction": VariableInfo(
        label="Wave Direction",
        category="Waves",
        unit="deg",
        available=True,
        provider=PROVIDER_COPERNICUS_WAVES,
        # Already a "from" direction in the dataset, so it is fetched
        # directly rather than derived — same convention as wind_direction,
        # opposite to the currents' "toward".
        source_field="VMDR",
        circular=True,
    ),
    # --- Sea Level ---
    "sea_surface_height": VariableInfo(
        label="Sea Surface Height",
        category="Sea Level",
        unit="m",
        available=True,
        provider=PROVIDER_COPERNICUS_PHYSICS,
        source_field="zos",
    ),
    "sea_level_anomaly": VariableInfo(
        label="Sea Level Anomaly",
        category="Sea Level",
        unit="m",
        available=True,
        # Altimetry (DUACS L4), not the model — the anomaly is defined
        # against a 20-year altimetric mean, so it only exists here.
        provider=PROVIDER_COPERNICUS_SEALEVEL,
        source_field="sla",
    ),
    "tidal_height": VariableInfo(
        label="Tidal Height", category="Sea Level", unit="m", available=False
    ),
    # --- Wind ---
    "wind_speed": VariableInfo(
        label="Wind Speed",
        category="Wind",
        unit="m/s",
        available=True,
        provider=PROVIDER_COPERNICUS_WIND,
        derived_from=("eastward_wind", "northward_wind"),
        derivation="speed",
    ),
    # The components exist as variables of their own, not only as the fields
    # `wind_speed`/`wind_direction` are derived from, for one reason: a vector
    # field has to be forecast as components. Direction is circular and every
    # step to the screen is linear, so a particle layer composed from a forecast
    # speed and a forecast bearing would flow backwards along every wrap — the
    # mean of 359 and 1 degrees is 180. Currents already work this way; this is
    # the same move for wind. It also makes `wind_direction` derivable rather
    # than trained, which is the better answer for it anyway.
    "wind_u": VariableInfo(
        label="Wind U Component",
        category="Wind",
        unit="m/s",
        available=True,
        provider=PROVIDER_COPERNICUS_WIND,
        source_field="eastward_wind",
    ),
    "wind_v": VariableInfo(
        label="Wind V Component",
        category="Wind",
        unit="m/s",
        available=True,
        provider=PROVIDER_COPERNICUS_WIND,
        source_field="northward_wind",
    ),
    "wind_direction": VariableInfo(
        label="Wind Direction",
        category="Wind",
        unit="deg",
        available=True,
        provider=PROVIDER_COPERNICUS_WIND,
        derived_from=("eastward_wind", "northward_wind"),
        # Meteorological convention: direction the wind blows FROM (matches
        # copernicus_wind.get_point's existing formula for the live map).
        derivation="direction_from",
        circular=True,
    ),
    "wind_gust": VariableInfo(
        label="Wind Gust",
        category="Wind",
        unit="m/s",
        available=True,
        # The Copernicus L4 wind product carries mean wind only, no gusts, so
        # this comes from the meteorology provider alongside the other
        # atmospheric variables rather than from the wind provider above.
        provider=PROVIDER_OPENMETEO,
        source_field="wind_gusts_10m",
    ),
    # --- Ocean Colour ---
    "chlorophyll_a": VariableInfo(
        label="Chlorophyll-a",
        category="Ocean Colour",
        unit="mg/m3",
        available=True,
        provider=PROVIDER_COPERNICUS_BGC_PFT,
        source_field="chl",
    ),
    "diffuse_attenuation": VariableInfo(
        label="Diffuse Attenuation",
        category="Ocean Colour",
        unit="1/m",
        available=True,
        provider=PROVIDER_COPERNICUS_BGC_OPTICS,
        source_field="kd",
    ),
    "water_clarity": VariableInfo(
        label="Water Clarity",
        category="Ocean Colour",
        unit="m",
        available=True,
        provider=PROVIDER_COPERNICUS_BGC_OPTICS,
        # Secchi depth, converted from the same attenuation coefficient
        # `diffuse_attenuation` exposes raw — there is no separate clarity
        # field to fetch. See cleaning.py's _derive_secchi_depth.
        derived_from=("kd",),
        derivation="secchi_depth",
    ),
    # --- Biogeochemistry ---
    "dissolved_oxygen": VariableInfo(
        label="Dissolved Oxygen",
        category="Biogeochemistry",
        unit="mmol/m3",
        available=True,
        provider=PROVIDER_COPERNICUS_BGC_BIO,
        source_field="o2",
    ),
    "ph": VariableInfo(
        label="pH",
        category="Biogeochemistry",
        unit="pH",
        available=True,
        provider=PROVIDER_COPERNICUS_BGC_CAR,
        source_field="ph",
    ),
    "nitrate": VariableInfo(
        label="Nitrate",
        category="Biogeochemistry",
        unit="mmol/m3",
        available=True,
        provider=PROVIDER_COPERNICUS_BGC_NUT,
        source_field="no3",
    ),
    "phosphate": VariableInfo(
        label="Phosphate",
        category="Biogeochemistry",
        unit="mmol/m3",
        available=True,
        provider=PROVIDER_COPERNICUS_BGC_NUT,
        source_field="po4",
    ),
    "silicate": VariableInfo(
        label="Silicate",
        category="Biogeochemistry",
        unit="mmol/m3",
        available=True,
        provider=PROVIDER_COPERNICUS_BGC_NUT,
        source_field="si",
    ),
    # The one biogeochemical variable with no global source: the Copernicus
    # global BGC suite models nitrate, phosphate, silicate and iron, but not
    # ammonium (it is a regional-product field only).
    "ammonium": VariableInfo(
        label="Ammonium", category="Biogeochemistry", unit="mmol/m3", available=False
    ),
    "primary_productivity": VariableInfo(
        label="Primary Productivity",
        category="Biogeochemistry",
        # The dataset's own unit is per unit *volume*, not the per-area
        # figure the label might suggest.
        unit="mg/m3/day",
        available=True,
        provider=PROVIDER_COPERNICUS_BGC_BIO,
        source_field="nppv",
    ),
    # --- Bathymetry ---
    "ocean_depth": VariableInfo(
        label="Ocean Depth",
        category="Bathymetry",
        unit="m",
        available=True,
        # Time-invariant: the same value repeats for every timestamp in the
        # range. See providers/gebco.py.
        provider=PROVIDER_GEBCO,
        source_field="ocean_depth",
    ),
    # --- Meteorology ---
    "air_temperature": VariableInfo(
        label="Air Temperature",
        category="Meteorology",
        unit="degC",
        available=True,
        provider=PROVIDER_OPENMETEO,
        source_field="temperature_2m",
    ),
    "humidity": VariableInfo(
        label="Humidity",
        category="Meteorology",
        unit="%",
        available=True,
        provider=PROVIDER_OPENMETEO,
        source_field="relative_humidity_2m",
    ),
    "pressure": VariableInfo(
        label="Pressure",
        category="Meteorology",
        unit="hPa",
        available=True,
        provider=PROVIDER_OPENMETEO,
        source_field="surface_pressure",
    ),
    "rainfall": VariableInfo(
        label="Rainfall",
        category="Meteorology",
        unit="mm",
        available=True,
        provider=PROVIDER_OPENMETEO,
        source_field="precipitation",
    ),
}


def resolve_variables(codes: list[str]) -> dict[str, VariableInfo]:
    """Validates requested variable codes and returns their registry entries.

    Raises ValueError (caller maps this to UnsupportedVariableError) naming
    the exact bad code(s) — either unknown to the registry or a real category
    that isn't backed by a provider yet.
    """
    resolved: dict[str, VariableInfo] = {}
    unknown: list[str] = []
    unavailable: list[str] = []

    for code in codes:
        info = VARIABLE_REGISTRY.get(code)
        if info is None:
            unknown.append(code)
        elif not info.available:
            unavailable.append(code)
        else:
            resolved[code] = info

    if unknown:
        raise ValueError(f"Unknown variable(s): {', '.join(unknown)}")
    if unavailable:
        raise ValueError(
            f"Variable(s) not yet available: {', '.join(unavailable)} "
            "(coming in a future release)"
        )
    return resolved


def grouped_for_frontend() -> list[dict[str, object]]:
    """The registry, grouped by category in spec order, for the frontend's
    grouped-checkbox layout. Single source of truth: the frontend never
    needs its own copy of the variable list, so adding a provider later is a
    pure backend change (flip `available`, no frontend edit required)."""
    categories: dict[str, list[dict[str, object]]] = {}
    for code, info in VARIABLE_REGISTRY.items():
        categories.setdefault(info.category, []).append(
            {
                "code": code,
                "label": info.label,
                "unit": info.unit,
                "available": info.available,
                "depth_resolved": info.depth_resolved,
            }
        )
    return [{"category": category, "variables": items} for category, items in categories.items()]
