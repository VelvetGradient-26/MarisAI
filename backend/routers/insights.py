from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dependencies.auth import current_user
from services.insights import InsightsError, generate_ocean_insights
from services.llm import LLMError

router = APIRouter(prefix="/api/insights", tags=["insights"])


class NearestPort(BaseModel):
    name: str
    country: str
    distance_km: float


class LocationContext(BaseModel):
    ocean_name: str | None = None
    nearest_port: NearestPort | None = None
    locality: str | None = None
    continent: str | None = None


class RequestedPoint(BaseModel):
    latitude: float | None = None
    longitude: float | None = None


class GenerateInsightsRequest(BaseModel):
    current: dict[str, float | str | None]
    units: dict[str, str | None] = {}
    location_context: LocationContext | None = None
    requested: RequestedPoint | None = None


# Sign-in required: every call spends real LLM quota, and an open endpoint
# burned through a Gemini free tier once already.
@router.post("/generate")
async def post_generate_insights(
    payload: GenerateInsightsRequest,
    _user: dict[str, Any] = Depends(current_user),
):
    try:
        return await generate_ocean_insights(
            current=payload.current,
            units=payload.units,
            location_context=payload.location_context.model_dump() if payload.location_context else None,
            requested=payload.requested.model_dump() if payload.requested else None,
        )
    except (InsightsError, LLMError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
