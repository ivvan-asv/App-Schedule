from datetime import UTC, datetime, timedelta
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import anthropic
from fastapi.testclient import TestClient
import httpx2
from pydantic import ValidationError

from app.core.config import settings
from app.main import app
from app.schemas.capture import CaptureCreate
from app.services.capture_parser import (
    CaptureNotUnderstood,
    CaptureParserUnavailable,
    ClaudeCaptureParser,
    ParsedCapture,
    build_user_message,
    resolve_capture,
)

SANTIAGO = ZoneInfo("America/Santiago")


def parsed_capture(**overrides) -> ParsedCapture:
    values = {
        "title": "Reunión de revisión",
        "event_type": "reunion",
        "priority": "media",
        "start_local": None,
        "duration_minutes": 30,
        "window_start_local": None,
        "window_end_local": None,
    }
    return ParsedCapture(**{**values, **overrides})


class ResolveCaptureTests(unittest.TestCase):
    def test_attaches_user_timezone_to_explicit_start(self) -> None:
        resolved = resolve_capture(
            parsed_capture(start_local="2026-11-03T15:00", duration_minutes=45),
            SANTIAGO,
        )

        self.assertEqual(resolved.start, datetime(2026, 11, 3, 15, 0, tzinfo=SANTIAGO))
        self.assertEqual(resolved.duration, timedelta(minutes=45))
        self.assertIsNone(resolved.window_start)

    def test_explicit_start_ignores_window(self) -> None:
        resolved = resolve_capture(
            parsed_capture(
                start_local="2026-11-03T15:00",
                window_start_local="2026-11-03T08:00",
                window_end_local="2026-11-03T18:00",
            ),
            SANTIAGO,
        )

        self.assertIsNone(resolved.window_start)
        self.assertIsNone(resolved.window_end)

    def test_keeps_window_when_no_start_is_given(self) -> None:
        resolved = resolve_capture(
            parsed_capture(
                window_start_local="2026-11-03T14:00",
                window_end_local="2026-11-03T19:00",
            ),
            SANTIAGO,
        )

        self.assertIsNone(resolved.start)
        self.assertEqual(resolved.window_start, datetime(2026, 11, 3, 14, tzinfo=SANTIAGO))
        self.assertEqual(resolved.window_end, datetime(2026, 11, 3, 19, tzinfo=SANTIAGO))

    def test_rejects_invalid_model_output(self) -> None:
        invalid_outputs = {
            "blank title": parsed_capture(title="  "),
            "zero duration": parsed_capture(duration_minutes=0),
            "excessive duration": parsed_capture(duration_minutes=2000),
            "unparseable start": parsed_capture(start_local="mañana"),
            "inverted window": parsed_capture(
                window_start_local="2026-11-03T19:00",
                window_end_local="2026-11-03T14:00",
            ),
        }
        for case, output in invalid_outputs.items():
            with self.subTest(case=case), self.assertRaises(CaptureNotUnderstood):
                resolve_capture(output, SANTIAGO)


class CaptureCreateTests(unittest.TestCase):
    def test_strips_text_and_defaults_capture_time(self) -> None:
        capture = CaptureCreate(text="  comprar pan  ")

        self.assertEqual(capture.text, "comprar pan")
        self.assertIsNotNone(capture.captured_at.utcoffset())

    def test_rejects_naive_capture_time_and_blank_text(self) -> None:
        with self.assertRaises(ValidationError):
            CaptureCreate(text="comprar pan", captured_at=datetime(2026, 11, 3, 9, 0))
        with self.assertRaises(ValidationError):
            CaptureCreate(text="   ")


class FakeMessages:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def fake_client(result: object) -> SimpleNamespace:
    return SimpleNamespace(messages=FakeMessages(result))


