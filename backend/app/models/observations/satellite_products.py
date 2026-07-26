import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class SatelliteProduct(Base):
    __tablename__ = "satellite_products"
    __table_args__ = {"schema": "observations"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("core.datasets.id"),
        nullable=False,
        index=True
    )

    product_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    product_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    observation_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    file_format: Mapped[str | None] = mapped_column(
        String(30),
    )

    resolution: Mapped[str | None] = mapped_column(
        String(50),
    )

    tile_url: Mapped[str | None] = mapped_column(
        String(1000),
    )

    file_path: Mapped[str | None] = mapped_column(
        String(1000),
    )

    bbox_west: Mapped[float | None] = mapped_column(Float)

    bbox_south: Mapped[float | None] = mapped_column(Float)

    bbox_east: Mapped[float | None] = mapped_column(Float)

    bbox_north: Mapped[float | None] = mapped_column(Float)

    cloud_cover: Mapped[float | None] = mapped_column(Float)
    dataset = relationship("Dataset")