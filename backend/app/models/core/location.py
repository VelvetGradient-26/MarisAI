import uuid

from geoalchemy2 import Geography
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    geometry: Mapped[str] = mapped_column(
        Geography(
            geometry_type="POINT",
            srid=4326,
        ),
        nullable=False,
    )

    ocean: Mapped[str | None] = mapped_column(
        String(100),
    )

    sea: Mapped[str | None] = mapped_column(
        String(100),
    )

    country: Mapped[str | None] = mapped_column(
        String(100),
    )

    eez: Mapped[str | None] = mapped_column(
        String(150),
    )