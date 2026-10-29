from datetime import datetime, timedelta
from types import SimpleNamespace
import uuid
from zoneinfo import ZoneInfo
import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.schedule import AgendaRuleCreate, EventCreate
from app.services.location import travel_block_duration
from app.services.schedule import ensure_no_overlap, generate_available_slots


class ScheduleSlotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.timezone = ZoneInfo("America/Santiago")

    def test_generates_candidate_slots_and_excludes_conflicts(self) -> None:
        window_start = datetime(2026, 10, 12, 9, 0, tzinfo=self.timezone)
        window_end = datetime(2026, 10, 12, 12, 0, tzinfo=self.timezone)
        busy_start = datetime(2026, 10, 12, 10, 0, tzinfo=self.timezone)
        busy_end = datetime(2026, 10, 12, 10, 30, tzinfo=self.timezone)

        slots = generate_available_slots(
            [(window_start, window_end)],
            [(busy_start, busy_end)],
            duration_minutes=60,
            step_minutes=30,
        )

        self.assertEqual(
            [start for start, _ in slots],
            [
                datetime(2026, 10, 12, 9, 0, tzinfo=self.timezone),
                datetime(2026, 10, 12, 10, 30, tzinfo=self.timezone),
                datetime(2026, 10, 12, 11, 0, tzinfo=self.timezone),
            ],
        )

    def test_merges_duplicate_slots_from_overlapping_windows(self) -> None:
        start = datetime(2026, 10, 12, 9, 0, tzinfo=self.timezone)
        middle = start + timedelta(minutes=30)
        end = start + timedelta(hours=1)

        slots = generate_available_slots(
            [(start, end), (middle, end)],
            [],
            duration_minutes=30,
            step_minutes=30,
        )

        self.assertEqual(len(slots), 2)

    def test_slot_duration_uses_elapsed_time_across_daylight_saving(self) -> None:
        timezone = ZoneInfo("America/New_York")
        window_start = datetime(2026, 3, 8, 1, 0, tzinfo=timezone)
        window_end = datetime(2026, 3, 8, 4, 0, tzinfo=timezone)

        slots = generate_available_slots(
            [(window_start, window_end)],
            [],
            duration_minutes=60,
            step_minutes=60,
        )

        self.assertEqual(
            [(start.hour, start.utcoffset()) for start, _ in slots],
            [
                (1, timedelta(hours=-5)),
                (3, timedelta(hours=-4)),
            ],
        )

    def test_rejects_naive_event_datetimes(self) -> None:
        with self.assertRaises(ValidationError):
            EventCreate(
                title="Review",
                start=datetime(2026, 10, 12, 9, 0),
                end=datetime(2026, 10, 12, 10, 0),
            )

    def test_rejects_invalid_working_hours_rule(self) -> None:
        with self.assertRaises(ValidationError):
            AgendaRuleCreate(
                weekdays=[1, 8],
                start_time="09:00",
                end_time="17:00",
            )


class FreeAgendaSession:
    """Session whose agenda has no overlapping events."""

    async def execute(self, statement: object) -> SimpleNamespace:
        _ = statement
        return SimpleNamespace(scalar_one_or_none=lambda: None)


class DeviceBusyOverlapTests(unittest.IsolatedAsyncioTestCase):
    timezone = ZoneInfo("America/Santiago")

    def at(self, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 11, 3, hour, minute, tzinfo=self.timezone)

    async def test_device_busy_time_is_a_conflict(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            await ensure_no_overlap(
                FreeAgendaSession(),
                uuid.uuid4(),
                self.at(10, 30),
                self.at(11, 30),
                [(self.at(11), self.at(12))],
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("device calendar", raised.exception.detail)

    async def test_adjacent_device_busy_time_is_not_a_conflict(self) -> None:
        await ensure_no_overlap(
            FreeAgendaSession(),
            uuid.uuid4(),
            self.at(10),
            self.at(11),
            [(self.at(9), self.at(10)), (self.at(11), self.at(12))],
        )


class TravelBlockDurationTests(unittest.TestCase):
    def test_rounds_trips_up_to_five_minutes(self) -> None:
        cases = {60: 5, 5 * 60: 5, 5 * 60 + 1: 10, 22 * 60: 25, 3600: 60}
        for seconds, minutes in cases.items():
            with self.subTest(seconds=seconds):
                self.assertEqual(travel_block_duration(seconds), timedelta(minutes=minutes))

    def test_very_short_trips_have_no_block(self) -> None:
        self.assertIsNone(travel_block_duration(0))
        self.assertIsNone(travel_block_duration(59))
