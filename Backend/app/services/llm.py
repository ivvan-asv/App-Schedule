from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import dateparser
import httpx

from app.core.config import settings
from app.schemas.event import ParsedEventSchema

SYSTEM_PROMPT = """Eres el extractor de entidades de Smart Scheduler AI.
Devuelve SOLO JSON válido con estas claves:
title (string), start_time (ISO 8601 con offset), duration_minutes (int >= 5),
location (string|null), priority (low|medium|high), notes (string|null),
attendees (array de strings), needs_travel (bool), origin_location (string|null).
Si no hay hora, usa el siguiente horario laboral a las 10:00 en la zona horaria dada.
Si no hay duración, usa 30.
Interpreta lenguaje natural en español o inglés.
"""


async def parse_intent(
    text: str,
    timezone: str,
    origin_location: str | None = None,
) -> tuple[ParsedEventSchema, str]:
    if settings.GEMINI_API_KEY:
        parsed = await _parse_with_gemini(text, timezone, origin_location)
        if parsed:
            return parsed, "gemini"
    if settings.OPENAI_API_KEY:
        parsed = await _parse_with_openai(text, timezone, origin_location)
        if parsed:
            return parsed, "openai"
    return _parse_heuristic(text, timezone, origin_location), "heuristic"


async def _parse_with_gemini(
    text: str, timezone: str, origin_location: str | None
) -> ParsedEventSchema | None:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-1.5-flash:generateContent"
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            f"{SYSTEM_PROMPT}\nZona horaria: {timezone}\n"
                            f"Origen del usuario: {origin_location}\nTexto: {text}"
                        )
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            url,
            params={"key": settings.GEMINI_API_KEY},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    raw = data["candidates"][0]["content"]["parts"][0]["text"]
    return ParsedEventSchema.model_validate_json(raw)


async def _parse_with_openai(
    text: str, timezone: str, origin_location: str | None
) -> ParsedEventSchema | None:
    schema = ParsedEventSchema.model_json_schema()
    payload = {
        "model": "gpt-4o-mini",
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Zona horaria: {timezone}. Origen: {origin_location}. Texto: {text}"
                ),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "parsed_event",
                "strict": True,
                "schema": schema,
            },
        },
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    raw = data["choices"][0]["message"]["content"]
    return ParsedEventSchema.model_validate_json(raw)


def _parse_heuristic(
    text: str, timezone: str, origin_location: str | None
) -> ParsedEventSchema:
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    parsed_dt = dateparser.parse(
        text,
        settings={
            "TIMEZONE": timezone,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": now,
        },
        languages=["es", "en"],
    )
    start = parsed_dt.astimezone(tz) if parsed_dt else _next_work_slot(now)
    if start.hour == 0 and start.minute == 0 and not _has_explicit_time(text):
        start = start.replace(hour=10, minute=0, second=0, microsecond=0)

    duration = 30
    duration_match = re.search(r"(\d+)\s*(min|minuto|minutos|hora|horas|h)\b", text, re.I)
    if duration_match:
        value = int(duration_match.group(1))
        unit = duration_match.group(2).lower()
        duration = value * 60 if unit.startswith("h") else value

    location = _extract_location(text)
    attendees = _extract_attendees(text)
    title = _extract_title(text, attendees)
    needs_travel = bool(location) and not _looks_virtual(location)
    priority = "high" if re.search(r"urgente|asap|hoy mismo", text, re.I) else "medium"

    return ParsedEventSchema(
        title=title,
        start_time=start,
        duration_minutes=max(5, duration),
        location=location,
        priority=priority,
        notes=text.strip(),
        attendees=attendees,
        needs_travel=needs_travel,
        origin_location=origin_location,
    )


def _next_work_slot(now: datetime) -> datetime:
    candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=30)
    if candidate.hour >= 20:
        candidate = (candidate + timedelta(days=1)).replace(hour=10, minute=0)
    if candidate.hour < 8:
        candidate = candidate.replace(hour=10, minute=0)
    return candidate


def _has_explicit_time(text: str) -> bool:
    return bool(re.search(r"\b(\d{1,2}(:\d{2})?\s*(am|pm)?|a las \d{1,2})\b", text, re.I))


def _extract_location(text: str) -> str | None:
    match = re.search(
        r"\b(?:en|at|@)\s+((?:https?://\S+)|(?:[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ .-]{2,}))",
        text,
    )
    if match:
        return match.group(1).strip(" .,")
    return None


def _extract_attendees(text: str) -> list[str]:
    match = re.search(r"\b(?:con|with)\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+(?:\s+y\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+)*)", text)
    if not match:
        return []
    return [part.strip() for part in re.split(r"\s+y\s+|\s+and\s+", match.group(1)) if part.strip()]


def _extract_title(text: str, attendees: list[str]) -> str:
    cleaned = re.sub(r"\b(agenda|agend[áa]|programa|schedule|reuni[oó]n con)\b", "", text, flags=re.I)
    cleaned = re.sub(r"\b(mañana|hoy|pasado mañana|tomorrow|today)\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\ba las \d{1,2}(:\d{2})?\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,")
    if attendees and len(cleaned) < 4:
        return f"Reunión con {', '.join(attendees)}"
    return cleaned[:120] or "Nuevo evento"


def _looks_virtual(location: str) -> bool:
    return bool(re.search(r"zoom|meet|teams|http", location, re.I))
