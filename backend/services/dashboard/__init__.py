"""Dashboard aggregation services.

Each module answers one dashboard section and owns its own error type, in
keeping with the backend convention that services are plain modules rather
than classes. Nothing here fetches from an upstream on request except
`trends`, which is inherently per-request (a point time series over a
user-chosen window); everything else reads the scheduled caches.
"""

from services.dashboard import alerts, health, history, live, summary, trends

__all__ = ["alerts", "health", "history", "live", "summary", "trends"]
