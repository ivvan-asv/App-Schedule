from datetime import datetime
from enum import Enum
from typing import Any
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CaptureChannel(str, Enum):
    VOICE = "voz"
    TEXT = "texto"


class CaptureStatus(str, Enum):
    QUEUED = "encolada"
    PROCESSING = "procesando"
    PROCESSED = "procesada"
    ERROR = "error"


def _enum_values(enum_class: type[Enum]) -> list[str]:
    return [item.value for item in enum_class]


class Capture(Base):
    __tablename__ = "capturas"

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
    # References dispositivos.id; the devices table is not mapped yet.
    device_id: Mapped[uuid.UUID | None] = mapped_column("dispositivo_id", Uuid(as_uuid=True))
    local_id: Mapped[uuid.UUID | None] = mapped_column("id_local", Uuid(as_uuid=True))
    channel: Mapped[CaptureChannel] = mapped_column(
        "canal",
        SqlEnum(CaptureChannel, name="canal_entrada_t", values_callable=_enum_values),
        nullable=False,
    )
    transcription: Mapped[str | None] = mapped_column("transcripcion", Text)
    stt_engine: Mapped[str | None] = mapped_column("motor_stt", String(40))
    llm_model: Mapped[str | None] = mapped_column("modelo_llm", String(40))
    llm_result: Mapped[dict[str, Any] | None] = mapped_column("resultado_llm", JSONB)
    status: Mapped[CaptureStatus] = mapped_column(
        "estado",
        SqlEnum(CaptureStatus, name="estado_captura_t", values_callable=_enum_values),
        nullable=False,
        server_default=text("'encolada'"),
    )
    error_detail: Mapped[str | None] = mapped_column("error_detalle", Text)
    created_offline: Mapped[bool] = mapped_column(
        "creada_offline",
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    captured_at: Mapped[datetime] = mapped_column(
        "capturada_en",
        DateTime(timezone=True),
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        "procesada_en",
        DateTime(timezone=True),
    )
    latency_ms: Mapped[int | None] = mapped_column("latencia_total_ms", Integer)
