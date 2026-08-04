"""Google OAuth sign-in and session tokens.

The authorization-code flow runs entirely server-side: the browser is only ever
redirected, and `GOOGLE_CLIENT_SECRET` never leaves this process. That matches
how every other external credential in this codebase is handled (Copernicus,
GFW, aisstream) — the client gets results, never keys.

Sessions are stateless: a signed JWT in an httpOnly cookie, no server-side
session collection. Consequences worth knowing before changing anything here:

  * There is no revocation. Signing out clears the cookie in that browser, but
    a token captured beforehand stays valid until `exp`. Adding real revocation
    means a Mongo read on every authenticated request, which is why it isn't
    here at this scale. Rotating `SESSION_SECRET` invalidates all sessions.
  * CSRF protection is `SameSite=Lax` on the cookie (set in routers/auth.py),
    which is sufficient only because every mutating endpoint is a POST. A
    mutating GET would silently defeat it.

Signing uses `joserfc` rather than `authlib.jose`: the latter is deprecated in
Authlib >= 1.6 and joserfc is already in the tree as an Authlib dependency.
"""

from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet, OctKey
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import settings
from app.database.mongo import USERS

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "marisai_session"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60

# HS256 session tokens are only as strong as this key. A short one is
# brute-forceable offline from a single captured cookie, and forging a token
# means picking any user id — full account takeover, with no way to notice.
# 32 characters is the floor for the 256-bit output `openssl rand -hex 32`
# produces, which is what the config comment tells you to generate.
MIN_SESSION_SECRET_LENGTH = 32

# Google rotates its signing keys infrequently; refetching the JWKS on every
# sign-in would add a round trip for no benefit.
_JWKS_TTL_SECONDS = 3600
_jwks_cache: tuple[float, KeySet] | None = None


class AuthError(RuntimeError):
    """Sign-in failed. Mapped to a real status code by routers/auth.py — a raw
    httpx/joserfc exception must never reach the client."""


class AuthNotConfiguredError(AuthError):
    """The deployment has no Google OAuth credentials (503, not 500)."""


def _require_oauth_config() -> None:
    """Needed only to talk to Google. Kept separate from the session-secret
    check so sessions keep working on a deployment that has rotated its Google
    client but not its cookie key, and vice versa."""
    missing = [
        name
        for name, value in (
            ("GOOGLE_CLIENT_ID", settings.GOOGLE_CLIENT_ID),
            ("GOOGLE_CLIENT_SECRET", settings.GOOGLE_CLIENT_SECRET),
        )
        if not value
    ]
    if missing:
        raise AuthNotConfiguredError(
            f"Google sign-in is not configured on this server (missing: {', '.join(missing)})."
        )


def _session_key() -> OctKey:
    if not settings.SESSION_SECRET:
        raise AuthNotConfiguredError(
            "Sign-in is not configured on this server (missing: SESSION_SECRET)."
        )
    if len(settings.SESSION_SECRET) < MIN_SESSION_SECRET_LENGTH:
        # Refusing to sign is the safe failure: sign-in breaks loudly instead
        # of appearing to work while issuing forgeable tokens.
        raise AuthNotConfiguredError(
            "Sign-in is misconfigured on this server (SESSION_SECRET is too short)."
        )
    return OctKey.import_key(settings.SESSION_SECRET)


# --- Step 1: send the browser to Google ------------------------------------


def new_state() -> str:
    return secrets.token_urlsafe(32)


def build_authorization_url(state: str) -> str:
    """The URL to 302 the browser to. `state` is echoed back by Google and must
    be compared against the copy stashed in the state cookie — that comparison
    is what stops a third party from feeding us their own callback."""
    _require_oauth_config()
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        # No refresh token wanted: we never call Google APIs on the user's
        # behalf after sign-in, so there's nothing to keep alive.
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"


# --- Step 2: exchange the code and verify the ID token ----------------------


