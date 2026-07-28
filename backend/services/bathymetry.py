"""Point elevation/depth lookup via the GEBCO bathymetric grid (GetFeatureInfo).

No API key, pure point query — used for the map's live depth-at-cursor
readout rather than a full-coverage raster overlay.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

GEBCO_WMS_URL = "https://wms.gebco.net/mapserv"
GEBCO_LAYER = "GEBCO_LATEST_2"

# Small bbox centered on the point, queried at the center pixel of a modest
# grid — verified more reliable than a 1x1 pixel request against this server.
_BBOX_HALF_WIDTH_DEG = 0.05
_GRID_SIZE = 64
_CENTER_PIXEL = _GRID_SIZE // 2

_VALUE_LIST_RE = re.compile(r"value_list\s*=\s*'(-?\d+(?:\.\d+)?)'")


class BathymetryError(RuntimeError):
    pass


async def get_elevation(latitude: float, longitude: float) -> dict[str, Any]:
    bbox = ",".join(
        str(v)
        for v in (
            longitude - _BBOX_HALF_WIDTH_DEG,
            latitude - _BBOX_HALF_WIDTH_DEG,
            longitude + _BBOX_HALF_WIDTH_DEG,
            latitude + _BBOX_HALF_WIDTH_DEG,
        )
    )

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(
                GEBCO_WMS_URL,
                params={
                    "service": "WMS",
                    "version": "1.1.1",
                    "request": "GetFeatureInfo",
                    "layers": GEBCO_LAYER,
                    "query_layers": GEBCO_LAYER,
                    "styles": "",
                    "srs": "EPSG:4326",
                    "bbox": bbox,
                    "width": _GRID_SIZE,
                    "height": _GRID_SIZE,
                    "x": _CENTER_PIXEL,
                    "y": _CENTER_PIXEL,
                    "info_format": "text/plain",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BathymetryError(f"GEBCO request failed: {exc}") from exc

    match = _VALUE_LIST_RE.search(response.text)
    if not match:
        raise BathymetryError("No elevation data at this point")

    elevation_m = float(match.group(1))
    return {
        "elevation_m": elevation_m,
        "depth_m": -elevation_m if elevation_m < 0 else None,
        "is_land": elevation_m >= 0,
    }
