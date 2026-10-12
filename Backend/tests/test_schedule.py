from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import unittest

from pydantic import ValidationError

from app.schemas.schedule import AgendaRuleCreate, EventCreate
from app.services.schedule import generate_available_slots


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
