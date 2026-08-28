"""One configured logger for the whole backend.

**The problem this fixes is that most of this codebase's logging did not
work.** Two systems had grown side by side — loguru in 13 modules, stdlib
`logging` in 31 — and nothing in the server process configured either. Measured
before this module existed:

    >>> logging.getLogger("services.forecast_tiles").isEnabledFor(logging.INFO)
    False
    >>> logging.getLogger().handlers
    []

Uvicorn configures only its own `uvicorn*` loggers and leaves root alone, so
every `logger.info(...)` and `.debug(...)` in those 31 modules was **dropped at
source**: most of the forecasting engine (`history`, `trainer`, `predictor`,
`grid_history`, `grid_predictor`, `model_store`), plus `predictions`,
`forecast_tiles`, `forecast_warm`, `gfw`, `ais`, `llm` and the whole chat agent.
`WARNING` and above survived only through `logging.lastResort`, which writes
bare text to stderr with no timestamp, no logger name and no routing — while
loguru's modules printed in an entirely different format beside them.

**Why that mattered more here than in a typical service.** The caches are
fire-and-forget scheduler tasks, and this repo has already been bitten twice by
exceptions asyncio swallows: `copernicus_wind` and `vector_source` both carry a
comment explaining that an error escaping the encode step leaves the cache empty
forever while every endpoint 503s with nothing actionable logged. The mitigation
for that class of failure *is* the log.

**stdlib routes into loguru, not the other way round.** Both directions work;
this one was chosen because `main.py` and every cached service already emit
through loguru, so the alternative would have meant rewriting the modules that
were working correctly in order to accommodate the ones that were not. One
`InterceptHandler` on root covers all 31 stdlib modules without touching them.

Three details in `InterceptHandler` are load-bearing and each is wrong in the
obvious implementation:

* **The level is looked up by name with a numeric fallback.** A library logging
  at a level loguru does not know (25, say) raises `ValueError` inside
  `logger.level()`, and an exception thrown *from a log call* is a spectacular
  failure mode — it propagates into whatever was being logged about.
* **The frame depth is walked, not guessed.** A fixed `depth=` makes every
  intercepted record claim to come from `logging/__init__.py`, which throws away
  the module name that is the entire point of routing them.
* **`exc_info` is passed through.** Dropping it turns `logger.exception(...)`
  into a one-line message with the traceback silently removed.
"""

from __future__ import annotations

import inspect
import logging
import sys
from contextvars import ContextVar
from typing import Any

from loguru import logger

# The current request's id, for correlation. A ContextVar rather than a header
# read at each call site: a forecast is a fan-out over several providers with
# retries, and the services doing the fanning out have no access to the request.
# asyncio copies the context per task, so a `create_task` inherits it.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Loggers whose records must not be re-emitted through the root handler.
# Uvicorn's access log is replaced by our own middleware (it cannot carry the
# request id, and two access lines per request is noise); its error logger is
# kept, since that is where startup failures and unhandled exceptions surface.
_SILENCED = ("uvicorn.access",)

# Third parties that are chatty at INFO and say nothing this project acts on.
# copernicusmarine is the notable one: it reconfigures logging when it opens a
# dataset, which is why `scripts/build_forecast_grid.py` uses a logging *filter*
# rather than a level — a level set beforehand is simply overwritten.
_NOISY = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "urllib3": logging.WARNING,
    "copernicusmarine": logging.WARNING,
    "botocore": logging.WARNING,
    "boto3": logging.WARNING,
    "s3fs": logging.WARNING,
    "asyncio": logging.WARNING,
    "apscheduler": logging.WARNING,
    "matplotlib": logging.WARNING,
}

_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{extra[request_id]}</cyan> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

_configured = False


class _NoiseFilter(logging.Filter):
    """Drops third-party chatter, on the *handler* rather than on the logger.

    A `setLevel` on the library's own logger is not enough on its own, and
    `scripts/build_forecast_grid.py` already records why: **copernicusmarine
    reconfigures logging when it opens a dataset**, so a level set beforehand is
    simply overwritten and the banner comes back. A filter attached to our
    handler cannot be undone that way, because the library never sees it.

    Matched on the root segment of the logger name, so `copernicusmarine.core`
    is caught by an entry for `copernicusmarine`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        threshold = _NOISY.get(record.name.split(".")[0])
        if threshold is None:
            return True
        return record.levelno >= threshold


class InterceptHandler(logging.Handler):
    """Hands a stdlib record to loguru with its origin and traceback intact."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except (ValueError, AttributeError):
            # A level loguru does not know. Falling back to the number keeps the
            # record rather than raising out of a log call.
            level = record.levelno

        # Walk out of the logging machinery so {name}/{function}/{line} describe
        # the caller rather than logging/__init__.py.
        frame, depth = inspect.currentframe(), 0
        while frame and (
            depth == 0 or frame.f_code.co_filename == logging.__file__
        ):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def configure_logging(level: str = "INFO", *, json_logs: bool = False) -> None:
    """Install one sink and route stdlib logging into it. Idempotent.

    Idempotence matters: this is called from `main.py`'s import path, and
    pytest imports `main` more than once across a session. Reconfiguring would
    stack duplicate sinks and print every line twice.
    """
    global _configured
    if _configured:
        return

    logger.remove()
    logger.configure(extra={"request_id": "-"})
    logger.add(
        sys.stderr,
        level=level,
        format="{message}" if json_logs else _FORMAT,
        serialize=json_logs,
        # Loguru's default. Kept explicit because it is what makes an exception
        # raised inside a fire-and-forget scheduler task legible rather than a
        # bare repr.
        backtrace=True,
        # Off deliberately: `diagnose=True` prints the *values* of local
        # variables in a traceback, and the locals here include Copernicus
        # credentials read from settings.
        diagnose=False,
        enqueue=False,
    )

    handler = InterceptHandler()
    # Both halves, deliberately. The filter is what actually holds — a library
    # that reconfigures logging can undo the `setLevel` below but cannot reach
    # this — while the levels keep the common case cheap by rejecting a record
    # before it is ever formatted.
    handler.addFilter(_NoiseFilter())
    logging.basicConfig(handlers=[handler], level=0, force=True)
    for name in _SILENCED:
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = False
    for name, noisy_level in _NOISY.items():
        logging.getLogger(name).setLevel(noisy_level)

    _configured = True


def bind_request_id(request_id: str) -> None:
    """Set the id for the current context, and patch loguru to emit it.

    The patch is installed once and reads the ContextVar at record time, so a
    log call made deep inside a service picks up the id without being handed it.
    """
    request_id_var.set(request_id)


def _patcher(record: dict[str, Any]) -> None:
    # Assigned, not `setdefault`. `record["extra"]` is pre-populated from the
    # core defaults configured above, so `request_id` is *already* present as
    # "-" by the time a patcher runs — a setdefault here silently never fires
    # and every line reads "-" no matter what the request set.
    record["extra"]["request_id"] = request_id_var.get()


# Applied at import: every record, from either library, carries the current
# request id or "-" outside a request (a scheduled refresh, or boot).
logger.configure(patcher=_patcher, extra={"request_id": "-"})
