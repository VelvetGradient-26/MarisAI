from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from services.insights import InsightsError, generate_ocean_insights
from services.llm import LLMError
from services.rate_limit import RateLimiter, enforce

router = APIRouter(prefix="/api/insights", tags=["insights"])

# Every field below is interpolated into the LLM prompt, and every one of them
# arrives from the browser. Two problems follow from that, and these bounds
# address the second while narrowing the first:
#
#   * Prompt injection. Nothing here can be trusted as instruction-free text,
#     so the prompt in services/insights.py must keep treating it as data.
#     Short fields at least deny the room a serious injection needs.
#   * Cost. Tokens are billed against the project's own LLM quota, so an
#     unbounded string is an unbounded bill from any one signed-in account.
_MAX_TEXT = 120
_MAX_METRICS = 40


class NearestPort(BaseModel):
    name: str = Field(..., max_length=_MAX_TEXT)
    country: str = Field(..., max_length=_MAX_TEXT)
    distance_km: float = Field(..., ge=0, le=25_000)


class LocationContext(BaseModel):
    ocean_name: str | None = Field(None, max_length=_MAX_TEXT)
    nearest_port: NearestPort | None = None
    locality: str | None = Field(None, max_length=_MAX_TEXT)
    continent: str | None = Field(None, max_length=_MAX_TEXT)


class RequestedPoint(BaseModel):
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)


class GenerateInsightsRequest(BaseModel):
    current: dict[str, float | str | None]
    units: dict[str, str | None] = {}
    location_context: LocationContext | None = None
    requested: RequestedPoint | None = None

    @field_validator("current", "units")
    @classmethod
    def _bounded_metrics(cls, value: dict[str, Any]) -> dict[str, Any]:
        """The prompt builder only reads a fixed set of keys, so extra ones are
        harmless — but the *values* are pasted in verbatim, and neither the
        number of entries nor the length of a value was capped."""
        if len(value) > _MAX_METRICS:
            raise ValueError(f"at most {_MAX_METRICS} entries are accepted")
        for entry in value.values():
            if isinstance(entry, str) and len(entry) > _MAX_TEXT:
                raise ValueError(f"values must be at most {_MAX_TEXT} characters")
        return value


# One brief every few seconds is well past what reading a dashboard needs, and
# far under what a script would do.
#
# **Tightened from 10/min when authentication was removed** (see
# `docs/AUTH_REMOVAL.md`). This limiter previously keyed on the user id, which
# a caller cannot rotate; keyed on the address it is materially weaker, since
# switching networks resets it. Every call spends real LLM quota and an open
# endpoint burned through a Gemini free tier once already, so the budget drops
# to compensate for the weaker key.
_INSIGHTS_LIMITER = RateLimiter(limit=5, window_seconds=60)


@router.post("/generate")
async def post_generate_insights(
    payload: GenerateInsightsRequest,
    request: Request,
):
    enforce(
        _INSIGHTS_LIMITER,
        request,
        "Too many insight requests. Please wait a moment and try again.",
    )
    try:
        return await generate_ocean_insights(
            current=payload.current,
            units=payload.units,
            location_context=payload.location_context.model_dump() if payload.location_context else None,
            requested=payload.requested.model_dump() if payload.requested else None,
        )
    except (InsightsError, LLMError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
