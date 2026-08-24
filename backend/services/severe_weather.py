"""IMD severe-weather alerts (heavy rain, heatwave, cold wave, thunderstorm
and lightning, ...), from IMD's own CAP 1.2 feed.

**This is the closest thing to a real, live, keyless IMD API found in the
2026-08-24 probe pass.** `mausam.imd.gov.in`'s own cyclone/weather pages are
HTML only, and RSMC New Delhi (the actual cyclone-bulletin authority) ships
PDFs. But IMD's National Weather Forecasting Centre also feeds a standard CAP
(Common Alerting Protocol) feed into a public aggregator —
`cap-sources.s3.amazonaws.com/in-imd-en/rss.xml`, an anonymous-read S3 bucket,
public domain — and that link was found embedded in `mausam.imd.gov.in`'s own
cyclone page. It needs no key and is a real OASIS CAP 1.2 document per alert:
event type, severity/urgency/certainty, onset/expiry, and a polygon or circle
for the affected area.

**It answers the "lightning" half of PS2's example query, not the "cyclone"
half.** Verified live 2026-08-24 by sampling the alerts issued during five
major cyclone landfalls spanning 2021-2024 (Biparjoy, Michaung, Tauktae,
Remal, Dana): every one of them appears here only as an `event` of "Heavy
Rain"/"Heavy rainfall"/"Extremely heavy" — never as "Cyclone". This feed is
IMD's *rainfall/heatwave/thunderstorm* nowcast channel, not a cyclone-track
bulletin. It does carry a genuine `event` of "Thunderstorm, hailstorm, gusty
winds and lightning" during pre-monsoon season (confirmed live, April 2023),
which is a real answer to "any lightning alerts in my area" — just not by
detecting a strike, by relaying IMD's own warning that a strike is likely.
`services/cyclones.py` (GDACS) is the cyclone-track half.

**The feed is a general severe-weather channel, not marine-specific.** It
covers all of India, land included — a hazard for context, not something
scoped to the coast the way the rest of this module's callers usually are.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from xml.etree import ElementTree

import httpx
from shapely.geometry import Point, Polygon

logger = logging.getLogger(__name__)

RSS_URL = "https://cap-sources.s3.amazonaws.com/in-imd-en/rss.xml"
_TIMEOUT = httpx.Timeout(20.0)
_CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}

# The aggregator's RSS has been observed carrying 7 items; fetched generously
# past that in case it ever carries more, since fetching a handful of small
# XML files costs nothing.
_MAX_ITEMS = 20


class SevereWeatherError(RuntimeError):
    """The IMD CAP feed could not be reached, or answered with nothing usable."""


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * 6371.0088 * asin(sqrt(a))


@dataclass
class _Alert:
    url: str
    event: str
    headline: str
    description: str
    severity: str
    urgency: str
    certainty: str
    onset: datetime | None
    expires: datetime | None
    area_desc: str
    polygons: list[Polygon] = field(default_factory=list)
    circles: list[tuple[float, float, float]] = field(default_factory=list)

    def is_active(self, now: datetime) -> bool:
        # No `expires` means this cannot be judged live or expired, and CAP
        # requires it on a real "Alert" message — treat a malformed one as
        # inactive rather than showing it forever.
        if self.expires is None:
            return False
        if self.onset is not None and now < self.onset:
            return False
        return now <= self.expires

    def covers(self, latitude: float, longitude: float) -> bool:
        point = Point(longitude, latitude)
        if any(polygon.covers(point) for polygon in self.polygons):
            return True
        return any(
            _haversine_km(latitude, longitude, lat, lon) <= radius_km
            for lat, lon, radius_km in self.circles
        )

    def summary(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "headline": self.headline,
            "description": self.description,
            "severity": self.severity,
            "urgency": self.urgency,
            "certainty": self.certainty,
            "onset": self.onset.isoformat() if self.onset else None,
            "expires": self.expires.isoformat() if self.expires else None,
            "area": self.area_desc,
            "url": self.url,
        }


@dataclass
class _Entry:
    alerts: list[_Alert]
    stored_at: datetime


_CACHE_TTL = timedelta(minutes=10)
_cache: _Entry | None = None
_lock = threading.Lock()


def _cached() -> list[_Alert] | None:
    with _lock:
        if _cache is None:
            return None
        if datetime.now(timezone.utc) - _cache.stored_at > _CACHE_TTL:
            return None
        return _cache.alerts


def _store(alerts: list[_Alert]) -> None:
    global _cache
    with _lock:
        _cache = _Entry(alerts=alerts, stored_at=datetime.now(timezone.utc))


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _parse_circle(raw: str) -> tuple[float, float, float] | None:
    """CAP circle syntax: "<lat>,<lon> <radius_km>"."""
    try:
        point, radius = raw.strip().split(" ")
        lat_str, lon_str = point.split(",")
        return float(lat_str), float(lon_str), float(radius)
    except (ValueError, AttributeError):
        return None


def _parse_polygon(raw: str) -> Polygon | None:
    """CAP polygon syntax: whitespace-separated "<lat>,<lon>" pairs, closed ring."""
    points: list[tuple[float, float]] = []
    for pair in raw.strip().split():
        try:
            lat_str, lon_str = pair.split(",")
            points.append((float(lon_str), float(lat_str)))
        except ValueError:
            return None
    if len(points) < 3:
        return None
    return Polygon(points)


def _parse_alert(xml_text: str, url: str) -> _Alert | None:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        logger.warning(f"IMD CAP alert at {url} was not valid XML")
        return None

    status = root.findtext("cap:status", default="", namespaces=_CAP_NS)
    msg_type = root.findtext("cap:msgType", default="", namespaces=_CAP_NS)
    # "Test"/"Exercise"/"System" are CAP's own non-operational statuses, and a
    # "Cancel" message's own validity window says nothing about whether the
    # alert it cancels is still live — excluding both here is simpler and
    # safer than trying to resolve a cancellation against the alert it refers
    # to via `cap:references`.
    if status.lower() != "actual" or msg_type.lower() == "cancel":
        return None

    info = root.find("cap:info", _CAP_NS)
    if info is None:
        return None

    def text(tag: str) -> str:
        return info.findtext(f"cap:{tag}", default="", namespaces=_CAP_NS) or ""

    area_descs: list[str] = []
    polygons: list[Polygon] = []
    circles: list[tuple[float, float, float]] = []
    for area in info.findall("cap:area", _CAP_NS):
        desc = area.findtext("cap:areaDesc", default="", namespaces=_CAP_NS)
        if desc:
            area_descs.append(desc)
        for poly_text in area.findall("cap:polygon", _CAP_NS):
            if poly_text.text:
                polygon = _parse_polygon(poly_text.text)
                if polygon is not None:
                    polygons.append(polygon)
        for circle_text in area.findall("cap:circle", _CAP_NS):
            if circle_text.text:
                circle = _parse_circle(circle_text.text)
                if circle is not None:
                    circles.append(circle)

    return _Alert(
        url=url,
        event=text("event"),
        headline=text("headline"),
        description=text("description"),
        severity=text("severity"),
        urgency=text("urgency"),
        certainty=text("certainty"),
        onset=_parse_datetime(text("onset") or text("effective")),
        expires=_parse_datetime(text("expires")),
        area_desc="; ".join(area_descs),
        polygons=polygons,
        circles=circles,
    )


async def _get_text(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url)
    response.raise_for_status()
    return response.text


async def _fetch_alerts() -> list[_Alert]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            rss_text = await _get_text(client, RSS_URL)
            try:
                rss = ElementTree.fromstring(rss_text)
            except ElementTree.ParseError as exc:
                raise SevereWeatherError("The IMD alert feed's RSS index was not valid XML") from exc

            links = [
                item_link.text
                for item_link in rss.findall(".//item/link")
                if item_link.text
            ][:_MAX_ITEMS]

            texts = await asyncio.gather(
                *(_get_text(client, link) for link in links), return_exceptions=True
            )
    except httpx.HTTPStatusError as exc:
        raise SevereWeatherError(
            f"The IMD alert feed returned {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning(f"IMD CAP feed request failed: {exc}")
        raise SevereWeatherError(f"The IMD alert feed could not be reached: {exc}") from exc

    alerts: list[_Alert] = []
    for link, text_or_exc in zip(links, texts):
        if isinstance(text_or_exc, BaseException):
            logger.warning(f"IMD CAP alert fetch failed for {link}: {text_or_exc}")
            continue
        parsed = _parse_alert(text_or_exc, link)
        if parsed is not None:
            alerts.append(parsed)
    return alerts


async def _active_alerts() -> list[_Alert]:
    cached = _cached()
    if cached is not None:
        return cached
    alerts = await _fetch_alerts()
    _store(alerts)
    return alerts


async def get_active_alerts() -> dict[str, Any]:
    """Every IMD severe-weather alert currently within its validity window.

    Nationwide — India, land included — since IMD does not scope this feed to
    the coast.
    """
    alerts = await _active_alerts()
    now = datetime.now(timezone.utc)
    active = [alert.summary() for alert in alerts if alert.is_active(now)]
    return {
        "alerts": active,
        "count": len(active),
        "source": "India Meteorological Department (NWFC), via its public CAP feed",
        "note": (
            "General severe-weather warnings (heavy rain, heatwave, cold wave, "
            "thunderstorm/lightning, ...), not a cyclone-track bulletin — see "
            "the cyclone tool for that. Coverage is all of India, not scoped "
            "to the coast."
        ),
    }


async def check_point(latitude: float, longitude: float) -> dict[str, Any]:
    """IMD severe-weather alerts whose warned area covers one point."""
    alerts = await _active_alerts()
    now = datetime.now(timezone.utc)
    covering = [
        alert.summary()
        for alert in alerts
        if alert.is_active(now) and alert.covers(latitude, longitude)
    ]
    total_active = sum(1 for alert in alerts if alert.is_active(now))
    return {
        "alerts": covering,
        "count": len(covering),
        "active_nationwide": total_active,
        "source": "India Meteorological Department (NWFC), via its public CAP feed",
        "note": (
            "General severe-weather warnings, not a cyclone-track bulletin. "
            "An empty list means no currently active alert's warned area "
            "covers this point — it does not mean nowhere in India has one; "
            "see active_nationwide."
        ),
    }
