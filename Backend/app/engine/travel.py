from datetime import datetime, timedelta

import httpx

from app.core.config import settings

DEFAULT_TRAVEL_MINUTES = 15


async def estimate_travel_minutes(origin: str | None, destination: str | None) -> int:
    if not origin or not destination:
        return 0
    if origin.strip().lower() == destination.strip().lower():
        return 0
    if not settings.GOOGLE_MAPS_API_KEY:
        return DEFAULT_TRAVEL_MINUTES

    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": origin,
        "destinations": destination,
        "mode": "driving",
        "departure_time": "now",
        "key": settings.GOOGLE_MAPS_API_KEY,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    try:
        seconds = data["rows"][0]["elements"][0]["duration_in_traffic"]["value"]
    except (KeyError, IndexError):
        try:
            seconds = data["rows"][0]["elements"][0]["duration"]["value"]
        except (KeyError, IndexError):
            return DEFAULT_TRAVEL_MINUTES
    return max(5, int(seconds / 60))


def event_window(start: datetime, duration_minutes: int, travel_before: int, travel_after: int) -> tuple[datetime, datetime]:
    block_start = start - timedelta(minutes=travel_before)
    block_end = start + timedelta(minutes=duration_minutes + travel_after)
    return block_start, block_end
