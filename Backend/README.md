# Backend scaffold

## Local setup

From the repository root:

```bash
test -f .env || cp .env.example .env
docker compose up -d db redis
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic -c alembic.ini upgrade head
uvicorn app.main:app --app-dir Backend --reload
```

The API is available at `http://localhost:8000`; interactive docs are at
`http://localhost:8000/docs`. The health endpoints are
`/health` and `/api/v1/health`.

`POST /api/v1/users/demo` creates or returns the local demo user. It requires
PostgreSQL. Database changes are tracked with Alembic in `Backend/migrations`;
run `alembic -c alembic.ini upgrade head` after starting PostgreSQL. The
initial schema was supplied in `Backend/migrations/smart_scheduler_schema.sql`
and is applied by the second migration. It creates all entities and
relationships from that schema, and copies existing demo users from the
scaffold's original `users` table into `usuarios`.

`PATCH /api/v1/users/{user_id}` updates `display_name` and/or `timezone` (an
IANA name such as `Europe/Madrid`; unknown names return 422). The timezone
decides how relative dates in captures are read, so the iOS app sends the
device timezone on first launch and again whenever it changes.

Health checks do not require PostgreSQL or Redis to be running.

## Scheduling API (initial backend milestone)

The scheduling endpoints use the existing `eventos` and `reglas_agenda` tables:

- `POST /api/v1/users/{user_id}/availability-rules` creates a weekly working-hours rule.
  Weekdays use ISO numbering (`1` = Monday, `7` = Sunday); times are local to the
  user's configured timezone.
- `GET /api/v1/users/{user_id}/availability-rules` lists active rules.
- `GET /api/v1/users/{user_id}/availability/slots?from=...&to=...&duration_minutes=...`
  returns candidate slots inside configured working hours, excluding tentative and
  confirmed events. Slots advance by 15 minutes by default; `step_minutes` can
  change that increment.
- `POST /api/v1/users/{user_id}/events` creates a manual task or meeting and rejects
  time conflicts with HTTP 409.
- `GET /api/v1/users/{user_id}/events?from=...&to=...` lists events intersecting
  the requested time range.

All datetime query/body values must include a timezone. This initial availability
service is deterministic slot enumeration, not yet the OR-Tools optimizer, and it
does not include travel buffers or external calendar synchronization.

## Capture API (voice or text to event)

`POST /api/v1/users/{user_id}/captures` turns a dictated note into a confirmed
event. The iOS app transcribes speech on the device and sends only the text:

```json
{
  "text": "mañana a las tres dentista una hora",
  "channel": "voz",
  "local_id": "9b2f6c1e-5a4d-4e8b-9c3a-2f1d0e7b6a54",
  "captured_at": "2026-11-02T09:15:00-03:00",
  "created_offline": false,
  "stt_engine": "apple_speech"
}
```

Only `text` is required. The app may also send `busy_intervals`, a list of
`{"start", "end"}` times (at most 500) that are busy in calendars the backend
does not see, such as the device calendar. They are treated like agenda events
when choosing a slot or checking an explicit time (409 with "device calendar"
in the detail) and are not stored.

The note is parsed by an LLM with structured output
(`CAPTURE_LLM_MODEL`, default `claude-haiku-5-5`) into a title, type, priority,
duration and either a clock time or a time window. Relative dates ("mañana",
"esta semana") are resolved against `captured_at` in the user's timezone.

- With a clock time, the event is created at that time if it is free.
- Without one, the event goes into the first free slot inside the window (or
  the next seven days) within the user's working hours, and is marked
  `flexible`.

Responses: `201` with the capture and its event; `200` when a capture with the
same `local_id` was already processed (safe retries from the offline queue);
`409` when the time is taken or no slot is free; `422` when the note cannot be
turned into an event; `503` when the LLM is unavailable or `ANTHROPIC_API_KEY`
is not set. Every attempt is stored in `capturas`, including the model output,
the error reason and `latencia_total_ms` (server-side processing time).

## Locations and travel blocks

Travel times are estimated on the phone with Apple Maps (MapKit), so the
backend needs no maps API key. The capture response includes
`location_query` when the note names a place ("dentista en Providencia"); the
app resolves it and calls:

- `GET/POST /api/v1/users/{user_id}/locations` lists or saves places. Saving
  a place with an existing alias ("Casa") moves it instead of adding another.
  `DELETE .../locations/{location_id}` removes one.
