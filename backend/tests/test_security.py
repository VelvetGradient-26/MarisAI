"""Regression tests for the hardening in the security pass.

Each of these encodes a specific weakness that was present and is now closed,
so a future refactor that reopens one fails here rather than in production.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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


class TestInsightsPromptBounds:
    """Every field here is pasted into an LLM prompt and paid for per token,
    so an unbounded string is both an injection surface and an open bill."""

    def test_rejects_oversized_metric_value(self):
        from routers.insights import GenerateInsightsRequest

        with pytest.raises(ValidationError):
            GenerateInsightsRequest(current={"sea_surface_temperature": "x" * 5000})

    def test_rejects_too_many_metrics(self):
        from routers.insights import GenerateInsightsRequest

        with pytest.raises(ValidationError):
            GenerateInsightsRequest(current={f"k{i}": 1.0 for i in range(500)})

    def test_rejects_oversized_location_text(self):
        from routers.insights import GenerateInsightsRequest, LocationContext

        with pytest.raises(ValidationError):
            GenerateInsightsRequest(
                current={"sea_surface_temperature": 21.5},
                location_context=LocationContext(ocean_name="y" * 5000),
            )

    def test_rejects_out_of_range_coordinates(self):
        from routers.insights import RequestedPoint

        with pytest.raises(ValidationError):
            RequestedPoint(latitude=91.0, longitude=0.0)

    def test_accepts_a_realistic_payload(self):
        from routers.insights import GenerateInsightsRequest, LocationContext, RequestedPoint

        request = GenerateInsightsRequest(
            current={"sea_surface_temperature": 28.9, "wind_speed": 23.5},
            units={"sea_surface_temperature": "°C"},
            location_context=LocationContext(ocean_name="Arabian Sea"),
            requested=RequestedPoint(latitude=14.3, longitude=70.7),
        )
        assert request.location_context is not None
        assert request.location_context.ocean_name == "Arabian Sea"


class TestProviderErrorsAreNotForwarded:
    def test_provider_body_is_withheld_from_the_message(self):
        """Gemini takes the API key as a URL query parameter, so a provider
        error body is exactly the wrong thing to hand to a browser."""
        import httpx

        from services.llm import _provider_failure

        response = httpx.Response(
            401,
            text='{"error":{"message":"API key not valid: AIzaSyLEAKED_KEY_VALUE"}}',
            request=httpx.Request("POST", "https://example.invalid/v1/models/x:generateContent"),
        )
        error = _provider_failure("Gemini", response)

        assert "AIzaSyLEAKED_KEY_VALUE" not in str(error)
        assert "401" in str(error)


class TestPublicBaseUrl:
    def test_public_base_url_drives_email_links_and_cors(self):
        from app.core.config import Settings

        configured = Settings(PUBLIC_BASE_URL="http://13.0.0.1", _env_file=None)
        assert configured.FRONTEND_BASE_URL == "http://13.0.0.1"
        assert configured.cors_origins == ["http://13.0.0.1"]

    def test_explicit_url_wins_over_ec2_metadata(self, monkeypatch):
        from app.core import public_url

        monkeypatch.setattr(public_url.settings, "PUBLIC_BASE_URL", "http://example.test")
        monkeypatch.setattr(public_url.settings, "PUBLIC_BASE_URL_FROM_EC2", True)
        public_url.public_base_url.cache_clear()
        assert public_url.public_base_url() == "http://example.test"

    def test_ec2_metadata_supplies_the_url_when_enabled(self, monkeypatch):
        import httpx

        from app.core import public_url

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "PUT" and request.url.path == "/latest/api/token":
                return httpx.Response(200, text="tok")
            if request.url.path == "/latest/meta-data/public-ipv4":
                assert request.headers["X-aws-ec2-metadata-token"] == "tok"
                return httpx.Response(200, text="13.233.129.231")
            return httpx.Response(404)

        monkeypatch.setattr(public_url.settings, "PUBLIC_BASE_URL", None)
        monkeypatch.setattr(public_url.settings, "PUBLIC_BASE_URL_FROM_EC2", True)
        monkeypatch.setattr(public_url, "_TRANSPORT", httpx.MockTransport(handler))
        public_url.public_base_url.cache_clear()
        assert public_url.public_base_url() == "http://13.233.129.231"

    def test_unreachable_metadata_falls_back_to_frontend_base_url(self, monkeypatch):
        import httpx

        from app.core import public_url

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no IMDS here")

        monkeypatch.setattr(public_url.settings, "PUBLIC_BASE_URL", None)
        monkeypatch.setattr(public_url.settings, "PUBLIC_BASE_URL_FROM_EC2", True)
        monkeypatch.setattr(public_url.settings, "FRONTEND_BASE_URL", "http://localhost:5173")
        monkeypatch.setattr(public_url, "_TRANSPORT", httpx.MockTransport(handler))
        public_url.public_base_url.cache_clear()
        assert public_url.public_base_url() == "http://localhost:5173"
