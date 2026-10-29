"""Connected Google / Outlook accounts (RF07).

The phone opens the provider's consent page; the provider redirects to this
backend, which exchanges the code with the client secret (never on the phone)
and stores the tokens encrypted. Busy times of connected calendars are then
avoided when captures are scheduled.
"""
import asyncio
import base64
from datetime import UTC, datetime, timedelta
import hashlib
import json
import logging
import secrets
from typing import Protocol
import uuid

from fastapi import HTTPException, status
import httpx
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import TokenCipher, TokenEncryptionNotConfigured
from app.models import CalendarAccount
from app.models.calendar import CalendarAccountStatus, CalendarProvider
from app.services.calendar_providers import (
    PROVIDER_CLIENTS,
    CalendarProviderClient,
    ProviderAuthError,
    ProviderUnavailable,
    redirect_uri,
)
from app.services.schedule import get_active_user

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 10 * 60
# Per provider, so a slow calendar cannot push a capture past the 3 s budget (RNF01).
BUSY_TIMEOUT_SECONDS = 1.5
TOKEN_REFRESH_MARGIN = timedelta(minutes=2)
EXTERNAL_BUSY_HORIZON = timedelta(days=14)

PROVIDER_NAMES = {CalendarProvider.GOOGLE: "Google Calendar", CalendarProvider.MICROSOFT: "Outlook"}


class OAuthStateStore(Protocol):
    """Short-lived, single-use storage for the OAuth `state` and PKCE verifier."""

    async def save(self, state: str, data: dict, ttl_seconds: int) -> None: ...

    async def take(self, state: str) -> dict | None: ...


class RedisOAuthStateStore:
    def __init__(self, redis: aioredis.Redis) -> None:
        self.redis = redis

    async def save(self, state: str, data: dict, ttl_seconds: int) -> None:
        await self.redis.set(f"oauth:state:{state}", json.dumps(data), ex=ttl_seconds)

    async def take(self, state: str) -> dict | None:
        raw = await self.redis.getdel(f"oauth:state:{state}")
        return json.loads(raw) if raw else None


class AuthorizationFailed(Exception):
    """The callback cannot be completed; the message is shown in the app."""


def provider_client(provider: CalendarProvider) -> CalendarProviderClient:
    client = PROVIDER_CLIENTS.get(provider)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown calendar provider")
    return client


def missing_settings(provider: CalendarProvider) -> list[str]:
    missing = provider_client(provider).missing_settings()
    if not settings.TOKEN_ENCRYPTION_KEY:
        missing.append("TOKEN_ENCRYPTION_KEY")
    return missing


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


async def start_authorization(
    session: AsyncSession,
    user_id: uuid.UUID,
    provider: CalendarProvider,
    state_store: OAuthStateStore,
) -> str:
    """The provider consent URL for the app to open."""
    missing = missing_settings(provider)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"{PROVIDER_NAMES[provider]} is not configured: set {', '.join(missing)} "
                "in .env (see docs/calendar-credentials.md)"
            ),
        )
    await get_active_user(session, user_id)

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)
    await state_store.save(
        state,
        {"user_id": str(user_id), "provider": provider.value, "verifier": verifier},
        STATE_TTL_SECONDS,
    )
    return provider_client(provider).authorization_url(state, challenge, redirect_uri(provider))


