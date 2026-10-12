from datetime import datetime, time
from decimal import Decimal
from enum import Enum
import uuid

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EventType(str, Enum):
    TASK = "tarea"
    MEETING = "reunion"
    TRAVEL = "traslado"
    BUFFER = "buffer"


class EventStatus(str, Enum):
    TENTATIVE = "tentativo"
    CONFIRMED = "confirmado"
    CANCELLED = "cancelado"


class EventPriority(str, Enum):
    LOW = "baja"
    MEDIUM = "media"
    HIGH = "alta"
    URGENT = "urgente"


class EventOrigin(str, Enum):
    CAPTURE = "captura"
    MANUAL = "manual"
    NEGOTIATION = "negociacion"
    SYNC = "sincronizacion"


class AgendaRuleType(str, Enum):
    WORKING_HOURS = "horario_laboral"
    MEAL = "comida"
    DEFAULT_BUFFER = "buffer_por_defecto"
    DO_NOT_DISTURB = "no_molestar"
    BLOCK = "bloqueo"


def _enum_values(enum_class: type[Enum]) -> list[str]:
    return [item.value for item in enum_class]


class Event(Base):
    __tablename__ = "eventos"

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
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        "ubicacion_id",
        Uuid(as_uuid=True),
        ForeignKey("ubicaciones.id", ondelete="SET NULL"),
    )
    title: Mapped[str] = mapped_column("titulo", String(255), nullable=False)
    description: Mapped[str | None] = mapped_column("descripcion", Text)
    type: Mapped[EventType] = mapped_column(
        "tipo",
        SqlEnum(
            EventType,
            name="tipo_evento_t",
            values_callable=_enum_values,
        ),
        nullable=False,
        server_default=text("'tarea'"),
    )
    status: Mapped[EventStatus] = mapped_column(
        "estado",
        SqlEnum(
            EventStatus,
            name="estado_evento_t",
            values_callable=_enum_values,
        ),
        nullable=False,
        server_default=text("'confirmado'"),
    )
    origin: Mapped[EventOrigin] = mapped_column(
        "origen",
        SqlEnum(
            EventOrigin,
            name="origen_evento_t",
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    priority: Mapped[EventPriority] = mapped_column(
        "prioridad",
        SqlEnum(
            EventPriority,
            name="prioridad_t",
            values_callable=_enum_values,
        ),
        nullable=False,
        server_default=text("'media'"),
    )
    start: Mapped[datetime] = mapped_column(
        "inicio",
        DateTime(timezone=True),
        nullable=False,
    )
    end: Mapped[datetime] = mapped_column(
        "fin",
        DateTime(timezone=True),
        nullable=False,
    )
    flexible: Mapped[bool] = mapped_column(
        "es_flexible",
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        "creado_en",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        "actualizado_en",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Location(Base):
    __tablename__ = "ubicaciones"

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
    alias: Mapped[str | None] = mapped_column(String(80))
    address: Mapped[str | None] = mapped_column("direccion", Text)
    latitude: Mapped[Decimal] = mapped_column("latitud", Numeric(9, 6), nullable=False)
    longitude: Mapped[Decimal] = mapped_column("longitud", Numeric(9, 6), nullable=False)
    place_id: Mapped[str | None] = mapped_column(String(255))
    is_frequent: Mapped[bool] = mapped_column(
        "es_frecuente",
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        "creado_en",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AgendaRule(Base):
    __tablename__ = "reglas_agenda"

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
    type: Mapped[AgendaRuleType] = mapped_column(
        "tipo",
        SqlEnum(
            AgendaRuleType,
            name="tipo_regla_t",
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    name: Mapped[str | None] = mapped_column("nombre", String(100))
    weekdays: Mapped[list[int]] = mapped_column(
        "dias_semana",
        ARRAY(SmallInteger),
        nullable=False,
        server_default=text("'{1,2,3,4,5}'"),
    )
    start_time: Mapped[time | None] = mapped_column("hora_inicio", Time)
    end_time: Mapped[time | None] = mapped_column("hora_fin", Time)
    strict: Mapped[bool] = mapped_column(
        "es_estricta",
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    active: Mapped[bool] = mapped_column(
        "activa",
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        "creado_en",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
