"""Regression tests for the hardening in the security pass.

Each of these encodes a specific weakness that was present and is now closed,
so a future refactor that reopens one fails here rather than in production.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from routers.feedback import FeedbackRequest
from services.rate_limit import RateLimiter


class TestFeedbackValidation:
    def test_rejects_newline_in_name(self):
        """A newline here reached the Subject header, where it is the classic
        SMTP header-injection vector."""
        for payload in ("Bob\r\nBcc: victim@example.com", "Bob\nX-Injected: yes"):
            with pytest.raises(ValidationError):
                FeedbackRequest(name=payload, email="a@example.com", message="hi")

    def test_rejects_null_byte_in_name(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(name="Bob\x00", email="a@example.com", message="hi")

    def test_accepts_ordinary_name(self):
        request = FeedbackRequest(name="  Ada Lovelace  ", email="a@example.com", message="hi")
        assert request.name == "Ada Lovelace"


class TestRateLimiter:
    def test_allows_up_to_the_limit_then_blocks(self):
        limiter = RateLimiter(limit=3, window_seconds=60)
        assert [limiter.check("1.2.3.4") for _ in range(3)] == [None, None, None]
        assert limiter.check("1.2.3.4") is not None

    def test_callers_are_independent(self):
        limiter = RateLimiter(limit=1, window_seconds=60)
        assert limiter.check("1.1.1.1") is None
        assert limiter.check("2.2.2.2") is None
        assert limiter.check("1.1.1.1") is not None

    def test_window_expiry_resets_the_count(self):
        limiter = RateLimiter(limit=1, window_seconds=0.05)
        assert limiter.check("1.2.3.4") is None
        assert limiter.check("1.2.3.4") is not None

        import time

        time.sleep(0.06)
        assert limiter.check("1.2.3.4") is None

    def test_reports_seconds_remaining(self):
        limiter = RateLimiter(limit=1, window_seconds=60)
        limiter.check("1.2.3.4")
        retry_after = limiter.check("1.2.3.4")
        assert retry_after is not None and 0 < retry_after <= 60


class TestCookieSecurity:
    def test_https_frontend_marks_cookies_secure_by_default(self):
        """The failure this prevents is silent: an HTTPS deployment that never
        set COOKIE_SECURE used to ship session cookies without the flag."""
        settings = Settings(FRONTEND_BASE_URL="https://marisai.example.com")
        assert settings.cookie_secure is True

    def test_http_dev_frontend_does_not(self):
        # Marking them Secure over plain http stops the browser storing them,
        # which would break local sign-in entirely.
        settings = Settings(FRONTEND_BASE_URL="http://localhost:5173")
        assert settings.cookie_secure is False

    def test_explicit_setting_overrides_the_inference(self):
        settings = Settings(FRONTEND_BASE_URL="https://marisai.example.com", COOKIE_SECURE=False)
        assert settings.cookie_secure is False


class TestSessionSecret:
    def test_short_secret_refuses_to_sign(self):
        """Signing with a weak key would appear to work while issuing tokens
        that can be forged offline — so this must fail loudly, not degrade."""
        import app.core.config as config_module
        from services.auth import AuthNotConfiguredError, issue_session_token

        saved = config_module.settings.SESSION_SECRET
        try:
            config_module.settings.SESSION_SECRET = "tooshort"
            with pytest.raises(AuthNotConfiguredError):
                issue_session_token("507f1f77bcf86cd799439011")
        finally:
            config_module.settings.SESSION_SECRET = saved

    def test_adequate_secret_signs_and_verifies(self):
        import app.core.config as config_module
        from services.auth import decode_session_token, issue_session_token

        saved = config_module.settings.SESSION_SECRET
        try:
            config_module.settings.SESSION_SECRET = "a" * 64
            token = issue_session_token("507f1f77bcf86cd799439011")
            assert decode_session_token(token) == "507f1f77bcf86cd799439011"
        finally:
            config_module.settings.SESSION_SECRET = saved

    def test_token_signed_with_a_different_secret_is_rejected(self):
        import app.core.config as config_module
        from services.auth import AuthError, decode_session_token, issue_session_token

        saved = config_module.settings.SESSION_SECRET
        try:
            config_module.settings.SESSION_SECRET = "a" * 64
            forged = issue_session_token("507f1f77bcf86cd799439011")
            config_module.settings.SESSION_SECRET = "b" * 64
            with pytest.raises(AuthError):
                decode_session_token(forged)
        finally:
            config_module.settings.SESSION_SECRET = saved
