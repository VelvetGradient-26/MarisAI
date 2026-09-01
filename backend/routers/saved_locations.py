from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from pymongo.asynchronous.database import AsyncDatabase

from app.database.mongo import get_mongo_db
from dependencies.auth import current_user
from services.saved_locations import (
    SavedLocationLimitError,
    SavedLocationNotFoundError,
    create_saved_location,
    delete_saved_location,
    list_saved_locations,
)

router = APIRouter(prefix="/api/v1/saved-locations", tags=["saved-locations"])


class SavedLocationRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


@router.get("")
async def get_saved_locations(
    user: dict[str, Any] = Depends(current_user),
    db: AsyncDatabase = Depends(get_mongo_db),
) -> dict[str, Any]:
    return {"locations": await list_saved_locations(db, user["_id"])}


@router.post("", status_code=status.HTTP_201_CREATED)
async def post_saved_location(
    request: SavedLocationRequest,
    user: dict[str, Any] = Depends(current_user),
    db: AsyncDatabase = Depends(get_mongo_db),
) -> dict[str, Any]:
    try:
        return await create_saved_location(
            db, user["_id"], request.label.strip(), request.lat, request.lon
        )
    except SavedLocationLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_saved_location(
    location_id: str,
    user: dict[str, Any] = Depends(current_user),
    db: AsyncDatabase = Depends(get_mongo_db),
) -> Response:
    try:
        await delete_saved_location(db, user["_id"], location_id)
    except SavedLocationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
