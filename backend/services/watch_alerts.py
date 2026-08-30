"""Proactive alert watches — sihtodo.md item 8.

Every alert tool elsewhere in this codebase (`get_active_alerts`,
`get_cyclone_alerts`, `get_severe_weather_alerts`, `assess_marine_risk`) is
pull: it answers only when a chat turn or a page visit asks. This module is
the push half — a subscription row (`app/models/alerts/subscription.py`)
plus a scheduled evaluation pass (`evaluate_and_notify`, registered in
`main.py`'s `AsyncIOScheduler`) that emails a confirmed address when
something changes at a saved point.

**This feature was designed once before and explicitly dropped** (`git show
8618f77`, 2026-08-17, "Subscribable alerts removed as requested"). Its
constraints are still the right ones and are followed here: double opt-in
(no alert is ever sent to an unconfirmed address), a signed token
independent of `client_id` gates every create/confirm/unsubscribe action
(`services/watch_tokens.py`), bloom-risk alerts only at +3d (+7d precision
is 0.202 — too many false alarms), point triggers only (no polygons),
email only (no webhooks — an outbound POST to a caller-supplied URL would
make this backend an SSRF vector against its own network).

**"The evaluation job must not turn N subscriptions into N live upstream
fetches" — verified, not assumed, against the three signals actually used**:
- `services/severe_weather.py` (IMD CAP) and `services/cyclones.py` (GDACS)
  are each a single worldwide feed behind an in-process TTL cache (10 min /
  15 min respectively) — `check_point(lat, lon)` fetches the whole feed
  once and filters locally, so N subscriptions checked in one tick cost at
  most one real fetch per feed, not N.
- `services/predictions.py::hab_point` (bloom risk) is a pure in-memory
  read over an `lru_cache`-held NetCDF grid — zero network, ever.
- **"High waves" is deliberately not a v1 signal.** `services/ocean_state.py`
  (which backs the dashboard's own wave alert) reduces its global wave grid
  to summary statistics and discards the grid — there is nothing left to
  sample at a point. `assess_marine_risk`/`get_active_alerts` remain the
  pull-based way to check wave height; this is a stated scope cut, not a
  silently missing feature.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import settings
from services import cyclones, predictions, severe_weather, watch_tokens
from services.cyclones import CycloneError
from services.severe_weather import SevereWeatherError
from services.watch_tokens import WatchTokenError

logger = logging.getLogger(__name__)

# Bloom-risk alerts fire only at this horizon — see the module docstring.
_BLOOM_HORIZON_DAYS = 3
_BLOOM_ALERT_PROBABILITY = 0.5

# An unconfirmed subscription this old is abandoned, not merely slow to
# confirm — cleaned up so a stream of never-confirmed signups (or abuse of
# the create endpoint) does not grow the table without bound.
_UNCONFIRMED_TTL = timedelta(hours=24)

_DISCLAIMER = (
    "This is a threshold rule over live model/satellite data, not an issued "
    "marine warning. Always check official advisories before venturing out."
)


class WatchError(RuntimeError):
    """Alert watches are not configured, or a database operation failed."""


def enabled() -> bool:
    return bool(settings.DATABASE_URL)


def _session_factory():
    from app.database.session import get_async_session_factory

    return get_async_session_factory()


# --------------------------------------------------------------------------
# Create / confirm / unsubscribe / list
# --------------------------------------------------------------------------


async def create(
    client_id: str, email: str, label: str, latitude: float, longitude: float, radius_km: float
) -> dict[str, Any]:
    """Open an unconfirmed watch and send the confirmation email.

    Never returns whether this email already has other watches — that would
    let a caller enumerate addresses via this endpoint.
    """
    if not enabled():
        raise WatchError("Alert watches need a database, which is not configured on this server.")

    from sqlalchemy.exc import SQLAlchemyError

    from app.models.alerts import AlertSubscription

    try:
        async with _session_factory()() as db:
            row = AlertSubscription(
                client_id=client_id,
                email=email,
                label=label,
                latitude=latitude,
                longitude=longitude,
                radius_km=radius_km,
            )
            db.add(row)
            await db.commit()
            subscription_id = row.id
    except SQLAlchemyError as exc:
        logger.exception("could not create an alert watch")
        raise WatchError("Could not create the watch right now. Please try again later.") from exc

    try:
        token = watch_tokens.make_token(subscription_id, "confirm", watch_tokens.CONFIRM_TOKEN_TTL)
    except WatchTokenError as exc:
        raise WatchError(str(exc)) from exc

    await _send_confirmation_email(email, label, token)
    return {"status": "pending_confirmation"}


async def confirm(token: str) -> bool:
    if not enabled():
        return False
    subscription_id = watch_tokens.verify_token(token, "confirm")
    if subscription_id is None:
        return False

    from sqlalchemy import update
    from sqlalchemy.exc import SQLAlchemyError

    from app.models.alerts import AlertSubscription

    try:
        async with _session_factory()() as db:
            result = await db.execute(
                update(AlertSubscription)
                .where(AlertSubscription.id == subscription_id)
                .values(confirmed_at=datetime.now(timezone.utc))
            )
            await db.commit()
            return bool(result.rowcount)
    except SQLAlchemyError:
        logger.exception("could not confirm an alert watch")
        return False


async def unsubscribe(token: str) -> bool:
    if not enabled():
        return False
    subscription_id = watch_tokens.verify_token(token, "unsubscribe")
    if subscription_id is None:
        return False

    from sqlalchemy import delete
    from sqlalchemy.exc import SQLAlchemyError

    from app.models.alerts import AlertSubscription

    try:
        async with _session_factory()() as db:
            result = await db.execute(
                delete(AlertSubscription).where(AlertSubscription.id == subscription_id)
            )
            await db.commit()
            return bool(result.rowcount)
    except SQLAlchemyError:
        logger.exception("could not remove an alert watch")
        return False


async def list_for_client(client_id: str) -> list[dict[str, Any]]:
    if not enabled():
        return []

    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError

    from app.models.alerts import AlertSubscription

    try:
        async with _session_factory()() as db:
            rows = (
                (
                    await db.execute(
                        select(AlertSubscription)
                        .where(AlertSubscription.client_id == client_id)
                        .order_by(AlertSubscription.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
        return [
            {
                "id": str(row.id),
                "label": row.label,
                "latitude": row.latitude,
                "longitude": row.longitude,
                "radius_km": row.radius_km,
                "confirmed": row.confirmed_at is not None,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    except SQLAlchemyError:
        logger.exception("could not list alert watches")
        return []


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------


def _confirm_url(token: str) -> str:
    return f"{settings.FRONTEND_BASE_URL}/confirm-watch?token={token}"


def _unsubscribe_url(token: str) -> str:
    return f"{settings.FRONTEND_BASE_URL}/unsubscribe-watch?token={token}"


async def _send_confirmation_email(email: str, label: str, token: str) -> None:
    subject = "Confirm your MarisAI alert watch"
    body = (
        f"You asked MarisAI to watch \"{label}\" for adverse weather, cyclones, "
        f"and harmful algal bloom risk.\n\n"
        f"Confirm this watch: {_confirm_url(token)}\n\n"
        f"This link expires in 24 hours. If you did not request this, ignore "
        f"this email — no watch is active until the link above is followed."
    )
    await _send(email, subject, body)


async def _send_alert_email(sub: Any, reasons: list[str]) -> None:
    unsubscribe_token = watch_tokens.make_token(
        sub.id, "unsubscribe", watch_tokens.UNSUBSCRIBE_TOKEN_TTL
    )
    subject = f"MarisAI alert: {sub.label}"
    body = (
        f"Conditions changed at your watched location \"{sub.label}\" "
        f"({sub.latitude:.3f}, {sub.longitude:.3f}):\n\n"
        + "\n".join(f"- {reason}" for reason in reasons)
        + f"\n\n{_DISCLAIMER}\n\n"
        f"Stop these alerts: {_unsubscribe_url(unsubscribe_token)}"
    )
    await _send(sub.email, subject, body)


async def _send(to_email: str, subject: str, body: str) -> None:
    import asyncio
    import smtplib
    from email.mime.text import MIMEText

    if not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
        logger.warning("alert email not sent (SMTP not configured): %s", subject)
        return

    def _send_sync() -> None:
        message = MIMEText(body, "plain", "utf-8")
        message["Subject"] = subject
        message["From"] = settings.SMTP_USERNAME
        message["To"] = to_email
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)

    try:
        await asyncio.to_thread(_send_sync)
    except Exception:  # noqa: BLE001 - never leak raw SMTP exceptions upward
        logger.exception("alert email send failed")


# --------------------------------------------------------------------------
# Scheduled evaluation
# --------------------------------------------------------------------------

# Sits inside both severe_weather's 10-minute and cyclones' 15-minute cache
# windows, so most ticks read from an already-warm cache rather than
# triggering a fetch.
EVALUATION_INTERVAL_MINUTES = 15


async def _confirmed_subscriptions() -> list[Any]:
    from sqlalchemy import select

    from app.models.alerts import AlertSubscription

    async with _session_factory()() as db:
        rows = (
            (
                await db.execute(
                    select(AlertSubscription).where(AlertSubscription.confirmed_at.is_not(None))
                )
            )
            .scalars()
            .all()
        )
        # Detach from the session before it closes — evaluate_and_notify
        # reads these after this `async with` block exits.
        for row in rows:
            db.expunge(row)
        return rows


async def _update_notification_state(subscription_id: uuid.UUID, signature: str, notified: bool) -> None:
    from sqlalchemy import update
    from sqlalchemy.exc import SQLAlchemyError

    from app.models.alerts import AlertSubscription

    values: dict[str, Any] = {"last_alert_signature": signature or None}
    if notified:
        values["last_notified_at"] = datetime.now(timezone.utc)

    try:
        async with _session_factory()() as db:
            await db.execute(
                update(AlertSubscription).where(AlertSubscription.id == subscription_id).values(**values)
            )
            await db.commit()
    except SQLAlchemyError:
        logger.exception("could not update alert-watch notification state for %s", subscription_id)


async def _cleanup_unconfirmed() -> None:
    from sqlalchemy import delete
    from sqlalchemy.exc import SQLAlchemyError

    from app.models.alerts import AlertSubscription

    cutoff = datetime.now(timezone.utc) - _UNCONFIRMED_TTL
    try:
        async with _session_factory()() as db:
            await db.execute(
                delete(AlertSubscription).where(
                    AlertSubscription.confirmed_at.is_(None),
                    AlertSubscription.created_at < cutoff,
                )
            )
            await db.commit()
    except SQLAlchemyError:
        logger.exception("could not clean up unconfirmed alert watches")


async def _evaluate_one(sub: Any) -> tuple[list[str], list[str]]:
    """Returns (signature_parts, human-readable reasons) for one subscription.
    Never raises — each signal's own fetch failure is caught and skipped,
    matching services/marine_risk.py's per-sub-check degradation, so one
    dead feed does not block the other signals for this subscription."""
    signature_parts: list[str] = []
    reasons: list[str] = []

    try:
        severe = await severe_weather.check_point(sub.latitude, sub.longitude)
        for alert in severe["alerts"]:
            signature_parts.append(f"severe:{alert['url']}")
            reasons.append(f"IMD alert: {alert['event']} ({alert['severity']})")
    except SevereWeatherError:
        logger.warning("severe-weather check failed for watch %s", sub.id)

    try:
        cyclone = await cyclones.check_point(sub.latitude, sub.longitude, sub.radius_km)
        if cyclone["within_watch_radius"] and cyclone["nearest"]:
            nearest = cyclone["nearest"]
            signature_parts.append(f"cyclone:{nearest['name']}")
            reasons.append(
                f"Cyclone {nearest['name']} within {sub.radius_km:.0f} km "
                f"({nearest['distance_km']:.0f} km away)"
            )
    except CycloneError:
        logger.warning("cyclone check failed for watch %s", sub.id)

    try:
        bloom = predictions.hab_point(_BLOOM_HORIZON_DAYS, sub.latitude, sub.longitude)
        if bloom["risk"] is not None and bloom["risk"] >= _BLOOM_ALERT_PROBABILITY:
            signature_parts.append("bloom")
            reasons.append(
                f"Harmful algal bloom risk {bloom['risk']:.0%} at +{_BLOOM_HORIZON_DAYS}d"
            )
    except Exception:  # noqa: BLE001 - hab_point should never raise, but this signal must not take the others down if it somehow does
        logger.exception("bloom-risk check failed for watch %s", sub.id)

    return signature_parts, reasons


async def evaluate_and_notify() -> None:
    """The scheduler job body — see the module docstring for why this does
    not turn N subscriptions into N live upstream fetches."""
    if not enabled():
        return

    subs = await _confirmed_subscriptions()
    for sub in subs:
        signature_parts, reasons = await _evaluate_one(sub)
        signature = ",".join(sorted(signature_parts))

        if signature != (sub.last_alert_signature or ""):
            if signature:
                await _send_alert_email(sub, reasons)
            await _update_notification_state(sub.id, signature, notified=bool(signature))

    await _cleanup_unconfirmed()
