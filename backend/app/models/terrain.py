from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base
from app.models.mixins import TimestampMixin


class Terrain(TimestampMixin, Base):
    __tablename__ = "terrains"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    route_configs: Mapped[list["RouteTerrainConfig"]] = relationship(
        back_populates="terrain"
    )


from app.models.route import RouteTerrainConfig  # noqa: E402
