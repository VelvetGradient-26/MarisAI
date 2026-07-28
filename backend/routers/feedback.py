from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from services.feedback import FeedbackError, send_feedback_email

router = APIRouter(prefix="/api/v1", tags=["feedback"])


class FeedbackRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    message: str = Field(..., min_length=1, max_length=5000)


@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest) -> dict[str, str]:
    try:
        await send_feedback_email(request.name, request.email, request.message)
    except FeedbackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "sent"}
