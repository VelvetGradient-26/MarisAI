"""The IMD CAP feed: RSS index -> per-alert CAP 1.2 XML -> active/point checks.

No network is touched: `severe_weather._get_text` is monkeypatched to serve
fixed RSS/CAP XML strings, the same convention `test_edna.py` uses for OBIS.
Alert onset/expiry are offsets from the real wall clock at test time rather
than a frozen instant — simpler, and this module never needs to know "now"
to the second.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services import severe_weather


def _rss(links: list[str]) -> str:
    items = "".join(f"<item><link>{link}</link></item>" for link in links)
    return f"<rss><channel>{items}</channel></rss>"


def _cap(
    *,
    event: str = "Heavy rainfall",
    status: str = "Actual",
    msg_type: str = "Alert",
    onset_hours: float = -1,
    expires_hours: float | None = 23,
    area_desc: str = "Odisha",
    polygon: str | None = None,
    circle: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    onset = now + timedelta(hours=onset_hours)
    area_geo = ""
    if polygon:
        area_geo += f"<cap:polygon>{polygon}</cap:polygon>"
    if circle:
        area_geo += f"<cap:circle>{circle}</cap:circle>"
    expires_tag = ""
    if expires_hours is not None:
        expires = now + timedelta(hours=expires_hours)
        expires_tag = f"<cap:expires>{expires.isoformat()}</cap:expires>"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cap:alert xmlns:cap="urn:oasis:names:tc:emergency:cap:1.2">
  <cap:status>{status}</cap:status>
  <cap:msgType>{msg_type}</cap:msgType>
  <cap:info>
    <cap:event>{event}</cap:event>
    <cap:headline>{event}</cap:headline>
    <cap:description>Test description</cap:description>
    <cap:severity>Severe</cap:severity>
    <cap:urgency>Expected</cap:urgency>
    <cap:certainty>Likely</cap:certainty>
    <cap:onset>{onset.isoformat()}</cap:onset>
    {expires_tag}
    <cap:area>
      <cap:areaDesc>{area_desc}</cap:areaDesc>
      {area_geo}
    </cap:area>
  </cap:info>
</cap:alert>"""


def _install(monkeypatch, rss_links: list[str], caps: dict[str, str]):
    severe_weather._cache = None

    async def fake_get_text(client, url):
        if url == severe_weather.RSS_URL:
            return _rss(rss_links)
        return caps[url]

    monkeypatch.setattr(severe_weather, "_get_text", fake_get_text)


@pytest.mark.asyncio
async def test_an_active_alert_is_reported(monkeypatch):
    _install(monkeypatch, ["https://x/a.xml"], {"https://x/a.xml": _cap()})

    payload = await severe_weather.get_active_alerts()

    assert payload["count"] == 1
    assert payload["alerts"][0]["event"] == "Heavy rainfall"


@pytest.mark.asyncio
async def test_an_expired_alert_is_excluded(monkeypatch):
    _install(
        monkeypatch,
        ["https://x/a.xml"],
        {"https://x/a.xml": _cap(onset_hours=-2, expires_hours=-1)},
    )

    payload = await severe_weather.get_active_alerts()

    assert payload["count"] == 0


@pytest.mark.asyncio
async def test_a_not_yet_started_alert_is_excluded(monkeypatch):
    _install(
        monkeypatch,
        ["https://x/a.xml"],
        {"https://x/a.xml": _cap(onset_hours=1, expires_hours=2)},
    )

    payload = await severe_weather.get_active_alerts()

    assert payload["count"] == 0


@pytest.mark.asyncio
async def test_an_alert_with_no_expires_is_excluded(monkeypatch):
    """CAP requires `expires` on a real alert; a malformed one without it must
    not be shown forever."""
    _install(
        monkeypatch,
        ["https://x/a.xml"],
        {"https://x/a.xml": _cap(expires_hours=None)},
    )

    payload = await severe_weather.get_active_alerts()

    assert payload["count"] == 0


@pytest.mark.asyncio
async def test_a_cancel_message_is_excluded(monkeypatch):
    _install(
        monkeypatch,
        ["https://x/a.xml"],
        {"https://x/a.xml": _cap(msg_type="Cancel")},
    )

    payload = await severe_weather.get_active_alerts()

    assert payload["count"] == 0


@pytest.mark.asyncio
async def test_a_test_status_message_is_excluded(monkeypatch):
    _install(
        monkeypatch,
        ["https://x/a.xml"],
        {"https://x/a.xml": _cap(status="Test")},
    )

    payload = await severe_weather.get_active_alerts()

    assert payload["count"] == 0


@pytest.mark.asyncio
async def test_a_point_inside_the_polygon_is_covered(monkeypatch):
    # A square roughly around 20N,85E.
    polygon = "19,84 19,86 21,86 21,84 19,84"
    _install(
        monkeypatch,
        ["https://x/a.xml"],
        {"https://x/a.xml": _cap(polygon=polygon)},
    )

    inside = await severe_weather.check_point(20.0, 85.0)
    outside = await severe_weather.check_point(0.0, 0.0)

    assert inside["count"] == 1
    assert outside["count"] == 0
    assert outside["active_nationwide"] == 1


@pytest.mark.asyncio
async def test_a_point_inside_the_circle_is_covered(monkeypatch):
    _install(
        monkeypatch,
        ["https://x/a.xml"],
        {"https://x/a.xml": _cap(circle="27.645,94.438 200")},
    )

    inside = await severe_weather.check_point(27.7, 94.5)
    outside = await severe_weather.check_point(0.0, 0.0)

    assert inside["count"] == 1
    assert outside["count"] == 0


@pytest.mark.asyncio
async def test_the_alert_list_is_cached(monkeypatch):
    calls = 0
    severe_weather._cache = None

    async def fake_get_text(client, url):
        nonlocal calls
        if url == severe_weather.RSS_URL:
            calls += 1
            return _rss(["https://x/a.xml"])
        return _cap()

    monkeypatch.setattr(severe_weather, "_get_text", fake_get_text)

    await severe_weather.get_active_alerts()
    await severe_weather.get_active_alerts()

    assert calls == 1


@pytest.mark.asyncio
async def test_a_fetch_failure_raises_severe_weather_error(monkeypatch):
    import httpx

    severe_weather._cache = None

    async def fake_get_text(client, url):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(severe_weather, "_get_text", fake_get_text)

    with pytest.raises(severe_weather.SevereWeatherError):
        await severe_weather.get_active_alerts()
