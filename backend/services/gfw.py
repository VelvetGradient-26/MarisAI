"""Global Fishing Watch 4Wings tile proxy.

GFW's heatmap tile endpoint needs a bearer token attached server-side (it
must never reach the browser) and a base64-encoded style payload. Only two
fixed datasets are exposed, each with a server-controlled style/date-range —
this is a narrow proxy for our own map layers, not a general GFW API passthrough.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import settings

GFW_TILE_URL = "https://gateway.api.globalfishingwatch.org/v3/4wings/tile/heatmap/{z}/{x}/{y}"


class GfwError(RuntimeError):
    pass


class GfwDataset:
    def __init__(self, dataset_id: str, color: tuple[int, int, int], ramp: list[float], window_days: int, lag_days: int):
        self.dataset_id = dataset_id
        self.color = color
        self.ramp = ramp
        self.window_days = window_days
        self.lag_days = lag_days


# Short public name -> real GFW dataset + rendering. `ramp` is calibrated at
# REFERENCE_ZOOM (see _scaled_ramp below) — GFW's 4Wings grid sums presence
# into whatever geographic area one output pixel covers, so the same raw
# value range only holds at one zoom; every other zoom needs it rescaled.
DATASETS: dict[str, GfwDataset] = {
    "ais-presence": GfwDataset(
        dataset_id="public-global-presence:latest",
        color=(34, 211, 238),
        ramp=[0, 1, 5, 10, 25, 50, 100, 250, 500],
        window_days=30,
        lag_days=2,
    ),
    "sar-presence": GfwDataset(
        dataset_id="public-global-sar-presence:latest",
        color=(255, 196, 0),
        ramp=[0, 1, 2, 3, 5, 8, 12, 20, 30],
        window_days=30,
        lag_days=60,
    ),
}

# The zoom the ramps above were tuned at (empirically: busy vs. quiet ocean
# gave good contrast here without saturating). One MapLibre tile pixel at
# zoom z covers ~4^(REFERENCE_ZOOM - z) times the area it covers at
# REFERENCE_ZOOM, and 4Wings sums presence per pixel, so without rescaling,
# every low-zoom tile saturates solid — verified directly: at z=2 with the
# unscaled ramp, open mid-Pacific ocean showed 52% pixel coverage at
# near-max alpha, indistinguishable from the Singapore Strait. Scaling the
# ramp by that same 4^(...) factor dropped quiet-ocean coverage to ~7% while
# keeping the strait's real structure visible.
REFERENCE_ZOOM = 8
MIN_SCALE_ZOOM = 1  # clamp: don't extrapolate the scale factor past z=1


def _scaled_ramp(ramp: list[float], z: int) -> list[float]:
    clamped_z = max(z, MIN_SCALE_ZOOM)
    scale = 4 ** (REFERENCE_ZOOM - clamped_z)
    return [round(v * scale, 3) for v in ramp]


def _style_param(color: tuple[int, int, int], ramp: list[float], z: int) -> str:
    payload = json.dumps({"color": list(color), "ramp": _scaled_ramp(ramp, z)})
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def _date_range(window_days: int, lag_days: int) -> tuple[str, str]:
    end = datetime.now(timezone.utc) - timedelta(days=lag_days)
    start = end - timedelta(days=window_days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


async def fetch_tile(dataset_key: str, z: int, x: int, y: int) -> bytes:
    dataset = DATASETS.get(dataset_key)
    if dataset is None:
        raise GfwError(f"Unknown dataset '{dataset_key}'")
    if not settings.GFW_TOKEN:
        raise GfwError("GFW_TOKEN is not configured")

    start, end = _date_range(dataset.window_days, dataset.lag_days)
    params: dict[str, Any] = {
        "format": "PNG",
        "datasets[0]": dataset.dataset_id,
        "date-range": f"{start},{end}",
        "interval": "MONTH",
        "style": _style_param(dataset.color, dataset.ramp, z),
    }

    url = GFW_TILE_URL.format(z=z, x=x, y=y)
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.get(
                url, params=params, headers={"Authorization": f"Bearer {settings.GFW_TOKEN}"}
            )
        except httpx.HTTPError as exc:
            raise GfwError(f"GFW tile request failed: {exc}") from exc

    if response.status_code == 404:
        # GFW returns 404 "Tile empty" for genuinely no-data tiles/dates, not
        # an outage — treat as an empty (fully transparent) tile.
        return _EMPTY_PNG
    if response.is_error:
        raise GfwError(f"GFW tile request failed ({response.status_code}): {response.text[:200]}")

    return response.content


# 1x1 fully-transparent PNG, returned in place of GFW's 404 "Tile empty" so
# the map just shows nothing there instead of a broken-image icon.
_EMPTY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
