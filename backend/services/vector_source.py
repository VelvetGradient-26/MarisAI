"""One live U/V field from Copernicus: fetch, cache, texture, point lookup.

`services/vector_field.py` owns the *encoding* — how a pair of velocity grids
becomes a texture the particle shader can sample. This module owns everything
around it: which dataset, which timestep, keeping a cache warm, and answering a
point query. Between them, adding a live vector field is a `VectorSourceSpec`
rather than a new service module.

That split is the same one the frontend already made. `VectorFieldParticleLayer`
was generic before a second field existed; the *backend* was not, and
`copernicus_wind` and `copernicus_currents` are two near-identical copies of the
same 250 lines. This exists because the third and fourth fields — Stokes drift,
and currents at depth — would have made four.

Three things here are field-specific and must stay declared rather than assumed,
because each has already been the cause of a bug that renders perfectly:

* **The geographic frame is data.** The physics and wave products run latitude
  -80 to 90 while the wind product covers -90 to 90. The shader takes the frame
  as a uniform (see `vector_field.encode`), and a field read with the wrong one
  animates convincingly with water from the wrong place.
* **The direction convention is declared, not inferred.** A current is named for
  where it flows *toward*; a wind for where it blows *from*. The two are 180
  degrees apart and both entirely plausible on screen.
* **The visual speed scale belongs to the field.** Wind runs 5-10 m/s and
  currents 0.1-0.4, an order of magnitude apart. At wind's scale a current is a
  still image.

What is deliberately *not* here: `copernicus_wind`'s candidate-timestep scan.
Its L4 product routinely publishes a day of all-NaN placeholder steps and needs
a wider search than an analysis product does. The bounded walk-back below covers
the general case — "the latest timestep exists" and "the latest timestep has
data" are different claims — and a source that needs more can raise its own
`max_lookback_steps`.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import numpy as np
from loguru import logger
from scipy.interpolate import RegularGridInterpolator
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from services import vector_field

_COMPASS_LABELS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

# Fraction of a timestep that must be finite before it counts as published.
# Low, because a global ocean field is mostly land-masked at some latitudes; the
# case being caught is an all-NaN placeholder, not a partial one.
_MIN_VALID_FRACTION = 0.1


class VectorSourceError(RuntimeError):
    """A live vector field is unavailable. Subclassed per field so a router can
    keep mapping one service's failure to one status code."""


@dataclass(frozen=True)
class VectorSourceSpec:
    """Everything that differs between one live vector field and another."""

    key: str
    dataset_id: str
    u_field: str
    v_field: str
    source_label: str
    unit: str
    # Legend top in the field's own units — not derived from the data, because a
    # legend that rescaled itself per refresh would make two screenshots of the
    # same ocean incomparable.
    speed_max_legend: float
    # Oceanographic ("toward") or meteorological ("from"). See the module note.
    convention: Literal["toward", "from"]
    # Texture downsample factor. The particle system samples with GPU bilinear
    # filtering, so native resolution buys nothing visually and costs the client
    # megabytes on every layer activation.
    downsample: int = 3
    # Depth to select, or None for a product whose surface level is a singleton.
    # A bound is always passed to the server either way: on the 50-level products
    # omitting it is the difference between ~60s and a fetch that does not
    # finish, which `machine_learning/` documents and this repo has paid for.
    depth_m: float | None = None
    max_lookback_steps: int = 4
    error_type: type[VectorSourceError] = VectorSourceError


@dataclass
class _Cache:
    u_interp: RegularGridInterpolator
    v_interp: RegularGridInterpolator
    lon_min: float
    texture: vector_field.FieldTexture
    # The timestep the data describes, distinct from `fetched_at`: judging
    # provider health on publication lag reports a working feed as down.
    timestamp: datetime
    fetched_at: datetime
    # The depth actually selected, which is the nearest model level rather than
    # the requested number. Reported, never rounded silently — a user asking for
    # 100 m and getting 92.3 m should be told which.
    depth_m: float | None = None


@dataclass
class VectorSource:
    """A live U/V field, with its cache. One instance per (dataset, depth)."""

    spec: VectorSourceSpec
    _cache: _Cache | None = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    # ---------------------------------------------------------------- fetch

    def _fetch(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, datetime, float | None]:
        @retry(
            retry=retry_if_not_exception_type(self.spec.error_type),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=2, min=2, max=20),
        )
        def _attempt():
            import copernicusmarine

            now = datetime.now(UTC)
            depth = self.spec.depth_m
            # A server-side bound either way. For a singleton-surface product it
            # is cheap insurance; for a 50-level one it is the whole cost of the
            # request, since a geo-series chunk otherwise brings every level.
            bounds = (
                {"minimum_depth": 0.0, "maximum_depth": 1.0}
                if depth is None
                else {"minimum_depth": max(depth - 20.0, 0.0), "maximum_depth": depth + 20.0}
            )
            dataset = copernicusmarine.open_dataset(
                dataset_id=self.spec.dataset_id,
                variables=[self.spec.u_field, self.spec.v_field],
                username=settings.COPERNICUS_USERNAME,
                password=settings.COPERNICUS_PASSWORD,
                # Explicit and load-bearing: these datasets also publish a
                # point-optimised "arco-time-series" service that `open_dataset`
                # picks by default and that takes many minutes for one global
                # timestep. Whole globe at one instant is geo-series' case.
                service="arco-geo-series",
                **bounds,
            )
            past = dataset.sel(time=slice(None, now.replace(tzinfo=None)))

            for step in range(1, self.spec.max_lookback_steps + 1):
                u_da = past[self.spec.u_field].isel(time=-step)
                v_da = past[self.spec.v_field].isel(time=-step)
                selected_depth: float | None = None
                if "depth" in u_da.dims:
                    index = 0 if depth is None else int(
                        np.abs(u_da["depth"].values - depth).argmin()
                    )
                    u_da = u_da.isel(depth=index)
                    v_da = v_da.isel(depth=index)
                    selected_depth = float(u_da["depth"].values)
                elif "depth" in u_da.coords:
                    selected_depth = float(u_da["depth"].values)

                u_da = u_da.load()
                valid_fraction = float(np.isfinite(u_da.values).mean())
                if valid_fraction < _MIN_VALID_FRACTION:
                    logger.warning(
                        f"{self.spec.key} timestep {str(u_da.time.values)[:19]} is only "
                        f"{valid_fraction:.1%} valid — trying an earlier timestep"
                    )
                    continue

                v_da = v_da.load()
                timestamp = datetime.fromisoformat(str(u_da.time.values)[:19]).replace(
                    tzinfo=UTC
                )
                return (
                    u_da.latitude.values.astype(np.float64),
                    u_da.longitude.values.astype(np.float64),
                    u_da.values.astype(np.float64),
                    v_da.values.astype(np.float64),
                    timestamp,
                    selected_depth,
                )

            raise self.spec.error_type(
                f"No usable {self.spec.key} timestep in the last "
                f"{self.spec.max_lookback_steps} steps — all appear to still be "
                "backfilling upstream"
            )

        return _attempt()

    async def refresh(self) -> None:
        """Refetch and re-encode. Never raises, and never clears a good cache.

        One try/except around fetch *and* encode, for the reason
        `copernicus_wind` documents at length: this runs as a fire-and-forget
        scheduler task, so an exception escaping the encode step is swallowed by
        asyncio, the cache stays empty forever, and every endpoint 503s
        permanently with nothing actionable logged.
        """
        async with self._lock:
            try:
                lat, lon, u, v, timestamp, depth = await asyncio.to_thread(self._fetch)
                u_interp = vector_field.build_interpolator(lat, lon, u)
                v_interp = vector_field.build_interpolator(lat, lon, v)
                texture = await asyncio.to_thread(
                    vector_field.encode, u, v, lat, lon, downsample=self.spec.downsample
                )
            except Exception:  # noqa: BLE001 - keep stale cache on any failure
                logger.opt(exception=True).warning(
                    f"{self.spec.key} refresh failed, keeping previous cache if any"
                )
                return

            self._cache = _Cache(
                u_interp=u_interp,
                v_interp=v_interp,
                lon_min=float(lon[0]),
                texture=texture,
                timestamp=timestamp,
                fetched_at=datetime.now(UTC),
                depth_m=depth,
            )
            logger.info(
                f"{self.spec.key} cache refreshed: timestep {timestamp.isoformat()}"
                + (f" at {depth:.1f} m" if depth is not None else "")
            )

    # ---------------------------------------------------------------- reads

    def _require(self) -> _Cache:
        if self._cache is None:
            raise self.spec.error_type(
                f"{self.spec.key} data not yet available — initial fetch still in "
                "progress or failed"
            )
        return self._cache

    def is_refreshing(self) -> bool:
        """Whether a refresh is in flight, derived from the existing lock rather
        than a second flag. Lets a caller tell "still warming up" from "failed"."""
        return self._lock.locked()

    def is_available(self) -> bool:
        return self._cache is not None

    def meta(self) -> dict[str, Any]:
        cache = self._require()
        payload = {
            "timestamp": cache.timestamp.isoformat(),
            "fetched_at": cache.fetched_at.isoformat(),
            "source": self.spec.source_label,
            "unit": self.spec.unit,
            "speed_max_legend": self.spec.speed_max_legend,
            "direction_convention": self.spec.convention,
            "u_min": cache.texture.u_min,
            "u_max": cache.texture.u_max,
            "v_min": cache.texture.v_min,
            "v_max": cache.texture.v_max,
            **cache.texture.bounds(),
        }
        if cache.depth_m is not None:
            payload["depth_m"] = round(cache.depth_m, 2)
            payload["requested_depth_m"] = self.spec.depth_m
        return payload

    def point(self, latitude: float, longitude: float) -> dict[str, Any]:
        cache = self._require()
        lon_query = vector_field.wrap_longitude(longitude, cache.lon_min)
        u = float(cache.u_interp([[latitude, lon_query]])[0])
        v = float(cache.v_interp([[latitude, lon_query]])[0])

        base: dict[str, Any] = {
            "timestamp": cache.timestamp.isoformat(),
            "source": self.spec.source_label,
        }
        if cache.depth_m is not None:
            base["depth_m"] = round(cache.depth_m, 2)

        if np.isnan(u) or np.isnan(v):
            return {
                **base,
                "speed_ms": None,
                self._direction_key(): None,
                "direction_compass": None,
                "u_ms": None,
                "v_ms": None,
                "is_land_or_no_data": True,
            }

        return {
            **base,
            "speed_ms": round(math.hypot(u, v), 3),
            self._direction_key(): round(self._direction(u, v), 1),
            "direction_compass": compass_label(self._direction(u, v)),
            "u_ms": round(u, 3),
            "v_ms": round(v, 3),
            "is_land_or_no_data": False,
        }

    def field_png(self) -> bytes:
        return self._require().texture.png

    # ------------------------------------------------------------ direction

    def _direction_key(self) -> str:
        # The convention is in the field *name*, not left to be inferred from a
        # bare "direction_deg". A consumer that reads the wrong one draws every
        # arrow backwards, and the result looks entirely plausible.
        return (
            "direction_toward_deg" if self.spec.convention == "toward" else "direction_from_deg"
        )

    def _direction(self, u: float, v: float) -> float:
        toward = (90.0 - math.degrees(math.atan2(v, u))) % 360.0
        return toward if self.spec.convention == "toward" else (toward + 180.0) % 360.0


def compass_label(direction_deg: float) -> str:
    return _COMPASS_LABELS[round(direction_deg / 45) % 8]
