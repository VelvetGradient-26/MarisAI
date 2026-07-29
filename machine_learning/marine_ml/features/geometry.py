"""Shared spatial-geometry features: fronts, eddies, upwelling, coastal distance.

Section 5 of the approach doc calls these out explicitly as shared library
functions rather than per-notebook code, because both problem statements need
the same physics:

* **Fronts** — sharp horizontal gradients in temperature or chlorophyll.
  Nutrients and plankton concentrate at them, which is why they drive both
  bloom initiation and fish aggregation. INCOIS's operational PFZ advisory is,
  at heart, a hand-tuned SST-front detector; these features are the learned
  version of the same signal.
* **Eddies** — the Okubo-Weiss parameter separates rotation-dominated
  (vortex core) from strain-dominated (filament) flow. Negative values mark
  eddy interiors.
* **Upwelling** — Bakun-style index from the alongshore wind stress
  component, the classical driver of the nutrient injection that precedes a
  bloom.

Everything is computed on the regular lat/lon grid the fusion layer produces,
so grid spacing is in degrees; where a physical unit matters the conversion to
metres is applied explicitly rather than left implicit.
"""

from __future__ import annotations

import numpy as np
import xarray as xr

EARTH_RADIUS_M = 6_371_000.0
METRES_PER_DEGREE_LAT = 111_320.0


def _spatial_dims(array: xr.DataArray) -> tuple[str, str]:
    lat = next((d for d in array.dims if str(d).lower().startswith("lat")), None)
    lon = next((d for d in array.dims if str(d).lower().startswith("lon")), None)
    if lat is None or lon is None:
        raise ValueError(f"expected latitude/longitude dims, got {array.dims}")
    return str(lat), str(lon)


def _metres_per_degree_lon(latitude: xr.DataArray) -> xr.DataArray:
    """Longitude degrees shrink towards the poles; at 20N a degree of
    longitude is ~6% shorter than at the equator. Ignoring this would bias
    every east-west gradient in the domain."""
    return METRES_PER_DEGREE_LAT * np.cos(np.deg2rad(latitude))


def gradient_magnitude(field: xr.DataArray, per_metre: bool = True) -> xr.DataArray:
    """Horizontal gradient magnitude of ``field`` — the frontal-strength feature.

    A centred-difference stand-in for the Sobel operator the doc names: on a
    smooth geophysical field at this resolution the two agree closely, and
    ``differentiate`` handles the irregular edges and NaN land mask without
    the padding gymnastics a hand-rolled convolution would need.

    With ``per_metre`` the result is in units of ``field`` per metre, properly
    latitude-corrected; otherwise it is per degree.
    """
    lat_dim, lon_dim = _spatial_dims(field)
    d_lat = field.differentiate(lat_dim)
    d_lon = field.differentiate(lon_dim)

    if per_metre:
        d_lat = d_lat / METRES_PER_DEGREE_LAT
        d_lon = d_lon / _metres_per_degree_lon(field[lat_dim])

    magnitude = np.sqrt(d_lat**2 + d_lon**2)
    magnitude.name = f"{field.name}_gradient" if field.name else "gradient"
    magnitude.attrs["long_name"] = f"horizontal gradient magnitude of {field.name}"
    return magnitude


def okubo_weiss(u: xr.DataArray, v: xr.DataArray) -> xr.DataArray:
    """Okubo-Weiss parameter W = Sn^2 + Ss^2 - w^2, in s^-2.

    Negative where rotation dominates strain — i.e. inside an eddy core.
    Positive in strain-dominated filaments between eddies. Many pelagic
    species aggregate at eddy edges, and blooms concentrate where eddies trap
    nutrients, so this feeds both problems.
    """
    lat_dim, lon_dim = _spatial_dims(u)
    m_lat = METRES_PER_DEGREE_LAT
    m_lon = _metres_per_degree_lon(u[lat_dim])

    du_dx = u.differentiate(lon_dim) / m_lon
    du_dy = u.differentiate(lat_dim) / m_lat
    dv_dx = v.differentiate(lon_dim) / m_lon
    dv_dy = v.differentiate(lat_dim) / m_lat

    normal_strain = du_dx - dv_dy
    shear_strain = dv_dx + du_dy
    relative_vorticity = dv_dx - du_dy

    w = normal_strain**2 + shear_strain**2 - relative_vorticity**2
    w.name = "okubo_weiss"
    w.attrs.update(units="s-2", long_name="Okubo-Weiss parameter")
    return w


