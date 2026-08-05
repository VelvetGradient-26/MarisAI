"""Universal Ocean Data Downloader endpoints.

**Previously sign-in gated.** Authentication was removed from the project (see
`docs/AUTH_REMOVAL.md`), and it was this endpoint's only abuse control — a
download can pull to the multi-million-cell cap in `services/download/limits.py`
against real Copernicus/ERDDAP quota. A rate limiter replaces it rather than
leaving the endpoint open: unlike sign-in it is per-IP and therefore weaker
against a determined caller, but it is what stops a script walking bounding
boxes and exhausting the free-tier quota for everyone.

Download *history* went with authentication, since a per-user record has no
meaning without users.
"""

from fastapi import APIRouter, HTTPException, Request, Response

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
from services.rate_limit import RateLimiter, enforce

router = APIRouter(prefix="/api/v1", tags=["download"])

# Deliberately hourly rather than per-minute. A legitimate user exports a
# handful of datasets in a session; the cost being defended against is a script
# looping over bounding boxes, and a per-minute window would let one run
# unbounded across an afternoon.
_DOWNLOAD_LIMITER = RateLimiter(limit=10, window_seconds=3600)


@router.get("/variables")
async def get_variables():
    return {"categories": grouped_for_frontend()}


@router.post("/download")
async def download(payload: DownloadRequest, request: Request) -> Response:
    enforce(
        _DOWNLOAD_LIMITER,
        request,
        "Download limit reached. Each export pulls live ocean data from "
        "Copernicus and ERDDAP; please try again later.",
    )

    try:
        result = await run_download(payload)
    except DownloadError as exc:
        if isinstance(exc, UnsupportedVariableError | AreaTooLargeError):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if isinstance(exc, NoDataFoundError):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if isinstance(exc, ProviderUnavailableError):
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )
