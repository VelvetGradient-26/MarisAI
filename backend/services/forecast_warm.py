"""Pre-warm the forecasting engine's history cache.

The problem this solves is measured, not assumed. A forecast for a point the
process has not seen recently costs ~33s; the identical call once warm costs
~0.08s. Inference is the 0.08s. The other 33 seconds are `forecasting.history`
fetching upstream series from Copernicus and ERDDAP, which is why the wait
feels like training even though nothing is training.

`forecasting/history.py` already caches those series on disk for 6 hours, and
that cache does survive a restart. What it does not do is fill itself: the
first person to open a metric page pays the full fetch, and the cache key
includes `end_date`, so every variable goes cold again each day. This module
does that filling on a schedule instead, so the cost lands on the scheduler
rather than on a page load.

Two deliberate choices:

- **It calls `predict` rather than reconstructing a `HistoryRequest`.** The
  cache key is derived from the exact window `predict` computes (the chart
  window plus the feature lookback plus a margin). Rebuilding that arithmetic
  here would warm a *neighbouring* key the moment either side drifted, and the
  failure mode is silent — the cache stays full and every page stays slow.
  Calling the real path cannot drift, and it validates that the model actually
  serves as a side effect.

- **It is sequential.** These are the same upstream services the rest of the
  platform shares, and a 31-way parallel sweep against Copernicus is a good
  way to get rate-limited during ordinary use. This is background work with no
  one waiting on it; it can take its time.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from forecasting import ForecastingError
from forecasting.predictor import predict
from forecasting.registry import catalog

logger = logging.getLogger(__name__)

# Kept under the history cache's own 6h TTL so a sweep lands before entries
# expire rather than just after, which would leave a window where every page
# is cold again.
REFRESH_INTERVAL_HOURS = 4

# The points worth holding warm. The first is `MetricIntelligencePage`'s
# DEFAULT_LOCATION — the Arabian Sea point every metric page loads when the
# URL carries no coordinates, and therefore the single most requested point in
# the system by a wide margin. A user who clicks elsewhere on the map still
# pays a cold fetch; warming the whole ocean is not possible and pretending
# otherwise would just move the cost around.
WARM_POINTS: tuple[tuple[float, float], ...] = ((15.0, 65.0),)

# The hero asks for 7 days when it is trained and the first trained horizon
# otherwise, so warming h=7 covers the panel that loads above the fold. Every
# other horizon reuses the same cached history, so warming one horizon warms
# the expensive part for all of them.
PREFERRED_HORIZON = 7

# One sweep at a time. The boot-time call and the interval job would otherwise
# overlap on a slow first run and issue every upstream fetch twice.
_lock = asyncio.Lock()

_last_result: WarmResult | None = None


@dataclass(frozen=True)
class WarmResult:
    """What a sweep did, for the health endpoint and the logs."""

    warmed: int
    failed: int
    skipped: int
    seconds: float

    def as_dict(self) -> dict[str, object]:
        return {
            "warmed": self.warmed,
            "failed": self.failed,
            "skipped": self.skipped,
            "seconds": round(self.seconds, 1),
        }


def is_warming() -> bool:
    """Whether a sweep is in flight.

    Mirrors the `is_refreshing()` convention the cached dashboard services
    use, and for the same reason: a cold page and a broken one must not look
    alike to the UI.
    """
    return _lock.locked()


def last_result() -> WarmResult | None:
    """The most recent sweep's outcome, or None before the first one."""
    return _last_result


async def refresh_cache() -> WarmResult:
    """Warm every trained variable at every configured point.

    Never raises. A warm failure is a slow page later, not an outage now, and
    this runs on the server's scheduler where an exception would be logged and
    discarded anyway — better to count it and carry on to the next variable
    than to abandon the remaining thirty.
    """
    global _last_result

    if _lock.locked():
        logger.debug("forecast warm already in progress; skipping this tick")
        return _last_result or WarmResult(0, 0, 0, 0.0)

    async with _lock:
        started = time.monotonic()
        warmed = failed = skipped = 0

        try:
            entries = catalog()
        except Exception as exc:  # noqa: BLE001 - never fail the scheduler
            logger.warning(f"forecast warm could not read the catalog: {exc}")
            return WarmResult(0, 0, 0, time.monotonic() - started)

        for entry in entries:
            if not entry.trained_horizons:
                skipped += 1
                continue

            horizon = (
                PREFERRED_HORIZON
                if PREFERRED_HORIZON in entry.trained_horizons
                else entry.trained_horizons[0]
            )

            for latitude, longitude in WARM_POINTS:
                try:
                    await predict(
                        entry.key,
                        latitude,
                        longitude,
                        horizon,
                        # Nothing reads this forecast — only the history it
                        # pulls into the cache matters, so the response is
                        # trimmed to nothing. Note this trims the *output*:
                        # SHAP still runs, since `explain_row` truncates after
                        # computing. That is deliberate, because it means the
                        # sweep exercises the explainer too and a broken one
                        # shows up in the warm log rather than on a page.
                        top_k=0,
                        include_history=False,
                    )
                    warmed += 1
                except ForecastingError as exc:
                    failed += 1
                    logger.warning(
                        f"forecast warm failed for {entry.key} h{horizon} "
                        f"at ({latitude}, {longitude}): {exc}"
                    )
                except Exception as exc:  # noqa: BLE001 - never fail the scheduler
                    failed += 1
                    logger.warning(
                        f"forecast warm errored for {entry.key} h{horizon}: {exc}"
                    )

        result = WarmResult(warmed, failed, skipped, time.monotonic() - started)
        _last_result = result
        logger.info(
            f"forecast cache warmed: {result.warmed} ok, {result.failed} failed, "
            f"{result.skipped} untrained, in {result.seconds:.0f}s"
        )
        return result
