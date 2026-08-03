from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pymongo.asynchronous.database import AsyncDatabase

from app.database.mongo import get_mongo_db
from dependencies.auth import current_user
from services.download.models import (
    AreaTooLargeError,
    DownloadError,
    DownloadRequest,
    NoDataFoundError,
    ProviderUnavailableError,
    UnsupportedVariableError,
)
from services.download.registry import grouped_for_frontend
from services.download.service import run_download
from services.download_history import list_download_history, record_download

router = APIRouter(prefix="/api/v1", tags=["download"])


@router.get("/variables")
async def get_variables():
    return {"categories": grouped_for_frontend()}


# Sign-in required: each request pulls real Copernicus/ERDDAP data and can run
# to the multi-million-cell cap in services/download/limits.py. `/variables`
# above stays public so the form still renders for signed-out visitors.
@router.post("/download")
async def download(
    request: DownloadRequest,
    user: dict[str, Any] = Depends(current_user),
    db: AsyncDatabase = Depends(get_mongo_db),
) -> Response:
    try:
        result = await run_download(request)
    except DownloadError as exc:
        # Failures are recorded too — "why didn't that one work" is most of what
        # the history view is for. Re-raised below with its real status code.
        await record_download(db, user["_id"], request, status="failed", error_message=str(exc))
        if isinstance(exc, UnsupportedVariableError | AreaTooLargeError):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if isinstance(exc, NoDataFoundError):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if isinstance(exc, ProviderUnavailableError):
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await record_download(
        db,
        user["_id"],
        request,
        status="succeeded",
        filename=result.filename,
        size_bytes=len(result.content),
    )

    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )


@router.get("/download-history")
async def get_download_history(
    limit: int = Query(50, ge=1, le=200),
    user: dict[str, Any] = Depends(current_user),
    db: AsyncDatabase = Depends(get_mongo_db),
) -> dict[str, Any]:
    return {"downloads": await list_download_history(db, user["_id"], limit=limit)}
