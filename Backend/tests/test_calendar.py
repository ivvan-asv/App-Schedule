import base64
from datetime import UTC, datetime
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
import httpx

from app.api.v1.calendar import get_oauth_state_store
from app.core.config import settings
from app.core.crypto import TokenCipher, TokenEncryptionNotConfigured
from app.main import app
from app.services.calendar_providers import (
    GoogleCalendarClient,
    MicrosoftCalendarClient,
    ProviderAuthError,
)

TEST_KEY = base64.b64encode(bytes(range(32))).decode()
CONFIGURED = {
    "TOKEN_ENCRYPTION_KEY": TEST_KEY,
    "GOOGLE_CLIENT_ID": "google-client",
    "GOOGLE_CLIENT_SECRET": "google-secret",
    "MICROSOFT_CLIENT_ID": "ms-client",
    "MICROSOFT_CLIENT_SECRET": "ms-secret",
    "OAUTH_REDIRECT_BASE_URL": "https://api.example.com",
}


def configured(**overrides):
    values = {**CONFIGURED, **overrides}
    return patch.multiple(settings, **values)


def id_token(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"header.{payload}.signature"


class InMemoryStateStore:
    def __init__(self) -> None:
        self.values: dict[str, dict] = {}

    async def save(self, state: str, data: dict, ttl_seconds: int) -> None:
        self.values[state] = data

    async def take(self, state: str) -> dict | None:
        return self.values.pop(state, None)


def mock_http(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TokenCipherTests(unittest.TestCase):
    def test_round_trips_and_never_stores_plain_text(self) -> None:
        cipher = TokenCipher(bytes(range(32)))

        encrypted = cipher.encrypt("ya29.secret-token")

        self.assertNotIn(b"secret-token", encrypted)
        self.assertNotEqual(encrypted, cipher.encrypt("ya29.secret-token"))
        self.assertEqual(cipher.decrypt(encrypted), "ya29.secret-token")

    def test_other_key_cannot_decrypt(self) -> None:
        encrypted = TokenCipher(bytes(range(32))).encrypt("token")

        with self.assertRaises(ValueError):
            TokenCipher(bytes(32)).decrypt(encrypted)

    def test_requires_a_32_byte_key_from_settings(self) -> None:
        for value in (None, "not base64!", base64.b64encode(b"short").decode()):
            with self.subTest(value=value), patch.object(settings, "TOKEN_ENCRYPTION_KEY", value):
                with self.assertRaises(TokenEncryptionNotConfigured):
                    TokenCipher.from_settings()


class GoogleClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_authorization_url_uses_pkce_and_offline_access(self) -> None:
        with configured():
            url = GoogleCalendarClient().authorization_url("st", "challenge", "https://cb")

        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["client_id"], ["google-client"])
        self.assertEqual(query["code_challenge"], ["challenge"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["redirect_uri"], ["https://cb"])
        self.assertIn("https://www.googleapis.com/auth/calendar.freebusy", query["scope"][0])

    async def test_exchanges_code_and_reads_email(self) -> None:
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(parse_qs(request.content.decode()))
            return httpx.Response(200, json={
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 3599,
                "scope": "openid email",
                "id_token": id_token({"email": "ana@gmail.com"}),
            })

        with configured():
            async with mock_http(handler) as http:
                tokens = await GoogleCalendarClient().exchange_code(http, "code", "verifier", "https://cb")

        self.assertEqual(tokens.email, "ana@gmail.com")
        self.assertEqual(tokens.refresh_token, "refresh")
        self.assertEqual(requests[0]["code_verifier"], ["verifier"])
        self.assertEqual(requests[0]["client_secret"], ["google-secret"])

    async def test_refresh_keeps_refresh_token_and_detects_revocation(self) -> None:
        responses = [
            httpx.Response(200, json={"access_token": "new", "expires_in": 3600}),
            httpx.Response(400, json={"error": "invalid_grant"}),
        ]
        with configured():
            async with mock_http(lambda request: responses.pop(0)) as http:
                tokens = await GoogleCalendarClient().refresh(http, "old-refresh")
                with self.assertRaises(ProviderAuthError):
                    await GoogleCalendarClient().refresh(http, "old-refresh")

        self.assertEqual(tokens.access_token, "new")
        self.assertEqual(tokens.refresh_token, "old-refresh")

    async def test_reads_busy_times_of_primary_calendar(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["Authorization"], "Bearer access")
            body = json.loads(request.content)
            self.assertEqual(body["items"], [{"id": "primary"}])
            self.assertEqual(body["timeMin"], "2026-11-09T12:00:00Z")
            return httpx.Response(200, json={"calendars": {"primary": {"busy": [
                {"start": "2026-11-09T13:00:00Z", "end": "2026-11-09T14:00:00Z"},
            ]}}})

        async with mock_http(handler) as http:
            busy = await GoogleCalendarClient().busy_intervals(
                http,
                "access",
                datetime(2026, 11, 9, 12, tzinfo=UTC),
                datetime(2026, 11, 10, 12, tzinfo=UTC),
            )

        self.assertEqual(busy, [(datetime(2026, 11, 9, 13, tzinfo=UTC), datetime(2026, 11, 9, 14, tzinfo=UTC))])


class MicrosoftClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_authorization_url_targets_the_tenant(self) -> None:
        with configured(MICROSOFT_TENANT="consumers"):
            url = MicrosoftCalendarClient().authorization_url("st", "challenge", "https://cb")

        parsed = urlparse(url)
        self.assertEqual(parsed.path, "/consumers/oauth2/v2.0/authorize")
        self.assertIn("offline_access", parse_qs(parsed.query)["scope"][0])

    async def test_busy_times_skip_free_all_day_and_cancelled_and_follow_pages(self) -> None:
        def event(start: str, end: str, **extra) -> dict:
            return {"start": {"dateTime": start}, "end": {"dateTime": end}, "showAs": "busy", **extra}

        pages = {
            "first": {
                "value": [
                    event("2026-11-09T13:00:00.0000000", "2026-11-09T14:00:00.0000000"),
                    event("2026-11-09T15:00:00", "2026-11-09T16:00:00", showAs="free"),
                    event("2026-11-09T00:00:00", "2026-11-10T00:00:00", isAllDay=True),
                    event("2026-11-09T17:00:00", "2026-11-09T18:00:00", isCancelled=True),
                ],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/calendarView?page=2",
            },
            "second": {"value": [event("2026-11-10T09:00:00", "2026-11-10T09:30:00", showAs="tentative")]},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["Prefer"], 'outlook.timezone="UTC"')
            return httpx.Response(200, json=pages["second" if "page=2" in str(request.url) else "first"])

        async with mock_http(handler) as http:
            busy = await MicrosoftCalendarClient().busy_intervals(
                http,
                "access",
                datetime(2026, 11, 9, tzinfo=UTC),
                datetime(2026, 11, 11, tzinfo=UTC),
            )

        self.assertEqual(
            [start for start, _ in busy],
            [datetime(2026, 11, 9, 13, tzinfo=UTC), datetime(2026, 11, 10, 9, tzinfo=UTC)],
        )


class CalendarEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state_store = InMemoryStateStore()
        app.dependency_overrides[get_oauth_state_store] = lambda: self.state_store
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()

    def test_providers_report_missing_settings_and_redirect_uris(self) -> None:
        with configured(GOOGLE_CLIENT_SECRET=None, TOKEN_ENCRYPTION_KEY=None):
            response = self.client.get("/api/v1/calendar-providers")

        providers = {item["provider"]: item for item in response.json()}
        self.assertFalse(providers["google"]["configured"])
        self.assertEqual(
            providers["google"]["missing_settings"],
            ["GOOGLE_CLIENT_SECRET", "TOKEN_ENCRYPTION_KEY"],
        )
        self.assertEqual(
            providers["microsoft"]["redirect_uri"],
            "https://api.example.com/api/v1/oauth/microsoft/callback",
        )

    def test_authorize_explains_what_is_missing(self) -> None:
        with configured(MICROSOFT_CLIENT_ID=None):
            response = self.client.post(
                "/api/v1/users/00000000-0000-0000-0000-000000000000/calendar-accounts/microsoft/authorize"
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("MICROSOFT_CLIENT_ID", response.json()["detail"])
        self.assertIn("docs/calendar-credentials.md", response.json()["detail"])

    def test_cancelled_consent_returns_to_the_app_with_an_error(self) -> None:
        self.state_store.values["st"] = {"provider": "google"}

        with configured():
            response = self.client.get(
                "/api/v1/oauth/google/callback",
                params={"state": "st", "error": "access_denied"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        location = urlparse(response.headers["location"])
        self.assertEqual(f"{location.scheme}://{location.netloc}", "smartscheduler://calendar-connected")
        self.assertEqual(parse_qs(location.query)["status"], ["error"])
        self.assertEqual(self.state_store.values, {})

    def test_legacy_env_names_are_accepted(self) -> None:
        from app.core.config import Settings

        with patch.dict(
            "os.environ",
            {"GOOGLE_CALENDAR_CLIENT_ID": "legacy-google", "MICROSOFT_GRAPH_CLIENT_SECRET": "legacy-ms"},
            clear=True,
        ):
            legacy = Settings(_env_file=None)

        self.assertEqual(legacy.GOOGLE_CLIENT_ID, "legacy-google")
        self.assertEqual(legacy.MICROSOFT_CLIENT_SECRET, "legacy-ms")