def relative_vorticity(u: xr.DataArray, v: xr.DataArray) -> xr.DataArray:
    """Vertical component of relative vorticity, in s^-1.

    Sign distinguishes cyclonic from anticyclonic circulation (in the northern
    hemisphere, positive is cyclonic) — the cyclonic/anticyclonic flag the doc
    asks for alongside eddy distance.
    """
    lat_dim, lon_dim = _spatial_dims(u)
    dv_dx = v.differentiate(lon_dim) / _metres_per_degree_lon(u[lat_dim])
    du_dy = u.differentiate(lat_dim) / METRES_PER_DEGREE_LAT
    zeta = dv_dx - du_dy
    zeta.name = "relative_vorticity"
    zeta.attrs.update(units="s-1", long_name="relative vorticity (vertical component)")
    return zeta


def current_speed(u: xr.DataArray, v: xr.DataArray) -> xr.DataArray:
    speed = np.sqrt(u**2 + v**2)
    speed.name = "current_speed"
    speed.attrs.update(units="m s-1", long_name="surface current speed")
    return speed


def eddy_kinetic_energy(u: xr.DataArray, v: xr.DataArray) -> xr.DataArray:
    """EKE relative to the record-mean flow, in m^2 s^-2.

    Anomalies are taken against the time mean at each cell, so a persistent
    boundary current does not read as eddy activity.
    """
    time_dim = "time" if "time" in u.dims else None
    if time_dim is None:
        raise ValueError("eddy_kinetic_energy needs a time dimension")
    u_prime = u - u.mean(time_dim)
    v_prime = v - v.mean(time_dim)
    eke = 0.5 * (u_prime**2 + v_prime**2)
    eke.name = "eddy_kinetic_energy"
    eke.attrs.update(units="m2 s-2", long_name="eddy kinetic energy")
    return eke


def upwelling_index(
    wind_u: xr.DataArray,
    wind_v: xr.DataArray,
    coast_angle_deg: float = 0.0,
) -> xr.DataArray:
    """Bakun-style upwelling index from wind stress, in m^3 s^-1 per metre of coast.

    Offshore Ekman transport driven by the alongshore wind stress component.
    Positive means offshore transport, i.e. upwelling-favourable — the
    nutrient-injection mechanism that precedes many coastal blooms and
    sustains the productive fishing grounds off India's west coast.

    ``coast_angle_deg`` is the orientation of the coastline (degrees clockwise
    from north). The default of 0 treats the coast as north-south, which is a
    fair approximation for the Indian west coast; it should be set per coastal
    segment for other geometries.

    Prefer ``upwelling_index_from_stress`` when observed stress is available:
    this variant has to *derive* stress from 10 m winds through a bulk formula
    with a fixed drag coefficient, and that constant is the least defensible
    number in the calculation — the real drag coefficient varies with sea
    state and stability.
    """
    tau_x, tau_y = wind_stress(wind_u, wind_v)
    return upwelling_index_from_stress(tau_x, tau_y, coast_angle_deg)


def upwelling_index_from_stress(
    tau_x: xr.DataArray,
    tau_y: xr.DataArray,
    coast_angle_deg: float = 0.0,
) -> xr.DataArray:
    """Bakun upwelling index from **observed** wind stress, m^3 s^-1 per metre.

    Same quantity as ``upwelling_index``, but fed the scatterometer-derived
    stress the L4 wind product serves directly, so no drag-coefficient
    assumption enters.
    """
    latitude = tau_x[_spatial_dims(tau_x)[0]]

    theta = np.deg2rad(coast_angle_deg)
    # Wind stress component parallel to the coastline.
    tau_alongshore = tau_x * np.sin(theta) + tau_y * np.cos(theta)

    f = coriolis_parameter(latitude)
    # Ekman transport is undefined at the equator, where f -> 0; mask a narrow
    # band rather than emitting an infinity that would poison the feature.
    f = xr.where(np.abs(latitude) < 2.0, np.nan, f)

    index = tau_alongshore / (SEAWATER_DENSITY * f)
    index.name = "upwelling_index"
    index.attrs.update(units="m3 s-1 m-1", long_name="Bakun upwelling index")
    return index


