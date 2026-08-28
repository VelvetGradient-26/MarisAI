"""services/webpage.py (sihtodo.md item 4's fetch_webpage tool).

No network: `socket.getaddrinfo` is monkeypatched so the SSRF guard's
behaviour is tested deterministically regardless of what DNS actually
resolves in CI, and `httpx.AsyncClient` is patched onto a `MockTransport`,
the same convention `test_download_gebco.py` uses. The module's own
docstring records the separate live probes (a real INCOIS page, a real
blocked loopback fetch) that established this design before these unit
tests were written.
"""

from __future__ import annotations

import socket

import httpx
import pytest

from services import webpage

# Captured once, before any test patches `webpage.httpx.AsyncClient` — see the
# identical note in tests/test_literature.py: that attribute lives on the
# shared `httpx` module, so re-reading it after a first patch would chain
# fakes together instead of reaching each test's own mock transport.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _addrinfo(ip: str) -> list:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


def _resolve_everything_to(monkeypatch: pytest.MonkeyPatch, ip: str) -> None:
    monkeypatch.setattr(webpage.socket, "getaddrinfo", lambda host, port: _addrinfo(ip))


def _install(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(webpage.httpx, "AsyncClient", patched)


@pytest.mark.asyncio
async def test_rejects_a_non_http_scheme():
    with pytest.raises(webpage.WebpageError, match="http/https"):
        await webpage.fetch("ftp://example.org/file")


@pytest.mark.asyncio
async def test_rejects_a_loopback_address(monkeypatch: pytest.MonkeyPatch):
    _resolve_everything_to(monkeypatch, "127.0.0.1")
    with pytest.raises(webpage.WebpageError, match="non-public address"):
        await webpage.fetch("http://localhost/")


@pytest.mark.asyncio
async def test_rejects_a_link_local_metadata_address(monkeypatch: pytest.MonkeyPatch):
    _resolve_everything_to(monkeypatch, "169.254.169.254")
    with pytest.raises(webpage.WebpageError, match="non-public address"):
        await webpage.fetch("http://metadata.internal/latest/meta-data/")


@pytest.mark.asyncio
async def test_rejects_a_private_range_address(monkeypatch: pytest.MonkeyPatch):
    _resolve_everything_to(monkeypatch, "10.0.0.5")
    with pytest.raises(webpage.WebpageError, match="non-public address"):
        await webpage.fetch("http://internal.example/")


@pytest.mark.asyncio
async def test_extracts_title_and_readable_text(monkeypatch: pytest.MonkeyPatch):
    _resolve_everything_to(monkeypatch, "93.184.216.34")
    html = (
        "<html><head><title>Ocean News</title><script>ignored();</script></head>"
        "<body><h1>Warm water off Kochi</h1><p>Scientists report an anomaly.</p>"
        "<style>.x{color:red}</style></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    _install(monkeypatch, handler)

    result = await webpage.fetch("https://example.org/article")

    assert result["title"] == "Ocean News"
    assert "Warm water off Kochi" in result["text"]
    assert "Scientists report an anomaly." in result["text"]
    assert "ignored();" not in result["text"]
    assert ".x{color:red}" not in result["text"]
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_a_meta_refresh_is_followed(monkeypatch: pytest.MonkeyPatch):
    _resolve_everything_to(monkeypatch, "93.184.216.34")
    pages = {
        "https://example.org/": (
            '<html><head><meta http-equiv="refresh" content="0; url=/site/index.jsp">'
            "</head></html>"
        ),
        "https://example.org/site/index.jsp": (
            "<html><head><title>Real page</title></head><body><p>Here it is.</p></body></html>"
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=pages[str(request.url)])

    _install(monkeypatch, handler)

    result = await webpage.fetch("https://example.org/")

    assert result["title"] == "Real page"
    assert "Here it is." in result["text"]
    assert result["url"] == "https://example.org/site/index.jsp"


@pytest.mark.asyncio
async def test_an_http_redirect_is_followed_and_revalidated(monkeypatch: pytest.MonkeyPatch):
    _resolve_everything_to(monkeypatch, "93.184.216.34")

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.org/old":
            return httpx.Response(302, headers={"location": "https://example.org/new"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><head><title>New</title></head><body>ok</body></html>",
        )

    _install(monkeypatch, handler)

    result = await webpage.fetch("https://example.org/old")

    assert result["url"] == "https://example.org/new"
    assert result["title"] == "New"


@pytest.mark.asyncio
async def test_a_redirect_to_a_private_address_is_rejected(monkeypatch: pytest.MonkeyPatch):
    """The public->private redirect is the actual SSRF vector this guards
    against: an attacker-controlled server passes the initial guard on its
    public hostname, then 302s the response to an internal address."""
    calls = {"n": 0}

    def fake_getaddrinfo(host, port):
        calls["n"] += 1
        return _addrinfo("93.184.216.34" if calls["n"] == 1 else "10.0.0.5")

    monkeypatch.setattr(webpage.socket, "getaddrinfo", fake_getaddrinfo)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://internal.example/secret"})

    _install(monkeypatch, handler)

    with pytest.raises(webpage.WebpageError, match="non-public address"):
        await webpage.fetch("https://example.org/redirects-away")


@pytest.mark.asyncio
async def test_non_html_content_type_is_rejected(monkeypatch: pytest.MonkeyPatch):
    _resolve_everything_to(monkeypatch, "93.184.216.34")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4")

    _install(monkeypatch, handler)

    with pytest.raises(webpage.WebpageError, match="not a fetchable"):
        await webpage.fetch("https://example.org/report.pdf")


@pytest.mark.asyncio
async def test_oversized_pages_are_rejected(monkeypatch: pytest.MonkeyPatch):
    _resolve_everything_to(monkeypatch, "93.184.216.34")
    huge = b"<html><body>" + b"x" * (webpage._MAX_BYTES + 1) + b"</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=huge)

    _install(monkeypatch, handler)

    with pytest.raises(webpage.WebpageError, match="byte fetch limit"):
        await webpage.fetch("https://example.org/huge")


@pytest.mark.asyncio
async def test_text_beyond_the_char_limit_is_truncated_and_flagged(monkeypatch: pytest.MonkeyPatch):
    _resolve_everything_to(monkeypatch, "93.184.216.34")
    long_paragraph = "word " * (webpage._MAX_TEXT_CHARS // 4)
    html = f"<html><body><p>{long_paragraph}</p></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    _install(monkeypatch, handler)

    result = await webpage.fetch("https://example.org/long")

    assert result["truncated"] is True
    assert len(result["text"]) == webpage._MAX_TEXT_CHARS


@pytest.mark.asyncio
async def test_a_redirect_loop_is_detected(monkeypatch: pytest.MonkeyPatch):
    _resolve_everything_to(monkeypatch, "93.184.216.34")

    def handler(request: httpx.Request) -> httpx.Response:
        other = "https://example.org/b" if str(request.url) == "https://example.org/a" else "https://example.org/a"
        return httpx.Response(302, headers={"location": other})

    _install(monkeypatch, handler)

    with pytest.raises(webpage.WebpageError, match="[Rr]edirect"):
        await webpage.fetch("https://example.org/a")
