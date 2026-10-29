"""OAuth and busy-time clients for Google Calendar and Microsoft Graph (Outlook).

Credentials come from settings; see docs/calendar-credentials.md for how to
create them. Only start and end times of events are read.
"""
import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from typing import Protocol
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.models.calendar import CalendarProvider

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_FREEBUSY_URL = "https://www.googleapis.com/calendar/v3/freeBusy"
GOOGLE_SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events",
]

MICROSOFT_LOGIN_URL = "https://login.microsoftonline.com"
MICROSOFT_CALENDAR_VIEW_URL = "https://graph.microsoft.com/v1.0/me/calendarView"
MICROSOFT_SCOPES = ["openid", "email", "offline_access", "User.Read", "Calendars.ReadWrite"]
# calendarView pages hold up to 100 events; 5 pages cover a busy fortnight.
MICROSOFT_MAX_PAGES = 5
# OAuth error codes that mean the grant or client is no longer valid.
AUTH_ERROR_CODES = {"invalid_grant", "invalid_client", "unauthorized_client"}


class ProviderAuthError(Exception):
    """The provider rejected the grant or token; the user must connect again."""


class ProviderUnavailable(Exception):
    """The provider could not be reached or answered unexpectedly."""


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    scopes: list[str]
    email: str | None


class CalendarProviderClient(Protocol):
    provider: CalendarProvider

    def missing_settings(self) -> list[str]: ...

    def authorization_url(self, state: str, code_challenge: str, redirect_uri: str) -> str: ...

    async def exchange_code(
        self, http: httpx.AsyncClient, code: str, code_verifier: str, redirect_uri: str
    ) -> TokenSet: ...

    async def refresh(self, http: httpx.AsyncClient, refresh_token: str) -> TokenSet: ...

    async def busy_intervals(
        self, http: httpx.AsyncClient, access_token: str, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]: ...


def _email_from_id_token(id_token: str | None) -> str | None:
    """Reads the email claim. The token comes straight from the provider's
    token endpoint over TLS, so its signature does not need checking here."""
    if not id_token:
        return None
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return None
    return claims.get("email") or claims.get("preferred_username")


def _token_set(body: dict, previous_refresh_token: str | None = None) -> TokenSet:
    try:
        access_token = body["access_token"]
    except KeyError as error:
        raise ProviderUnavailable("Token response has no access_token") from error
    return TokenSet(
        access_token=access_token,
        # Google omits refresh_token on refresh; Microsoft rotates it.
        refresh_token=body.get("refresh_token") or previous_refresh_token,
        expires_at=datetime.now(UTC) + timedelta(seconds=int(body.get("expires_in", 3600))),
        scopes=body.get("scope", "").split(),
        email=_email_from_id_token(body.get("id_token")),
    )


async def _post_token(http: httpx.AsyncClient, url: str, data: dict) -> dict:
    try:
        response = await http.post(url, data=data, headers={"Accept": "application/json"})
    except httpx.HTTPError as error:
        raise ProviderUnavailable(str(error)) from error
    if response.status_code in (400, 401):
        try:
            error_code = response.json().get("error")
        except ValueError:
            error_code = None
        if response.status_code == 401 or error_code in AUTH_ERROR_CODES:
            raise ProviderAuthError(error_code or "unauthorized")
    if response.is_error:
        raise ProviderUnavailable(f"Token endpoint answered {response.status_code}")
    return response.json()


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # Graph returns naive times in the zone asked for with Prefer (UTC here).
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class GoogleCalendarClient:
    provider = CalendarProvider.GOOGLE

    def missing_settings(self) -> list[str]:
        return [
            name
            for name, value in (
                ("GOOGLE_CLIENT_ID", settings.GOOGLE_CLIENT_ID),
                ("GOOGLE_CLIENT_SECRET", settings.GOOGLE_CLIENT_SECRET),
            )
            if not value
        ]

    def authorization_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            # Offline access and consent so Google always returns a refresh token.
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(
        self, http: httpx.AsyncClient, code: str, code_verifier: str, redirect_uri: str
    ) -> TokenSet:
        body = await _post_token(
            http,
            GOOGLE_TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
            },
        )
        return _token_set(body)

    async def refresh(self, http: httpx.AsyncClient, refresh_token: str) -> TokenSet:
        body = await _post_token(
            http,
            GOOGLE_TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
            },
        )
        return _token_set(body, refresh_token)

    async def busy_intervals(
        self, http: httpx.AsyncClient, access_token: str, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]:
        try:
            response = await http.post(
                GOOGLE_FREEBUSY_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"timeMin": _iso_utc(start), "timeMax": _iso_utc(end), "items": [{"id": "primary"}]},
            )
        except httpx.HTTPError as error:
            raise ProviderUnavailable(str(error)) from error
        if response.status_code == 401:
            raise ProviderAuthError("access token rejected")
        if response.is_error:
            raise ProviderUnavailable(f"freeBusy answered {response.status_code}")
        busy = response.json().get("calendars", {}).get("primary", {}).get("busy", [])
        return [(_parse_utc(item["start"]), _parse_utc(item["end"])) for item in busy]


