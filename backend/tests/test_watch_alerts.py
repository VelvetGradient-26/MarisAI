"""services/watch_alerts.py — sihtodo.md item 8.

`_evaluate_one`/`evaluate_and_notify`'s signal-gathering and dedup logic is
tested here with the three live signals (severe_weather, cyclones,
predictions) monkeypatched, the same shape `test_marine_risk.py` uses for
its own composed live checks. The create/confirm/unsubscribe/list DB path is
tested against the real Postgres in `DATABASE_URL`, skipped when there isn't
one — same convention as `test_chat_store.py`, and for the same reason: the
service is written to degrade rather than fail without a database.
"""

from __future__ import annotations

import uuid

import pytest

from services import watch_alerts
from services.cyclones import CycloneError
from services.severe_weather import SevereWeatherError

_NO_SEVERE_WEATHER = {"alerts": [], "count": 0, "active_nationwide": 0}
_NO_CYCLONE = {
    "active_cyclones_worldwide": 0,
    "nearest": None,
    "within_watch_radius": False,
    "watch_radius_km": 200.0,
}
_NO_BLOOM = {"horizon_days": 3, "date": "2026-08-27", "risk": 0.1, "outside_coverage": False}


class _Sub:
    def __init__(self, id=None, latitude=10.0, longitude=76.0, radius_km=200.0):
        self.id = id or uuid.uuid4()
        self.latitude = latitude
        self.longitude = longitude
        self.radius_km = radius_km


def _patch_all_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    async def severe(lat, lon):
        return _NO_SEVERE_WEATHER

    async def cyclone(lat, lon, radius_km):
        return _NO_CYCLONE

    def bloom(horizon, lat, lon):
        return _NO_BLOOM

    monkeypatch.setattr(watch_alerts.severe_weather, "check_point", severe)
    monkeypatch.setattr(watch_alerts.cyclones, "check_point", cyclone)
    monkeypatch.setattr(watch_alerts.predictions, "hab_point", bloom)


@pytest.mark.asyncio
async def test_no_active_hazards_produces_an_empty_signature(monkeypatch: pytest.MonkeyPatch):
    _patch_all_clear(monkeypatch)

    signature_parts, reasons = await watch_alerts._evaluate_one(_Sub())

    assert signature_parts == []
    assert reasons == []


@pytest.mark.asyncio
async def test_a_severe_weather_alert_is_included(monkeypatch: pytest.MonkeyPatch):
    _patch_all_clear(monkeypatch)

    async def severe(lat, lon):
        return {
            "alerts": [
                {
                    "event": "Thunderstorm",
                    "severity": "Severe",
                    "url": "https://example.org/alert/1",
                }
            ],
            "count": 1,
            "active_nationwide": 1,
        }

    monkeypatch.setattr(watch_alerts.severe_weather, "check_point", severe)

    signature_parts, reasons = await watch_alerts._evaluate_one(_Sub())

    assert signature_parts == ["severe:https://example.org/alert/1"]
    assert "Thunderstorm" in reasons[0]


@pytest.mark.asyncio
async def test_a_nearby_cyclone_is_included(monkeypatch: pytest.MonkeyPatch):
    _patch_all_clear(monkeypatch)

    async def cyclone(lat, lon, radius_km):
        return {
            "active_cyclones_worldwide": 1,
            "nearest": {"name": "MICHAUNG-23", "distance_km": 120.0},
            "within_watch_radius": True,
            "watch_radius_km": radius_km,
        }

    monkeypatch.setattr(watch_alerts.cyclones, "check_point", cyclone)

    signature_parts, reasons = await watch_alerts._evaluate_one(_Sub())

    assert signature_parts == ["cyclone:MICHAUNG-23"]
    assert "MICHAUNG-23" in reasons[0]


@pytest.mark.asyncio
async def test_a_cyclone_outside_the_watch_radius_is_not_included(monkeypatch: pytest.MonkeyPatch):
    _patch_all_clear(monkeypatch)

    async def cyclone(lat, lon, radius_km):
        return {
            "active_cyclones_worldwide": 1,
            "nearest": {"name": "FAR-AWAY-24", "distance_km": 5000.0},
            "within_watch_radius": False,
            "watch_radius_km": radius_km,
        }

    monkeypatch.setattr(watch_alerts.cyclones, "check_point", cyclone)

    signature_parts, reasons = await watch_alerts._evaluate_one(_Sub())

    assert signature_parts == []


