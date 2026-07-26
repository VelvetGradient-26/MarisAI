import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class EarthquakeEvent(Base):
    __tablename__ = "earthquake_events"
    __table_args__ = {"schema": "observations"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.locations.id"),
        nullable=False,
        index=True
    )

    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("core.datasets.id"),
        nullable=False,
        index=True
    )

    usgs_event_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    magnitude: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    depth_km: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    place: Mapped[str | None] = mapped_column(
        String(255),
    )

    tsunami: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    alert_level: Mapped[str | None] = mapped_column(
        String(20),
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    event_url: Mapped[str | None] = mapped_column(
    String(1000),
    )

    location = relationship("Location")
    dataset = relationship("Dataset")