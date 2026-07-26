from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Variable(Base):
    __tablename__ = "variables"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    code: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    category_id: Mapped[int] = mapped_column(
        ForeignKey("core.variable_categories.id"),
        nullable=False,
        index=True
    )

    unit_id: Mapped[int] = mapped_column(
        ForeignKey("core.units.id"),
        nullable=False,
        index=True
    )

    description: Mapped[str | None] = mapped_column(
        String(500)
    )

    category = relationship(
        "VariableCategory",
        back_populates="variables",
    )

    unit = relationship(
        "Unit",
        back_populates="variables",
    )