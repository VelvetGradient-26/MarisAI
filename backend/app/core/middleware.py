"""Request correlation and the access log.

One middleware, doing the two things the previous setup could not do at all:
give every log line emitted while serving a request a shared id, and record how
long the request took.

**Why the access log is ours rather than uvicorn's.** Uvicorn's is fine and says
nothing about the request beyond method, path and status — in particular it
cannot carry the request id, because it logs from outside the context the id
lives in. Two access lines per request is noise, so `uvicorn.access` is silenced
in `app.core.logging` and this replaces it.

**Duration is the point, not decoration.** This backend's characteristic failure
is slowness rather than error: a cold forecast is 33s against 0.08s warm, a
Copernicus read once ran 98 minutes without returning, and the dashboard's whole
`warming` state exists because a cold cache and a broken one look alike. A
status code alone cannot distinguish any of those from a healthy response.
"""

from __future__ import annotations

import time
import uuid

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.logging import bind_request_id, request_id_var

# Header carrying the id, in and out. Accepted from the client so a request can
# be followed across a proxy; generated when absent.
REQUEST_ID_HEADER = "X-Request-ID"

# A client-supplied id is echoed into logs, so it is length-capped and stripped
# of anything that could forge a log line. Without this, a caller can inject a
# newline and write arbitrary text into the log at will.
_MAX_ID_LENGTH = 64

# Paths that must not produce an access line. `/` is the container health check
# and is hit every few seconds; logging it buries everything else.
_UNLOGGED_PATHS = frozenset({"/", "/health", "/favicon.ico"})

# Above this, a request is slow enough to be worth its own level. Chosen from
# what this app actually does: a warm point forecast is well under a second, a
# tile render is a few hundred ms, and anything past 5s means a cache missed and
# an upstream fetch happened on the request path — which is the thing the
# "cached, scheduled, never fetched per request" rule exists to prevent.
SLOW_REQUEST_S = 5.0


def _sanitize(candidate: str) -> str:
    cleaned = "".join(
        character for character in candidate if character.isalnum() or character in "-_."
    )
    return cleaned[:_MAX_ID_LENGTH]


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Binds a request id for the duration of the request and logs the result."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = _sanitize(incoming) or uuid.uuid4().hex[:12]
        bind_request_id(request_id)

        # perf_counter, not time(): this is a duration, and wall-clock is
        # subject to NTP steps that can make an elapsed time negative.
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            # Logged here as well as by the exception handler, because this is
            # the only place that knows how long it ran before failing.
            logger.opt(exception=True).error(
                f"{request.method} {request.url.path} failed after {elapsed_ms:.0f}ms"
            )
            raise

        elapsed = time.perf_counter() - started
        response.headers[REQUEST_ID_HEADER] = request_id

        if request.url.path not in _UNLOGGED_PATHS:
            message = (
                f"{request.method} {request.url.path} "
                f"{response.status_code} {elapsed * 1000:.0f}ms"
            )
            if elapsed >= SLOW_REQUEST_S:
                # A slow success is the failure mode this app actually has, and
                # at INFO it reads identically to a fast one.
                logger.warning(f"{message} (slow: an upstream fetch likely ran inline)")
            elif response.status_code >= 500:
                logger.error(message)
            elif response.status_code >= 400:
                logger.warning(message)
            else:
                logger.info(message)

        return response


def current_request_id() -> str:
    """The id of the request being served, or "-" outside one."""
    return request_id_var.get()
