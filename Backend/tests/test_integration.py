"""Integration tests that run against a real PostgreSQL server.

Set TEST_DATABASE_URL to a server where the role may create databases. Each
run creates a throwaway database, applies the Alembic migrations to it and
drops it afterwards, so existing data is never touched.
"""
import asyncio
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid
from zoneinfo import ZoneInfo

from alembic import command
from alembic.config import Config
import httpx
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app
from app.models import Capture, Event, User
from app.models.capture import CaptureStatus
from app.services.capture_parser import (
    CaptureNotUnderstood,
    ParsedCapture,
    get_capture_parser,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
SANTIAGO = ZoneInfo("America/Santiago")


def next_monday_after_a_week() -> datetime:
    """A Monday far enough ahead that captures never land in the past."""
    day = date.today() + timedelta(days=7)
    day += timedelta(days=(7 - day.weekday()) % 7)
    return datetime(day.year, day.month, day.day, tzinfo=SANTIAGO)


class FakeCaptureParser:
    model_name = "fake-parser"

    def __init__(self, result: ParsedCapture | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, datetime]] = []

    async def parse(self, text: str, reference_local: datetime) -> ParsedCapture:
        self.calls.append((text, reference_local))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def _run_admin_statement(server_url: URL, statement: str) -> None:
    engine = create_async_engine(
        server_url,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "set TEST_DATABASE_URL to run the PostgreSQL integration tests",
)
class PostgresTestCase(unittest.IsolatedAsyncioTestCase):
    """Creates a migrated throwaway database for the subclass's tests."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.server_url = make_url(TEST_DATABASE_URL)
        cls.database_name = f"smart_scheduler_test_{uuid.uuid4().hex[:12]}"
        cls.database_url = cls.server_url.set(database=cls.database_name)

        asyncio.run(
            _run_admin_statement(
                cls.server_url,
                f'CREATE DATABASE "{cls.database_name}"',
            )
        )
        cls.addClassCleanup(cls._drop_database)

        with patch.object(
            settings,
            "DATABASE_URL",
            cls.database_url.render_as_string(hide_password=False),
        ):
            command.upgrade(Config(str(ALEMBIC_INI)), "head")

    @classmethod
    def _drop_database(cls) -> None:
        asyncio.run(
            _run_admin_statement(
                cls.server_url,
                f'DROP DATABASE IF EXISTS "{cls.database_name}" WITH (FORCE)',
            )
        )

    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(self.database_url, poolclass=NullPool)
        self.addAsyncCleanup(self.engine.dispose)
        self.session_factory = session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )

        async def override_get_db():
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)

        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        )
        self.addAsyncCleanup(self.client.aclose)


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "set TEST_DATABASE_URL to run the PostgreSQL integration tests",
)
class PostgresIntegrationTests(PostgresTestCase):
    async def test_mapped_columns_exist_in_migrated_schema(self) -> None:
        def database_columns(connection) -> dict[str, set[str]]:
            inspector = inspect(connection)
            return {
                table_name: {
                    column["name"] for column in inspector.get_columns(table_name)
                }
                for table_name in inspector.get_table_names()
            }

        async with self.engine.connect() as connection:
            columns_by_table = await connection.run_sync(database_columns)

        for table in Base.metadata.sorted_tables:
            with self.subTest(table=table.name):
                self.assertIn(table.name, columns_by_table)
                missing_columns = {
                    column.name for column in table.columns
                } - columns_by_table[table.name]
                self.assertEqual(missing_columns, set())

    async def test_user_update(self) -> None:
        user_response = await self.client.post("/api/v1/users/demo")
        user_url = f"/api/v1/users/{user_response.json()['id']}"

        response = await self.client.patch(user_url, json={"timezone": "Europe/Madrid"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["timezone"], "Europe/Madrid")

        restored = await self.client.patch(user_url, json={"timezone": "America/Santiago"})
        self.assertEqual(restored.json()["timezone"], "America/Santiago")

        missing = await self.client.patch(
            f"/api/v1/users/{uuid.uuid4()}",
            json={"timezone": "Europe/Madrid"},
        )
        self.assertEqual(missing.status_code, 404, missing.text)

    async def test_scheduling_flow(self) -> None:
        user_response = await self.client.post("/api/v1/users/demo")
        self.assertEqual(user_response.status_code, 200, user_response.text)
        user_url = f"/api/v1/users/{user_response.json()['id']}"

        rule_response = await self.client.post(
            f"{user_url}/availability-rules",
            json={
                "name": "Morning",
                "weekdays": [1, 2, 3, 4, 5],
                "start_time": "09:00",
                "end_time": "12:00",
            },
        )
        self.assertEqual(rule_response.status_code, 201, rule_response.text)

        rules_response = await self.client.get(f"{user_url}/availability-rules")
        self.assertEqual(rules_response.status_code, 200, rules_response.text)
        self.assertEqual(
            [rule["id"] for rule in rules_response.json()],
            [rule_response.json()["id"]],
        )

        timezone = ZoneInfo("America/Santiago")
        monday = datetime(2026, 11, 2, tzinfo=timezone)
        event_payload = {
            "title": "Review",
            "start": monday.replace(hour=10).isoformat(),
            "end": monday.replace(hour=10, minute=30).isoformat(),
        }
        event_response = await self.client.post(f"{user_url}/events", json=event_payload)
        self.assertEqual(event_response.status_code, 201, event_response.text)

        conflict_response = await self.client.post(
            f"{user_url}/events",
            json=event_payload,
        )
        self.assertEqual(conflict_response.status_code, 409, conflict_response.text)

        day_range = {
            "from": monday.isoformat(),
            "to": monday.replace(hour=23, minute=59).isoformat(),
        }
        events_response = await self.client.get(f"{user_url}/events", params=day_range)
        self.assertEqual(events_response.status_code, 200, events_response.text)
        self.assertEqual(
            [event["id"] for event in events_response.json()],
            [event_response.json()["id"]],
        )

        slots_response = await self.client.get(
            f"{user_url}/availability/slots",
            params={**day_range, "duration_minutes": 60, "step_minutes": 30},
        )
        self.assertEqual(slots_response.status_code, 200, slots_response.text)
        self.assertEqual(
            [
                datetime.fromisoformat(slot["start"]).astimezone(timezone)
                for slot in slots_response.json()
            ],
            [
                monday.replace(hour=9),
                monday.replace(hour=10, minute=30),
                monday.replace(hour=11),
            ],
        )


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "set TEST_DATABASE_URL to run the PostgreSQL integration tests",
)
class CaptureIntegrationTests(PostgresTestCase):
    """Capture flow with a fake LLM parser; the agenda logic runs for real."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.monday = next_monday_after_a_week()

        async with self.session_factory() as session:
            user = User(email=f"{uuid.uuid4().hex}@example.com", display_name="Capture")
            session.add(user)
            await session.commit()
            self.user_id = user.id
        self.user_url = f"/api/v1/users/{self.user_id}"

        rule_response = await self.client.post(
            f"{self.user_url}/availability-rules",
            json={"weekdays": [1, 2, 3, 4, 5], "start_time": "09:00", "end_time": "12:00"},
        )
        self.assertEqual(rule_response.status_code, 201, rule_response.text)

    def use_parser(self, result: ParsedCapture | Exception) -> FakeCaptureParser:
        parser = FakeCaptureParser(result)
        app.dependency_overrides[get_capture_parser] = lambda: parser
        return parser

    def parsed(self, **overrides) -> ParsedCapture:
        values = {
            "title": "Dentista",
            "event_type": "tarea",
            "priority": "media",
            "start_local": None,
            "duration_minutes": 60,
            "window_start_local": None,
            "window_end_local": None,
        }
        return ParsedCapture(**{**values, **overrides})

    async def captures(self) -> list[Capture]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Capture).where(Capture.user_id == self.user_id)
            )
            return list(result.scalars().all())

    async def test_explicit_time_creates_event_and_replay_is_idempotent(self) -> None:
        start = self.monday.replace(hour=10)
        parser = self.use_parser(self.parsed(start_local=f"{start:%Y-%m-%dT%H:%M}"))
        payload = {
            "text": "el lunes a las diez dentista",
            "channel": "voz",
            "local_id": str(uuid.uuid4()),
            "captured_at": self.monday.replace(hour=8).isoformat(),
            "stt_engine": "apple_speech",
        }

        response = await self.client.post(f"{self.user_url}/captures", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["status"], "procesada")
        self.assertEqual(datetime.fromisoformat(body["event"]["start"]), start)
        self.assertEqual(
            datetime.fromisoformat(body["event"]["end"]),
            start + timedelta(hours=1),
        )
        self.assertFalse(body["event"]["flexible"])
        self.assertEqual(parser.calls[0][1], self.monday.replace(hour=8))

        replay = await self.client.post(f"{self.user_url}/captures", json=payload)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["id"], body["id"])
        self.assertEqual(replay.json()["event"]["id"], body["event"]["id"])
        self.assertEqual(len(parser.calls), 1)

        async with self.session_factory() as session:
            event = await session.get(Event, uuid.UUID(body["event"]["id"]))
        self.assertEqual(event.origin.value, "captura")
        self.assertEqual(str(event.capture_id), body["id"])

        [capture] = await self.captures()
        self.assertEqual(capture.llm_model, "fake-parser")
        self.assertEqual(capture.llm_result["title"], "Dentista")
        self.assertIsNotNone(capture.latency_ms)

    async def test_without_time_uses_first_free_slot_in_window(self) -> None:
        busy = {
            "title": "Ocupado",
            "start": self.monday.replace(hour=9).isoformat(),
            "end": self.monday.replace(hour=10).isoformat(),
        }
        busy_response = await self.client.post(f"{self.user_url}/events", json=busy)
        self.assertEqual(busy_response.status_code, 201, busy_response.text)
        self.use_parser(
            self.parsed(
                event_type="reunion",
                window_start_local=f"{self.monday:%Y-%m-%d}T00:00",
                window_end_local=f"{self.monday:%Y-%m-%d}T23:59",
            )
        )

        response = await self.client.post(
            f"{self.user_url}/captures",
            json={"text": "reunión con Laura el lunes"},
        )

        self.assertEqual(response.status_code, 201, response.text)
        event = response.json()["event"]
        self.assertEqual(datetime.fromisoformat(event["start"]), self.monday.replace(hour=10))
        self.assertEqual(event["type"], "reunion")
        self.assertTrue(event["flexible"])

    async def test_device_busy_intervals_are_avoided(self) -> None:
        device_busy = [
            {
                "start": self.monday.replace(hour=9).isoformat(),
                "end": self.monday.replace(hour=10, minute=30).isoformat(),
            }
        ]
        self.use_parser(
            self.parsed(
                window_start_local=f"{self.monday:%Y-%m-%d}T00:00",
                window_end_local=f"{self.monday:%Y-%m-%d}T23:59",
            )
        )

        response = await self.client.post(
            f"{self.user_url}/captures",
            json={"text": "dentista el lunes", "busy_intervals": device_busy},
        )

        self.assertEqual(response.status_code, 201, response.text)
        event = response.json()["event"]
        self.assertEqual(
            datetime.fromisoformat(event["start"]),
            self.monday.replace(hour=10, minute=30),
        )

        self.use_parser(self.parsed(start_local=f"{self.monday:%Y-%m-%d}T09:30"))
        conflict = await self.client.post(
            f"{self.user_url}/captures",
            json={"text": "dentista el lunes a las 9:30", "busy_intervals": device_busy},
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertIn("device calendar", conflict.json()["detail"])

    async def test_failures_are_recorded_and_reported(self) -> None:
        taken = {
            "title": "Ocupado",
            "start": self.monday.replace(hour=10).isoformat(),
            "end": self.monday.replace(hour=11).isoformat(),
        }
        taken_response = await self.client.post(f"{self.user_url}/events", json=taken)
        self.assertEqual(taken_response.status_code, 201, taken_response.text)

        cases = [
            (
                self.parsed(start_local=f"{self.monday:%Y-%m-%d}T10:30"),
                409,
                "overlaps",
            ),
            (CaptureNotUnderstood("The note does not describe anything"), 422, "describe"),
        ]
        for result, status_code, detail in cases:
            with self.subTest(status_code=status_code):
                self.use_parser(result)
                response = await self.client.post(
                    f"{self.user_url}/captures",
                    json={"text": "algo"},
                )
                self.assertEqual(response.status_code, status_code, response.text)
                self.assertIn(detail, response.json()["detail"])

        captures = await self.captures()
        self.assertEqual(len(captures), 2)
        self.assertTrue(all(c.status == CaptureStatus.ERROR for c in captures))
        self.assertTrue(all(c.error_detail for c in captures))
