"""fetch_webpage's fetch/extract logic and its SSRF guard.

No network and no real DNS: `_resolve_addresses` is monkeypatched directly so
the SSRF checks are deterministic, and the HTTP layer is a stub transport —
the same two seams `test_cyclones.py` and `test_download_gebco.py` each use
on their own.
"""

from __future__ import annotations

import httpx
import pytest

from services import webpage


def _install_transport(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(webpage.httpx, "AsyncClient", patched)


def _install_dns(monkeypatch, by_host: dict[str, list[str]], default: list[str]):
    async def fake(host: str) -> list[str]:
        return by_host.get(host, default)

    monkeypatch.setattr(webpage, "_resolve_addresses", fake)


def _install_public_dns(monkeypatch):
    _install_dns(monkeypatch, {}, ["93.184.216.34"])  # a real public address


@pytest.mark.asyncio
async def test_a_private_address_is_rejected(monkeypatch):
    _install_dns(monkeypatch, {}, ["10.0.0.5"])

    with pytest.raises(webpage.WebpageError):
        await webpage.fetch("http://internal.example/")


@pytest.mark.asyncio
async def test_a_loopback_address_is_rejected(monkeypatch):
    _install_dns(monkeypatch, {}, ["127.0.0.1"])

    with pytest.raises(webpage.WebpageError):
        await webpage.fetch("http://localhost:8000/admin")


@pytest.mark.asyncio
async def test_a_link_local_metadata_address_is_rejected(monkeypatch):
    """169.254.169.254 is the cloud-metadata endpoint SSRF guards exist for."""
    _install_dns(monkeypatch, {}, ["169.254.169.254"])

    with pytest.raises(webpage.WebpageError):
        await webpage.fetch("http://169.254.169.254/latest/meta-data/")


@pytest.mark.asyncio
async def test_a_non_http_scheme_is_rejected(monkeypatch):
    _install_public_dns(monkeypatch)

    with pytest.raises(webpage.WebpageError):
        await webpage.fetch("file:///etc/passwd")


@pytest.mark.asyncio
async def test_an_empty_url_is_rejected(monkeypatch):
    with pytest.raises(webpage.WebpageError):
        await webpage.fetch("   ")


@pytest.mark.asyncio
async def test_a_public_html_page_is_extracted(monkeypatch):
    _install_public_dns(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        html = (
            "<html><head><title>Test Page</title></head>"
            "<body><script>ignored();</script>"
            "<nav>Home About</nav>"
            "<p>The Arabian Sea is warmer than usual this week.</p>"
            "</body></html>"
        )
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=html)

    _install_transport(monkeypatch, handler)

    result = await webpage.fetch("https://example.com/article")

    assert result["title"] == "Test Page"
    assert "Arabian Sea is warmer" in result["content"]
    assert "ignored" not in result["content"]
    assert "Home About" not in result["content"]
    assert result["truncated"] is False
    assert result["source"] == "example.com"


@pytest.mark.asyncio
async def test_a_redirect_target_is_revalidated(monkeypatch):
    """A page that 302s to a private address must not slip through just
    because the first hop passed the SSRF check."""
    _install_dns(
        monkeypatch,
        {"internal.example": ["10.0.0.5"]},
        default=["93.184.216.34"],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://internal.example/secret"})
        raise AssertionError("the redirect target must never actually be reached")

    _install_transport(monkeypatch, handler)

    with pytest.raises(webpage.WebpageError):
        await webpage.fetch("https://example.com/redirector")


@pytest.mark.asyncio
async def test_a_non_text_content_type_is_refused(monkeypatch):
    _install_public_dns(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4")

    _install_transport(monkeypatch, handler)

    with pytest.raises(webpage.WebpageError):
        await webpage.fetch("https://example.com/paper.pdf")


@pytest.mark.asyncio
async def test_a_server_error_status_is_refused(monkeypatch):
    _install_public_dns(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, headers={"content-type": "text/html"}, text="<html></html>")

    _install_transport(monkeypatch, handler)

    with pytest.raises(webpage.WebpageError):
        await webpage.fetch("https://example.com/down")


@pytest.mark.asyncio
async def test_an_oversized_page_is_refused(monkeypatch):
    _install_public_dns(monkeypatch)
    monkeypatch.setattr(webpage, "_MAX_BYTES", 100)

    big_html = "<html><body>" + ("x" * 500) + "</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=big_html.encode())

    _install_transport(monkeypatch, handler)

    with pytest.raises(webpage.WebpageError):
        await webpage.fetch("https://example.com/huge")


@pytest.mark.asyncio
async def test_long_text_is_truncated_and_says_so(monkeypatch):
    _install_public_dns(monkeypatch)
    monkeypatch.setattr(webpage, "_MAX_CHARS", 20)

    html = "<html><body><p>" + ("word " * 20) + "</p></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=html.encode())

    _install_transport(monkeypatch, handler)

    result = await webpage.fetch("https://example.com/long")

    assert result["truncated"] is True
    assert len(result["content"]) == 20
