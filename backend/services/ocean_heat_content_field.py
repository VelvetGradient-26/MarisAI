"""Ocean heat content as a map field — the grid `services/dashboard/copernicus_series.py`
only ever serves one point of.

That module's own docstring calls this out as "a different cost class":
its OHC series is one point across a *year* of daily timesteps (`arco-time-
series`, 8-13s) — a field is one *snapshot* across a whole region, which is
the opposite access pattern and needs its own offline build
(`scripts/build_ocean_heat_content_grid.py`), the same reason
`backend/forecasting/`'s tile grids are built by a script rather than
computed inline on a tile request.

**Regional, not global, and that is a deliberate scope-down, not a
limitation discovered later.** OHC needs the *whole depth column* (0-700 m,
~20-30 model levels) at every cell, not one surface value — a materially
heavier fetch than a 2-D field like SST or wind. A global fetch at that
depth resolution was not attempted; the habitat/HAB models' own region
(55-95 degE, 5S-25N — see `services/predictions.py`, `services/brief.py`)
already establishes that this platform's real usage is regional, so this
field reuses that exact box rather than paying for global coverage nothing
downstream asks for.

**Reuses `services/dashboard/copernicus_series.py`'s own constants**
(`OHC_LAYERS_M`, seawater density/heat capacity) via the integration helper
in that module — kept there because the point series and this field must
agree on what a heat-content number *means*, the same reason
`services/heatwave_common.py` exists for the Hobday formula.

**Read-only over a file the build script writes** — this module never
touches Copernicus itself, matching `services/predictions.py`'s "the
backend reads these files; it never triggers the fetch" split, so a
malformed or slow tile request can never start a multi-minute Copernicus
read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from services import field_sampling
from services.dashboard.copernicus_series import OHC_LAYERS_M, ohc_key

GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "ocean_heat_content_grid.nc"

# The habitat/HAB models' own established region (55-95E, 5S-25N) — see the
# module docstring for why this field reuses it rather than going global.
REGION_WEST, REGION_SOUTH, REGION_EAST, REGION_NORTH = 55.0, -5.0, 95.0, 25.0

SOURCE_LABEL = "Copernicus Marine Service (regional grid build, not live)"


class OceanHeatContentFieldError(RuntimeError):
    """No grid has been built yet, or the built one could not be read."""


@dataclass(frozen=True)
class OceanHeatContentField:
    latitude: np.ndarray
    longitude: np.ndarray
    # depth_m -> (lat, lon) float32, GJ/m^2. NaN on land or below the model's
    # own bottom at that cell.
    layers: dict[float, np.ndarray]
    timestamp: datetime
    built_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "built_at": self.built_at.isoformat(),
            "source": SOURCE_LABEL,
            "region": {
                "west": REGION_WEST, "south": REGION_SOUTH, "east": REGION_EAST, "north": REGION_NORTH,
            },
            "layers_m": list(OHC_LAYERS_M),
            "unit": "GJ/m^2",
            "note": (
                "A regional grid built offline (scripts/build_ocean_heat_content_grid.py), "
                "not a live field — see this module's docstring for why global "
                "depth-resolved coverage was not attempted. Rebuild on a schedule "
                "to keep it current; this endpoint only ever reads whatever the "
                "last build wrote."
            ),
        }


_cache: OceanHeatContentField | None = None


def _load() -> OceanHeatContentField:
    global _cache
    if _cache is not None:
        return _cache

    if not GRID_PATH.exists():
        raise OceanHeatContentFieldError(
            f"no ocean heat content grid at {GRID_PATH} — run "
            "`python scripts/build_ocean_heat_content_grid.py` first"
        )
    try:
        with xr.open_dataset(GRID_PATH) as handle:
            dataset = handle.load()
    except Exception as exc:  # xarray raises a range of backend-specific types
        raise OceanHeatContentFieldError(f"could not read {GRID_PATH}: {exc}") from exc

    layers = {depth: dataset[ohc_key(depth)].values.astype("float32") for depth in OHC_LAYERS_M}
    field = OceanHeatContentField(
        latitude=dataset["latitude"].values.astype("float64"),
        longitude=dataset["longitude"].values.astype("float64"),
        layers=layers,
        timestamp=datetime.fromisoformat(dataset.attrs["timestamp"]),
        built_at=datetime.fromisoformat(dataset.attrs["built_at"]),
    )
    _cache = field
    return field


def reload() -> None:
    """Drop the in-memory cache so the next read picks up a fresh build.

    Not on a timer: nothing calls this automatically, the same "read what
    the script wrote, on request" split `services/predictions.py` already
    uses for ML-exported grids. Call it after re-running the build script
    against a running server, or restart the process.
    """
    global _cache
    _cache = None


def is_available() -> bool:
    try:
        _load()
    except OceanHeatContentFieldError:
        return False
    return True


def summary() -> dict[str, Any]:
    return _load().as_dict()


def at_point(latitude: float, longitude: float) -> dict[str, Any]:
    """Every layer's value at the nearest cell to one coordinate."""
    field = _load()
    if not (REGION_SOUTH <= latitude <= REGION_NORTH and REGION_WEST <= longitude <= REGION_EAST):
        return {
            "available": False,
            "unavailable_reason": (
                f"outside this field's region ({REGION_WEST}-{REGION_EAST} degE, "
                f"{REGION_SOUTH}-{REGION_NORTH} degN)"
            ),
        }

    row = int(np.abs(field.latitude - latitude).argmin())
    column = int(np.abs(field.longitude - longitude).argmin())

    values = {}
    for depth in OHC_LAYERS_M:
        value = float(field.layers[depth][row, column])
        values[ohc_key(depth)] = round(value, 3) if np.isfinite(value) else None

    if all(v is None for v in values.values()):
        return {
            "available": False,
            "unavailable_reason": "land, or below the model's own coverage at this cell",
        }

    return {
        "available": True,
        "latitude": float(field.latitude[row]),
        "longitude": float(field.longitude[column]),
        "timestamp": field.timestamp.isoformat(),
        "unit": "GJ/m^2",
        **values,
    }


def cells(depth_m: float = OHC_LAYERS_M[-1]) -> dict[str, Any]:
    """One layer's field as drawable rectangles — same shape
    `services/heatwaves.py::cells`/`services/upwelling.py::cells` already
    use, for the same reason: a map layer that already knows this convention
    from three other detectors does not need a fourth response shape.
    """
    if depth_m not in OHC_LAYERS_M:
        raise OceanHeatContentFieldError(f"unknown layer {depth_m} — expected one of {OHC_LAYERS_M}")

    field = _load()
    values = field.layers[depth_m]
    south, north = field_sampling.cell_edges(field.latitude)
    west, east = field_sampling.cell_edges(field.longitude)
    rows, columns = np.nonzero(np.isfinite(values))

    return {
        **field.as_dict(),
        "layer_m": depth_m,
        "cells": [
            {
                "west": round(float(west[column]), 4),
                "south": round(float(south[row]), 4),
                "east": round(float(east[column]), 4),
                "north": round(float(north[row]), 4),
                "value": round(float(values[row, column]), 3),
            }
            for row, column in zip(rows.tolist(), columns.tolist(), strict=True)
        ],
    }
