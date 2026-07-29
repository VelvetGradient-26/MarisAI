"""Feedback form email delivery via Gmail SMTP + an app password.

No SMTP credentials are committed anywhere — `SMTP_USERNAME`/`SMTP_PASSWORD`
default to empty strings in `app/core/config.py` and must be supplied in the
deployer's own untracked `.env` (a Gmail "app password", not the account's
real login password — https://myaccount.google.com/apppasswords).
"""

from __future__ import annotations

import asyncio
import json
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

from loguru import logger

from app.core.config import settings

FEEDBACK_RECIPIENT = "nycteakryfos@gmail.com"

# One JSON object per line — a durable local record of every submission,
# independent of whether the email send below succeeds. Gitignored (real
# user emails/messages, not something to commit).
FEEDBACK_LOG_PATH = Path(__file__).resolve().parent.parent / "feedback_log.jsonl"


class FeedbackError(RuntimeError):
    pass


def _log_submission(name: str, email: str, message: str) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "name": name,
        "email": email,
        "message": message,
    }
    try:
        with FEEDBACK_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as exc:  # noqa: BLE001 - logging failure shouldn't block the email
        logger.warning(f"Failed to write feedback log entry: {exc}")


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
    await asyncio.to_thread(_log_submission, name, email, message)

    if not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
        raise FeedbackError(
            "Feedback email is not configured on this server (missing SMTP credentials)."
        )
    try:
        await asyncio.to_thread(_send_sync, name, email, message)
    except FeedbackError:
        raise
    except Exception as exc:  # noqa: BLE001 - never leak raw SMTP exceptions
        raise FeedbackError(f"Failed to send feedback email: {exc}") from exc
