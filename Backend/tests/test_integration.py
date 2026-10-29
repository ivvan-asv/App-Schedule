"""Integration tests that run against a real PostgreSQL server.

Set TEST_DATABASE_URL to a server where the role may create databases. Each
run creates a throwaway database, applies the Alembic migrations to it and
drops it afterwards, so existing data is never touched.
"""
import asyncio
from datetime import UTC, date, datetime, timedelta
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
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
from app.models import CalendarAccount, Capture, Event, Travel, User
from app.models.calendar import CalendarAccountStatus
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

    async def test_working_hours_are_replaced_as_a_whole(self) -> None:
        user_response = await self.client.post("/api/v1/users/demo")
        user_url = f"/api/v1/users/{user_response.json()['id']}"
        await self.client.post(
            f"{user_url}/availability-rules",
            json={"weekdays": [1, 2, 3, 4, 5], "start_time": "09:00", "end_time": "18:00"},
        )

        response = await self.client.put(
            f"{user_url}/working-hours",
            json={
                "rules": [
                    {"weekdays": [1, 3], "start_time": "08:00", "end_time": "14:00"},
                    {"weekdays": [6], "start_time": "10:00", "end_time": "13:00"},
                ]
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        listed = await self.client.get(f"{user_url}/availability-rules")
        self.assertEqual(
            sorted((rule["weekdays"], rule["start_time"]) for rule in listed.json()),
            [([1, 3], "08:00:00"), ([6], "10:00:00")],
        )

        monday = next_monday_after_a_week()
        slots = await self.client.get(
            f"{user_url}/availability/slots",
            params={
                "from": monday.replace(hour=0).isoformat(),
                "to": monday.replace(hour=23).isoformat(),
                "duration_minutes": 60,
                "step_minutes": 60,
            },
        )
        starts = [datetime.fromisoformat(slot["start"]).astimezone(SANTIAGO).hour for slot in slots.json()]
        self.assertEqual(starts[0], 8)
        self.assertEqual(starts[-1], 13)

        empty = await self.client.put(f"{user_url}/working-hours", json={"rules": []})
        self.assertEqual(empty.status_code, 422, empty.text)

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
            "location_query": None,
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

        self.assertIsNone(body["location_query"])

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

    async def test_capture_returns_the_place_to_resolve(self) -> None:
        start = self.monday.replace(hour=10)
        self.use_parser(
            self.parsed(
                start_local=f"{start:%Y-%m-%dT%H:%M}",
                location_query="dentista en Providencia",
            )
        )

        response = await self.client.post(
            f"{self.user_url}/captures",
            json={"text": "el lunes a las diez dentista en Providencia"},
        )

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["location_query"], "dentista en Providencia")
        self.assertIsNone(response.json()["event"]["location_id"])

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


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "set TEST_DATABASE_URL to run the PostgreSQL integration tests",
)
class LocationIntegrationTests(PostgresTestCase):
    """Saved places and travel blocks; the travel time comes from the app."""

    office = {"alias": "Oficina", "latitude": -33.4372, "longitude": -70.6506}
    dentist = {
        "alias": "Clínica Dental",
        "address": "Av. Providencia 1234",
        "latitude": -33.4263,
        "longitude": -70.6170,
        "place_id": "mapkit:dental-1",
    }

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.monday = next_monday_after_a_week()
        async with self.session_factory() as session:
            user = User(email=f"{uuid.uuid4().hex}@example.com", display_name="Places")
            session.add(user)
            await session.commit()
            self.user_id = user.id
        self.user_url = f"/api/v1/users/{self.user_id}"
        rule_response = await self.client.post(
            f"{self.user_url}/availability-rules",
            json={"weekdays": [1, 2, 3, 4, 5], "start_time": "09:00", "end_time": "18:00"},
        )
        self.assertEqual(rule_response.status_code, 201, rule_response.text)

    async def create_event(self, hour: int, minute: int = 0, **extra) -> dict:
        start = self.monday.replace(hour=hour, minute=minute)
        response = await self.client.post(
            f"{self.user_url}/events",
            json={
                "title": extra.pop("title", "Dentista"),
                "start": start.isoformat(),
                "end": (start + timedelta(hours=1)).isoformat(),
                **extra,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def make_flexible(self, event_id: str) -> None:
        async with self.session_factory() as session:
            event = await session.get(Event, uuid.UUID(event_id))
            event.flexible = True
            event.window_start = self.monday.replace(hour=0)
            event.window_end = self.monday.replace(hour=23, minute=59)
            await session.commit()

    async def put_location(self, event_id: str, **body) -> httpx.Response:
        return await self.client.put(f"{self.user_url}/events/{event_id}/location", json=body)

    async def travel_children(self, event_id: str) -> list[Event]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Event).where(Event.parent_id == uuid.UUID(event_id))
            )
            return list(result.scalars().all())

    async def test_saved_places_are_upserted_by_alias(self) -> None:
        first = await self.client.post(f"{self.user_url}/locations", json=self.office)
        self.assertEqual(first.status_code, 201, first.text)
        moved = await self.client.post(
            f"{self.user_url}/locations",
            json={**self.office, "alias": "oficina", "latitude": -33.40},
        )
        self.assertEqual(moved.json()["id"], first.json()["id"])
        self.assertEqual(moved.json()["latitude"], -33.40)

        listed = await self.client.get(f"{self.user_url}/locations")
        self.assertEqual([place["id"] for place in listed.json()], [first.json()["id"]])

        deleted = await self.client.delete(f"{self.user_url}/locations/{first.json()['id']}")
        self.assertEqual(deleted.status_code, 204)
        missing = await self.client.delete(f"{self.user_url}/locations/{first.json()['id']}")
        self.assertEqual(missing.status_code, 404)

    async def test_travel_block_is_inserted_before_the_event(self) -> None:
        office = (await self.client.post(f"{self.user_url}/locations", json=self.office)).json()
        event = await self.create_event(11)
        body = {
            "location": self.dentist,
            "travel": {
                "origin_location_id": office["id"],
                "duration_seconds": 22 * 60,
                "distance_meters": 5400,
            },
        }

        response = await self.put_location(event["id"], **body)

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertFalse(result["moved"])
        self.assertFalse(result["travel_overlaps"])
        self.assertEqual(result["event"]["location_id"], result["location"]["id"])
        travel = result["travel"]
        self.assertEqual(travel["type"], "traslado")
        self.assertEqual(travel["parent_id"], event["id"])
        self.assertEqual(travel["title"], "Traslado a Clínica Dental")
        # 22 minutes round up to 25.
        self.assertEqual(
            datetime.fromisoformat(travel["start"]),
            self.monday.replace(hour=10, minute=35),
        )
        self.assertEqual(datetime.fromisoformat(travel["end"]), self.monday.replace(hour=11))

        async with self.session_factory() as session:
            detail = await session.get(Travel, uuid.UUID(travel["id"]))
        self.assertEqual(detail.duration_seconds, 22 * 60)
        self.assertEqual(str(detail.origin_id), office["id"])
        self.assertEqual(detail.provider, "mapkit")

        # A retry replaces the block and reuses the place.
        retry = await self.put_location(event["id"], **body)
        self.assertEqual(retry.json()["location"]["id"], result["location"]["id"])
        self.assertEqual(len(await self.travel_children(event["id"])), 1)

        # The travel block makes that time busy for later events.
        overlapping = await self.client.post(
            f"{self.user_url}/events",
            json={
                "title": "Llamada",
                "start": self.monday.replace(hour=10, minute=40).isoformat(),
                "end": self.monday.replace(hour=10, minute=50).isoformat(),
            },
        )
        self.assertEqual(overlapping.status_code, 409, overlapping.text)

    async def test_flexible_event_moves_so_the_trip_fits(self) -> None:
        await self.create_event(9, 30, title="Reunión")
        event = await self.create_event(10, 30)
        await self.make_flexible(event["id"])

        response = await self.put_location(
            event["id"],
            location=self.dentist,
            travel={"duration_seconds": 30 * 60},
        )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertTrue(result["moved"])
        self.assertFalse(result["travel_overlaps"])
        # The meeting ends at 10:30; the trip takes 10:30–11:00.
        self.assertEqual(
            datetime.fromisoformat(result["event"]["start"]),
            self.monday.replace(hour=11),
        )
        self.assertEqual(
            datetime.fromisoformat(result["travel"]["start"]),
            self.monday.replace(hour=10, minute=30),
        )

    async def test_flexible_event_avoids_device_busy_times_when_moving(self) -> None:
        event = await self.create_event(10)
        await self.make_flexible(event["id"])

        response = await self.put_location(
            event["id"],
            location=self.dentist,
            travel={"duration_seconds": 15 * 60},
            busy_intervals=[
                {
                    "start": self.monday.replace(hour=9).isoformat(),
                    "end": self.monday.replace(hour=10).isoformat(),
                }
            ],
        )

        # The trip (9:45–10:00) hits the device busy time, so the event moves
        # to the first slot after it with room for the trip.
        result = response.json()
        self.assertTrue(result["moved"], response.text)
        self.assertEqual(
            datetime.fromisoformat(result["travel"]["start"]),
            self.monday.replace(hour=10),
        )
        self.assertEqual(
            datetime.fromisoformat(result["event"]["start"]),
            self.monday.replace(hour=10, minute=15),
        )

    async def test_fixed_event_keeps_its_time_and_reports_the_overlap(self) -> None:
        await self.create_event(9, 30, title="Reunión")
        event = await self.create_event(10, 30)

        response = await self.put_location(
            event["id"],
            location=self.dentist,
            travel={"duration_seconds": 30 * 60},
        )

        result = response.json()
        self.assertFalse(result["moved"])
        self.assertTrue(result["travel_overlaps"])
        self.assertEqual(
            datetime.fromisoformat(result["event"]["start"]),
            self.monday.replace(hour=10, minute=30),
        )
        self.assertEqual(
            datetime.fromisoformat(result["travel"]["start"]),
            self.monday.replace(hour=10),
        )

    async def test_short_trip_and_place_only_create_no_travel_block(self) -> None:
        event = await self.create_event(11)

        for travel in (None, {"duration_seconds": 30}):
            with self.subTest(travel=travel):
                response = await self.put_location(
                    event["id"], location=self.dentist, travel=travel
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIsNone(response.json()["travel"])
        self.assertEqual(await self.travel_children(event["id"]), [])

    async def test_rejects_other_users_places_and_events(self) -> None:
        event = await self.create_event(11)
        foreign = await self.put_location(event["id"], location_id=str(uuid.uuid4()))
        self.assertEqual(foreign.status_code, 404, foreign.text)

        missing = await self.put_location(str(uuid.uuid4()), location=self.dentist)
        self.assertEqual(missing.status_code, 404, missing.text)

        both = await self.put_location(
            event["id"], location=self.dentist, location_id=str(uuid.uuid4())
        )
        self.assertEqual(both.status_code, 422, both.text)


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "set TEST_DATABASE_URL to run the PostgreSQL integration tests",
)
class CalendarIntegrationTests(PostgresTestCase):
    """Google connection with the provider's HTTP API simulated."""

    async def asyncSetUp(self) -> None:
        from app.api.v1.calendar import get_oauth_state_store
        from app.services.calendar_accounts import get_calendar_http
        from tests.test_calendar import CONFIGURED, InMemoryStateStore, id_token

        await super().asyncSetUp()
        self.monday = next_monday_after_a_week()
        settings_patch = patch.multiple(settings, **CONFIGURED)
        settings_patch.start()
        self.addCleanup(settings_patch.stop)

        self.state_store = InMemoryStateStore()
        self.provider_calls: list[tuple[str, dict]] = []
        self.refresh_response = {"access_token": "google-access-2", "expires_in": 3600}

        def provider(request: httpx.Request) -> httpx.Response:
            if request.url.host == "oauth2.googleapis.com":
                form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
                self.provider_calls.append(("token", form))
                if form["grant_type"] == "refresh_token":
                    status_code = 400 if "error" in self.refresh_response else 200
                    return httpx.Response(status_code, json=self.refresh_response)
                return httpx.Response(200, json={
                    "access_token": "google-access",
                    "refresh_token": "google-refresh",
                    "expires_in": 3600,
                    "scope": "openid email",
                    "id_token": id_token({"email": "ana@gmail.com"}),
                })
            self.provider_calls.append(("freebusy", json.loads(request.content)))
            return httpx.Response(200, json={"calendars": {"primary": {"busy": [{
                "start": self.monday.replace(hour=9).isoformat(),
                "end": self.monday.replace(hour=10).isoformat(),
            }]}}})

        self.http = httpx.AsyncClient(transport=httpx.MockTransport(provider))
        self.addAsyncCleanup(self.http.aclose)
        app.dependency_overrides[get_oauth_state_store] = lambda: self.state_store
        app.dependency_overrides[get_calendar_http] = lambda: self.http

        async with self.session_factory() as session:
            user = User(email=f"{uuid.uuid4().hex}@example.com", display_name="Calendars")
            session.add(user)
            await session.commit()
            self.user_id = user.id
        self.user_url = f"/api/v1/users/{self.user_id}"
        await self.client.post(
            f"{self.user_url}/availability-rules",
            json={"weekdays": [1, 2, 3, 4, 5], "start_time": "09:00", "end_time": "12:00"},
        )

    async def connect_google(self) -> httpx.Response:
        start = await self.client.post(f"{self.user_url}/calendar-accounts/google/authorize")
        self.assertEqual(start.status_code, 200, start.text)
        state = parse_qs(urlparse(start.json()["authorization_url"]).query)["state"][0]
        return await self.client.get(
            "/api/v1/oauth/google/callback",
            params={"state": state, "code": "auth-code"},
            follow_redirects=False,
        )

    async def accounts(self) -> list[CalendarAccount]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(CalendarAccount).where(CalendarAccount.user_id == self.user_id)
            )
            return list(result.scalars().all())

    async def expire_access_token(self, session: AsyncSession) -> None:
        result = await session.execute(
            select(CalendarAccount).where(CalendarAccount.user_id == self.user_id)
        )
        result.scalar_one().token_expires_at = datetime(2020, 1, 1, tzinfo=UTC)
        await session.commit()

    async def capture_on_monday(self) -> httpx.Response:
        app.dependency_overrides[get_capture_parser] = lambda: FakeCaptureParser(ParsedCapture(
            title="Dentista",
            event_type="tarea",
            priority="media",
            start_local=None,
            duration_minutes=60,
            window_start_local=f"{self.monday:%Y-%m-%d}T00:00",
            window_end_local=f"{self.monday:%Y-%m-%d}T23:59",
            location_query=None,
        ))
        return await self.client.post(f"{self.user_url}/captures", json={"text": "dentista el lunes"})

    async def test_connecting_stores_encrypted_tokens_once_per_account(self) -> None:
        callback = await self.connect_google()

        self.assertEqual(callback.status_code, 302, callback.text)
        location = urlparse(callback.headers["location"])
        self.assertEqual(parse_qs(location.query)["status"], ["ok"])
        self.assertEqual(parse_qs(location.query)["email"], ["ana@gmail.com"])
        self.assertEqual(self.provider_calls[0][1]["code"], "auth-code")
        self.assertIn("code_verifier", self.provider_calls[0][1])

        [account] = await self.accounts()
        self.assertEqual(account.external_email, "ana@gmail.com")
        self.assertNotIn(b"google-access", account.access_token_encrypted)
        self.assertNotIn(b"google-refresh", account.refresh_token_encrypted)

        listed = await self.client.get(f"{self.user_url}/calendar-accounts")
        self.assertEqual(listed.json()[0]["external_email"], "ana@gmail.com")
        self.assertEqual(listed.json()[0]["status"], "activa")

        await self.connect_google()
        self.assertEqual(len(await self.accounts()), 1)

        # A state can be used only once.
        replay = await self.client.get(
            "/api/v1/oauth/google/callback",
            params={"state": "used-or-invented", "code": "x"},
            follow_redirects=False,
        )
        self.assertEqual(parse_qs(urlparse(replay.headers["location"]).query)["status"], ["error"])

    async def test_captures_avoid_busy_times_of_connected_calendars(self) -> None:
        await self.connect_google()

        response = await self.capture_on_monday()

        self.assertEqual(response.status_code, 201, response.text)
        start = datetime.fromisoformat(response.json()["event"]["start"])
        self.assertEqual(start, self.monday.replace(hour=10))
        self.assertEqual(self.provider_calls[-1][0], "freebusy")

    async def test_expired_access_token_is_refreshed(self) -> None:
        await self.connect_google()
        async with self.session_factory() as session:
            await self.expire_access_token(session)

        response = await self.capture_on_monday()

        self.assertEqual(response.status_code, 201, response.text)
        self.assertIn(("token", "refresh_token"), [(kind, body.get("grant_type")) for kind, body in self.provider_calls])
        [account] = await self.accounts()
        self.assertGreater(account.token_expires_at, datetime.now(UTC))

    async def test_revoked_access_marks_account_and_does_not_block_captures(self) -> None:
        await self.connect_google()
        async with self.session_factory() as session:
            await self.expire_access_token(session)
        self.refresh_response = {"error": "invalid_grant"}

        response = await self.capture_on_monday()

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(
            datetime.fromisoformat(response.json()["event"]["start"]),
            self.monday.replace(hour=9),
        )
        [account] = await self.accounts()
        self.assertEqual(account.status, CalendarAccountStatus.TOKEN_EXPIRED)

    async def test_disconnect_forgets_the_account(self) -> None:
        await self.connect_google()
        [account] = await self.accounts()

        deleted = await self.client.delete(f"{self.user_url}/calendar-accounts/{account.id}")

        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(await self.accounts(), [])
        missing = await self.client.delete(f"{self.user_url}/calendar-accounts/{account.id}")
        self.assertEqual(missing.status_code, 404)