class MicrosoftCalendarClient:
    provider = CalendarProvider.MICROSOFT

    def missing_settings(self) -> list[str]:
        return [
            name
            for name, value in (
                ("MICROSOFT_CLIENT_ID", settings.MICROSOFT_CLIENT_ID),
                ("MICROSOFT_CLIENT_SECRET", settings.MICROSOFT_CLIENT_SECRET),
            )
            if not value
        ]

    @property
    def _oauth_base(self) -> str:
        return f"{MICROSOFT_LOGIN_URL}/{settings.MICROSOFT_TENANT}/oauth2/v2.0"

    def authorization_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
        params = {
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "response_mode": "query",
            "scope": " ".join(MICROSOFT_SCOPES),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self._oauth_base}/authorize?{urlencode(params)}"

    async def exchange_code(
        self, http: httpx.AsyncClient, code: str, code_verifier: str, redirect_uri: str
    ) -> TokenSet:
        body = await _post_token(
            http,
            f"{self._oauth_base}/token",
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
                "client_id": settings.MICROSOFT_CLIENT_ID,
                "client_secret": settings.MICROSOFT_CLIENT_SECRET,
                "scope": " ".join(MICROSOFT_SCOPES),
            },
        )
        return _token_set(body)

    async def refresh(self, http: httpx.AsyncClient, refresh_token: str) -> TokenSet:
        body = await _post_token(
            http,
            f"{self._oauth_base}/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.MICROSOFT_CLIENT_ID,
                "client_secret": settings.MICROSOFT_CLIENT_SECRET,
                "scope": " ".join(MICROSOFT_SCOPES),
            },
        )
        return _token_set(body, refresh_token)

    async def busy_intervals(
        self, http: httpx.AsyncClient, access_token: str, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]:
        url: str | None = MICROSOFT_CALENDAR_VIEW_URL
        params: dict | None = {
            "startDateTime": _iso_utc(start),
            "endDateTime": _iso_utc(end),
            "$select": "start,end,showAs,isAllDay,isCancelled",
            "$top": "100",
        }
        headers = {"Authorization": f"Bearer {access_token}", "Prefer": 'outlook.timezone="UTC"'}
        busy: list[tuple[datetime, datetime]] = []
        for _ in range(MICROSOFT_MAX_PAGES):
            if url is None:
                break
            try:
                response = await http.get(url, params=params, headers=headers)
            except httpx.HTTPError as error:
                raise ProviderUnavailable(str(error)) from error
            if response.status_code == 401:
                raise ProviderAuthError("access token rejected")
            if response.is_error:
                raise ProviderUnavailable(f"calendarView answered {response.status_code}")
            body = response.json()
            for item in body.get("value", []):
                # Same rules as the device calendar: free, all-day and cancelled entries do not block.
                if item.get("isAllDay") or item.get("isCancelled") or item.get("showAs") == "free":
                    continue
                busy.append(
                    (_parse_utc(item["start"]["dateTime"]), _parse_utc(item["end"]["dateTime"]))
                )
            # nextLink already carries the query.
            url, params = body.get("@odata.nextLink"), None
        return busy


PROVIDER_CLIENTS: dict[CalendarProvider, CalendarProviderClient] = {
    CalendarProvider.GOOGLE: GoogleCalendarClient(),
    CalendarProvider.MICROSOFT: MicrosoftCalendarClient(),
}


def redirect_uri(provider: CalendarProvider) -> str:
    """The URI to register with the provider for this backend."""
    return (
        f"{settings.OAUTH_REDIRECT_BASE_URL.rstrip('/')}"
        f"{settings.API_V1_PREFIX}/oauth/{provider.value}/callback"
    )