@pytest.mark.asyncio
async def test_bloom_risk_above_threshold_is_included(monkeypatch: pytest.MonkeyPatch):
    _patch_all_clear(monkeypatch)

    def bloom(horizon, lat, lon):
        assert horizon == 3  # +3d only, per the module's stated design
        return {"horizon_days": 3, "date": "2026-08-27", "risk": 0.62, "outside_coverage": False}

    monkeypatch.setattr(watch_alerts.predictions, "hab_point", bloom)

    signature_parts, reasons = await watch_alerts._evaluate_one(_Sub())

    assert signature_parts == ["bloom"]
    assert "62%" in reasons[0]


@pytest.mark.asyncio
async def test_bloom_risk_below_threshold_is_not_included(monkeypatch: pytest.MonkeyPatch):
    _patch_all_clear(monkeypatch)

    signature_parts, _ = await watch_alerts._evaluate_one(_Sub())

    assert signature_parts == []


@pytest.mark.asyncio
async def test_a_failed_severe_weather_check_does_not_block_the_others(
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_all_clear(monkeypatch)

    async def broken_severe(lat, lon):
        raise SevereWeatherError("feed down")

    async def cyclone(lat, lon, radius_km):
        return {
            "active_cyclones_worldwide": 1,
            "nearest": {"name": "STILL-DETECTED", "distance_km": 10.0},
            "within_watch_radius": True,
            "watch_radius_km": radius_km,
        }

    monkeypatch.setattr(watch_alerts.severe_weather, "check_point", broken_severe)
    monkeypatch.setattr(watch_alerts.cyclones, "check_point", cyclone)

    signature_parts, reasons = await watch_alerts._evaluate_one(_Sub())

    assert signature_parts == ["cyclone:STILL-DETECTED"]


@pytest.mark.asyncio
async def test_a_failed_cyclone_check_does_not_block_the_others(monkeypatch: pytest.MonkeyPatch):
    _patch_all_clear(monkeypatch)

    async def broken_cyclone(lat, lon, radius_km):
        raise CycloneError("feed down")

    monkeypatch.setattr(watch_alerts.cyclones, "check_point", broken_cyclone)

    # Should not raise, and severe_weather (clear) still runs.
    signature_parts, _ = await watch_alerts._evaluate_one(_Sub())
    assert signature_parts == []


# --------------------------------------------------------------------------
# DB-backed: create / confirm / unsubscribe / list / evaluate_and_notify dedup
# --------------------------------------------------------------------------

pytestmark_db = pytest.mark.skipif(
    not watch_alerts.enabled(), reason="DATABASE_URL is not configured"
)


@pytest.fixture(autouse=True)
def _token_secret(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "WATCH_TOKEN_SECRET", "test-secret-value")


@pytest.fixture(autouse=True)
async def _fresh_engine():
    """Same fix test_chat_store.py's own fixture documents: asyncpg binds a
    connection to the event loop that opened it, and pytest-asyncio gives
    each test its own loop."""
    yield
    from app.database import session as db_session

    if db_session._async_engine is not None:
        await db_session._async_engine.dispose()
        db_session._async_engine = None
        db_session._AsyncSessionLocal = None


def _client_id() -> str:
    return f"test-{uuid.uuid4().hex}"[:64]


@pytestmark_db
@pytest.mark.asyncio
async def test_create_opens_an_unconfirmed_watch_and_does_not_notify_yet(monkeypatch):
    async def no_email(*args, **kwargs):
        pass

    monkeypatch.setattr(watch_alerts, "_send_confirmation_email", no_email)
    client_id = _client_id()

    result = await watch_alerts.create(client_id, "watcher@example.org", "Test point", 9.0, 76.0, 200.0)
    assert result == {"status": "pending_confirmation"}

    watches = await watch_alerts.list_for_client(client_id)
    assert len(watches) == 1
    assert watches[0]["confirmed"] is False
    assert watches[0]["label"] == "Test point"

    from sqlalchemy import delete

    from app.models.alerts import AlertSubscription

    async with watch_alerts._session_factory()() as db:
        await db.execute(delete(AlertSubscription).where(AlertSubscription.client_id == client_id))
        await db.commit()


@pytestmark_db
@pytest.mark.asyncio
async def test_confirm_then_unsubscribe_round_trip(monkeypatch):
    async def no_email(*args, **kwargs):
        pass

    monkeypatch.setattr(watch_alerts, "_send_confirmation_email", no_email)
    client_id = _client_id()
    await watch_alerts.create(client_id, "watcher@example.org", "Round trip", 9.0, 76.0, 200.0)

    watches = await watch_alerts.list_for_client(client_id)
    subscription_id = uuid.UUID(watches[0]["id"])

    from services import watch_tokens

    confirm_token = watch_tokens.make_token(subscription_id, "confirm", watch_tokens.CONFIRM_TOKEN_TTL)
    assert await watch_alerts.confirm(confirm_token) is True

    watches = await watch_alerts.list_for_client(client_id)
    assert watches[0]["confirmed"] is True

    unsub_token = watch_tokens.make_token(
        subscription_id, "unsubscribe", watch_tokens.UNSUBSCRIBE_TOKEN_TTL
    )
    assert await watch_alerts.unsubscribe(unsub_token) is True
    assert await watch_alerts.list_for_client(client_id) == []


@pytestmark_db
@pytest.mark.asyncio
async def test_a_confirm_token_does_not_unsubscribe_and_vice_versa(monkeypatch):
    async def no_email(*args, **kwargs):
        pass

    monkeypatch.setattr(watch_alerts, "_send_confirmation_email", no_email)
    client_id = _client_id()
    await watch_alerts.create(client_id, "watcher@example.org", "Purpose check", 9.0, 76.0, 200.0)
    watches = await watch_alerts.list_for_client(client_id)
    subscription_id = uuid.UUID(watches[0]["id"])

    from services import watch_tokens

    confirm_token = watch_tokens.make_token(subscription_id, "confirm", watch_tokens.CONFIRM_TOKEN_TTL)
    # A confirm token must not also work as an unsubscribe token.
    assert await watch_alerts.unsubscribe(confirm_token) is False
    # The watch must still exist and still be unconfirmed.
    watches = await watch_alerts.list_for_client(client_id)
    assert len(watches) == 1
    assert watches[0]["confirmed"] is False

    from sqlalchemy import delete

    from app.models.alerts import AlertSubscription

    async with watch_alerts._session_factory()() as db:
        await db.execute(delete(AlertSubscription).where(AlertSubscription.client_id == client_id))
        await db.commit()


@pytestmark_db
@pytest.mark.asyncio
async def test_evaluate_and_notify_dedups_an_unchanged_alert_signature(monkeypatch):
    """The core dedup rule: an email is sent on a signature *change*, never
    every tick for an ongoing, unchanged alert."""
    sent: list[str] = []

    async def fake_send_alert(sub, reasons):
        sent.append(sub.email)

    async def no_confirmation_email(*args, **kwargs):
        pass

    async def cyclone_always_active(lat, lon, radius_km):
        return {
            "active_cyclones_worldwide": 1,
            "nearest": {"name": "PERSISTENT-24", "distance_km": 10.0},
            "within_watch_radius": True,
            "watch_radius_km": radius_km,
        }

    async def no_severe_weather(lat, lon):
        return _NO_SEVERE_WEATHER

    def no_bloom(horizon, lat, lon):
        return _NO_BLOOM

    monkeypatch.setattr(watch_alerts, "_send_confirmation_email", no_confirmation_email)
    monkeypatch.setattr(watch_alerts, "_send_alert_email", fake_send_alert)
    monkeypatch.setattr(watch_alerts.severe_weather, "check_point", no_severe_weather)
    monkeypatch.setattr(watch_alerts.cyclones, "check_point", cyclone_always_active)
    monkeypatch.setattr(watch_alerts.predictions, "hab_point", no_bloom)

    client_id = _client_id()
    await watch_alerts.create(client_id, "watcher@example.org", "Dedup check", 9.0, 76.0, 200.0)
    watches = await watch_alerts.list_for_client(client_id)
    subscription_id = uuid.UUID(watches[0]["id"])

    from services import watch_tokens

    token = watch_tokens.make_token(subscription_id, "confirm", watch_tokens.CONFIRM_TOKEN_TTL)
    await watch_alerts.confirm(token)

    await watch_alerts.evaluate_and_notify()
    assert len(sent) == 1  # first sighting of the cyclone -> notified

    await watch_alerts.evaluate_and_notify()
    assert len(sent) == 1  # still the same cyclone -> no second email

    from sqlalchemy import delete

    from app.models.alerts import AlertSubscription

    async with watch_alerts._session_factory()() as db:
        await db.execute(delete(AlertSubscription).where(AlertSubscription.client_id == client_id))
        await db.commit()
