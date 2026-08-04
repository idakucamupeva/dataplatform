"""Test fixtures.

Every test runs against a throwaway data directory: its own SQLite file and
its own git repositories. The environment has to be set before anything under
``app`` is imported, because the settings object is built at import time.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="dmp-tests-")
os.environ["DMP_DATA_DIR"] = _TMP
os.environ["DMP_DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["DMP_SECRET_KEY"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Domain, Role, User  # noqa: E402


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture
def db() -> Session:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    shutil.rmtree(f"{_TMP}/repos", ignore_errors=True)
    shutil.rmtree(f"{_TMP}/workspaces", ignore_errors=True)

    session = SessionLocal()
    session.add_all(
        [
            User(username="alice", email="alice@test.io", full_name="Alice Producer",
                 hashed_password=hash_password("password123"), role=Role.USER),
            User(username="bruno", email="bruno@test.io", full_name="Bruno Consumer",
                 hashed_password=hash_password("password123"), role=Role.USER),
            User(username="gwen", email="gwen@test.io", full_name="Gwen Governance",
                 hashed_password=hash_password("password123"), role=Role.GOVERNANCE),
        ]
    )
    session.flush()
    session.add(Domain(name="sales", title="Sales"))
    session.add(Domain(name="marketing", title="Marketing"))
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db: Session) -> TestClient:  # noqa: ARG001 - db seeds the database
    return TestClient(app)


@pytest.fixture
def auth(client: TestClient):
    """Return a callable producing an Authorization header for a username."""

    def _auth(username: str = "alice") -> dict[str, str]:
        response = client.post("/api/auth/login", json={"username": username, "password": "password123"})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['accessToken']}"}

    return _auth


@pytest.fixture
def alice(db: Session) -> User:
    return db.query(User).filter(User.username == "alice").one()


def schema_columns(*rows) -> list[dict]:
    return [
        {"name": n, "dataType": t, "description": d, "nullable": nu, "pii": p, "classification": c}
        for n, t, d, nu, p, c in rows
    ]
