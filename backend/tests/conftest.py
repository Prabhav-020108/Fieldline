"""
Shared pytest setup for the FieldLine BACKEND tests.

What this file guarantees for every test:

  1. The app talks to a THROWAWAY SQLite file in your temp folder -- never to
     your real Supabase/Postgres database. The DATABASE_URL environment
     variable is force-set below BEFORE any app module is imported, because
     backend/models.py builds its database engine at import time.
  2. Every test starts with empty tables containing only two demo companies
     ("site-demo", "acme-elevator") and the six demo login accounts.
  3. Nothing ever calls the real Moss cloud: the background "sync to Moss"
     job is replaced by a fake that just records which company was synced.
  4. slowapi's rate limiter is switched off (so 100 test requests from one
     "IP" don't get blocked with HTTP 429). The one test that checks the
     limiter itself switches it back on temporarily.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

# --- 1. Make backend/ importable (main.py, auth.py, models.py live there) ---
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# --- 2. Point the app at a throwaway database BEFORE importing it ----------
# These are assigned with "=" (not setdefault) on purpose: even if your shell
# or backend/.env holds real Supabase credentials, tests must never use them.
_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="fieldline_backend_tests_"))
_TEST_DB_FILE = _TEST_DB_DIR / "test.sqlite3"

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_FILE.as_posix()}"
os.environ["FIELDLINE_JWT_SECRET"] = "test-only-jwt-secret-not-for-production"
os.environ["MOSS_PROJECT_ID"] = "test-moss-project-id"
os.environ["MOSS_PROJECT_KEY"] = "test-moss-project-key"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
from models import Base, Company, SessionLocal, User, engine  # noqa: E402

# Safety net: refuse to run at all if the engine is somehow not SQLite.
if engine.url.get_backend_name() != "sqlite":
    raise RuntimeError(
        "Backend tests must run against SQLite, but the engine points at "
        f"{engine.url.get_backend_name()!r}. Refusing to continue so real data "
        "can never be touched."
    )

DEMO_PASSWORD = "FieldLine123!"
# bcrypt is deliberately slow, so hash the demo password ONCE and reuse it.
_DEMO_PASSWORD_HASH = auth.hash_password(DEMO_PASSWORD)

_DEMO_COMPANIES = [
    ("site-demo", "Site Demo Electrical Co.", "electrical", "hinglish", "site-demo"),
    ("acme-elevator", "Acme Elevator AMC", "elevator_amc", "english", "company-acme-elevator"),
]

_DEMO_USERS = [
    ("tech.demo", "site-demo", "technician"),
    ("supervisor.demo", "site-demo", "supervisor"),
    ("dispatcher.demo", "site-demo", "dispatcher"),
    ("tech.acme", "acme-elevator", "technician"),
    ("supervisor.acme", "acme-elevator", "supervisor"),
    ("dispatcher.acme", "acme-elevator", "dispatcher"),
]


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_database_file():
    """After the whole run, close the DB connections and delete the temp file."""
    yield
    engine.dispose()
    shutil.rmtree(_TEST_DB_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def _fresh_database():
    """Empty every table, then insert the two demo companies and six users."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    db = SessionLocal()
    try:
        for company_id, name, industry, language, index_name in _DEMO_COMPANIES:
            db.add(
                Company(
                    id=company_id,
                    name=name,
                    industry=industry,
                    language_preference=language,
                    moss_index_name=index_name,
                )
            )
        db.commit()

        for username, company_id, role in _DEMO_USERS:
            db.add(
                User(
                    id=f"user-{username}",
                    company_id=company_id,
                    username=username,
                    hashed_password=_DEMO_PASSWORD_HASH,
                    role=role,
                )
            )
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture(autouse=True)
def sync_calls(monkeypatch):
    """Replace the real Moss sync with a fake. The returned list records the
    company id of every sync the app tried to run, so tests can assert on it."""
    calls: list[str] = []

    async def _fake_sync_company(company_id: str) -> int:
        calls.append(company_id)
        return 7  # pretend 7 documents were pushed

    monkeypatch.setattr(main.moss_sync, "sync_company", _fake_sync_company)
    return calls


@pytest.fixture(autouse=True)
def _rate_limiter_off():
    """Switch the limiter off for normal tests (see the module docstring)."""
    main.limiter.enabled = False
    yield
    main.limiter.enabled = False


@pytest.fixture
def client():
    """A FastAPI TestClient wired to the real app."""
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    """Factory: auth_headers("dispatcher") -> {"Authorization": "Bearer ..."}.

    Tokens are minted directly with auth.create_access_token, so tests don't
    need to log in first. Pass company_id to act as another company's user.
    """

    def _make(role: str, company_id: str = "site-demo") -> dict[str, str]:
        token = auth.create_access_token(
            username=f"{role}.{company_id}", role=role, company_id=company_id
        )
        return {"Authorization": f"Bearer {token}"}

    return _make
