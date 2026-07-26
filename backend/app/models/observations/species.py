import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class SpeciesOccurrence(Base):
    __tablename__ = "species_occurrences"
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

    occurrence_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )

    scientific_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    common_name: Mapped[str | None] = mapped_column(
        String(255),
    )

    kingdom: Mapped[str | None] = mapped_column(
        String(100),
    )

    phylum: Mapped[str | None] = mapped_column(
        String(100),
    )

    class_name: Mapped[str | None] = mapped_column(
        "class",
        String(100),
    )

    order: Mapped[str | None] = mapped_column(
        String(100),
    )

    family: Mapped[str | None] = mapped_column(
        String(100),
    )

    genus: Mapped[str | None] = mapped_column(
        String(100),
    )

    species: Mapped[str | None] = mapped_column(
        String(100),
    )

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    dataset_name: Mapped[str | None] = mapped_column(
    String(255),
    )

    basis_of_record: Mapped[str | None] = mapped_column(
        String(100),
    )

    recorded_by: Mapped[str | None] = mapped_column(
        String(255),
    )

    license: Mapped[str | None] = mapped_column(
        String(255),
    )

    location = relationship("Location")
    dataset = relationship("Dataset")