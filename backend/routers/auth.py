"""Google sign-in endpoints.

Thin, per the router convention: the OAuth mechanics live in `services/auth.py`
and this module only translates them into redirects, cookies and status codes.

`/login` and `/callback` are visited by the browser directly (they are
redirects, not fetches), so failures there redirect back to the frontend with
an `?auth_error=` message rather than returning JSON the user would see as a
raw error page.
"""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import settings
from app.database.mongo import get_mongo_db
from dependencies.auth import current_user, public_user
from services.auth import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    AuthError,
    build_authorization_url,
    exchange_code,
    issue_session_token,
    new_state,
    upsert_user,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

STATE_COOKIE_NAME = "marisai_oauth_state"
STATE_MAX_AGE_SECONDS = 600


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        # Lax, not None: it is the only CSRF defence here, and it works
        # because every mutating endpoint is a POST. See services/auth.py.
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def _frontend_redirect(error: str | None = None) -> RedirectResponse:
    target = settings.FRONTEND_BASE_URL.rstrip("/") + "/"
    if error:
        target += "?" + urlencode({"auth_error": error})
    return RedirectResponse(target, status_code=status.HTTP_302_FOUND)


@router.get("/login")
async def login() -> RedirectResponse:
    state = new_state()
    try:
        authorization_url = build_authorization_url(state)
    except AuthError as exc:
        return _frontend_redirect(str(exc))

    response = RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)
    # Google echoes `state` back to /callback; comparing it against this cookie
    # is what proves the callback belongs to a flow this browser actually
    # started, rather than one an attacker triggered.
    response.set_cookie(
        STATE_COOKIE_NAME,
        state,
        max_age=STATE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    db: AsyncDatabase = Depends(get_mongo_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    # The user hit "Cancel" on Google's consent screen.
    if error:
        return _frontend_redirect("Sign-in was cancelled.")

    expected_state = request.cookies.get(STATE_COOKIE_NAME)
    # compare_digest rather than ==: the comparison is against a value the
    # caller supplies, and a short-circuiting compare leaks how much of the
    # state it guessed correctly.
    if (
        not code
        or not state
        or not expected_state
        or not secrets.compare_digest(state, expected_state)
    ):
        return _frontend_redirect("Sign-in could not be verified. Please try again.")

    try:
        claims = await exchange_code(code)
        user = await upsert_user(db, claims)
        token = issue_session_token(str(user["_id"]))
    except AuthError as exc:
        return _frontend_redirect(str(exc))

    response = _frontend_redirect()
    _set_session_cookie(response, token)
    response.delete_cookie(STATE_COOKIE_NAME, path="/")
    return response


@router.post("/logout")
async def logout() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    # Only clears this browser's cookie — sessions are stateless, so an
    # already-issued token stays valid until it expires (see services/auth.py).
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@router.get("/me")
async def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return public_user(user)
