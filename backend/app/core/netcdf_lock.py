"""One process-wide lock around every local NetCDF/HDF5 open.

**The failure this exists for** (2026-09-16, first two production boots after
`git lfs pull` replaced pointer stubs with real grid files): the worker
segfaulted inside `libhdf5` - confirmed via `journalctl` (`ANOM_ABEND ...
sig=11`) - while two threads touched HDF5-backed files at the same instant.
One was a request handler reading a forecast grid directly on the event
loop thread; the other was a background `asyncio.to_thread` job (a cache
refresh, a grid rebuild) reading or writing a different `.nc` file on a
thread-pool worker. `COPERNICUS_MAX_CONCURRENT_FETCHES=1` was tried first
and reduced but did not eliminate the crash, because it only serializes
`app/core/copernicus_io.py`'s dedicated fetch threads - the Copernicus reads
themselves are zarr/S3, not HDF5, so that semaphore was guarding the wrong
door. The actual HDF5 traffic is every local `xr.open_dataset()` /
`Dataset.to_netcdf()` call across `services/` and `forecasting/`.

The pip-distributed `netCDF4`/`h5netcdf` wheels wrap libhdf5 without its
`--enable-threadsafe` build option, so the library has no internal locking
of its own - two threads inside it at once is undefined behavior, not just
a race on Python-level state. A single lock around every call site is the
only fix that holds regardless of which two operations happen to collide;
finer-grained locking would need to know libhdf5's internals well enough to
prove two given calls never share state, which nothing here can promise.

Held only for the syscall-bound duration of an open/read/write - never
across a `yield` or an `await` - so this never blocks the event loop for
longer than the DVD-sized grids here take to read (well under a second).
"""

from __future__ import annotations

import threading

# Re-entrant: some holders call into code that opens another file under the
# same lock (forecast_tiles._derive_grid_from_components reads two grids and
# derives a third). A plain Lock would deadlock the thread against itself.
NETCDF_LOCK = threading.RLock()
