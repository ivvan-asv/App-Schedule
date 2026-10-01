from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ParsedEventSchema(BaseModel):
    title: str = Field(..., description="Título o descripción resumida del evento")
    start_time: datetime = Field(..., description="Fecha y hora de inicio estimada (ISO 8601)")
    duration_minutes: int = Field(default=30, ge=5, description="Duración estimada en minutos")
    location: Optional[str] = Field(None, description="Lugar físico o enlace virtual del evento")
    priority: str = Field(default="medium", description="Nivel de prioridad: low, medium, high")
    notes: Optional[str] = Field(None, description="Notas adicionales extraídas del comando")