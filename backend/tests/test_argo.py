"""services/argo.py: live ARGO float profiles via Argovis.

No network is touched: `argo._get` is monkeypatched directly, the same
convention `test_cyclones.py` uses for GDACS — `_get` takes `(client, params)`
and this fakes the two distinct calls (`nearest_profile` makes a metadata
search, then a detail fetch by `_id`) by branching on whether `params`
carries an `id`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services import argo


def _candidate(profile_id: str, lat: float, lon: float) -> dict:
    return {"_id": profile_id, "geolocation": {"type": "Point", "coordinates": [lon, lat]}}


def _detail(
    profile_id: str,
    lat: float,
    lon: float,
    *,
    pressures: list[float],
    temperatures: list[float | None],
    salinities: list[float | None],
    stamp: str = "2026-08-09T13:26:00.000Z",
) -> dict:
    return {
        "_id": profile_id,
        "geolocation": {"type": "Point", "coordinates": [lon, lat]},
        "timestamp": stamp,
        "data": [temperatures, salinities, pressures],
        "data_info": [["temperature", "salinity", "pressure"], ["units"], []],
    }


def _install(monkeypatch, *, search_result: list[dict], detail_by_id: dict[str, dict]):
    async def fake_get(client, params):
        if "id" in params:
            return [detail_by_id[params["id"]]]
        return search_result

    monkeypatch.setattr(argo, "_get", fake_get)


class TestNearestProfile:
    @pytest.mark.asyncio
    async def test_no_float_nearby_is_a_real_answer_not_an_error(self, monkeypatch):
        _install(monkeypatch, search_result=[], detail_by_id={})

        result = await argo.nearest_profile(15.0, 65.0)

        assert result["available"] is False
        assert "no ARGO float profiled" in result["unavailable_reason"]

    @pytest.mark.asyncio
    async def test_finds_the_nearest_of_several_candidates(self, monkeypatch):
        near = _candidate("111_1", 15.1, 65.1)  # ~15 km from the query point
        far = _candidate("222_1", 25.0, 75.0)  # ~1400 km away
        _install(
            monkeypatch,
            search_result=[far, near],
            detail_by_id={
                "111_1": _detail("111_1", 15.1, 65.1, pressures=[2.0], temperatures=[28.0], salinities=[35.0]),
                "222_1": _detail("222_1", 25.0, 75.0, pressures=[2.0], temperatures=[20.0], salinities=[34.0]),
            },
        )

        result = await argo.nearest_profile(15.0, 65.0)

        assert result["available"] is True
        assert result["profile"]["profile_id"] == "111_1"
        assert result["profile"]["distance_km"] < 20

    @pytest.mark.asyncio
    async def test_levels_are_sorted_by_pressure(self, monkeypatch):
        _install(
            monkeypatch,
            search_result=[_candidate("1_1", 15.0, 65.0)],
            detail_by_id={
                "1_1": _detail(
                    "1_1", 15.0, 65.0,
                    pressures=[50.0, 2.0, 20.0],
                    temperatures=[20.0, 28.0, 25.0],
                    salinities=[35.0, 36.0, 35.5],
                )
            },
        )

        result = await argo.nearest_profile(15.0, 65.0)

        levels = result["profile"]["levels"]
        assert [level["pressure_dbar"] for level in levels] == [2.0, 20.0, 50.0]

    @pytest.mark.asyncio
    async def test_a_level_missing_temperature_is_kept_not_dropped(self, monkeypatch):
        """Only a missing *pressure* drops a level — this is a real reading
        with a real depth and a sensor gap at that depth, not a hole in the
        profile's own vertical axis."""
        _install(
            monkeypatch,
            search_result=[_candidate("1_1", 15.0, 65.0)],
            detail_by_id={
                "1_1": _detail(
                    "1_1", 15.0, 65.0,
                    pressures=[0.5, 2.0],
                    temperatures=[None, 28.0],
                    salinities=[None, 35.0],
                )
            },
        )

        result = await argo.nearest_profile(15.0, 65.0)

        levels = result["profile"]["levels"]
        assert len(levels) == 2
        assert levels[0]["temperature_c"] is None

    def test_shallowest_skips_a_level_with_no_temperature(self):
        detail = _detail(
            "1_1", 15.0, 65.0, pressures=[0.5, 2.0], temperatures=[None, 28.0], salinities=[None, 35.0]
        )
        profile = argo._parse_profile(detail, distance_km=1.0)

        shallowest = profile.shallowest()
        assert shallowest is not None
        assert shallowest.pressure_dbar == 2.0

    @pytest.mark.asyncio
    async def test_a_fetch_failure_raises_argo_error(self, monkeypatch):
        import httpx

        async def fake_get(client, params):
            raise httpx.ConnectError("boom")

        monkeypatch.setattr(argo, "_get", fake_get)

        with pytest.raises(argo.ArgoError):
            await argo.nearest_profile(15.0, 65.0)


class TestBboxPolygon:
    def test_widens_in_longitude_at_high_latitude(self):
        """A plain degree box narrows in longitude toward the poles; the
        margin must widen to compensate or a high-latitude query silently
        under-covers its own stated radius."""
        equator = argo._bbox_polygon(0.0, 0.0, 300.0)
        high_lat = argo._bbox_polygon(70.0, 0.0, 300.0)

        equator_lon_span = equator[1][0] - equator[0][0]
        high_lat_lon_span = high_lat[1][0] - high_lat[0][0]
        assert high_lat_lon_span > equator_lon_span

    def test_is_closed(self):
        polygon = argo._bbox_polygon(15.0, 65.0, 300.0)
        assert polygon[0] == polygon[-1]
