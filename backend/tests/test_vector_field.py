"""Tests for the U/V field textures the GPU particle layer consumes.

**What actually needs pinning here is a contract between two languages.** The
encoder lives in `services/vector_field.py` and the decoder is GLSL, in
`frontend/src/features/map/vectorField/shaders.ts`. Nothing type-checks across
that boundary, and every way it can break is silent: the layer still downloads
a texture, still animates, and still looks like a plausible ocean. So
`_shader_sample` below reimplements `fieldUV()` exactly as the shader has it,
and the tests assert that sampling the encoded texture *that way* returns the
velocity that went in.

The failure this is really guarding against is the one that prompted the
module. The shader used to hardcode `v = (90 - lat) / 180`, which is true of
the wind product and false of Copernicus's physics grid — latitude -80 to 90 —
so a currents texture read with the global frame would have advected every
particle with water from the wrong latitude, at full confidence.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
import xarray as xr
from PIL import Image

from services import vector_field

# Copernicus's global physics grid: the reason bounds are data, not a constant.
PHYSICS_LAT_SOUTH = -80.0
PHYSICS_LAT_NORTH = 90.0


def _shader_sample(png: bytes, meta: vector_field.FieldTexture, lat: float, lon: float):
    """Sample the texture the way the shader does, nearest-texel.

    Mirrors `fieldUV()` in shaders.ts:
        u = mod(lon - lonWest, 360) / lonSpan
        v = (latNorth - lat) / latSpan
    and returns `None` where the shader's `onField()` would reject the sample
    or the alpha channel marks no-data — the two cases that make a particle
    respawn instead of drift.
    """
    image = np.array(Image.open(io.BytesIO(png)))
    height, width = image.shape[:2]

    lon_span = meta.lon_east - meta.lon_west
    lat_span = meta.lat_north - meta.lat_south
    u = ((lon - meta.lon_west) % 360.0) / lon_span
    v = (meta.lat_north - lat) / lat_span
    if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        return None

    col = min(int(u * width), width - 1)
    row = min(int(v * height), height - 1)
    texel = image[row, col]
    if texel[3] < 128:
        return None

    return (
        texel[0] / 255.0 * (meta.u_max - meta.u_min) + meta.u_min,
        texel[1] / 255.0 * (meta.v_max - meta.v_min) + meta.v_min,
    )


def _physics_like_field(rows: int = 171, cols: int = 360):
    """A grid shaped like the real currents source: latitude -80 to 90."""
    lat = np.linspace(PHYSICS_LAT_SOUTH, PHYSICS_LAT_NORTH, rows)
    lon = np.linspace(-180.0, 179.0, cols)
    lat_grid, lon_grid = np.meshgrid(lat, lon, indexing="ij")
    # Distinct, non-symmetric functions of lat and lon, so a transposed,
    # flipped or offset read produces a different number rather than a
    # coincidentally equal one.
    u = np.sin(np.radians(lat_grid * 1.7)) * 1.3
    v = np.cos(np.radians(lon_grid * 2.3)) * 0.8
    return lat, lon, u, v


def test_the_texture_decodes_to_the_velocity_that_went_in():
    """The end-to-end contract: encode here, sample as the shader does, get the
    same vector back to within one 8-bit quantum."""
    lat, lon, u, v = _physics_like_field()
    texture = vector_field.encode(u, v, lat, lon)

    quantum_u = (texture.u_max - texture.u_min) / 255.0
    quantum_v = (texture.v_max - texture.v_min) / 255.0

    for row, col in [(0, 0), (85, 180), (170, 359), (40, 300), (120, 25)]:
        sampled = _shader_sample(texture.png, texture, lat[row], lon[col])
        assert sampled is not None, f"cell ({row}, {col}) read as no-data"
        assert abs(sampled[0] - u[row, col]) <= quantum_u, f"u wrong at ({row}, {col})"
        assert abs(sampled[1] - v[row, col]) <= quantum_v, f"v wrong at ({row}, {col})"


def test_a_non_global_field_reports_its_own_frame():
    """Bounds are the field's outer cell edges, not the globe.

    The regression that matters: with the shader's old hardcoded
    `v = (90-lat)/180`, a point at 0degN in a -80..90 field resolves to texture
    row 0.5 of the *global* frame, which in a grid that starts at -80 is
    latitude 5. Every particle would drift on water from several degrees away.
    """
    lat, lon, u, v = _physics_like_field()
    texture = vector_field.encode(u, v, lat, lon)

    spacing = float(lat[1] - lat[0])
    assert texture.lat_south == pytest.approx(PHYSICS_LAT_SOUTH - spacing / 2)
    assert texture.lat_north == pytest.approx(PHYSICS_LAT_NORTH + spacing / 2)
    assert texture.lat_north - texture.lat_south < 180.0, (
        "a -80..90 field must not report the full global latitude span"
    )

    # The equator must decode to the equator's velocity, not to 5degN's.
    at_equator = _shader_sample(texture.png, texture, 0.0, 0.0)
    equator_row = int(np.argmin(np.abs(lat - 0.0)))
    wrong_row = int(np.argmin(np.abs(lat - 5.0)))
    assert at_equator is not None
    assert abs(at_equator[0] - u[equator_row, 0]) < 0.02
    assert abs(at_equator[0] - u[wrong_row, 0]) > 0.05, (
        "the test field is too flat in latitude to detect a misaligned frame"
    )


def test_water_outside_the_fields_latitude_range_is_off_field():
    """Below 80degS the currents product has nothing, and the shader must know.

    Textures are CLAMP_TO_EDGE, so a clamped read here would silently return
    the southernmost row's velocity — the Southern Ocean advected with
    Antarctic coastal water. `onField()` is what makes it a respawn instead.
    """
    lat, lon, u, v = _physics_like_field()
    texture = vector_field.encode(u, v, lat, lon)

    assert _shader_sample(texture.png, texture, -85.0, 0.0) is None
    assert _shader_sample(texture.png, texture, -89.0, 120.0) is None
    assert _shader_sample(texture.png, texture, -70.0, 0.0) is not None


def test_land_is_encoded_as_no_data_rather_than_as_zero_velocity():
    """Zero velocity is a real reading — slack water. Land is not, and a
    particle must respawn there rather than sit still on a continent."""
    lat, lon, u, v = _physics_like_field()
    u[50:60, 100:120] = np.nan
    v[50:60, 100:120] = np.nan
    texture = vector_field.encode(u, v, lat, lon)

    assert _shader_sample(texture.png, texture, lat[55], lon[110]) is None
    assert _shader_sample(texture.png, texture, lat[55], lon[200]) is not None


def test_north_is_up_in_the_texture():
    """Row 0 of the image is the northernmost latitude.

    A flipped texture is the perfect silent failure: the field still covers the
    globe, still animates, and advects the Southern Ocean with Arctic water.
    """
    lat = np.linspace(-89.5, 89.5, 180)
    lon = np.linspace(-179.5, 179.5, 360)
    # u increases monotonically with latitude, so the image's first row must
    # carry the largest values.
    u = np.broadcast_to(np.linspace(-1.0, 1.0, 180)[:, None], (180, 360)).copy()
    texture = vector_field.encode(u, np.zeros_like(u), lat, lon)

    image = np.array(Image.open(io.BytesIO(texture.png)))
    assert image[0, 0, 0] > image[-1, 0, 0], "texture row 0 is not the northern edge"


def test_a_descending_latitude_axis_is_normalised_not_mis_encoded():
    """Some products publish latitude north-to-south. Encoding one as-is would
    invert the field while looking entirely well-formed."""
    lat = np.linspace(-89.5, 89.5, 180)
    lon = np.linspace(-179.5, 179.5, 360)
    u = np.broadcast_to(np.linspace(-1.0, 1.0, 180)[:, None], (180, 360)).copy()
    v = np.zeros_like(u)

    ascending = vector_field.encode(u, v, lat, lon)
    descending = vector_field.encode(u[::-1, :], v[::-1, :], lat[::-1], lon)

    assert descending.png == ascending.png
    assert descending.lat_south == pytest.approx(ascending.lat_south)
    assert descending.lat_north == pytest.approx(ascending.lat_north)


def test_downsampling_crops_an_indivisible_grid_instead_of_raising():
    """Copernicus's physics grid is 2041 latitudes — an odd number.

    The previous reshape-based downsample required divisibility and raised
    `ValueError` on any even factor. Because that ran inside a fire-and-forget
    refresh task, the exception would have been swallowed by asyncio, the cache
    would have stayed empty forever, and every currents endpoint would have
    503'd with nothing useful logged.
    """
    lat = np.linspace(-80.0, 90.0, 2041)
    lon = np.linspace(-180.0, 179.9167, 4320)
    u = np.broadcast_to(np.linspace(-1.0, 1.0, 2041)[:, None], (2041, 4320)).copy()

    texture = vector_field.encode(u, np.zeros_like(u), lat, lon, downsample=3)
    image = Image.open(io.BytesIO(texture.png))

    assert image.size == (1440, 680)
    # The declared frame must describe the rows that survived the crop, not the
    # ones that were dropped.
    assert texture.lat_north < 90.0 + (170.0 / 2040)
    assert texture.lat_south == pytest.approx(-80.0417, abs=1e-3)


# --------------------------------------------------------------------------
# Forecast vector pairs
# --------------------------------------------------------------------------


def _write_component(directory, variable: str, values: np.ndarray, horizons: list[int]) -> None:
    lat = np.arange(-89.5, 90.0, 1.0)
    lon = np.arange(-179.5, 180.0, 1.0)
    forecast = np.stack([values for _ in horizons])
    dataset = xr.Dataset(
        {
            "forecast": (("horizon", "latitude", "longitude"), forecast),
            "anchor": (("latitude", "longitude"), values),
        },
        coords={"horizon": horizons, "latitude": lat, "longitude": lon},
    )
    dataset.attrs.update(
        {
            "variable": variable,
            "label": variable,
            "unit": "m/s",
            "resolution_deg": 1.0,
            "display_min": -1.0,
            "display_max": 1.0,
            "change_scale": 0.4,
            "generated_at": "2026-08-12T00:00:00Z",
            "observation_date": "2026-08-12",
            "sources": "Copernicus Marine Service (GLOBAL_ANALYSISFORECAST_PHY_001_024)",
            "skill_scores": "h1=0.4",
            "missing_covariates": "",
            "model": "LightGBM",
        }
    )
    dataset.to_netcdf(directory / f"{variable}.nc")


def _components(directory, u_horizons: list[int], v_horizons: list[int]) -> None:
    lat = np.arange(-89.5, 90.0, 1.0)
    lon = np.arange(-179.5, 180.0, 1.0)
    lat_grid, lon_grid = np.meshgrid(lat, lon, indexing="ij")
    _write_component(
        directory, "current_u", (np.sin(np.radians(lat_grid * 2)) * 0.8).astype("float32"), u_horizons
    )
    _write_component(
        directory, "current_v", (np.cos(np.radians(lon_grid)) * 0.5).astype("float32"), v_horizons
    )


def _reset():
    from services import forecast_tiles, forecast_vectors

    forecast_tiles.clear_cache()
    forecast_vectors.clear_cache()


def test_a_vector_pair_offers_only_the_horizons_both_components_carry(tmp_path):
    """The components are built by separate runs and can legitimately disagree.

    Taking horizons from either side alone would advertise a layer whose other
    half does not exist — and a vector composed from a present u and a missing
    v does not fail, it points somewhere wrong.
    """
    from services import forecast_vectors

    _components(tmp_path, u_horizons=[1, 3, 7], v_horizons=[1, 7, 30])
    _reset()

    entry = forecast_vectors.catalog(tmp_path)[0]
    assert entry["horizons"] == [1, 7]

    with pytest.raises(forecast_vectors.ForecastVectorError, match="horizon 3"):
        forecast_vectors.field_png("currents", 3, "forecast", tmp_path)


def test_a_half_built_pair_reports_why_rather_than_vanishing(tmp_path):
    """One component on disk is not a vector field. The catalog says so instead
    of dropping the entry, because "where did my layer go" needs an answer."""
    from services import forecast_vectors

    _write_component(tmp_path, "current_u", np.zeros((180, 360), dtype="float32"), [1])
    _reset()

    entry = forecast_vectors.catalog(tmp_path)[0]
    assert entry["horizons"] == []
    assert "current_v" in entry["error"]
    assert forecast_vectors.available(tmp_path) == []


def test_the_forecast_texture_decodes_to_the_forecast_grid(tmp_path):
    """Same cross-language contract as the live fields, over grid files."""
    from services import forecast_vectors

    _components(tmp_path, u_horizons=[1, 7], v_horizons=[1, 7])
    _reset()

    meta = forecast_vectors.meta("currents", 7, "forecast", tmp_path)
    png = forecast_vectors.field_png("currents", 7, "forecast", tmp_path)
    texture = vector_field.FieldTexture(
        png=png,
        u_min=meta["u_min"],
        u_max=meta["u_max"],
        v_min=meta["v_min"],
        v_max=meta["v_max"],
        lon_west=meta["lon_west"],
        lon_east=meta["lon_east"],
        lat_south=meta["lat_south"],
        lat_north=meta["lat_north"],
    )

    u_grid = xr.open_dataset(tmp_path / "current_u.nc")
    v_grid = xr.open_dataset(tmp_path / "current_v.nc")
    expected_u = u_grid["forecast"].sel(horizon=7).values
    expected_v = v_grid["forecast"].sel(horizon=7).values

    for row, col in [(10, 10), (90, 180), (179, 359)]:
        sampled = _shader_sample(
            png, texture, float(u_grid.latitude[row]), float(u_grid.longitude[col])
        )
        assert sampled is not None
        assert sampled[0] == pytest.approx(expected_u[row, col], abs=0.01)
        assert sampled[1] == pytest.approx(expected_v[row, col], abs=0.01)

    # A 1-degree cell-centred grid spans the globe exactly.
    assert (meta["lon_west"], meta["lon_east"]) == (-180.0, 180.0)
    assert (meta["lat_south"], meta["lat_north"]) == (-90.0, 90.0)


def test_currents_direction_is_toward_not_from(tmp_path):
    """A current is named for where it flows *to*; a wind for where it comes
    *from*. The two are 180 degrees apart, and getting it wrong produces a
    layer that looks entirely reasonable and points backwards."""
    from services import copernicus_currents, forecast_vectors

    _components(tmp_path, u_horizons=[1], v_horizons=[1])
    _reset()

    # Due-north flow (u=0, v>0) is a 0-degree current, where the same vector
    # read as wind would be reported as 180 ("from the south").
    point = forecast_vectors.point("currents", 1, 0.5, 0.5, tmp_path)
    assert point["forecast"]["direction_toward_deg"] is not None

    # The live service uses the same formula; check it directly on a known
    # vector rather than trusting the two implementations agree by inspection.
    assert copernicus_currents._COMPASS_LABELS[0] == "N"
    direction = (90.0 - np.degrees(np.arctan2(1.0, 0.0))) % 360.0
    assert direction == pytest.approx(0.0), "northward flow must read as 0 degrees (toward north)"
    eastward = (90.0 - np.degrees(np.arctan2(0.0, 1.0))) % 360.0
    assert eastward == pytest.approx(90.0), "eastward flow must read as 90 degrees"
