"""Chat endpoints. Thin, per the router convention: validate, call the service,
map its one error type to a status code.

`client_id` is a browser-generated UUID, not an authenticated identity — see
`app/models/chat/session.py` for what that does and does not buy. It is taken
as an explicit field rather than a cookie so it is obvious at every call site
that this is scoping, not auth.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services.chat import ChatError, answer, store

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
