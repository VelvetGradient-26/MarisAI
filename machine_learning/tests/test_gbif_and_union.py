"""GBIF occurrence fetching and the OBIS+GBIF presence union.

No network is touched: `gbif.requests.get` is monkeypatched directly, the
same convention `test_global_sources.py` uses for OBIS's `requests.get`.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fish_habitat_prediction.src import labels
from marine_ml import config
from marine_ml.sources import gbif


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.ok = True
        self.status_code = 200
        self.text = ""

    def json(self) -> dict:
        return self._payload


def _gbif_record(
    lat: float,
    lon: float,
    *,
    scientific_name: str = "Thunnus albacares",
    event_date: str = "2010-05-01",
    occurrence_id: str | None = "occ-1",
    dataset_key: str = "ds-1",
    catalog_number: str = "cat-1",
) -> dict:
    return {
        "decimalLatitude": lat,
        "decimalLongitude": lon,
        "eventDate": event_date,
        "scientificName": scientific_name,
        "species": scientific_name,
        "basisOfRecord": "HUMAN_OBSERVATION",
        "datasetKey": dataset_key,
        "institutionCode": "TEST",
        "individualCount": 1,
        "occurrenceID": occurrence_id,
        "catalogNumber": catalog_number,
    }


class TestGbifPaging:
    @pytest.fixture(autouse=True)
    def _isolated_cache(self, monkeypatch, tmp_path):
        """Every test gets its own cache directory — `fetch_occurrences`
        caches to disk keyed only on species/region/date, so two tests
        calling it with the same (default) arguments would otherwise read
        each other's cached parquet instead of exercising the mocked
        `requests.get` at all."""
        monkeypatch.setattr(config, "GBIF_RAW_DIR", tmp_path)

    def test_a_single_page_is_returned_whole(self, monkeypatch):
        records = [_gbif_record(10.0 + i * 0.1, 65.0) for i in range(5)]
        monkeypatch.setattr(
            gbif.requests, "get",
            lambda *a, **k: _FakeResponse({"results": records, "endOfRecords": True}),
        )

        frame = gbif.fetch_occurrences("Thunnus albacares")

        assert len(frame) == 5
        assert set(frame["scientific_name"]) == {"Thunnus albacares"}

    def test_pages_are_followed_until_end_of_records(self, monkeypatch):
        page1 = [_gbif_record(10.0, 65.0, occurrence_id=f"occ-{i}") for i in range(300)]
        page2 = [_gbif_record(11.0, 66.0, occurrence_id=f"occ-{300+i}") for i in range(10)]
        calls = []

        def fake_get(url, params=None, timeout=None):
            calls.append(params["offset"])
            if params["offset"] == 0:
                return _FakeResponse({"results": page1, "endOfRecords": False})
            return _FakeResponse({"results": page2, "endOfRecords": True})

        monkeypatch.setattr(gbif.requests, "get", fake_get)

        frame = gbif.fetch_occurrences("Thunnus albacares")

        assert len(frame) == 310
        assert calls == [0, 300]

    def test_exceeding_the_offset_cap_raises_rather_than_truncating(self, monkeypatch):
        page = [_gbif_record(10.0, 65.0, occurrence_id=f"occ-{i}") for i in range(300)]
        monkeypatch.setattr(
            gbif.requests, "get",
            lambda *a, **k: _FakeResponse({"results": page, "endOfRecords": False}),
        )

        with pytest.raises(gbif.GbifError, match="offset cap"):
            list(gbif._paged_request({"scientificName": "Thunnus albacares"}))

    def test_a_request_failure_raises_gbif_error(self, monkeypatch):
        import requests as requests_module

        def fake_get(*a, **k):
            raise requests_module.exceptions.ConnectionError("boom")

        monkeypatch.setattr(gbif.requests, "get", fake_get)

        with pytest.raises(gbif.GbifError):
            gbif.fetch_occurrences("Thunnus albacares")

    def test_records_with_no_coordinate_are_dropped(self, monkeypatch):
        with_coord = _gbif_record(10.0, 65.0, occurrence_id="a")
        without_coord = _gbif_record(10.0, 65.0, occurrence_id="b")
        without_coord["decimalLatitude"] = None
        without_coord["decimalLongitude"] = None
        monkeypatch.setattr(
            gbif.requests, "get",
            lambda *a, **k: _FakeResponse({"results": [with_coord, without_coord], "endOfRecords": True}),
        )

        frame = gbif.fetch_occurrences("Thunnus albacares")

        assert len(frame) == 1


def _presence_frame(rows: list[dict]) -> pd.DataFrame:
    base_columns = [
        "latitude", "longitude", "event_date", "scientific_name", "species",
        "basis_of_record", "dataset_id", "institution_code", "individual_count",
        "occurrence_id", "catalog_number", "observation_date", "species_key",
    ]
    frame = pd.DataFrame(rows)
    for column in base_columns:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame["observation_date"] = pd.to_datetime(frame["observation_date"])
    return frame


class TestUnionPresences:
    def test_is_a_union_not_a_switch(self):
        """Neither source may be dropped wholesale — a species where OBIS
        dominates and one where GBIF dominates must both survive."""
        obis = _presence_frame(
            [{"latitude": 10.0, "longitude": 65.0, "observation_date": "2010-01-01",
              "occurrence_id": "obis-only-1", "scientific_name": "Rastrelliger kanagurta"}]
        )
        gbif_frame = _presence_frame(
            [{"latitude": 11.0, "longitude": 66.0, "observation_date": "2011-01-01",
              "occurrence_id": "gbif-only-1", "scientific_name": "Thunnus albacares"}]
        )

        result = labels.union_presences(obis, gbif_frame)

        assert set(result["occurrence_id"]) == {"obis-only-1", "gbif-only-1"}

    def test_a_shared_occurrence_id_is_deduplicated(self):
        obis = _presence_frame(
            [{"latitude": 10.0, "longitude": 65.0, "observation_date": "2010-01-01", "occurrence_id": "shared-1"}]
        )
        gbif_frame = _presence_frame(
            [{"latitude": 10.0, "longitude": 65.0, "observation_date": "2010-01-01", "occurrence_id": "shared-1"}]
        )

        result = labels.union_presences(obis, gbif_frame)

        assert len(result) == 1

    def test_falls_back_to_dataset_catalog_lat_lon_date_without_an_occurrence_id(self):
        obis = _presence_frame(
            [{"latitude": 10.0, "longitude": 65.0, "observation_date": "2010-01-01",
              "occurrence_id": None, "dataset_id": "ds-1", "catalog_number": "cat-1"}]
        )
        gbif_frame = _presence_frame(
            [{"latitude": 10.0, "longitude": 65.0, "observation_date": "2010-01-01",
              "occurrence_id": None, "dataset_id": "ds-1", "catalog_number": "cat-1"}]
        )

        result = labels.union_presences(obis, gbif_frame)

        assert len(result) == 1

    def test_the_fallback_key_does_not_collapse_genuinely_distinct_records(self):
        obis = _presence_frame(
            [{"latitude": 10.0, "longitude": 65.0, "observation_date": "2010-01-01",
              "occurrence_id": None, "dataset_id": "ds-1", "catalog_number": "cat-1"}]
        )
        gbif_frame = _presence_frame(
            [{"latitude": 12.0, "longitude": 68.0, "observation_date": "2012-06-01",
              "occurrence_id": None, "dataset_id": "ds-2", "catalog_number": "cat-2"}]
        )

        result = labels.union_presences(obis, gbif_frame)

        assert len(result) == 2

    def test_both_frames_empty_raises(self):
        empty = _presence_frame([])
        with pytest.raises(labels.LabelError):
            labels.union_presences(empty, empty)

    def test_one_frame_empty_still_returns_the_other(self):
        obis = _presence_frame(
            [{"latitude": 10.0, "longitude": 65.0, "observation_date": "2010-01-01", "occurrence_id": "obis-1"}]
        )
        empty = _presence_frame([])

        result = labels.union_presences(obis, empty)

        assert len(result) == 1
