"""The last good copy of each live Copernicus cache, kept on disk.

A restart used to empty every cache, and refilling them means re-downloading
from Copernicus — which, on a day CloudFerro is degraded, is how a `--reload`
turns into hours of blank map layers. Each warmer now writes what it fetched
here and restores it at startup, so the previous data is servable in the first
second while a fresh fetch runs behind it.

**The old copy is never deleted before the new one is complete.** There is one
file per key. A write goes to a temporary file in the same directory, is read
back and checked, and only then `os.replace`s the old one — a single atomic
rename, so at every instant the path holds either the whole old file or the
whole new one. A fetch that times out, a crash mid-write, or a file that fails
its read-back leaves the previous copy exactly where it was.

**Arrays, not objects.** Stored with `np.savez` and read with
`allow_pickle=False`. The interpolators and textures are rebuilt from the
arrays on restore rather than pickled: pickle is version-fragile across a
scipy upgrade, and unpickling a file off disk is a code-execution surface.

**Restores report their real age.** Metadata carries the data's own
`timestamp` and the original `fetched_at`; callers restore both and mark the
cache as loaded from disk, so a restart never presents yesterday's grid as a
fresh sync.

**Only restored from `lifespan`, never at import** — tests that set a module's
cache directly would otherwise pick up whatever this machine last downloaded.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

# backend/downloads/copernicus-cache — namespaced so it is not mistaken for the
# Universal Ocean Data Downloader's output. Anchored on this file, not the cwd.
CACHE_DIR = Path(__file__).resolve().parents[2] / "downloads" / "copernicus-cache"

_META_KEY = "__meta__"


def _path(key: str) -> Path:
    if not key.replace("_", "").replace("-", "").replace(".", "").isalnum():
        raise ValueError(f"unsafe disk cache key: {key!r}")
    return CACHE_DIR / f"{key}.npz"


def save(key: str, arrays: dict[str, np.ndarray], meta: dict[str, Any]) -> bool:
    """Atomically replace `key`'s file. Returns False (and keeps the old file)
    on any failure — a disk problem must never cost the in-memory cache."""
    target = _path(key)
    temp = target.with_name(f".{key}.{os.getpid()}.{uuid.uuid4().hex}.tmp.npz")
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = dict(arrays)
        payload[_META_KEY] = np.array(json.dumps(meta))
        with temp.open("wb") as handle:
            np.savez(handle, **payload)
            handle.flush()
            os.fsync(handle.fileno())

        # Read back before it may replace anything: "completely downloaded and
        # servable" is checked, not assumed from a write that returned.
        restored = load(key, path=temp)
        if restored is None or set(restored[0]) != set(arrays):
            raise OSError("read-back of the new cache file did not match what was written")
        for name, array in arrays.items():
            if restored[0][name].shape != array.shape:
                raise OSError(f"read-back shape mismatch for {name}")

        os.replace(temp, target)
        return True
    except Exception:  # noqa: BLE001 - disk failure keeps the previous file
        logger.opt(exception=True).warning(f"disk cache write for {key} failed; previous copy kept")
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def load(key: str, *, path: Path | None = None) -> tuple[dict[str, np.ndarray], dict[str, Any]] | None:
    """`(arrays, meta)` for `key`, or None if there is no usable file."""
    source = path or _path(key)
    if not source.exists():
        return None
    try:
        with np.load(source, allow_pickle=False) as data:
            meta = json.loads(str(data[_META_KEY]))
            arrays = {name: data[name] for name in data.files if name != _META_KEY}
        return arrays, meta
    except Exception:  # noqa: BLE001 - a corrupt file is "no cache", not a crash
        logger.opt(exception=True).warning(f"disk cache for {key} is unreadable; ignoring it")
        return None


def save_json(key: str, payload: dict[str, Any]) -> bool:
    """Same atomic-replace contract for a JSON-only cache (no arrays)."""
    target = CACHE_DIR / f"{key}.json"
    _path(key)  # key validation
    temp = target.with_name(f".{key}.{os.getpid()}.{uuid.uuid4().hex}.tmp.json")
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with temp.open("w") as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        with temp.open() as handle:
            json.load(handle)
        os.replace(temp, target)
        return True
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning(f"disk cache write for {key} failed; previous copy kept")
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def load_json(key: str) -> dict[str, Any] | None:
    _path(key)
    source = CACHE_DIR / f"{key}.json"
    if not source.exists():
        return None
    try:
        with source.open() as handle:
            return json.load(handle)
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning(f"disk cache for {key} is unreadable; ignoring it")
        return None
