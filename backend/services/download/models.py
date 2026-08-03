"""Request/response shapes for the Universal Ocean Data Downloader.

Kept deliberately separate from `app/models/` (the SQLAlchemy schema under
`core`/`observations`) — that schema is real and migrated but nothing in the
app queries it yet, and this feature doesn't need persistence, only a request
contract, so introducing a DB dependency here would be scope creep for no
functional gain.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class Resolution(str, Enum):
    hourly = "hourly"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class OutputFormat(str, Enum):
    csv = "csv"
    json = "json"
    pdf = "pdf"


class PointArea(BaseModel):
    type: Literal["point"] = "point"
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class BboxArea(BaseModel):
    type: Literal["bbox"] = "bbox"
    west: float = Field(..., ge=-180, le=180)
    south: float = Field(..., ge=-90, le=90)
    east: float = Field(..., ge=-180, le=180)
    north: float = Field(..., ge=-90, le=90)

    @model_validator(mode="after")
    def _check_order(self) -> "BboxArea":
        if self.east <= self.west:
            raise ValueError("east must be greater than west")
        if self.north <= self.south:
            raise ValueError("north must be greater than south")
        return self


Area = Annotated[PointArea | BboxArea, Field(discriminator="type")]


class DownloadRequest(BaseModel):
    area: Area
    start_date: date
    end_date: date
    resolution: Resolution
    variables: list[str] = Field(..., min_length=1)
    format: OutputFormat
    # Target depth for the depth-resolved variables (water temperature and
    # salinity); ignored by every other variable, which is why it defaults
    # rather than being required. The value is snapped to the nearest of the
    # model's 50 levels, and the level actually used is reported back in the
    # export's metadata. The deepest level is ~5728m.
    depth_m: float = Field(0.0, ge=0, le=6000)

    @model_validator(mode="after")
    def _check_dates(self) -> "DownloadRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class DownloadError(RuntimeError):
    """Base for download-service errors surfaced as a clean HTTP error —
    never a raw copernicusmarine/xarray traceback."""


class UnsupportedVariableError(DownloadError):
    pass


class AreaTooLargeError(DownloadError):
    pass


class NoDataFoundError(DownloadError):
    pass


class ProviderUnavailableError(DownloadError):
    pass
