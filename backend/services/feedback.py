"""Feedback form email delivery via Gmail SMTP + an app password.

No SMTP credentials are committed anywhere — `SMTP_USERNAME`/`SMTP_PASSWORD`
default to empty strings in `app/core/config.py` and must be supplied in the
deployer's own untracked `.env` (a Gmail "app password", not the account's
real login password — https://myaccount.google.com/apppasswords).

**Mail-only, by deliberate choice.** This used to also append every
submission to a local `feedback_log.jsonl` as a durable record independent
of whether the send succeeded. Dropped: a failed send now surfaces as a
real error to the person submitting (`FeedbackError`, a 502 at the router),
which is the honest signal — a silent on-disk fallback masked exactly the
failure a submitter needs to know about, and there is no second consumer
of that file to preserve.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.mime.text import MIMEText

from loguru import logger

from app.core.config import settings

FEEDBACK_RECIPIENT = "nycteakryfos@gmail.com"


class FeedbackError(RuntimeError):
    pass


def _send_sync(name: str, email: str, message: str) -> None:
    body = f"From: {name} <{email}>\n\n{message}"
    mime_message = MIMEText(body, "plain", "utf-8")
    mime_message["Subject"] = f"MarisAI feedback from {name}"
    mime_message["From"] = settings.SMTP_USERNAME
    mime_message["To"] = FEEDBACK_RECIPIENT
    mime_message["Reply-To"] = email

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(mime_message)


async def send_feedback_email(name: str, email: str, message: str) -> None:
    if not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
        raise FeedbackError(
            "Feedback email is not configured on this server (missing SMTP credentials)."
        )
    try:
        await asyncio.to_thread(_send_sync, name, email, message)
    except FeedbackError:
        raise
    except Exception as exc:  # noqa: BLE001 - never leak raw SMTP exceptions
        # The upstream text is logged, not returned: SMTP failures name the
        # mail host and port and can quote parts of the authentication
        # exchange, none of which a browser needs to see.
        logger.error(f"Feedback email send failed: {exc}")
        raise FeedbackError(
            "Could not send your feedback right now. It has been recorded — please try again later."
        ) from exc
