"""Chat endpoint. Thin, per the router convention: validate, call the service,
map its one error type to a status code."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.chat import ChatError, answer

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class ChatTurn(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'.")
    content: str = Field(..., max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    # Bounded server-side rather than trusted from the client: the history is
    # replayed into the prompt, so an unbounded list is a way to run up cost
    # and blow the context window from the browser.
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


@router.post("")
async def post_chat(request: ChatRequest):
    try:
        return await answer(
            request.message,
            [turn.model_dump() for turn in request.history],
        )
    except ChatError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