- `PUT /api/v1/users/{user_id}/events/{event_id}/location` sets where an
  event happens, with `location_id` (a saved place) or `location` (a new one;
  reused when the same `place_id` or coordinates already exist). With
  `travel` (`duration_seconds`, optional `origin_location_id`,
  `distance_meters`, `mode`, `provider`) it inserts a `traslado` event right
  before the event, rounded up to 5 minutes and linked with `evento_padre_id`,
  plus its detail row in `traslados`. Trips under a minute get no block.

If the trip overlaps another event or a device busy time (`busy_intervals`),
a flexible event moves to the first slot in its window with room for the trip
(`moved: true`); a fixed one keeps its time and the response says
`travel_overlaps: true`. Calling it again replaces the previous travel block.
A new event inserted between two others does not yet recalculate the trip of
the following one; that cascade belongs to adaptive rescheduling (phase 4).

## Working hours

`PUT /api/v1/users/{user_id}/working-hours` replaces the whole weekly schedule
in one transaction, with a body like
`{"rules": [{"weekdays": [1, 2, 3, 4], "start_time": "09:00", "end_time": "18:00"}]}`
(at least one rule). The iOS settings screen edits one range per day and
groups equal days into rules.

## Connected calendars (Google, Outlook)

Setup, credentials and troubleshooting: [docs/calendar-credentials.md](../docs/calendar-credentials.md).

- `GET /api/v1/calendar-providers` says which providers have credentials,
  what is missing and the redirect URI to register.
- `POST /api/v1/users/{user_id}/calendar-accounts/{google|microsoft}/authorize`
  returns the consent URL (503 naming the missing `.env` variables when not
  configured). The provider redirects to `/api/v1/oauth/{provider}/callback`,
  which stores the tokens AES-256-GCM encrypted and sends the browser back to
  `APP_OAUTH_CALLBACK_URL`. The OAuth state lives in Redis for 10 minutes.
- `GET .../calendar-accounts` lists them; `DELETE .../calendar-accounts/{id}`
  forgets one.

Captures then avoid busy times of active accounts for the next 14 days,
fetched in parallel with a 1.5 s limit per provider; a failing provider is
skipped, and one whose access was revoked is marked `token_expirado`. Writing
events to those calendars is not implemented yet.

## Naming conventions

- Python modules and files use lowercase `snake_case`; resource modules use
  the singular entity name consistently (`user.py`).
- Python functions and variables use `snake_case`, classes use `PascalCase`,
  and constants use `UPPER_SNAKE_CASE`.
- Environment variables use `UPPER_SNAKE_CASE`; API routing configuration is
  named `API_V1_PREFIX`. The previous `API_V1_STR` name remains accepted for
  existing local `.env` files.
- Application code uses English identifiers. Database identifiers retain the
  Spanish names from the supplied SQL schema; ORM attributes map explicitly
  to those names where they differ.

To create a new revision after changing SQLAlchemy models:

```bash
alembic -c alembic.ini revision --autogenerate -m "describe schema change"
```

Review autogenerated migrations before applying them. New ORM models should
track the tables in the supplied SQL schema before using autogeneration, so
Alembic does not suggest dropping schema tables it does not yet have mapped.

## Tests

From the repository root:

```bash
PYTHONPATH=Backend python -m unittest discover -s Backend/tests
```

The API tests use a fake database session and do not need external services.

The integration tests in `Backend/tests/test_integration.py` run against a real
PostgreSQL server and are skipped unless `TEST_DATABASE_URL` is set:

```bash
docker compose up -d db
TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgrespassword@localhost:5432/postgres" \
  PYTHONPATH=Backend python -m unittest discover -s Backend/tests
```

Each run creates a throwaway `smart_scheduler_test_*` database, applies the
Alembic migrations to it and drops it afterwards, so the development database
is not modified. They check that every mapped ORM column exists in the migrated
schema and exercise the scheduling and capture endpoints end to end; the
capture tests replace the LLM with a fake parser.

Tests that call the real model are opt-in, because each run is billed (a
fraction of a cent). They need `ANTHROPIC_API_KEY` in `.env`:

```bash
RUN_LLM_TESTS=1 PYTHONPATH=Backend python -m unittest Backend.tests.test_capture -v
```

They print each parsed result and its latency, which is the quickest way to
check the model against the 3-second budget (RNF01).
