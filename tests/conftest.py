"""共享测试 fixture — pytest 自动发现喵~"""

import pytest
from tests.fixtures import FakeRobotBackend
from robocode.services.analytics.db import AuditDB
from robocode.config import Settings
from robocode.orchestrator.safety import SafetyPolicy
from robocode.orchestrator.approval import ApprovalGate


@pytest.fixture
def fake_backend():
    """Fake 机器人后端 fixture 喵~"""
    return FakeRobotBackend()


@pytest.fixture
def settings():
    """默认设置 fixture 喵~"""
    return Settings()


@pytest.fixture
def tmp_db(tmp_path):
    """临时 SQLite 审计数据库 fixture 喵~"""
    db = AuditDB(path=str(tmp_path / "test.db"))
    db.initialize()
    yield db
    db.close()


@pytest.fixture
def safety_policy(settings):
    """安全策略 fixture 喵~"""
    return SafetyPolicy(settings)


@pytest.fixture
def approval_gate():
    """审批门 fixture 喵~"""
    return ApprovalGate()
