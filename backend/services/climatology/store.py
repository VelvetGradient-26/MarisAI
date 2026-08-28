"""Where a fitted climatology lives, and how it is read back.

Deliberately **not** under `models/forecasting/_grids/`. A forecast grid is
model output with a horizon and an anchor, rebuilt twice a day and thrown away;
a climatology is a 30-year observational summary that changes when the baseline
period changes, i.e. once a decade. Filing one under the other's directory
invites the scheduler that refreshes forecast grids to treat this as stale.

Kept in the forecast grids' *file shape* though — a NetCDF whose horizontal
coords are plain `latitude`/`longitude` — precisely so
`services/field_sampling.py::build_sampler` reads it with no changes, including
the periodic-longitude test and the separate coverage resampling that keeps a
coastline crisp.
"""

from __future__ import annotations

from pathlib import Path

import xarray as xr
from loguru import logger

# `backend/models/climatology/<variable>.nc`. `models/` already holds trained
# artifacts and is already git-tracked through LFS.
ROOT = Path(__file__).resolve().parents[2] / "models" / "climatology"


class ClimatologyNotBuilt(RuntimeError):
    """No climatology exists for this variable yet.

    A distinct type rather than a bare `FileNotFoundError` because the caller's
    correct response is specific: this is a 503 with "not built yet, run
    scripts/build_climatology.py", never a 500 and never a fabricated zero.
    """


def climatology_path(variable: str, root: Path | None = None) -> Path:
    return (root or ROOT) / f"{variable}.nc"


def available(root: Path | None = None) -> list[str]:
    """Variables with a built climatology, newest-safe and cheap to call."""
    directory = root or ROOT
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.nc"))


def save(climatology: xr.Dataset, variable: str, root: Path | None = None) -> Path:
    """Write atomically, so a reader never sees a half-written file.

    Same construction as `forecasting/grid_predictor.save_grid`: the build takes
    tens of minutes and the server may read this file at any moment.
    """
    path = climatology_path(variable, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".nc.tmp")
    climatology.to_netcdf(temporary)
    temporary.replace(path)
    logger.info(f"wrote climatology to {path}")
    return path


def load(variable: str, root: Path | None = None) -> xr.Dataset:
    """Read a fitted climatology, or say clearly that it was never built."""
    path = climatology_path(variable, root)
    if not path.exists():
        raise ClimatologyNotBuilt(
            f"no climatology built for {variable!r} — run "
            f"`python scripts/build_climatology.py --variable {variable}`"
        )
    return xr.open_dataset(path)
