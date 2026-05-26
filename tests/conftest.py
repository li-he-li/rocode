"""Shared test fixtures — auto-discovered by pytest."""

import pytest
from tests.fixtures import FakeRobotBackend
from robocode.services.analytics.db import AuditDB
from robocode.config import Settings
from robocode.orchestrator.safety import SafetyPolicy
from robocode.orchestrator.approval import ApprovalGate


@pytest.fixture
def fake_backend():
    return FakeRobotBackend()


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def tmp_db(tmp_path):
    db = AuditDB(path=str(tmp_path / "test.db"))
    db.initialize()
    yield db
    db.close()


@pytest.fixture
def safety_policy(settings):
    return SafetyPolicy(settings)


@pytest.fixture
def approval_gate():
    return ApprovalGate()
