from typing import Literal
from urllib.parse import urlencode
import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import RedirectResponse
import httpx
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.models import CalendarAccount
from app.models.calendar import CalendarProvider
from app.schemas.calendar import AuthorizationStart, CalendarAccountRead, CalendarProviderStatus
from app.services.calendar_accounts import (
    PROVIDER_NAMES,
    AuthorizationFailed,
    OAuthStateStore,
    RedisOAuthStateStore,
    complete_authorization,
    disconnect_account,
    get_calendar_http,
    list_accounts,
    missing_settings,
    start_authorization,
)
from app.services.calendar_providers import redirect_uri

router = APIRouter(tags=["Calendars"])

ExternalProvider = Literal["google", "microsoft"]


async def get_oauth_state_store(redis: aioredis.Redis = Depends(get_redis)) -> OAuthStateStore:
    return RedisOAuthStateStore(redis)


@router.get("/calendar-providers", response_model=list[CalendarProviderStatus])
async def get_calendar_providers() -> list[CalendarProviderStatus]:
    """Which providers have credentials, and the redirect URI to register."""
    statuses = []
    for provider in PROVIDER_NAMES:
        missing = missing_settings(provider)
        statuses.append(
            CalendarProviderStatus(
                provider=provider,
                configured=not missing,
                missing_settings=missing,
                redirect_uri=redirect_uri(provider),
            )
        )
    return statuses


@router.get("/users/{user_id}/calendar-accounts", response_model=list[CalendarAccountRead])
async def get_calendar_accounts(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> list[CalendarAccount]:
    return await list_accounts(session, user_id)


@router.post(
    "/users/{user_id}/calendar-accounts/{provider}/authorize",
    response_model=AuthorizationStart,
    responses={503: {"description": "The provider's credentials are not set in .env."}},
)
async def post_authorize(
    user_id: uuid.UUID,
    provider: ExternalProvider,
    session: AsyncSession = Depends(get_db),
    state_store: OAuthStateStore = Depends(get_oauth_state_store),
) -> AuthorizationStart:
    url = await start_authorization(session, user_id, CalendarProvider(provider), state_store)
    return AuthorizationStart(authorization_url=url)


@router.delete(
    "/users/{user_id}/calendar-accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_calendar_account(
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> Response:
    await disconnect_account(session, user_id, account_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/oauth/{provider}/callback", include_in_schema=False)
async def oauth_callback(
    provider: ExternalProvider,
    state: str = Query(default=""),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
    state_store: OAuthStateStore = Depends(get_oauth_state_store),
    http: httpx.AsyncClient = Depends(get_calendar_http),
) -> RedirectResponse:
    """The provider redirects here; the browser is then sent back to the app."""
    result = {"provider": provider}
    if error or not code:
        # The user cancelled or the provider refused; consume the state anyway.
        await state_store.take(state)
        result |= {"status": "error", "message": "No se completó la conexión."}
    else:
        try:
            account = await complete_authorization(
                session, CalendarProvider(provider), code, state, state_store, http
            )
            result |= {"status": "ok", "email": account.external_email or ""}
        except AuthorizationFailed as failure:
            result |= {"status": "error", "message": str(failure)}
    return RedirectResponse(f"{settings.APP_OAUTH_CALLBACK_URL}?{urlencode(result)}", status_code=302)
