from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    source_id: Mapped[int] = mapped_column(
        ForeignKey("core.data_sources.id"),
        nullable=False,
        index=True
    )

    dataset_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(500),
    )

    spatial_resolution: Mapped[str | None] = mapped_column(
        String(50),
    )

    temporal_resolution: Mapped[str | None] = mapped_column(
        String(50),
    )

    update_frequency: Mapped[str | None] = mapped_column(
        String(50),
    )

    source = relationship(
        "DataSource",
        back_populates="datasets",
    )
