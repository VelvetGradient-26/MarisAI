from fastapi import APIRouter, HTTPException, Response

from services.download.models import (
    AreaTooLargeError,
    DownloadRequest,
    NoDataFoundError,
    ProviderUnavailableError,
    UnsupportedVariableError,
)
from services.download.registry import grouped_for_frontend
from services.download.service import run_download

router = APIRouter(prefix="/api/v1", tags=["download"])


@router.get("/variables")
async def get_variables():
    return {"categories": grouped_for_frontend()}


@router.post("/download")
async def download(request: DownloadRequest) -> Response:
    try:
        result = await run_download(request)
    except (UnsupportedVariableError, AreaTooLargeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NoDataFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProviderUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )
