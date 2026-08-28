"""Signed, purpose-scoped tokens for confirm/unsubscribe links (sihtodo.md
item 8).

**Why a token independent of `client_id` exists at all.** `client_id` is a
browser-generated UUID that scopes a person's own history on their own
machine — explicitly not access control (see `app/models/chat/session.py`).
A subscription row carries a *delivery target* (an email address), which
raises the stakes past what a transcript does: if creating or confirming a
watch were gated only on knowing a `client_id`, a guessable UUID could be
used to spam an address of the caller's choosing. The confirm link proves
the recipient actually controls the mailbox (double opt-in); the unsubscribe
link must keep working for as long as the subscription might send mail,
without requiring the original browser's `client_id` at all — someone
reading the email on a different device must be able to unsubscribe.

**Hand-rolled with stdlib `hmac`/`hashlib`, not a new dependency.** No
signed-token library (itsdangerous, pyjwt, ...) exists anywhere in this
backend already, and a purpose-scoped, timed, HMAC-signed token is a small
enough primitive that adding one matches this codebase's standing
preference for stdlib over a new package for a narrow need — the same
choice `services/webpage.py` made for HTML parsing and
`services/severe_weather.py` made for CAP XML.

Token shape: `base64url(payload) + "." + hex(hmac_sha256(payload))`, where
`payload = "<subscription_id>:<purpose>:<expires_at_epoch_seconds>"`. The
signature covers the purpose and expiry, not just the id — a confirm token
must not verify as an unsubscribe token, and an expired token must not
verify at all, no matter how it is presented.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from app.core.config import settings

logger = logging.getLogger(__name__)

Purpose = Literal["confirm", "unsubscribe"]

CONFIRM_TOKEN_TTL = timedelta(hours=24)
# Must keep working for as long as the subscription might send mail — a
# year is generous without being "forever" (a genuinely abandoned
# subscription's unsubscribe link should not remain valid indefinitely).
UNSUBSCRIBE_TOKEN_TTL = timedelta(days=365)


class WatchTokenError(RuntimeError):
    """`WATCH_TOKEN_SECRET` is not configured."""


def _secret() -> bytes:
    if not settings.WATCH_TOKEN_SECRET:
        raise WatchTokenError(
            "Alert watches are not configured (set WATCH_TOKEN_SECRET in backend/.env)."
        )
    return settings.WATCH_TOKEN_SECRET.encode("utf-8")


def _sign(payload: bytes) -> str:
    return hmac.new(_secret(), payload, hashlib.sha256).hexdigest()


def make_token(subscription_id: uuid.UUID, purpose: Purpose, ttl: timedelta) -> str:
    expires_at = int((datetime.now(timezone.utc) + ttl).timestamp())
    payload = f"{subscription_id}:{purpose}:{expires_at}".encode("utf-8")
    signature = _sign(payload)
    encoded_payload = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"{encoded_payload}.{signature}"


def verify_token(token: str, purpose: Purpose) -> uuid.UUID | None:
    """Returns the subscription id if `token` is a validly signed,
    unexpired token for exactly `purpose` — `None` for anything else
    (malformed, wrong purpose, expired, bad signature). Never raises on a
    bad token; only raises `WatchTokenError` if the secret itself is
    unconfigured, since that is a server misconfiguration, not a bad token.
    """
    try:
        encoded_payload, signature = token.split(".", 1)
        padding = "=" * (-len(encoded_payload) % 4)
        payload = base64.urlsafe_b64decode(encoded_payload + padding)
    except (ValueError, TypeError):
        return None

    expected_signature = _sign(payload)
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        raw_id, token_purpose, expires_at_str = payload.decode("utf-8").split(":", 2)
        subscription_id = uuid.UUID(raw_id)
        expires_at = int(expires_at_str)
    except (ValueError, TypeError):
        return None

    if token_purpose != purpose:
        return None
    if datetime.now(timezone.utc).timestamp() > expires_at:
        return None

    return subscription_id
