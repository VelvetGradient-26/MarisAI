from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class ObservationValue(Base):
    __tablename__ = "observation_values"
    __table_args__ = {"schema": "observations"}

    observation_id: Mapped[UUID] = mapped_column(
        ForeignKey("observations.observations.id"),
        primary_key=True
    )

    quality_flag: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True
    )

    variable_id: Mapped[int] = mapped_column(
        ForeignKey("core.variables.id"),
        primary_key=True,
        index=True
    )

    value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    observation = relationship(
        "Observation",
        back_populates="values",
    )

    variable = relationship("Variable")