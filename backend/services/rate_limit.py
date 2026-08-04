"""In-memory fixed-window rate limiting.

Hand-rolled rather than pulling in slowapi, matching how the rest of this
codebase treats single-purpose dependencies. That choice comes with a real
constraint worth stating: counters live in this process's memory, so the
limit is **per worker**, not per cluster. Running N uvicorn workers means the
effective limit is N times what is configured here. For a deployment that
needs a true global limit, this is the piece to replace with something
backed by Redis or Mongo — the call sites should not have to change.

Fixed windows, not a sliding log: a caller can burst up to 2x the limit
across a window boundary. That is acceptable for abuse control (the point is
to stop unbounded automated hammering, not to meter precisely) and it keeps
the bookkeeping to one integer per caller instead of a list of timestamps.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from fastapi import HTTPException, Request, status


@dataclass
class _Window:
    started_at: float
    count: int


@dataclass
class RateLimiter:
    """Allows `limit` requests per `window_seconds` per key."""

    limit: int
    window_seconds: float
    _hits: dict[str, _Window] = field(default_factory=dict)
    # Stale keys are swept during check() rather than by a background task,
    # so an idle process holds nothing and there is no timer to shut down.
    _last_sweep: float = 0.0

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < self.window_seconds:
            return
        self._last_sweep = now
        expired = [
            key
            for key, window in self._hits.items()
            if now - window.started_at >= self.window_seconds
        ]
        for key in expired:
            del self._hits[key]

    def check(self, key: str) -> float | None:
        """Records a hit. Returns None if allowed, or the seconds remaining in
        the current window if the caller is over the limit."""
        now = time.monotonic()
        self._sweep(now)

        window = self._hits.get(key)
        if window is None or now - window.started_at >= self.window_seconds:
            self._hits[key] = _Window(started_at=now, count=1)
            return None

        window.count += 1
        if window.count > self.limit:
            return self.window_seconds - (now - window.started_at)
        return None


def client_key(request: Request) -> str:
    """Best-effort caller identity.

    Behind a proxy the socket address is the proxy's, so the leftmost
    X-Forwarded-For entry is used when present. That header is client-supplied
    and trivially spoofed, which means this is an abuse-control heuristic, not
    an authorization boundary — never gate anything security-critical on it.
    Deployments that terminate TLS at a trusted proxy should run uvicorn with
    --proxy-headers so request.client reflects the real peer.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def enforce(
    limiter: RateLimiter, request: Request, message: str, key: str | None = None
) -> None:
    """Applies `limiter` to this request. Pass `key` to limit by something
    stronger than the caller's address — a user id, for an authenticated
    endpoint, cannot be rotated by changing networks the way an IP can."""
    retry_after = limiter.check(key or client_key(request))
    if retry_after is None:
        return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=message,
        headers={"Retry-After": str(max(1, int(retry_after)))},
    )
