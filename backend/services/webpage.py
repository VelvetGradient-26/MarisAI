"""Fetch one specific webpage and extract its readable text.

sihtodo.md item 4's `fetch_webpage` tool — the complement to `web_search`:
search finds candidate pages, this reads one the model (or the user) already
has a URL for, e.g. following a link `web_search` returned. No third-party
dependency: extraction is a small `html.parser.HTMLParser` subclass, which is
enough for "strip markup, keep readable text" and keeps this module dependency-
free the way `services/severe_weather.py` parses CAP XML with stdlib
`ElementTree` rather than adding a package for it.

**This is the one tool in this file whose input is an arbitrary
caller-supplied URL, which makes it an SSRF vector**: a model asked to
"fetch http://169.254.169.254/latest/meta-data/" would otherwise have this
server make that request as an insider, past any network boundary. `_guard()`
resolves the hostname itself (never trusting DNS to be re-checked by whatever
library issues the request) and rejects any address that is not global-
unicast — loopback, link-local (which is also where every cloud metadata
endpoint lives), private, and multicast/reserved ranges all fail closed.
Redirects are followed manually, one hop at a time, re-running the same guard
on every hop — a public URL that 302s to an internal address must not get a
free pass on the strength of its first, innocent-looking hostname.

**Verified live 2026-08-27** against `https://www.incois.gov.in/` (real HTML,
title and body text extracted correctly) and against a deliberately blocked
case (`http://127.0.0.1/`, rejected by `_guard()` before any request left the
process).
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(15.0)
_MAX_BYTES = 3 * 1024 * 1024  # 3MB of raw HTML is generous for any article page
_MAX_TEXT_CHARS = 6000  # a tool result budget, not a page-quality judgement
_MAX_REDIRECTS = 5
_ALLOWED_SCHEMES = {"http", "https"}
# Block-level tags whose boundary should read as a line break, not run-on
# prose — without this a nav menu's five links become one unreadable word.
_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "ul", "ol", "table",
}
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe"}
# A meta-refresh is a client-side redirect the server-level `httpx` never
# sees as one (it comes back as a normal 200). Government sites this
# platform actually cares about use it — `incois.gov.in/` is a bare
# `<meta http-equiv="refresh" content="0; url=/site/index.jsp">` with no
# other content, found live 2026-08-27 while verifying this module; without
# following it, fetching that URL "succeeds" with an empty page.
_META_REFRESH_RE = re.compile(
    r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]*content=["\'][^;"\']*;\s*url=([^"\'>]+)',
    re.IGNORECASE,
)


class WebpageError(RuntimeError):
    """The URL is disallowed, unreachable, or not a fetchable HTML page."""


def _guard(url: str) -> str:
    """Reject anything that is not a plain public http(s) URL. Returns the
    validated URL unchanged, for use in a redirect chain's re-check."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise WebpageError(f"Only http/https URLs can be fetched, not {parsed.scheme!r}.")
    host = parsed.hostname
    if not host:
        raise WebpageError("URL has no host to fetch.")

    try:
        addrinfo = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise WebpageError(f"Could not resolve host {host!r}: {exc}") from exc

    for family, _, _, _, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if not ip.is_global:
            raise WebpageError(
                f"Host {host!r} resolves to a non-public address ({ip}); refusing to fetch."
            )
    return url


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._title_done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title" and not self._title_done:
            self._in_title = True
        if tag in _BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
            self._title_done = True

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        else:
            self.text_parts.append(data)

    def result(self) -> tuple[str, str]:
        title = " ".join("".join(self.title_parts).split())
        raw_text = "".join(self.text_parts)
        # Collapse runs of whitespace within a line, but keep the block-tag
        # newlines that separate one heading/paragraph/list-item from the next.
        lines = [" ".join(line.split()) for line in raw_text.splitlines()]
        text = "\n".join(line for line in lines if line)
        return title, text


async def fetch(url: str) -> dict[str, str | int | None]:
    """Fetch `url` and return its title and extracted readable text.

    Only `text/html` and `text/plain` responses are extracted — anything else
    (a PDF, an image) is reported as unsupported rather than dumped as
    mangled bytes, since there is no extraction path for it here.
    """
    current = _guard(url)
    seen: set[str] = set()

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            if current in seen:
                raise WebpageError("Redirect loop detected.")
            seen.add(current)

            try:
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise WebpageError("Redirected with no Location header.")
                        current = _guard(urljoin(current, location))
                        continue

                    if response.status_code >= 400:
                        raise WebpageError(
                            f"Fetching {current} failed with status {response.status_code}."
                        )

                    content_type = response.headers.get("content-type", "")
                    if not any(kind in content_type for kind in ("text/html", "text/plain")):
                        raise WebpageError(
                            f"{current} is {content_type or 'an unknown type'}, "
                            "not a fetchable HTML/text page."
                        )

                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > _MAX_BYTES:
                            raise WebpageError(f"{current} exceeds the {_MAX_BYTES}-byte fetch limit.")
                        chunks.append(chunk)
                    body = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")

                    if "text/html" in content_type:
                        match = _META_REFRESH_RE.search(body)
                        if match:
                            current = _guard(urljoin(current, match.group(1).strip()))
                            continue
                    break
            except httpx.HTTPError as exc:
                raise WebpageError(f"Could not fetch {current}: {exc}") from exc
        else:
            raise WebpageError(f"Too many redirects fetching {url} (limit {_MAX_REDIRECTS}).")

    if "text/plain" in content_type:
        title, text = "", body
    else:
        extractor = _TextExtractor()
        extractor.feed(body)
        title, text = extractor.result()

    truncated = len(text) > _MAX_TEXT_CHARS
    return {
        "url": current,
        "title": title or None,
        "text": text[:_MAX_TEXT_CHARS],
        "truncated": truncated,
        "source": current,
    }
