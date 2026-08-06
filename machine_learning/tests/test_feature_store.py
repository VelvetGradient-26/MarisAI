"""Feature store persistence: dtype compaction and columnar projection.

The projection tests assert on what Parquet was *asked* for, not just on the
frame that comes back. Selecting columns after ``pd.read_parquet`` returns an
identical frame while materializing the whole 2.6 GB store first, which is the
exact cost the parameter exists to avoid — a test that only compared frames
would pass against the useless implementation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from marine_ml import config, fusion


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FEATURE_STORE_DIR", tmp_path)
    frame = pd.DataFrame(
        {
            "latitude": np.linspace(8.0, 24.0, 50),
            "longitude": np.linspace(66.0, 78.0, 50),
            "chlor_a": np.random.default_rng(0).normal(1.0, 0.2, 50),
            "sst": np.random.default_rng(1).normal(28.0, 1.0, 50),
            "label": np.arange(50, dtype="int64"),
        }
    )
    fusion.write_feature_store(frame, "probe")
    return frame


def test_write_compacts_dtypes_but_keeps_coordinates_at_float64(store, tmp_path):
    schema = pq.read_schema(tmp_path / "probe.parquet")
    types = dict(zip(schema.names, schema.types))
    assert types["latitude"] == "double"
    assert types["longitude"] == "double"
    assert types["chlor_a"] == "float"
    assert types["sst"] == "float"


def test_read_returns_every_column_when_unprojected(store):
    frame = fusion.read_feature_store("probe")
    assert list(frame.columns) == list(store.columns)
    assert len(frame) == len(store)


def test_projection_is_pushed_into_parquet(store, monkeypatch):
    seen = {}
    original = pd.read_parquet

    def spy(path, *args, **kwargs):
        seen["columns"] = kwargs.get("columns")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(fusion.pd, "read_parquet", spy)
    frame = fusion.read_feature_store("probe", columns=["latitude", "chlor_a"])

    # The whole point: pyarrow never reads the other three columns.
    assert seen["columns"] == ["latitude", "chlor_a"]
    assert list(frame.columns) == ["latitude", "chlor_a"]


def test_projected_values_match_the_full_read(store):
    full = fusion.read_feature_store("probe")
    projected = fusion.read_feature_store("probe", columns=["sst"])
    pd.testing.assert_series_equal(projected["sst"], full["sst"])


def test_unknown_column_names_what_is_available(store):
    with pytest.raises(fusion.FusionError) as excinfo:
        fusion.read_feature_store("probe", columns=["sst", "no_such_column"])
    message = str(excinfo.value)
    assert "no_such_column" in message
    assert "feature_store_columns" in message


def test_columns_can_be_listed_without_reading_rows(store):
    assert fusion.feature_store_columns("probe") == list(store.columns)


def test_missing_store_raises_fusion_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FEATURE_STORE_DIR", tmp_path)
    with pytest.raises(fusion.FusionError):
        fusion.read_feature_store("absent")
    with pytest.raises(fusion.FusionError):
        fusion.feature_store_columns("absent")
