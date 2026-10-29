from datetime import UTC, datetime
import uuid
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import get_db
from app.main import app
from app.models import User


class FakeResult:
    def __init__(self, user: User | None) -> None:
        self.user = user

    def scalar_one_or_none(self) -> User | None:
        return self.user


class FakeSession:
    def __init__(self) -> None:
        self.user: User | None = None
        self.commits = 0

    async def execute(self, statement: object) -> FakeResult:
        _ = statement
        return FakeResult(self.user)

    def add(self, user: User) -> None:
        self.user = user

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, user: User) -> None:
        # Stand-ins for the values PostgreSQL fills in.
        user.id = user.id or uuid.uuid4()
        user.created_at = user.created_at or datetime.now(UTC)
        user.timezone = user.timezone or "America/Santiago"
        if not isinstance(user.updated_at, datetime):
            user.updated_at = datetime.now(UTC)


class BackendApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = FakeSession()

        async def override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()

    def test_health_endpoints(self) -> None:
        self.assertEqual(self.client.get("/health").json()["status"], "healthy")
        self.assertEqual(
            self.client.get("/api/v1/health").json(),
            {"status": "healthy"},
        )

    def test_demo_user_is_idempotent(self) -> None:
        first_response = self.client.post("/api/v1/users/demo")
        second_response = self.client.post("/api/v1/users/demo")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.json()["id"], second_response.json()["id"])
        self.assertEqual(self.session.commits, 1)
        self.assertEqual(first_response.json()["timezone"], "America/Santiago")

    def test_update_user_sets_timezone(self) -> None:
        user_id = self.client.post("/api/v1/users/demo").json()["id"]

        response = self.client.patch(
            f"/api/v1/users/{user_id}",
            json={"timezone": "Europe/Madrid"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["timezone"], "Europe/Madrid")
        self.assertEqual(response.json()["display_name"], "Demo User")

    def test_update_user_rejects_unknown_timezone(self) -> None:
        response = self.client.patch(
            f"/api/v1/users/{uuid.uuid4()}",
            json={"timezone": "Mars/Olympus_Mons"},
        )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.session.commits, 0)


class SettingsNamingTests(unittest.TestCase):
    def test_api_prefix_accepts_new_and_legacy_setting_names(self) -> None:
        current_setting = Settings(_env_file=None, API_V1_PREFIX="/api/v2")
        legacy_setting = Settings(_env_file=None, API_V1_STR="/legacy")

        self.assertEqual(current_setting.API_V1_PREFIX, "/api/v2")
        self.assertEqual(legacy_setting.API_V1_PREFIX, "/legacy")

    def test_api_prefix_accepts_legacy_environment_variable(self) -> None:
        with patch.dict("os.environ", {"API_V1_STR": "/legacy"}, clear=True):
            setting = Settings(_env_file=None)

        self.assertEqual(setting.API_V1_PREFIX, "/legacy")
