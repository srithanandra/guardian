import os
import tempfile
from pathlib import Path

os.environ["GUARDIAN_DB_PATH"] = str(Path(tempfile.gettempdir()) / f"guardian-test-{os.getpid()}.db")
os.environ["GUARDIAN_TIER_HOLD_SECONDS"] = "8"
os.environ["GUARDIAN_DEMO_PING_SECONDS"] = "0"
os.environ["GUARDIAN_DEMO_SYNC"] = "1"
os.environ["GUARDIAN_AUTO_ESCALATE"] = "0"

import pytest
from fastapi.testclient import TestClient

from backend.app.db import init_db
from backend.app.main import app


@pytest.fixture
def client():
    init_db()
    with TestClient(app) as test_client:
        test_client.post("/demo/reset")
        yield test_client
        test_client.post("/demo/reset")
