"""NASA GIBS — satellite product availability and freshness.

The dashboard's "recent satellite products" table needs to say which NASA
imagery is current, at what resolution, and how far behind real time it is.
GIBS publishes exactly that in its WMTS capabilities document: every layer
carries a `<Default>` date (the newest timestep it can serve) alongside its
tile-matrix set, which encodes native resolution.

The document is ~5MB, so it is parsed once on a schedule and the curated
subset below is kept in memory. Parsing it per request would put a multi-
megabyte XML parse behind a five-minute dashboard poll.

No credentials — GIBS is open. A layer that disappears upstream is skipped
rather than faulting the whole refresh.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from xml.etree import ElementTree

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

CAPABILITIES_URL = "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/1.0.0/WMTSCapabilities.xml"

SOURCE_LABEL = "NASA Global Imagery Browse Services (GIBS)"
SOURCE_URL = "https://nasa-gibs.github.io/gibs-api-docs/"

_TIMEOUT = httpx.Timeout(120.0)

# The capabilities document changes when a layer is added or retired, not
# when new imagery lands, so this only needs to be occasional.
REFRESH_INTERVAL_HOURS = 6

_WMTS_NS = "{http://www.opengis.net/wmts/1.0}"
_OWS_NS = "{http://www.opengis.net/ows/1.1}"

# GIBS carries ~1000 layers; these are the ocean-relevant ones, grouped so the
# table can say which platform produced each. Identifiers were taken from the
# live capabilities document — any that vanish upstream are skipped silently.
_TRACKED: tuple[dict[str, str], ...] = (
    {
        "id": "GHRSST_L4_MUR_Sea_Surface_Temperature",
        "satellite": "Multi-sensor (MUR)",
        "product": "Sea Surface Temperature",
    },
    {
        "id": "GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies",
        "satellite": "Multi-sensor (MUR)",
        "product": "SST Anomaly",
    },
    {
        "id": "GHRSST_L4_AVHRR-OI_Sea_Surface_Temperature",
        "satellite": "AVHRR-OI",
        "product": "Sea Surface Temperature",
    },
    {
        "id": "OCI_PACE_Chlorophyll_a",
        "satellite": "PACE / OCI",
        "product": "Chlorophyll-a",
    },
    {
        "id": "VIIRS_NOAA21_Chlorophyll_a",
        "satellite": "NOAA-21 / VIIRS",
        "product": "Chlorophyll-a",
    },
    {
        "id": "MODIS_Aqua_L2_Chlorophyll_A",
        "satellite": "Aqua / MODIS",
        "product": "Chlorophyll-a",
    },
    {
        "id": "MODIS_Aqua_CorrectedReflectance_TrueColor",
        "satellite": "Aqua / MODIS",
        "product": "True Colour Imagery",
    },
    {
        "id": "VIIRS_SNPP_CorrectedReflectance_TrueColor",
        "satellite": "Suomi NPP / VIIRS",
        "product": "True Colour Imagery",
    },
    {
        "id": "GHRSST_L4_MUR_Sea_Ice_Concentration",
        "satellite": "Multi-sensor (MUR)",
        "product": "Sea Ice Concentration",
    },
    {
        "id": "AMSRU2_Sea_Ice_Concentration_12km",
        "satellite": "GCOM-W1 / AMSR2",
        "product": "Sea Ice Concentration",
    },
    {
        "id": "OSCAR_Sea_Surface_Currents_Zonal",
        "satellite": "OSCAR (multi-mission)",
        "product": "Surface Currents (zonal)",
    },
)

# TileMatrixSet identifiers encode ground resolution at the equator. Mapping
# them keeps the table's "resolution" column honest rather than guessed.
_RESOLUTION_LABELS = {
    "250m": "250 m",
    "500m": "500 m",
    "1km": "1 km",
    "2km": "2 km",
    "4km": "4 km",
    "16km": "16 km",
    "31.25m": "31.25 m",
}


class GibsError(RuntimeError):
    """GIBS capabilities unavailable or unparseable."""


@dataclass(frozen=True)
class SatelliteProduct:
    layer_id: str
    satellite: str
    product: str
    title: str
    latest_date: date | None
    resolution: str | None
    format: str | None
    period: str | None

    def age_days(self, today: date) -> int | None:
        if self.latest_date is None:
            return None
        return (today - self.latest_date).days

    def to_dict(self, today: date) -> dict[str, Any]:
        age = self.age_days(today)
        return {
            "layer_id": self.layer_id,
            "satellite": self.satellite,
            "product": self.product,
            "title": self.title,
            "latest_date": self.latest_date.isoformat() if self.latest_date else None,
            "resolution": self.resolution,
            "format": self.format,
            "cadence": self.period,
            "age_days": age,
            "status": _status_for(age),
        }


def _status_for(age_days: int | None) -> str:
    """Freshness relative to what these products normally achieve.

    NASA's L3/L4 ocean products publish with a one-to-two day lag as a matter
    of course, so "current" has to allow for that or every row reads as late.
    """
    if age_days is None:
        return "unknown"
    if age_days <= 2:
        return "current"
    if age_days <= 7:
        return "delayed"
    return "stale"


@dataclass
class _GibsCache:
    products: list[SatelliteProduct]
    fetched_at: datetime
    latency_ms: float


_cache: _GibsCache | None = None
_refresh_lock = asyncio.Lock()

# Layer `<Value>` entries look like "2022-04-17/2026-08-04/P1D" — a start, an
# end and an ISO 8601 repeat interval.
_PERIOD_LABELS = {
    "P1D": "Daily",
    "P1M": "Monthly",
    "P1Y": "Annual",
    "P8D": "8-day",
    "PT1H": "Hourly",
}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
def _fetch_capabilities() -> tuple[str, float]:
    started = datetime.now(timezone.utc)
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        response = client.get(CAPABILITIES_URL)
        response.raise_for_status()
        text = response.text
    latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
    return text, latency_ms


def _parse_date(value: str) -> date | None:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", value.strip())
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _layer_details(layer: ElementTree.Element) -> tuple[date | None, str | None]:
    """Newest servable date and cadence for one layer.

    `<Default>` is GIBS' own statement of the newest timestep, which is more
    reliable than parsing every `<Value>` range; the ranges are only consulted
    for the repeat interval.
    """
    latest: date | None = None
    period: str | None = None

    for dimension in layer.findall(f"{_WMTS_NS}Dimension"):
        identifier = dimension.findtext(f"{_OWS_NS}Identifier")
        if identifier != "Time":
            continue

        default = dimension.findtext(f"{_WMTS_NS}Default")
        if default:
            latest = _parse_date(default)

        for value in dimension.findall(f"{_WMTS_NS}Value"):
            text = (value.text or "").strip()
            parts = text.split("/")
            if len(parts) == 3:
                period = _PERIOD_LABELS.get(parts[2], parts[2])
                if latest is None:
                    latest = _parse_date(parts[1])
    return latest, period


def _parse(text: str, latency_ms: float) -> _GibsCache:
    root = ElementTree.fromstring(text)

    by_id: dict[str, ElementTree.Element] = {}
    for layer in root.iter(f"{_WMTS_NS}Layer"):
        identifier = layer.findtext(f"{_OWS_NS}Identifier")
        if identifier:
            by_id[identifier] = layer

    products: list[SatelliteProduct] = []
    for tracked in _TRACKED:
        layer = by_id.get(tracked["id"])
        if layer is None:
            # A retired layer should cost one table row, not the refresh.
            logger.debug(f"GIBS layer not present in capabilities: {tracked['id']}")
            continue

        latest, period = _layer_details(layer)
        matrix_set = layer.findtext(
            f"{_WMTS_NS}TileMatrixSetLink/{_WMTS_NS}TileMatrixSet"
        )
        products.append(
            SatelliteProduct(
                layer_id=tracked["id"],
                satellite=tracked["satellite"],
                product=tracked["product"],
                title=layer.findtext(f"{_OWS_NS}Title") or tracked["id"],
                latest_date=latest,
                resolution=_RESOLUTION_LABELS.get(matrix_set or "", matrix_set),
                format=layer.findtext(f"{_WMTS_NS}Format"),
                period=period,
            )
        )

    if not products:
        raise GibsError("No tracked layers found in the GIBS capabilities document")

    # Freshest first — the table is about what just landed.
    products.sort(key=lambda p: (p.latest_date or date.min), reverse=True)

    return _GibsCache(
        products=products,
        fetched_at=datetime.now(timezone.utc),
        latency_ms=latency_ms,
    )


def _load() -> _GibsCache:
    text, latency_ms = _fetch_capabilities()
    return _parse(text, latency_ms)


async def refresh_cache() -> None:
    global _cache
    async with _refresh_lock:
        try:
            fresh = await asyncio.to_thread(_load)
        except Exception:  # noqa: BLE001 - keep the previous listing
            logger.opt(exception=True).warning("GIBS refresh failed, keeping previous cache if any")
            return

        _cache = fresh
        logger.info(f"GIBS cache refreshed: {len(fresh.products)} tracked products")


def _require_cache() -> _GibsCache:
    if _cache is None:
        raise GibsError("Satellite product listing not yet available — initial fetch in progress")
    return _cache


def is_refreshing() -> bool:
    """Whether a refresh is in flight right now.

    Reuses the existing refresh lock rather than tracking a second flag: the
    lock is held for exactly the duration of a fetch, so it already is the
    answer. Lets the dashboard tell "still warming up" apart from "failed",
    which are very different things to show a user.
    """
    return _refresh_lock.locked()


def is_available() -> bool:
    return _cache is not None


def health() -> dict[str, Any]:
    if _cache is None:
        return {"connected": False, "latency_ms": None, "last_sync": None, "records": 0}
    return {
        "connected": True,
        "latency_ms": round(_cache.latency_ms),
        "last_sync": _cache.fetched_at.isoformat(),
        "records": len(_cache.products),
    }


def products() -> list[dict[str, Any]]:
    """The tracked satellite products, freshest first."""
    cache = _require_cache()
    today = datetime.now(timezone.utc).date()
    return [product.to_dict(today) for product in cache.products]


def latest_product() -> dict[str, Any] | None:
    """The single most recently updated product, for the live feed."""
    listing = products()
    return listing[0] if listing else None


def meta() -> dict[str, Any]:
    cache = _require_cache()
    return {
        "source": SOURCE_LABEL,
        "source_url": SOURCE_URL,
        "fetched_at": cache.fetched_at.isoformat(),
        "product_count": len(cache.products),
    }
