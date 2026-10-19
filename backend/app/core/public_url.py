"""The address the deployed site is reached at, for links that leave the app.

Email links (watch confirmation and unsubscribe) cannot be relative, so the
backend needs its own public origin. On EC2 there is no fixed one: the
instance has no Elastic IP, so its public IPv4 changes on every start. With
`PUBLIC_BASE_URL_FROM_EC2` set, the address is read once from instance
metadata (IMDSv2) and cached for the life of the process, which is exactly
the life of that IP. An explicit `PUBLIC_BASE_URL` always wins, and anything
that fails falls back to `FRONTEND_BASE_URL` rather than raising: a wrong
link in one email is better than a watch that cannot be created at all.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_IMDS = "http://169.254.169.254"
_TIMEOUT = httpx.Timeout(1.0)
# Replaced in tests with an httpx.MockTransport.
_TRANSPORT: httpx.BaseTransport | None = None


def _ec2_public_ipv4() -> str | None:
    try:
        with httpx.Client(base_url=_IMDS, timeout=_TIMEOUT, transport=_TRANSPORT) as client:
            token = client.put(
                "/latest/api/token", headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"}
            )
            token.raise_for_status()
            response = client.get(
                "/latest/meta-data/public-ipv4",
                headers={"X-aws-ec2-metadata-token": token.text},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"could not read the public IPv4 from EC2 instance metadata: {exc}")
        return None
    address = response.text.strip()
    return address or None


@lru_cache(maxsize=1)
def public_base_url() -> str:
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL.rstrip("/")
    if settings.PUBLIC_BASE_URL_FROM_EC2:
        address = _ec2_public_ipv4()
        if address:
            return f"http://{address}"
    return settings.FRONTEND_BASE_URL.rstrip("/")
