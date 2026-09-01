"""Per-user record of download requests.

Metadata only — the exported file itself is never stored. A CSV/PDF export runs
to megabytes, and keeping them would exhaust the free 512 MB tier in a few
dozen requests; a record here is ~500 bytes. Re-running a past request is
cheaper than warehousing its output anyway.

Failed attempts are recorded too: "why did that request not work" is most of
what a history view is for.

Like `saved_locations.py`, every query is scoped by `userId`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from loguru import logger
from pymongo import DESCENDING
from pymongo.asynchronous.database import AsyncDatabase

from app.database.mongo import DOWNLOAD_HISTORY
from services.download.models import DownloadRequest

# Rolling window per user. Old entries are trimmed on insert rather than by a
# TTL index, so the cap is on count (predictable storage) rather than age.
MAX_HISTORY_PER_USER = 200


def _serialize(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(document["_id"]),
        "requestedAt": document["requestedAt"].isoformat(),
        "status": document["status"],
        "area": document["area"],
        "startDate": document["startDate"],
        "endDate": document["endDate"],
        "resolution": document["resolution"],
        "variables": document["variables"],
        "format": document["format"],
        "depthM": document.get("depthM", 0.0),
        "filename": document.get("filename"),
        "sizeBytes": document.get("sizeBytes"),
        "errorMessage": document.get("errorMessage"),
    }


async def record_download(
    db: AsyncDatabase,
    user_id: ObjectId,
    request: DownloadRequest,
    *,
    status: str,
    filename: str | None = None,
    size_bytes: int | None = None,
    error_message: str | None = None,
) -> None:
    """Best-effort: a history-write failure must never turn a download the user
    already has into an error response."""
    document = {
        "userId": user_id,
        "requestedAt": datetime.now(timezone.utc),
        "status": status,
        "area": request.area.model_dump(mode="json"),
        "startDate": request.start_date.isoformat(),
        "endDate": request.end_date.isoformat(),
        "resolution": request.resolution.value,
        "variables": list(request.variables),
        "format": request.format.value,
        "depthM": request.depth_m,
        "filename": filename,
        "sizeBytes": size_bytes,
        "errorMessage": error_message,
    }

    try:
        await db[DOWNLOAD_HISTORY].insert_one(document)
        await _trim_history(db, user_id)
    except Exception as exc:  # noqa: BLE001 - never fail the download over this
        logger.warning(f"Could not record download history: {exc}")


async def _trim_history(db: AsyncDatabase, user_id: ObjectId) -> None:
    count = await db[DOWNLOAD_HISTORY].count_documents({"userId": user_id})
    excess = count - MAX_HISTORY_PER_USER
    if excess <= 0:
        return

    cursor = (
        db[DOWNLOAD_HISTORY]
        .find({"userId": user_id}, {"_id": 1})
        .sort("requestedAt", 1)
        .limit(excess)
    )
    stale_ids = [document["_id"] async for document in cursor]
    if stale_ids:
        await db[DOWNLOAD_HISTORY].delete_many({"_id": {"$in": stale_ids}, "userId": user_id})


async def list_download_history(
    db: AsyncDatabase,
    user_id: ObjectId,
    limit: int = 50,
) -> list[dict[str, Any]]:
    cursor = (
        db[DOWNLOAD_HISTORY]
        .find({"userId": user_id})
        .sort("requestedAt", DESCENDING)
        .limit(limit)
    )
    return [_serialize(document) async for document in cursor]
