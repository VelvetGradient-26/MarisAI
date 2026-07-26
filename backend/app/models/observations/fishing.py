import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class FishingActivity(Base):
    __tablename__ = "fishing_activity"
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

    vessel_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    vessel_name: Mapped[str | None] = mapped_column(
        String(255),
    )

    flag_state: Mapped[str | None] = mapped_column(
        String(100),
    )

    vessel_type: Mapped[str | None] = mapped_column(
        String(100),
    )

    gear_type: Mapped[str | None] = mapped_column(
        String(100),
    )

    speed_knots: Mapped[float | None] = mapped_column(
        Float,
    )

    heading: Mapped[float | None] = mapped_column(
        Float,
    )

    fishing_hours: Mapped[float | None] = mapped_column(
        Float,
    )

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    location = relationship("Location")

    dataset = relationship("Dataset")