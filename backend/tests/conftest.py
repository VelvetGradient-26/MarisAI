"""Suite-wide fixtures."""

from __future__ import annotations

import pytest

from app.core import disk_cache


@pytest.fixture(autouse=True)
def _never_touch_the_real_disk_cache(tmp_path, monkeypatch):
    """Any test that drives a Copernicus refresh would otherwise write into
    backend/downloads/copernicus-cache on the developer's machine — and a later
    backend restart would serve that fake grid as if it were real data."""
    monkeypatch.setattr(disk_cache, "CACHE_DIR", tmp_path / "copernicus-cache")
