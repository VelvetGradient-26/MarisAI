"""services/watch_tokens.py — signed confirm/unsubscribe tokens for
sihtodo.md item 8's proactive alert watches.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.core.config import settings
from services import watch_tokens


@pytest.fixture(autouse=True)
def _secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "WATCH_TOKEN_SECRET", "test-secret-value")


def test_a_valid_token_verifies_to_the_same_subscription_id():
    subscription_id = uuid.uuid4()
    token = watch_tokens.make_token(subscription_id, "confirm", watch_tokens.CONFIRM_TOKEN_TTL)

    assert watch_tokens.verify_token(token, "confirm") == subscription_id


def test_a_token_does_not_verify_for_the_wrong_purpose():
    subscription_id = uuid.uuid4()
    token = watch_tokens.make_token(subscription_id, "confirm", watch_tokens.CONFIRM_TOKEN_TTL)

    assert watch_tokens.verify_token(token, "unsubscribe") is None


def test_a_tampered_token_does_not_verify():
    subscription_id = uuid.uuid4()
    token = watch_tokens.make_token(subscription_id, "confirm", watch_tokens.CONFIRM_TOKEN_TTL)

    assert watch_tokens.verify_token(token + "x", "confirm") is None
    assert watch_tokens.verify_token(token[:-1], "confirm") is None


def test_an_expired_token_does_not_verify():
    subscription_id = uuid.uuid4()
    token = watch_tokens.make_token(subscription_id, "confirm", timedelta(seconds=-1))

    assert watch_tokens.verify_token(token, "confirm") is None


def test_a_token_signed_with_a_different_secret_does_not_verify(monkeypatch: pytest.MonkeyPatch):
    subscription_id = uuid.uuid4()
    token = watch_tokens.make_token(subscription_id, "confirm", watch_tokens.CONFIRM_TOKEN_TTL)

    monkeypatch.setattr(settings, "WATCH_TOKEN_SECRET", "a-different-secret")

    assert watch_tokens.verify_token(token, "confirm") is None


@pytest.mark.parametrize(
    "garbage",
    ["", "no-dot-separator", "not-base64.deadbeef", "."],
)
def test_malformed_tokens_never_raise(garbage: str):
    assert watch_tokens.verify_token(garbage, "confirm") is None


def test_make_token_raises_when_the_secret_is_not_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "WATCH_TOKEN_SECRET", "")

    with pytest.raises(watch_tokens.WatchTokenError, match="not configured"):
        watch_tokens.make_token(uuid.uuid4(), "confirm", watch_tokens.CONFIRM_TOKEN_TTL)


def test_verify_token_raises_when_the_secret_is_not_configured(monkeypatch: pytest.MonkeyPatch):
    """Verification needs the secret too — a bad token and a missing secret
    are different failures, and only the latter should raise (a server
    misconfiguration, not a caller error)."""
    subscription_id = uuid.uuid4()
    token = watch_tokens.make_token(subscription_id, "confirm", watch_tokens.CONFIRM_TOKEN_TTL)

    monkeypatch.setattr(settings, "WATCH_TOKEN_SECRET", "")

    with pytest.raises(watch_tokens.WatchTokenError):
        watch_tokens.verify_token(token, "confirm")
