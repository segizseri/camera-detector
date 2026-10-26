import os
from pathlib import Path

TEST_DB_PATH = Path("data-test/sqlite/pytest.db")
TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ.setdefault("ENCRYPTION_KEY", "mzxG9QZ0N9E5_n-I54aWXZ5G8X-G9oN-w-X_gZJpL14=")
os.environ["AUTH_ENABLED"] = "false"
os.environ["HLS_OUTPUT_DIR"] = "data-test/media/hls"
os.environ["SNAPSHOTS_DIR"] = "data-test/media/snapshots"
os.environ["CLIPS_DIR"] = "data-test/media/clips"
os.environ["DETECTION_TESTS_DIR"] = "data-test/media/detection-tests"

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routers import cameras as cameras_router
from libs.database import Base, SessionLocal, engine


@pytest.fixture(autouse=True)
def reset_database():
    cameras_router._hls_processes.clear()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    cameras_router._hls_processes.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