def ekman_pumping(stress_curl: xr.DataArray) -> xr.DataArray:
    """Ekman pumping velocity from wind stress curl, in m s^-1.

    The *open-ocean* upwelling mechanism, distinct from the coastal Ekman
    transport that ``upwelling_index`` captures. Positive curl in the northern
    hemisphere drives divergence and upwells nutrient-rich water from below;
    negative curl downwells. In the Arabian Sea this matters specifically
    because the Findlater Jet's curl drives a large open-ocean upwelling
    region well offshore of the coastal band, and blooms there are not
    explained by the coastal index at all.
    """
    latitude = stress_curl[_spatial_dims(stress_curl)[0]]
    f = coriolis_parameter(latitude)
    f = xr.where(np.abs(latitude) < 2.0, np.nan, f)

    velocity = stress_curl / (SEAWATER_DENSITY * f)
    velocity.name = "ekman_pumping"
    velocity.attrs.update(units="m s-1", long_name="Ekman pumping velocity")
    return velocity


SEAWATER_DENSITY = 1025.0  # kg m-3
AIR_DENSITY = 1.22  # kg m-3
DRAG_COEFFICIENT = 1.3e-3
EARTH_ANGULAR_VELOCITY = 7.2921e-5  # rad s-1


def wind_stress(wind_u: xr.DataArray, wind_v: xr.DataArray) -> tuple[xr.DataArray, xr.DataArray]:
    """Surface wind stress (tau_x, tau_y) in Pa, via the standard bulk formula."""
    speed = np.sqrt(wind_u**2 + wind_v**2)
    factor = AIR_DENSITY * DRAG_COEFFICIENT * speed
    return factor * wind_u, factor * wind_v


def coriolis_parameter(latitude: xr.DataArray) -> xr.DataArray:
    return 2.0 * EARTH_ANGULAR_VELOCITY * np.sin(np.deg2rad(latitude))


def distance_to_coast(land_mask: xr.DataArray) -> xr.DataArray:
    """Great-circle distance from each ocean cell to the nearest land cell, in km.

    ``land_mask`` is True over land. Computed by brute-force nearest-neighbour
    against the land cells; at the grid sizes used here (order 10^4-10^5
    cells) that is fast enough and avoids pulling in a geospatial dependency
    for one feature, matching the repo's minimal-dependency convention.

    Ocean cells with no land anywhere in the domain get NaN rather than a
    fabricated distance to an out-of-domain coast.
    """
    lat_dim, lon_dim = _spatial_dims(land_mask)
    lats = land_mask[lat_dim].values
    lons = land_mask[lon_dim].values

    lon_grid, lat_grid = np.meshgrid(lons, lats)
    land = np.asarray(land_mask.values, dtype=bool)

    if not land.any():
        return xr.full_like(land_mask, np.nan, dtype=float).rename("distance_to_coast")

    land_lat = np.deg2rad(lat_grid[land])
    land_lon = np.deg2rad(lon_grid[land])
    land_xyz = np.column_stack(
        (
            np.cos(land_lat) * np.cos(land_lon),
            np.cos(land_lat) * np.sin(land_lon),
            np.sin(land_lat),
        )
    )

    all_lat = np.deg2rad(lat_grid.ravel())
    all_lon = np.deg2rad(lon_grid.ravel())
    all_xyz = np.column_stack(
        (
            np.cos(all_lat) * np.cos(all_lon),
            np.cos(all_lat) * np.sin(all_lon),
            np.sin(all_lat),
        )
    )

    from scipy.spatial import cKDTree

    # Chord distance in 3D orders identically to great-circle distance, so the
    # nearest neighbour found on the unit sphere is the correct one; the chord
    # is then converted back to arc length.
    tree = cKDTree(land_xyz)
    chord, _ = tree.query(all_xyz, k=1)
    chord = np.clip(chord, 0.0, 2.0)
    arc = 2.0 * np.arcsin(chord / 2.0)
    distance_km = (arc * EARTH_RADIUS_M / 1000.0).reshape(lat_grid.shape)

    result = xr.DataArray(
        distance_km,
        coords={lat_dim: lats, lon_dim: lons},
        dims=(lat_dim, lon_dim),
        name="distance_to_coast",
    )
    result.attrs.update(units="km", long_name="distance to nearest land cell")
    return result.where(~land_mask)
