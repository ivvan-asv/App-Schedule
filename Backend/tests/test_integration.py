"""Integration tests that run against a real PostgreSQL server.

Set TEST_DATABASE_URL to a server where the role may create databases. Each
run creates a throwaway database, applies the Alembic migrations to it and
drops it afterwards, so existing data is never touched.
"""
import asyncio
from datetime import datetime
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid
from zoneinfo import ZoneInfo

from alembic import command
from alembic.config import Config
import httpx
from sqlalchemy import inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


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
class PostgresIntegrationTests(unittest.IsolatedAsyncioTestCase):
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
        session_factory = async_sessionmaker(
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
