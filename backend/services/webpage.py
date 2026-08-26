"""Generic webpage fetch-and-read, with an SSRF guard.

sihtodo.md item 4 ("controlled internet tools") names `fetch_webpage`
alongside `web_search`/`search_scientific_literature` — a search result gives
a title and a two-line snippet, and a genuine "why did X happen" answer often
needs the actual article.

**This is the one internet tool with no external provider to document — the
risk here is not an upstream API's behaviour, it is that the tool exists to
fetch a URL an LLM chose, which may itself have been steered there by
untrusted text the model read (a search snippet, a user message). That is a
textbook SSRF vector**: a model asked (directly, or via a poisoned page it
already fetched) to read `http://169.254.169.254/latest/meta-data/` would
otherwise reach the server's own cloud metadata endpoint, or a service on
localhost never meant to be internet-facing.

`_check_target` resolves the hostname itself (via `_resolve_addresses`) and
rejects it if any resolved address is private, loopback, link-local,
multicast or otherwise reserved (stdlib `ipaddress`'s own classification),
*before* httpx ever opens a connection. Redirects are followed manually, one
hop at a time, re-checking every hop's host the same way — an
attacker-controlled page that 302s to a private address must not slip through
just because the first hop passed.

**This does not close every hole.** A DNS-rebinding attack (resolve to a
public address for the check, then to a private one for the connection made
moments later) is not defended against — that would require pinning the
resolved IP and forcing the connection to it while still presenting the
original Host header, a heavier change left for if this tool is ever exposed
beyond a bounded, logged tool call inside this codebase's own agent loop.

Only `text/html` and `text/plain` are read; anything else (a PDF, an image, a
binary download) is refused rather than dumped as decoded garbage into the
model's context. HTML is reduced to text with BeautifulSoup —
`<script>`/`<style>`/`<nav>`/`<footer>`/`<noscript>` are dropped before
extraction, since their text is markup noise (menu labels, tracking JSON)
rather than article content. The response body is read as a bounded stream
(`_MAX_BYTES`) rather than downloaded whole, so a caller cannot be made to
pull an arbitrarily large file into memory, and the extracted text is capped
at `_MAX_CHARS` — a long page would otherwise spend the model's entire
context on one source.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(15.0)
_MAX_BYTES = 3_000_000  # generous for an article page, not for a video/binary
_MAX_CHARS = 8_000  # what a chat answer can actually use; the rest is noise
_MAX_REDIRECTS = 5
_ALLOWED_CONTENT_TYPES = ("text/html", "text/plain")
_USER_AGENT = "MarisAI-OceanAssistant/1.0 (webpage reader tool)"


class WebpageError(RuntimeError):
    """The URL was rejected, or the page could not be fetched or read."""


async def _resolve_addresses(host: str) -> list[str]:
    """The IP addresses `host` resolves to.

    Split out from the check itself so tests can control resolution directly
    rather than depending on real DNS — the same reasoning every other
    provider module here has for isolating its own network call behind a
    monkeypatchable seam.
    """
    infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    return [info[4][0] for info in infos]


async def _check_target(url: str) -> str:
    """Validate one hop's URL, returning it unchanged.

    Raises `WebpageError` for anything that is not a plain public http(s)
    address — a non-http(s) scheme, an unresolvable host, or a host that
    resolves to a private/loopback/link-local/reserved address.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise WebpageError(f"Only http/https URLs are supported, not {parsed.scheme!r}.")
    if not parsed.hostname:
        raise WebpageError("URL has no host.")

    try:
        addresses = await _resolve_addresses(parsed.hostname)
    except socket.gaierror as exc:
        raise WebpageError(f"Could not resolve host {parsed.hostname!r}: {exc}") from exc
    if not addresses:
        raise WebpageError(f"Could not resolve host {parsed.hostname!r}.")

    for raw_ip in addresses:
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise WebpageError(
                f"{url!r} resolves to a private, local or otherwise "
                "non-public address and cannot be fetched."
            )
    return url


def _extract_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    text = " ".join(soup.get_text(separator=" ").split())
    return title, text


async def fetch(url: str) -> dict[str, Any]:
    """Fetch one webpage and return its title and main text.

    Raises `WebpageError` for a bad/unsafe URL, an unreachable host, a
    non-text response, or a response too large to be a normal article page.
    Never silently returns partial content as though it were the whole page —
    truncation is reported, not hidden.
    """
    url = (url or "").strip()
    if not url:
        raise WebpageError("A URL is required.")
    target = await _check_target(url)

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            request = client.build_request("GET", target)
            try:
                response = await client.send(request, stream=True, follow_redirects=False)
            except httpx.HTTPError as exc:
                raise WebpageError(f"Could not reach {target!r}: {exc}") from exc

            if response.is_redirect:
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise WebpageError(f"{target!r} redirected with no Location header.")
                target = await _check_target(urljoin(target, location))
                continue
            break
        else:
            raise WebpageError(f"Too many redirects fetching {url!r}.")

        if response.status_code >= 400:
            await response.aclose()
            raise WebpageError(f"{target!r} returned HTTP {response.status_code}.")

        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type not in _ALLOWED_CONTENT_TYPES:
            await response.aclose()
            raise WebpageError(
                f"Cannot read content type {content_type!r} — only HTML and "
                "plain text pages are supported."
            )

        chunks = bytearray()
        try:
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > _MAX_BYTES:
                    raise WebpageError(
                        f"{target!r} is too large to read (over {_MAX_BYTES} bytes)."
                    )
        finally:
            await response.aclose()

        text_body = chunks.decode(response.encoding or "utf-8", errors="replace")

    if content_type == "text/html":
        title, text = _extract_text(text_body)
    else:
        title, text = "", " ".join(text_body.split())

    truncated = len(text) > _MAX_CHARS
    content = text[:_MAX_CHARS]

    return {
        "url": target,
        "title": title or None,
        "content": content,
        "truncated": truncated,
        "source": urlparse(target).hostname,
    }
