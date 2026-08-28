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
from services.download import progress
from services.download.progress import ProgressReporter
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

    reporter = ProgressReporter(payload.request_id)

    try:
        result = await run_download(payload, reporter)
    except DownloadError as exc:
        reporter.failed()
        if isinstance(exc, UnsupportedVariableError | AreaTooLargeError):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if isinstance(exc, NoDataFoundError):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if isinstance(exc, ProviderUnavailableError):
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    else:
        # Only on success. A failed entry is deliberately left behind so a poll
        # already in flight reports the failure rather than a bar frozen at
        # whatever fraction it had reached; the TTL sweeps it up.
        reporter.release()

    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )


@router.get("/download/progress/{request_id}")
async def download_progress(request_id: str) -> dict[str, object]:
    """Where an in-flight download has got to.

    Deliberately outside the download rate limiter: this is polled every few
    hundred milliseconds *by* a legitimate download, and counting those against
    an hourly export budget would make watching a download cost you the ability
    to start one.

    A missing entry is reported as `tracked: false` with a 200 rather than a
    404. It is the normal state twice in every download's life — before the
    server registers the request, and after it completes and releases — and
    neither is an error the client should surface.
    """
    state = progress.snapshot(request_id)
    if state is None:
        return {"tracked": False}
    return {"tracked": True, **state}
