"""Session-token tests.

Deliberately limited to the pure functions: issuing and decoding a session
token needs no Mongo, no network and no Google. The OAuth exchange itself is
covered by the manual sign-in walkthrough in the plan, since faking Google's
JWKS well enough to be meaningful would mostly test the fake.
"""

import time

import pytest

from services import auth
from services.auth import AuthError, decode_session_token, issue_session_token

SECRET = "0" * 64
OTHER_SECRET = "f" * 64
USER_ID = "6a70270c973668ca35b816a6"


@pytest.fixture(autouse=True)
def _session_secret(monkeypatch):
    monkeypatch.setattr(auth.settings, "SESSION_SECRET", SECRET)


def test_round_trip_returns_the_user_id():
    assert decode_session_token(issue_session_token(USER_ID)) == USER_ID


def test_rejects_a_tampered_payload():
    token = issue_session_token(USER_ID)
    header, payload, signature = token.split(".")
    # Same signature, different payload — the case a bare base64 decode would
    # happily accept.
    other = issue_session_token("6a70270c973668ca35b816ff")
    forged = f"{header}.{other.split('.')[1]}.{signature}"

    with pytest.raises(AuthError):
        decode_session_token(forged)


def test_rejects_a_token_signed_with_a_different_secret(monkeypatch):
    monkeypatch.setattr(auth.settings, "SESSION_SECRET", OTHER_SECRET)
    foreign_token = issue_session_token(USER_ID)

    monkeypatch.setattr(auth.settings, "SESSION_SECRET", SECRET)
    with pytest.raises(AuthError):
        decode_session_token(foreign_token)


def test_rejects_an_expired_token(monkeypatch):
    # Issue the token as though it were created a full lifetime + 1s ago.
    real_time = time.time
    monkeypatch.setattr(
        auth.time, "time", lambda: real_time() - auth.SESSION_MAX_AGE_SECONDS - 1
    )
    expired = issue_session_token(USER_ID)
    monkeypatch.setattr(auth.time, "time", real_time)

    with pytest.raises(AuthError):
        decode_session_token(expired)


def test_rejects_garbage():
    for value in ("", "not-a-token", "a.b.c"):
        with pytest.raises(AuthError):
            decode_session_token(value)


def test_issuing_without_a_configured_secret_is_an_auth_error(monkeypatch):
    monkeypatch.setattr(auth.settings, "SESSION_SECRET", "")
    with pytest.raises(AuthError):
        issue_session_token(USER_ID)