class ClaudeCaptureParserTests(unittest.IsolatedAsyncioTestCase):
    reference = datetime(2026, 11, 2, 9, 15, tzinfo=SANTIAGO)

    async def test_requests_structured_output_and_returns_it(self) -> None:
        expected = parsed_capture()
        client = fake_client(SimpleNamespace(stop_reason="end_turn", parsed_output=expected))
        parser = ClaudeCaptureParser(client, "claude-haiku-5-5")

        result = await parser.parse("reunión con Laura esta semana", self.reference)

        self.assertEqual(result, expected)
        call = client.messages.calls[0]
        self.assertEqual(call["model"], "claude-haiku-5-5")
        self.assertIs(call["output_format"], ParsedCapture)
        self.assertEqual(call["output_config"], {"effort": "low"})
        self.assertIn("reunión con Laura esta semana", call["messages"][0]["content"])

    async def test_refusal_and_truncation_are_not_understood(self) -> None:
        for stop_reason in ("refusal", "max_tokens"):
            client = fake_client(SimpleNamespace(stop_reason=stop_reason, parsed_output=None))
            parser = ClaudeCaptureParser(client, "claude-haiku-5-5")
            with self.subTest(stop_reason=stop_reason):
                with self.assertRaises(CaptureNotUnderstood):
                    await parser.parse("texto", self.reference)

    async def test_connection_errors_mean_unavailable(self) -> None:
        error = anthropic.APIConnectionError(
            request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"),
        )
        parser = ClaudeCaptureParser(fake_client(error), "claude-haiku-5-5")

        with self.assertLogs("app.services.capture_parser", "ERROR"):
            with self.assertRaises(CaptureParserUnavailable):
                await parser.parse("texto", self.reference)

    def test_user_message_includes_spanish_weekday_and_delimited_note(self) -> None:
        message = build_user_message("llamar al banco", self.reference)

        self.assertIn("lunes 2026-11-02 09:15 (America/Santiago)", message)
        self.assertIn("<captura>\nllamar al banco\n</captura>", message)


class CaptureEndpointConfigurationTests(unittest.TestCase):
    def test_missing_api_key_is_reported_as_unavailable(self) -> None:
        with patch.object(settings, "ANTHROPIC_API_KEY", None), TestClient(app) as client:
            response = client.post(
                "/api/v1/users/00000000-0000-0000-0000-000000000000/captures",
                json={"text": "comprar pan"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("ANTHROPIC_API_KEY", response.json()["detail"])


@unittest.skipUnless(
    os.environ.get("RUN_LLM_TESTS") == "1" and settings.ANTHROPIC_API_KEY,
    "set RUN_LLM_TESTS=1 and ANTHROPIC_API_KEY to call the real model",
)
class LiveCaptureParserTests(unittest.IsolatedAsyncioTestCase):
    """Calls the real API; each run costs a fraction of a cent."""

    reference = datetime(2026, 11, 2, 9, 15, tzinfo=SANTIAGO)  # a Monday

    async def asyncSetUp(self) -> None:
        self.parser = ClaudeCaptureParser(
            anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY),
            settings.CAPTURE_LLM_MODEL,
        )
        self.addAsyncCleanup(self.parser.aclose)

    async def parse(self, text: str):
        started = datetime.now(UTC)
        parsed = await self.parser.parse(text, self.reference)
        elapsed = datetime.now(UTC) - started
        print(f"\n{text!r} -> {parsed.model_dump()} in {elapsed.total_seconds():.2f}s")
        return resolve_capture(parsed, SANTIAGO)

    async def test_explicit_relative_time(self) -> None:
        resolved = await self.parse("mañana a las tres de la tarde dentista una hora")

        self.assertEqual(resolved.start, datetime(2026, 11, 3, 15, 0, tzinfo=SANTIAGO))
        self.assertEqual(resolved.duration, timedelta(hours=1))

    async def test_meeting_with_window_and_no_time(self) -> None:
        resolved = await self.parse(
            "necesito agendar una reunión de revisión con Laura Martínez esta semana"
        )

        self.assertIsNone(resolved.start)
        self.assertEqual(resolved.event_type, "reunion")
        self.assertIsNotNone(resolved.window_end)
        self.assertLessEqual(resolved.window_end, datetime(2026, 11, 9, tzinfo=SANTIAGO))
