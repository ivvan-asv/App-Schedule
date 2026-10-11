"""Create the Smart Scheduler relational schema.

Revision ID: 0002_smart_scheduler
Revises: 0001_users
Create Date: 2026-10-11
"""
from pathlib import Path
from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_smart_scheduler"
down_revision: str | None = "0001_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_statements() -> list[str]:
    schema_path = Path(__file__).resolve().parents[1] / "smart_scheduler_schema.sql"
    sql_lines = (
        line.split("--", maxsplit=1)[0]
        for line in schema_path.read_text(encoding="utf-8").splitlines()
    )
    return [
        statement.strip()
        for statement in "\n".join(sql_lines).split(";")
        if statement.strip()
    ]


def upgrade() -> None:
    for statement in _schema_statements():
        op.execute(statement)

    op.execute(
        """
        INSERT INTO usuarios (id, email, nombre, creado_en)
        SELECT id, email, display_name, created_at
        FROM users
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.drop_table("users")


def downgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.execute(
        """
        INSERT INTO users (id, email, display_name, created_at)
        SELECT id, email, nombre, creado_en
        FROM usuarios
        ON CONFLICT (id) DO NOTHING
        """
    )

    for table in (
        "reprogramaciones",
        "mensajes",
        "propuestas_horario",
        "negociaciones",
        "contacto_canales",
        "contactos",
        "reglas_agenda",
        "traslados",
        "eventos",
        "capturas",
        "ubicaciones",
        "calendarios",
        "cuentas_calendario",
        "dispositivos",
        "usuarios",
    ):
        op.drop_table(table)

    for enum_name in (
        "estado_reprog_t",
        "motivo_reprog_t",
        "estado_msg_t",
        "direccion_msg_t",
        "estado_propuesta_t",
        "estado_negoc_t",
        "canal_mensaje_t",
        "tipo_regla_t",
        "modo_transporte_t",
        "prioridad_t",
        "origen_evento_t",
        "estado_evento_t",
        "tipo_evento_t",
        "estado_captura_t",
        "canal_entrada_t",
        "estado_cuenta_t",
        "proveedor_cal_t",
        "plataforma_t",
    ):
        op.execute(f"DROP TYPE {enum_name}")
