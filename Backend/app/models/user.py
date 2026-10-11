from datetime import datetime
import uuid

from sqlalchemy import DateTime, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    __tablename__ = "usuarios"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column("nombre", String(120))
    phone: Mapped[str | None] = mapped_column("telefono", String(20))
    timezone: Mapped[str] = mapped_column(
        "zona_horaria",
        String(64),
        nullable=False,
        server_default=text("'America/Santiago'"),
    )
    language: Mapped[str] = mapped_column(
        "idioma",
        String(10),
        nullable=False,
        server_default=text("'es'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        "creado_en",
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        "actualizado_en",
        DateTime(timezone=True),
        server_default=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        "eliminado_en",
        DateTime(timezone=True),
    )
