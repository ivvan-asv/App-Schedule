from datetime import datetime
from enum import Enum
import uuid

from sqlalchemy import (
    ARRAY,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CalendarProvider(str, Enum):
    GOOGLE = "google"
    MICROSOFT = "microsoft"
    APPLE_LOCAL = "apple_local"


class CalendarAccountStatus(str, Enum):
    ACTIVE = "activa"
    TOKEN_EXPIRED = "token_expirado"
    REVOKED = "revocada"


def _enum_values(enum_class: type[Enum]) -> list[str]:
    return [item.value for item in enum_class]


class CalendarAccount(Base):
    """A connected Google or Microsoft account. Tokens are AES-256-GCM encrypted."""

    __tablename__ = "cuentas_calendario"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        "usuario_id",
        Uuid(as_uuid=True),
        ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[CalendarProvider] = mapped_column(
        "proveedor",
        SqlEnum(CalendarProvider, name="proveedor_cal_t", values_callable=_enum_values),
        nullable=False,
    )
    external_email: Mapped[str | None] = mapped_column("email_externo", String(255))
    access_token_encrypted: Mapped[bytes | None] = mapped_column("access_token_cifrado", LargeBinary)
    refresh_token_encrypted: Mapped[bytes | None] = mapped_column("refresh_token_cifrado", LargeBinary)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        "token_expira_en",
        DateTime(timezone=True),
    )
    scopes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    status: Mapped[CalendarAccountStatus] = mapped_column(
        "estado",
        SqlEnum(CalendarAccountStatus, name="estado_cuenta_t", values_callable=_enum_values),
        nullable=False,
        server_default=text("'activa'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        "creado_en",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
