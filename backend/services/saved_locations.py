"""Per-user saved map locations.

Every query here is scoped by `userId` as well as `_id`. Filtering on the
document id alone would let anyone who guessed an ObjectId read or delete
another account's data — the scoping is the authorization check, so it must
never be dropped as "redundant".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import DESCENDING
from pymongo.asynchronous.database import AsyncDatabase

from app.database.mongo import SAVED_LOCATIONS

# Storage is not the real constraint (a document is ~150 bytes against a
# 512 MB tier), but an unbounded per-user list is still a free write
# amplifier for anyone with a session.
MAX_SAVED_PER_USER = 100


class SavedLocationError(RuntimeError):
    pass


class SavedLocationLimitError(SavedLocationError):
    pass


class SavedLocationNotFoundError(SavedLocationError):
    pass


def _serialize(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(document["_id"]),
        "label": document["label"],
        "lat": document["lat"],
        "lon": document["lon"],
        "createdAt": document["createdAt"].isoformat(),
    }


async def list_saved_locations(db: AsyncDatabase, user_id: ObjectId) -> list[dict[str, Any]]:
    cursor = db[SAVED_LOCATIONS].find({"userId": user_id}).sort("createdAt", DESCENDING)
    return [_serialize(document) async for document in cursor]


async def create_saved_location(
    db: AsyncDatabase,
    user_id: ObjectId,
    label: str,
    lat: float,
    lon: float,
) -> dict[str, Any]:
    count = await db[SAVED_LOCATIONS].count_documents({"userId": user_id})
    if count >= MAX_SAVED_PER_USER:
        raise SavedLocationLimitError(
            f"You've reached the limit of {MAX_SAVED_PER_USER} saved locations. "
            "Delete one to save another."
        )

    document = {
        "userId": user_id,
        "label": label,
        "lat": lat,
        "lon": lon,
        "createdAt": datetime.now(timezone.utc),
    }
    result = await db[SAVED_LOCATIONS].insert_one(document)
    document["_id"] = result.inserted_id
    return _serialize(document)


async def delete_saved_location(
    db: AsyncDatabase,
    user_id: ObjectId,
    location_id: str,
) -> None:
    try:
        object_id = ObjectId(location_id)
    except InvalidId as exc:
        raise SavedLocationNotFoundError("That saved location does not exist.") from exc

    result = await db[SAVED_LOCATIONS].delete_one({"_id": object_id, "userId": user_id})
    if result.deleted_count == 0:
        # Deliberately the same message whether the id is unknown or belongs to
        # someone else — distinguishing them would confirm the existence of
        # another user's records.
        raise SavedLocationNotFoundError("That saved location does not exist.")
