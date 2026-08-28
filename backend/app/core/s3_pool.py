"""Widen botocore's connection pool for the Copernicus zarr reads.

The symptom is a WARNING, once or twice a second for the length of every
Copernicus fetch:

    urllib3.connectionpool:_put_conn - Connection pool is full, discarding
    connection: s3.waw3-1.cloudferro.com. Connection pool size: 10

**Nothing is lost — but it is not free either.** The discarded object is the
*connection*, not the chunk; urllib3 closes a socket it has no room to keep
instead of returning it to the pool, and the read succeeds. What it costs is a
fresh TCP + TLS handshake for the next request that would have reused it, on a
path that issues thousands of range requests per fetch.

**The cause is upstream and has no setting.** copernicusmarine builds its S3
client in `core_functions/sessions.py::get_configured_boto3_session`, passing
`botocore.config.Config` only `signature_version` and `retries`, so
`max_pool_connections` falls back to botocore's default of 10 — while the zarr
read fans out over dask's thread pool, which is wider than that on any machine
here. There is no `COPERNICUSMARINE_*` variable for it (the environment knobs
that module reads are SSL, timeout, retries and trust-env) and no argument
threaded down from `open_dataset`.

So the lever is botocore's own default, which is a **mutable class attribute**
read when a `Config` is constructed rather than a constant baked in at import.
Rewriting the entry changes what every client built *without* an explicit
`max_pool_connections` gets — which is exactly copernicusmarine's — and changes
nothing for a caller that sets one. It must run before the first client is
built; copernicusmarine constructs its session lazily on the first dataset open,
so calling this at import time in `main.py` (or at the top of a script) is early
enough.

The alternative — raising the `urllib3` threshold in `app/core/logging.py` to
ERROR — was rejected: it hides the noise by hiding every urllib3 warning,
including the retry and connection-error lines that are worth reading when
CloudFerro flaps, and it leaves the handshakes in place.
"""

from __future__ import annotations

import botocore.config
from loguru import logger

# Sized against the fan-out, not against a guess at "big". dask's threaded
# scheduler defaults to one worker per core and each worker holds one connection
# in flight, so a pool a few times the core count absorbs the burst without
# leaving many sockets idle. Pool entries are created on demand — this is a
# ceiling, not an allocation.
DEFAULT_MAX_POOL_CONNECTIONS = 32

_applied = False


def widen_s3_connection_pool(size: int = DEFAULT_MAX_POOL_CONNECTIONS) -> None:
    """Raise the default `max_pool_connections` for new botocore clients.

    Idempotent, and never fatal: a botocore that stopped exposing
    `OPTION_DEFAULTS` would be a cosmetic regression here, not a reason to fail
    a server boot or a 40-minute training run.
    """
    global _applied
    if _applied:
        return

    defaults = getattr(botocore.config.Config, "OPTION_DEFAULTS", None)
    if defaults is None or "max_pool_connections" not in defaults:
        logger.warning(
            "botocore.config.Config.OPTION_DEFAULTS no longer carries "
            "max_pool_connections; leaving the S3 pool at its default"
        )
        return

    defaults["max_pool_connections"] = size
    _applied = True
