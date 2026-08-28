"""REST surface for proactive alert watches (sihtodo.md item 8).

Thin, same convention as every other router in this codebase: validate here,
call the service, map its exception type to a real status code. See
`services/watch_alerts.py`'s own docstring for the feature design.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field, field_validator

from services.rate_limit import RateLimiter, enforce
from services.watch_alerts import WatchError, confirm, create, list_for_client, unsubscribe

router = APIRouter(prefix="/api/v1", tags=["watch"])

# A watch, like feedback, spends a real resource (an email send) on an
# unauthenticated endpoint — the same cap `routers/feedback.py` uses and the
# same reasoning: comfortably above genuine use, comfortably below abuse.
_CREATE_LIMITER = RateLimiter(limit=5, window_seconds=3600)


def _no_control_characters(value: str) -> str:
    """Guards against header/body injection into the outgoing email — the
    same rule `routers/feedback.py::FeedbackRequest` applies to `name`,
    needed here for `label` since it is interpolated into an email subject
    and body."""
    if "\r" in value or "\n" in value or "\x00" in value:
        raise ValueError("must not contain line breaks or null bytes")
    return value.strip()


class WatchRequest(BaseModel):
    client_id: str = Field(..., min_length=8, max_length=64)
    email: EmailStr
    label: str = Field(..., min_length=1, max_length=120)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    radius_km: float = Field(200.0, ge=50, le=2000)

    @field_validator("label")
    @classmethod
    def _label_is_clean(cls, value: str) -> str:
        return _no_control_characters(value)


@router.post("/watch")
async def create_watch(request: WatchRequest, http_request: Request) -> dict[str, str]:
    enforce(
        _CREATE_LIMITER,
        http_request,
        "Too many watch requests from this address. Please try again later.",
    )
    try:
        return await create(
            request.client_id,
            request.email,
            request.label,
            request.latitude,
            request.longitude,
            request.radius_km,
        )
    except WatchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/watch/confirm")
async def confirm_watch(token: str = Query(..., min_length=1)) -> dict[str, str]:
    if not await confirm(token):
        raise HTTPException(status_code=400, detail="This confirmation link is invalid or has expired.")
    return {"status": "confirmed"}


@router.get("/watch/unsubscribe")
async def unsubscribe_watch(token: str = Query(..., min_length=1)) -> dict[str, str]:
    if not await unsubscribe(token):
        raise HTTPException(status_code=400, detail="This unsubscribe link is invalid or has expired.")
    return {"status": "unsubscribed"}


@router.get("/watch")
async def get_watches(client_id: str = Query(..., min_length=8, max_length=64)) -> dict[str, list]:
    return {"watches": await list_for_client(client_id)}
