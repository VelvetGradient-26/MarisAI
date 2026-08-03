"""Variable -> provider -> dataset mapping for the Universal Ocean Data
Downloader — the "dataset resolver" from the spec, as an in-code registry
rather than the (real, migrated, but currently unused) `app/models/core`
DB schema. Matches how `copernicus_sst.py`/`copernicus_wind.py` are already
built: no DB session needed to serve this feature.

Adding a real provider for a currently-`available=False` variable later is
purely: implement a new adapter under `providers/`, then flip that entry's
`available`/`provider`/`source_field` here — the frontend contract and
`service.py`'s orchestration are untouched.
"""

from __future__ import annotations

from dataclasses import dataclass

# Provider identifiers used by service.py to group variables before fetching.
PROVIDER_COPERNICUS_PHYSICS = "copernicus_physics"
PROVIDER_COPERNICUS_WIND = "copernicus_wind"
PROVIDER_COPERNICUS_WAVES = "copernicus_waves"


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
    # (u_field, v_field) inside the provider's Dataset, for variables computed
    # from a vector pair rather than fetched directly.
    derived_from: tuple[str, str] | None = None
    # "speed" or "direction", paired with derived_from.
    derivation: str | None = None


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
        label="Bottom Temperature", category="Temperature", unit="degC", available=False
    ),
    "water_temperature": VariableInfo(
        label="Water Temperature", category="Temperature", unit="degC", available=False
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
        label="Bottom Salinity", category="Salinity", unit="PSU", available=False
    ),
    "water_salinity": VariableInfo(
        label="Water Salinity", category="Salinity", unit="PSU", available=False
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
        label="Sea Level Anomaly", category="Sea Level", unit="m", available=False
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
    ),
    "wind_gust": VariableInfo(label="Wind Gust", category="Wind", unit="m/s", available=False),
    # --- Ocean Colour (no provider wired yet) ---
    "chlorophyll_a": VariableInfo(
        label="Chlorophyll-a", category="Ocean Colour", unit="mg/m3", available=False
    ),
    "diffuse_attenuation": VariableInfo(
        label="Diffuse Attenuation", category="Ocean Colour", unit="1/m", available=False
    ),
    "water_clarity": VariableInfo(
        label="Water Clarity", category="Ocean Colour", unit="m", available=False
    ),
    # --- Biogeochemistry (no provider wired yet) ---
    "dissolved_oxygen": VariableInfo(
        label="Dissolved Oxygen", category="Biogeochemistry", unit="mmol/m3", available=False
    ),
    "ph": VariableInfo(label="pH", category="Biogeochemistry", unit="pH", available=False),
    "nitrate": VariableInfo(
        label="Nitrate", category="Biogeochemistry", unit="mmol/m3", available=False
    ),
    "phosphate": VariableInfo(
        label="Phosphate", category="Biogeochemistry", unit="mmol/m3", available=False
    ),
    "silicate": VariableInfo(
        label="Silicate", category="Biogeochemistry", unit="mmol/m3", available=False
    ),
    "ammonium": VariableInfo(
        label="Ammonium", category="Biogeochemistry", unit="mmol/m3", available=False
    ),
    "primary_productivity": VariableInfo(
        label="Primary Productivity",
        category="Biogeochemistry",
        unit="mg C/m2/day",
        available=False,
    ),
    # --- Bathymetry (point-only lookup exists in services/bathymetry.py, but
    # doesn't fit this feature's gridded/time-series row shape yet) ---
    "ocean_depth": VariableInfo(
        label="Ocean Depth", category="Bathymetry", unit="m", available=False
    ),
    # --- Meteorology (no provider wired yet) ---
    "air_temperature": VariableInfo(
        label="Air Temperature", category="Meteorology", unit="degC", available=False
    ),
    "humidity": VariableInfo(
        label="Humidity", category="Meteorology", unit="%", available=False
    ),
    "pressure": VariableInfo(
        label="Pressure", category="Meteorology", unit="hPa", available=False
    ),
    "rainfall": VariableInfo(
        label="Rainfall", category="Meteorology", unit="mm", available=False
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
            {"code": code, "label": info.label, "unit": info.unit, "available": info.available}
        )
    return [{"category": category, "variables": items} for category, items in categories.items()]