async def _fetch_jwks() -> KeySet:
    global _jwks_cache
    now = time.time()
    if _jwks_cache is not None and now - _jwks_cache[0] < _JWKS_TTL_SECONDS:
        return _jwks_cache[1]

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(GOOGLE_JWKS_URL)
        response.raise_for_status()
        key_set = KeySet.import_key_set(response.json())

    _jwks_cache = (now, key_set)
    return key_set


async def exchange_code(code: str) -> dict[str, Any]:
    """Trade the authorization code for an ID token and return its *verified*
    claims. Every field the caller goes on to store comes from here, so the
    signature/issuer/audience checks below are the whole security boundary —
    an unverified `id_token` payload is attacker-controlled."""
    _require_oauth_config()

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.OAUTH_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as exc:
        # These messages are rendered into a redirect URL the user sees, so
        # the upstream text is logged rather than echoed.
        logger.warning(f"Google token exchange failed: {exc}")
        raise AuthError("Could not reach Google to complete sign-in.") from exc

    if response.status_code != 200:
        raise AuthError("Google rejected the sign-in attempt.")

    id_token = response.json().get("id_token")
    if not id_token:
        raise AuthError("Google's response did not include an ID token.")

    try:
        key_set = await _fetch_jwks()
    except httpx.HTTPError as exc:
        logger.warning(f"Could not fetch Google JWKS: {exc}")
        raise AuthError("Could not verify the sign-in with Google.") from exc

    try:
        # Algorithm pinned: accepting whatever the token's own header asks for
        # is how algorithm-confusion attacks get in.
        token = jwt.decode(id_token, key_set, algorithms=["RS256"])
        claims_registry = jwt.JWTClaimsRegistry(
            iss={"essential": True, "values": list(GOOGLE_ISSUERS)},
            aud={"essential": True, "value": settings.GOOGLE_CLIENT_ID},
            exp={"essential": True},
            sub={"essential": True},
        )
        claims_registry.validate(token.claims)
    except JoseError as exc:
        logger.warning(f"Google ID token failed verification: {exc}")
        raise AuthError("Google's sign-in response could not be verified.") from exc

    claims = token.claims
    if not claims.get("email"):
        raise AuthError("Google did not return an email address for this account.")
    # Google sets this false for unverified addresses on some account types;
    # trusting one would let someone claim an address they don't control.
    if claims.get("email_verified") is False:
        raise AuthError("This Google account's email address is not verified.")

    return claims


# --- Step 3: persist the user ----------------------------------------------


async def upsert_user(db: AsyncDatabase, claims: dict[str, Any]) -> dict[str, Any]:
    """Create-or-update keyed on `sub`, Google's stable per-user identifier.
    Deliberately not keyed on email: users can change their Google address, and
    matching on it would silently hand one account to a different person."""
    now = datetime.now(timezone.utc)
    return await db[USERS].find_one_and_update(
        {"googleSub": claims["sub"]},
        {
            "$setOnInsert": {"googleSub": claims["sub"], "createdAt": now},
            "$set": {
                "email": claims["email"],
                "name": claims.get("name") or claims["email"].split("@")[0],
                "picture": claims.get("picture", ""),
                "lastLoginAt": now,
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


# --- Session tokens ---------------------------------------------------------


def issue_session_token(user_id: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"alg": "HS256", "typ": "JWT"},
        {"sub": user_id, "iat": now, "exp": now + SESSION_MAX_AGE_SECONDS},
        _session_key(),
    )


def decode_session_token(token: str) -> str:
    """Return the user id, or raise. Callers treat any AuthError here as
    "not signed in" — never as a server error."""
    try:
        decoded = jwt.decode(token, _session_key(), algorithms=["HS256"])
        jwt.JWTClaimsRegistry(exp={"essential": True}, sub={"essential": True}).validate(
            decoded.claims
        )
    except JoseError as exc:
        raise AuthError("Session is invalid or has expired.") from exc

    user_id = decoded.claims.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise AuthError("Session is invalid or has expired.")
    return user_id
