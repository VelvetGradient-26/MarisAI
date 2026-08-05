"""Chat persistence.

Runs against the real Postgres in `DATABASE_URL` and skips when there isn't
one — the store is written to degrade rather than fail without a database, so a
developer with no Postgres must still get a green suite. Every test cleans up
the session it created.
"""

from __future__ import annotations

import uuid

import pytest

from services.chat import store

pytestmark = pytest.mark.skipif(
    not store.enabled(), reason="DATABASE_URL is not configured"
)


@pytest.fixture(autouse=True)
async def fresh_engine():
    """Dispose the async engine between tests.

    The engine and its pool are module-level singletons, while pytest-asyncio
    gives each test its own event loop. asyncpg binds a connection to the loop
    that opened it, so the second test to run inherits a pooled connection from
    a closed loop and fails with "another operation is in progress". Production
    never hits this — uvicorn serves every request on one long-lived loop — so
    the fix belongs here rather than in the engine.
    """
    yield
    from app.database import session as db_session

    if db_session._async_engine is not None:
        await db_session._async_engine.dispose()
        db_session._async_engine = None
        db_session._AsyncSessionLocal = None


@pytest.fixture
def client_id() -> str:
    return f"test-{uuid.uuid4().hex}"[:64]


async def _cleanup(session_id, client_id: str) -> None:
    if session_id:
        await store.remove(str(session_id), client_id)


@pytest.mark.asyncio
async def test_history_comes_back_in_the_order_it_was_written(client_id):
    """The regression this column exists for.

    A question and its answer are written in one transaction, and `created_at`
    defaults to `now()` — which in Postgres is *transaction start time*, so
    both rows carry an identical timestamp. Ordering on it put the assistant's
    reply before the question that prompted it, and that scrambled pairing then
    went straight into the next prompt. Ordering is by the identity column
    `seq`, which cannot tie.
    """
    session_id = await store.ensure_session(None, client_id, "first question")
    try:
        for index in range(3):
            await store.record(
                session_id,
                f"question {index}",
                {"answer": f"answer {index}", "observations": [], "sources": [],
                 "grounded": True, "unsupported_numbers": []},
            )

        history = await store.history(session_id)
        assert [m["role"] for m in history] == ["user", "assistant"] * 3
        assert [m["content"] for m in history] == [
            "question 0", "answer 0", "question 1", "answer 1", "question 2", "answer 2",
        ]
    finally:
        await _cleanup(session_id, client_id)


@pytest.mark.asyncio
async def test_a_session_resumes_rather_than_forking(client_id):
    """The whole point: the second message must land in the first conversation."""
    first = await store.ensure_session(None, client_id, "hello")
    try:
        again = await store.ensure_session(str(first), client_id, "hello again")
        assert again == first
    finally:
        await _cleanup(first, client_id)


@pytest.mark.asyncio
async def test_another_client_cannot_append_to_or_read_a_session(client_id):
    """`client_id` is scoping, not auth — but it must at least hold that line.

    A guessed id gets a *new* session rather than an error, so the response
    cannot be used to confirm the guess was right.
    """
    mine = await store.ensure_session(None, client_id, "private question")
    intruder = f"test-{uuid.uuid4().hex}"[:64]
    forked = None
    try:
        await store.record(
            mine, "private question",
            {"answer": "private answer", "observations": [], "sources": [],
             "grounded": True, "unsupported_numbers": []},
        )

        forked = await store.ensure_session(str(mine), intruder, "let me in")
        assert forked != mine

        assert await store.transcript(str(mine), intruder) is None
        assert await store.remove(str(mine), intruder) is False
        # Still intact after the failed attempts.
        assert await store.transcript(str(mine), client_id) is not None
    finally:
        await _cleanup(mine, client_id)
        await _cleanup(forked, intruder)


@pytest.mark.asyncio
async def test_provenance_survives_a_reload(client_id):
    """A reopened conversation must still show which calls produced which
    answer — without this the transcript loses the property the feature is
    built on and renders as bare paragraphs."""
    session_id = await store.ensure_session(None, client_id, "depth?")
    try:
        await store.record(
            session_id, "depth?",
            {
                "answer": "About 1234.5 m.",
                "observations": [
                    {"tool": "get_seafloor_depth", "arguments": {"latitude": 10.0},
                     "result": {"elevation_m": -1234.5}}
                ],
                "sources": ["GEBCO_2021 via Ifremer ERDDAP"],
                "grounded": False,
                "unsupported_numbers": ["28.4"],
            },
        )

        transcript = await store.transcript(str(session_id), client_id)
        answer = transcript[1]
        assert answer["observations"][0]["tool"] == "get_seafloor_depth"
        assert answer["sources"] == ["GEBCO_2021 via Ifremer ERDDAP"]
        assert answer["grounded"] is False
        assert answer["unsupported_numbers"] == ["28.4"]
    finally:
        await _cleanup(session_id, client_id)


@pytest.mark.asyncio
async def test_deleting_a_session_takes_its_messages(client_id):
    """The FK is ON DELETE CASCADE; this asserts it is actually wired."""
    session_id = await store.ensure_session(None, client_id, "temporary")
    await store.record(
        session_id, "temporary",
        {"answer": "gone soon", "observations": [], "sources": [],
         "grounded": True, "unsupported_numbers": []},
    )

    assert await store.remove(str(session_id), client_id) is True
    assert await store.transcript(str(session_id), client_id) is None
    assert await store.history(session_id) == []


@pytest.mark.asyncio
async def test_sessions_list_newest_used_first(client_id):
    """Ordering is by last *use*, not creation — an old chat you just replied
    to belongs at the top."""
    older = await store.ensure_session(None, client_id, "older chat")
    newer = await store.ensure_session(None, client_id, "newer chat")
    try:
        # Touch the older one; it should overtake.
        await store.record(
            older, "still going",
            {"answer": "yes", "observations": [], "sources": [],
             "grounded": True, "unsupported_numbers": []},
        )
        listed = await store.list_sessions(client_id)
        assert [row["id"] for row in listed][:2] == [str(older), str(newer)]
        assert listed[0]["title"] == "older chat"
    finally:
        await _cleanup(older, client_id)
        await _cleanup(newer, client_id)


@pytest.mark.asyncio
async def test_a_malformed_session_id_is_not_an_error(client_id):
    """The id comes from a URL, so it is attacker-controlled text, not a UUID."""
    assert await store.transcript("not-a-uuid", client_id) is None
    assert await store.remove("not-a-uuid", client_id) is False

    opened = await store.ensure_session("not-a-uuid", client_id, "hi")
    try:
        assert opened is not None  # falls back to a fresh session
    finally:
        await _cleanup(opened, client_id)


def test_titles_are_derived_and_bounded():
    """A session needs to be identifiable in a list without being named."""
    assert store.title_from("  What is  the SST?  ") == "What is the SST?"
    assert store.title_from("") == "New chat"
    long = store.title_from("x" * 500)
    assert len(long) <= 80 and long.endswith("…")
