# Backend scaffold

## Local setup

From the repository root:

```bash
test -f .env || cp .env.example .env
docker compose up -d db redis
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=Backend python -m app.init_db
uvicorn app.main:app --app-dir Backend --reload
```

The API is available at `http://localhost:8000`; interactive docs are at
`http://localhost:8000/docs`. The health endpoints are
`/health` and `/api/v1/health`.

`POST /api/v1/users/demo` creates or returns the local demo user. It requires
PostgreSQL and the `users` table, created by `app.init_db`. This is a
development-only schema bootstrap; replace it with Alembic migrations before
production. Health checks do not require PostgreSQL or Redis to be running.

## Tests

From the repository root:

```bash
PYTHONPATH=Backend python -m unittest discover -s Backend/tests
```

The API tests use a fake database session and do not need external services.
