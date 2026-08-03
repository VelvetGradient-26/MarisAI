"""FastAPI dependencies for reading the signed-in user.

`current_user` guards a route; `optional_user` lets a route serve anonymous
callers but personalise for signed-in ones. Both read the httpOnly session
cookie — there is no Authorization-header path, because the frontend never
holds the token in JavaScript.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, HTTPException, Request, status

from app.database.mongo import USERS, MongoUnavailableError, get_database
from services.auth import SESSION_COOKIE_NAME, AuthError, decode_session_token

UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sign in to continue.",
)


async def optional_user(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    try:
        user_id = decode_session_token(token)
    except AuthError:
        # Expired or tampered-with: anonymous, not an error. The stale cookie
        # is cleared the next time the user signs in or out.
        return None

    try:
        object_id = ObjectId(user_id)
    except InvalidId:
        return None

    # Resolved here rather than via Depends(get_mongo_db) on purpose: an
    # anonymous request must not touch Mongo at all, so a misconfigured or
    # unreachable cluster still answers "signed out" with a 401 instead of
    # turning every guarded route into a 503.
    return await get_database()[USERS].find_one({"_id": object_id})


async def current_user(
    user: dict[str, Any] | None = Depends(optional_user),
) -> dict[str, Any]:
    if user is None:
        raise UNAUTHENTICATED
    return user


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    """The subset of a user document that is safe to send to the browser.
    Whitelisted rather than blacklisted so a field added later isn't leaked
    by default."""
    return {
        "id": str(user["_id"]),
        "email": user["email"],
        "name": user.get("name", ""),
        "picture": user.get("picture", ""),
    }


__all__ = [
    "MongoUnavailableError",
    "current_user",
    "optional_user",
    "public_user",
]
