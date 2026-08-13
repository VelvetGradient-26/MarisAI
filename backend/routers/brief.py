"""Point brief — one coordinate as a document.

Thin, like every router here: the service raises its own error type and this
maps it to a status code. Two representations of one thing, and the JSON is not
a lesser form of the PDF — the frontend renders a preview from it before anyone
commits to a download.
"""

from fastapi import APIRouter, HTTPException, Query, Response

from services import brief as brief_service
from services import brief_pdf
from services.brief import BriefError

router = APIRouter(prefix="/api/brief", tags=["brief"])


@router.get("")
async def get_brief(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    try:
        return await brief_service.build_brief(lat, lon)
    except BriefError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/pdf")
async def get_brief_pdf(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    try:
        brief = await brief_service.build_brief(lat, lon)
    except BriefError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    filename = f"marisai-brief-{lat:.3f}_{lon:.3f}.pdf"
    return Response(
        content=brief_pdf.render(brief),
        media_type="application/pdf",
        # `attachment`, so a click downloads rather than navigating away from the
        # map. The filename carries the coordinate because the first thing anyone
        # does with two of these is compare them.
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
