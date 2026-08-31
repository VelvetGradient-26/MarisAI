"""services/predictions.py — habitat suitability's SHAP driver wiring.

No existing test file touched `services/predictions.py` before this (it has
no unit coverage at all — HAB's own equivalent `_hab_drivers` wiring was
verified live against a real export, per DONE.md's "SHAP explainability,
Phase 1" entry, not by a fixture test). This adds coverage for the new
`_habitat_drivers`/`habitat_point` logic specifically, using small synthetic
NetCDF fixtures — real xarray objects, not mocks, so a real dims/coords
mismatch would fail here rather than only in a live run.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import xarray as xr

from services import predictions


@pytest.fixture(autouse=True)
def _clear_caches():
    """`_load_grid`/`_load_manifest` are `lru_cache`d for the process
    lifetime — real per-request behaviour, but poison for tests unless
    cleared before and after each one."""
    predictions._load_grid.cache_clear()
    predictions._load_manifest.cache_clear()
    yield
    predictions._load_grid.cache_clear()
    predictions._load_manifest.cache_clear()


@pytest.fixture
def export_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(predictions.settings, "PREDICTIONS_DIR", str(tmp_path))
    return tmp_path


def _write_habitat_grid(export_dir, species=("yellowfin_tuna",), months=(6,), suitability=0.71):
    latitudes = np.array([10.0, 10.25])
    longitudes = np.array([70.0, 70.25])
    grid = np.full((len(species), len(months), len(latitudes), len(longitudes)), np.nan, dtype="float32")
    grid[0, 0, 0, 0] = suitability
    xr.Dataset(
        {"suitability": (("species", "month", "latitude", "longitude"), grid)},
        coords={"species": list(species), "month": list(months), "latitude": latitudes, "longitude": longitudes},
    ).to_netcdf(export_dir / predictions.HABITAT_GRID)


def _write_habitat_shap_grid(export_dir, species=("yellowfin_tuna",), months=(6,), top_k=2):
    latitudes = np.array([10.0, 10.25])
    longitudes = np.array([70.0, 70.25])
    index_grid = np.full((len(species), len(months), len(latitudes), len(longitudes), top_k), -1, dtype="int16")
    contribution_grid = np.full(
        (len(species), len(months), len(latitudes), len(longitudes), top_k), np.nan, dtype="float32"
    )
    index_grid[0, 0, 0, 0] = [1, 0]
    contribution_grid[0, 0, 0, 0] = [0.32, -0.11]
    xr.Dataset(
        {
            "driver_index": (("species", "month", "latitude", "longitude", "top_k"), index_grid),
            "driver_contribution": (("species", "month", "latitude", "longitude", "top_k"), contribution_grid),
        },
        coords={
            "species": list(species), "month": list(months),
            "latitude": latitudes, "longitude": longitudes, "top_k": np.arange(top_k),
        },
    ).to_netcdf(export_dir / predictions.HABITAT_SHAP_GRID)


def _write_manifest(export_dir, feature_names=None):
    manifest = {
        "products": {
            "habitat": {
                "region": {"south": 0.0, "north": 30.0, "west": 55.0, "east": 95.0},
                **({"shap": {"feature_names": feature_names}} if feature_names else {}),
            }
        }
    }
    (export_dir / predictions.MANIFEST).write_text(json.dumps(manifest))


def test_drivers_is_none_when_the_shap_companion_file_is_missing(export_dir):
    _write_habitat_grid(export_dir)
    _write_manifest(export_dir)

    result = predictions.habitat_point("yellowfin_tuna", 6, 10.0, 70.0)

    assert result["suitability"] == pytest.approx(0.71)
    assert result["drivers"] is None


def test_drivers_are_returned_when_the_shap_companion_and_manifest_agree(export_dir):
    _write_habitat_grid(export_dir)
    _write_habitat_shap_grid(export_dir)
    _write_manifest(export_dir, feature_names=["thetao", "chl", "depth"])

    result = predictions.habitat_point("yellowfin_tuna", 6, 10.0, 70.0)

    assert result["drivers"] == [
        {
            "feature": "chl", "label": "Chl", "value": None,
            "contribution": pytest.approx(0.32), "direction": "increases",
        },
        {
            "feature": "thetao", "label": "Thetao", "value": None,
            "contribution": pytest.approx(-0.11), "direction": "decreases",
        },
    ]


def test_drivers_is_none_when_the_manifest_has_no_feature_names(export_dir):
    """Same degrade-to-None shape HAB's own wiring uses: an index into a
    feature list that does not exist is worse than useless."""
    _write_habitat_grid(export_dir)
    _write_habitat_shap_grid(export_dir)
    _write_manifest(export_dir)  # no "shap" key at all

    result = predictions.habitat_point("yellowfin_tuna", 6, 10.0, 70.0)

    assert result["drivers"] is None


def test_drivers_is_none_when_suitability_itself_has_no_value(export_dir):
    """`habitat_point` must not even look at the SHAP grid for a cell where
    `suitability` is NaN (land, or outside the model's domain) — matching
    `hab_point`'s identical `if value is not None else None` guard."""
    _write_habitat_grid(export_dir)
    _write_habitat_shap_grid(export_dir)
    _write_manifest(export_dir, feature_names=["thetao", "chl", "depth"])

    # (10.25, 70.25) was never written a real value above -- stays NaN.
    result = predictions.habitat_point("yellowfin_tuna", 6, 10.25, 70.25)

    assert result["suitability"] is None
    assert result["drivers"] is None


def test_a_negative_driver_index_is_skipped_not_rendered_as_a_feature(export_dir):
    """`-1` is the fill value for "no k-th driver at this cell" (fewer than
    top_k features had a nonzero contribution) — it must never resolve to
    `feature_names[-1]`, the *last* real feature, silently."""
    _write_habitat_grid(export_dir)
    _write_habitat_shap_grid(export_dir, top_k=2)
    _write_manifest(export_dir, feature_names=["thetao", "chl", "depth"])

    # Overwrite just the second driver slot with the -1 fill value.
    dataset = xr.open_dataset(export_dir / predictions.HABITAT_SHAP_GRID).load()
    dataset["driver_index"].values[0, 0, 0, 0, 1] = -1
    dataset.close()
    dataset.to_netcdf(export_dir / predictions.HABITAT_SHAP_GRID)
    predictions._load_grid.cache_clear()

    result = predictions.habitat_point("yellowfin_tuna", 6, 10.0, 70.0)

    assert len(result["drivers"]) == 1
    assert result["drivers"][0]["feature"] == "chl"