async def complete_authorization(
    session: AsyncSession,
    provider: CalendarProvider,
    code: str,
    state: str,
    state_store: OAuthStateStore,
    http: httpx.AsyncClient,
) -> CalendarAccount:
    data = await state_store.take(state)
    if data is None or data.get("provider") != provider.value:
        raise AuthorizationFailed("La conexión caducó. Vuelve a intentarlo desde la app.")
    try:
        cipher = TokenCipher.from_settings()
        tokens = await provider_client(provider).exchange_code(
            http, code, data["verifier"], redirect_uri(provider)
        )
    except TokenEncryptionNotConfigured as error:
        raise AuthorizationFailed(str(error)) from error
    except (ProviderAuthError, ProviderUnavailable) as error:
        logger.warning("OAuth code exchange with %s failed: %s", provider.value, error)
        raise AuthorizationFailed(f"{PROVIDER_NAMES[provider]} rechazó la conexión.") from error

    user_id = uuid.UUID(data["user_id"])
    await get_active_user(session, user_id)
    result = await session.execute(
        select(CalendarAccount).where(
            CalendarAccount.user_id == user_id,
            CalendarAccount.provider == provider,
            CalendarAccount.external_email.is_not_distinct_from(tokens.email),
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        account = CalendarAccount(user_id=user_id, provider=provider, external_email=tokens.email)
        session.add(account)
    _store_tokens(account, tokens, cipher)
    account.status = CalendarAccountStatus.ACTIVE
    await session.commit()
    await session.refresh(account)
    return account


def _store_tokens(account: CalendarAccount, tokens, cipher: TokenCipher) -> None:
    account.access_token_encrypted = cipher.encrypt(tokens.access_token)
    if tokens.refresh_token:
        account.refresh_token_encrypted = cipher.encrypt(tokens.refresh_token)
    account.token_expires_at = tokens.expires_at
    account.scopes = tokens.scopes or account.scopes


async def list_accounts(session: AsyncSession, user_id: uuid.UUID) -> list[CalendarAccount]:
    await get_active_user(session, user_id)
    result = await session.execute(
        select(CalendarAccount)
        .where(
            CalendarAccount.user_id == user_id,
            CalendarAccount.provider != CalendarProvider.APPLE_LOCAL,
        )
        .order_by(CalendarAccount.created_at)
    )
    return list(result.scalars().all())


async def disconnect_account(session: AsyncSession, user_id: uuid.UUID, account_id: uuid.UUID) -> None:
    """Forgets the account and its tokens. Access can also be revoked from the
    provider's security settings."""
    result = await session.execute(
        select(CalendarAccount).where(
            CalendarAccount.id == account_id,
            CalendarAccount.user_id == user_id,
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar account not found")
    await session.delete(account)
    await session.commit()


async def _access_token(
    client: CalendarProviderClient,
    http: httpx.AsyncClient,
    account: CalendarAccount,
    cipher: TokenCipher,
) -> str:
    """A valid access token, refreshed when it is about to expire.

    Only changes the account's attributes; the caller commits.
    """
    expires_at = account.token_expires_at
    if account.access_token_encrypted and expires_at and expires_at > datetime.now(UTC) + TOKEN_REFRESH_MARGIN:
        return cipher.decrypt(account.access_token_encrypted)
    if not account.refresh_token_encrypted:
        raise ProviderAuthError("no refresh token")
    tokens = await client.refresh(http, cipher.decrypt(account.refresh_token_encrypted))
    _store_tokens(account, tokens, cipher)
    return tokens.access_token


async def connected_calendar_busy(
    session: AsyncSession,
    user_id: uuid.UUID,
    start: datetime,
    end: datetime,
    http: httpx.AsyncClient,
) -> list[tuple[datetime, datetime]]:
    """Busy times from every active connected account, fetched in parallel.

    A calendar that fails or is slow is skipped, so it never blocks a capture;
    one whose grant was revoked is marked as expired for the app to show.
    """
    result = await session.execute(
        select(CalendarAccount).where(
            CalendarAccount.user_id == user_id,
            CalendarAccount.status == CalendarAccountStatus.ACTIVE,
            CalendarAccount.provider.in_(list(PROVIDER_CLIENTS)),
        )
    )
    accounts = list(result.scalars().all())
    if not accounts:
        return []
    try:
        cipher = TokenCipher.from_settings()
    except TokenEncryptionNotConfigured:
        logger.warning("Connected calendars skipped: TOKEN_ENCRYPTION_KEY is not set")
        return []

    async def busy_for(account: CalendarAccount) -> list[tuple[datetime, datetime]]:
        client = PROVIDER_CLIENTS[account.provider]
        try:
            async with asyncio.timeout(BUSY_TIMEOUT_SECONDS):
                token = await _access_token(client, http, account, cipher)
                return await client.busy_intervals(http, token, start, end)
        except ProviderAuthError:
            account.status = CalendarAccountStatus.TOKEN_EXPIRED
        except (ProviderUnavailable, TimeoutError, ValueError) as error:
            logger.warning("Busy times from %s skipped: %s", account.provider.value, error)
        return []

    results = await asyncio.gather(*(busy_for(account) for account in accounts))
    if session.dirty:
        # Refreshed tokens or expired accounts.
        await session.commit()
    return [interval for intervals in results for interval in intervals]


_http: httpx.AsyncClient | None = None


def get_calendar_http() -> httpx.AsyncClient:
    """FastAPI dependency: the shared HTTP client for calendar providers."""
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0))
    return _http


async def close_calendar_http() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None
