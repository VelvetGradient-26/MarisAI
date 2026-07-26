import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

# Parent Record (stores metadata)
class Observation(Base):
    __tablename__ = "observations"
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

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    location = relationship("Location")

    dataset = relationship("Dataset")

    values = relationship(
        "ObservationValue",
        back_populates="observation",
        cascade="all, delete-orphan",
    )