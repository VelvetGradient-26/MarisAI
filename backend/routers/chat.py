"""Chat endpoints. Thin, per the router convention: validate, call the service,
map its one error type to a status code.

`client_id` is a browser-generated UUID, not an authenticated identity — see
`app/models/chat/session.py` for what that does and does not buy. It is taken
as an explicit field rather than a cookie so it is obvious at every call site
that this is scoping, not auth.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from services.chat import ChatError, answer, answer_stream, store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class ChatTurn(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'.")
    content: str = Field(..., max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    client_id: str = Field(..., min_length=8, max_length=64)
    session_id: str | None = Field(
        None, description="Continue this session. Omit to start a new one."
    )
    # Only used when no database is configured — otherwise the stored
    # transcript is the authority. Bounded server-side regardless, since it is
    # replayed into the prompt.
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


@router.post("")
async def post_chat(request: ChatRequest):
    try:
        return await answer(
            request.message,
            [turn.model_dump() for turn in request.history],
            session_id=request.session_id,
            client_id=request.client_id,
        )
    except ChatError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/stream")
async def post_chat_stream(request: ChatRequest):
    """The same turn as `POST /api/v1/chat`, as Server-Sent Events.

    Additive: the JSON endpoint above is unchanged and remains the fallback.

    **Errors are split across two regimes, and the split is forced by HTTP.**
    A `ChatError` raised before the first byte is a normal 503. Once the
    response has started, the status line is already sent and cannot be taken
    back — so a later failure can only be reported *inside* the stream, as an
    `error` event. A client must therefore treat an `error` event as fatal for
    the turn, not merely informational; the alternative, tearing the connection
    down mid-stream, is indistinguishable to the browser from a network drop.
    """

    async def events():
        try:
            async for event in answer_stream(
                request.message,
                [turn.model_dump() for turn in request.history],
                session_id=request.session_id,
                client_id=request.client_id,
            ):
                yield _sse(event)
        except ChatError as exc:
            yield _sse({"type": "error", "message": str(exc)})
        except Exception:  # noqa: BLE001 - the stream must not end silently
            logger.exception("chat stream failed")
            yield _sse({"type": "error", "message": "The assistant failed mid-answer."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            # Nginx buffers proxied responses by default, which holds every
            # event until the turn ends and silently turns this back into the
            # non-streaming endpoint.
            "X-Accel-Buffering": "no",
        },
    )


def _sse(payload: dict) -> str:
    """One SSE frame.

    `json.dumps` rather than an f-string because answer text routinely contains
    newlines, and a bare newline inside `data:` terminates the frame — the
    message would arrive truncated at the first line break.
    """
    return f"data: {json.dumps(payload)}\n\n"


@router.get("/sessions")
async def get_sessions(client_id: str = Query(..., min_length=8, max_length=64)):
    return {
        "sessions": await store.list_sessions(client_id),
        # The UI needs to distinguish "no history yet" from "history is not
        # available on this deployment" — they look identical otherwise.
        "persistence": store.enabled(),
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str, client_id: str = Query(..., min_length=8, max_length=64)
):
    messages = await store.transcript(session_id, client_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="No such chat session.")
    return {"session_id": session_id, "messages": messages}


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str, client_id: str = Query(..., min_length=8, max_length=64)
):
    if not await store.remove(session_id, client_id):
        raise HTTPException(status_code=404, detail="No such chat session.")
    return {"deleted": session_id}
