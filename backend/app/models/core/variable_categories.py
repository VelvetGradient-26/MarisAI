from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class VariableCategory(Base):
    __tablename__ = "variable_categories"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(500)
    )

    variables = relationship(
        "Variable",
        back_populates="category",
    )