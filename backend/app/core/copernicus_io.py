"""Where Copernicus network reads run, and how long anyone waits for one.

**The failure this exists for** (2026-09-16, CloudFerro degraded — a 10-degree
box that normally loads in seconds took 154s): every live-cache warmer called
`asyncio.to_thread(fetch)`, and `to_thread` always uses asyncio's *default*
executor — about 12 threads on an 8-core machine. Seven warmers fired at
startup, each hung on the slow upstream, and the pool filled. Every other
`to_thread` in the app then queued behind them, so an SST map tile rendered
from an already-cached grid hung past 120s. A `--reload` then hung too,
because the interpreter joins that pool's threads on exit.

Three separate guarantees, because no one of them is enough:

* **Dedicated threads.** Fetches never run on the default executor, so a slow
  Copernicus costs Copernicus layers and nothing else. At most
  `COPERNICUS_MAX_CONCURRENT_FETCHES` run at once.
* **A wall-clock budget.** The caller stops waiting after
  `COPERNICUS_FETCH_TIMEOUT_SECONDS` and reports failure, which releases its
  refresh lock and lets the service say "unavailable" instead of "warming"
  forever. **What the timeout does not do is stop the thread** — Python cannot
  cancel a thread blocked in a socket read. The abandoned read keeps its slot
  until the socket gives up on its own (botocore's own timeouts and retries).
* **One fetch per key.** Because an abandoned read outlives its caller, a
  scheduled refresh whose predecessor is still running is *skipped* rather
  than queued. Without this, each tick against a hung upstream would add
  another zombie until every slot held one.

The threads are daemon threads, not a `ThreadPoolExecutor`: the executor's
workers are joined at interpreter exit, which is exactly what made a code
reload wait on a hung download.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import TypeVar

from loguru import logger

from app.core.config import settings

T = TypeVar("T")


class CopernicusFetchError(RuntimeError):
    """A fetch timed out, or was skipped because the previous one is still running."""


class CopernicusFetchTimeout(CopernicusFetchError):
    pass


class CopernicusFetchBusy(CopernicusFetchError):
    pass


# Keys with a thread still running — including ones whose caller already gave
# up. Guarded by a plain lock: it is written from worker threads when they end.
_in_flight: set[str] = set()
_in_flight_lock = threading.Lock()
_slots: threading.BoundedSemaphore | None = None


def _get_slots() -> threading.BoundedSemaphore:
    global _slots
    if _slots is None:
        _slots = threading.BoundedSemaphore(max(1, settings.COPERNICUS_MAX_CONCURRENT_FETCHES))
    return _slots


def is_in_flight(key: str) -> bool:
    with _in_flight_lock:
        return key in _in_flight


async def run_fetch(key: str, fn: Callable[[], T], *, timeout: float | None = None) -> T:
    """Run blocking `fn` on a dedicated daemon thread and await its result.

    Raises `CopernicusFetchBusy` if a fetch for `key` is still running (even an
    abandoned one), and `CopernicusFetchTimeout` if this one — including any
    wait for a free slot — takes longer than `timeout`. Anything `fn` raises
    propagates unchanged.
    """
    budget = float(timeout if timeout is not None else settings.COPERNICUS_FETCH_TIMEOUT_SECONDS)

    with _in_flight_lock:
        if key in _in_flight:
            raise CopernicusFetchBusy(
                f"{key}: the previous fetch is still running upstream; skipping this one"
            )
        _in_flight.add(key)

    loop = asyncio.get_running_loop()
    future: asyncio.Future[T] = loop.create_future()
    slots = _get_slots()

    # Set when the caller stops waiting. The late result is then dropped rather
    # than set on a future nobody will read, which asyncio would otherwise log
    # as "exception was never retrieved" for every abandoned failed fetch.
    abandoned = threading.Event()

    def _settle(result: T | None, error: BaseException | None) -> None:
        if abandoned.is_set() or future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)  # type: ignore[arg-type]

    def _worker() -> None:
        acquired = slots.acquire(timeout=budget)
        try:
            if not acquired:
                raise CopernicusFetchTimeout(
                    f"{key}: no free Copernicus fetch slot within {budget:.0f}s"
                )
            result = fn()
        except BaseException as exc:  # noqa: BLE001 - handed to the awaiting caller
            _deliver(None, exc)
        else:
            _deliver(result, None)
        finally:
            if acquired:
                slots.release()
            with _in_flight_lock:
                _in_flight.discard(key)

    def _deliver(result: T | None, error: BaseException | None) -> None:
        try:
            loop.call_soon_threadsafe(_settle, result, error)
        except RuntimeError:
            # The loop is closed (shutdown or reload) — nobody is waiting.
            pass

    threading.Thread(target=_worker, name=f"copernicus-{key}", daemon=True).start()

    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=budget)
    except TimeoutError as exc:
        abandoned.set()
        logger.warning(
            f"{key}: Copernicus fetch exceeded {budget:.0f}s; giving up on it "
            "(the read keeps its thread until the socket gives up)"
        )
        raise CopernicusFetchTimeout(f"{key}: Copernicus fetch exceeded {budget:.0f}s") from exc
