from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator

from services.feedback import FeedbackError, send_feedback_email
from services.rate_limit import RateLimiter, enforce

router = APIRouter(prefix="/api/v1", tags=["feedback"])

# The only unauthenticated endpoint that spends a real resource: it sends mail
# through the project's Gmail account. Without a cap it is an open relay for
# filling that mailbox, which gets the account throttled or blocked by Google.
# Five an hour sits far above genuine use and far below automated abuse.
_FEEDBACK_LIMITER = RateLimiter(limit=5, window_seconds=3600)


class FeedbackRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    message: str = Field(..., min_length=1, max_length=5000)

    @field_validator("name")
    @classmethod
    def _no_control_characters(cls, value: str) -> str:
        """`name` is interpolated into the Subject header downstream. Python's
        email generator already refuses to serialise a header holding an
        embedded newline, so this is not the only thing between us and header
        injection — but rejecting it here turns a confusing 502 from the mail
        layer into a plain 422, and keeps the guarantee at the boundary rather
        than resting on stdlib behaviour that could change."""
        if "\r" in value or "\n" in value or "\x00" in value:
            raise ValueError("name must not contain line breaks or null bytes")
        return value.strip()


@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest, http_request: Request) -> dict[str, str]:
    enforce(
        _FEEDBACK_LIMITER,
        http_request,
        "Too many feedback submissions from this address. Please try again later.",
    )
    try:
        await send_feedback_email(request.name, request.email, request.message)
    except FeedbackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "sent"}
