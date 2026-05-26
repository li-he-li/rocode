"""Model behavior tests — verify schemas, defaults, and enum values."""

from robocode.utils.models import (
    ToolResult,
    RobotStatus,
    BackendHealth,
)
from robocode.config import Settings


class TestToolResult:
    def test_defaults(self):
        r = ToolResult(success=True)
        assert r.success is True
        assert r.message == ""
        assert r.metrics == {}
        assert r.artifacts == {}

    def test_with_metrics(self):
        r = ToolResult(success=True, message="ok", metrics={"rms_mm": 1.5})
        assert r.metrics["rms_mm"] == 1.5


class TestRobotStatus:
    def test_defaults(self):
        s = RobotStatus(connected=False)
        assert s.connected is False
        assert s.motor_angles == []
        assert s.pose == []
        assert s.estop_active is False


class TestBackendHealth:
    def test_fields(self):
        h = BackendHealth(healthy=True, backend="sdk", latency_ms=2.0)
        assert h.healthy is True
        assert h.backend == "sdk"


class TestSettings:
    def test_defaults(self):
        s = Settings()
        assert s.provider.base_url == "https://api.deepseek.com"
        assert s.safety.max_radius_mm == 510.0
        assert s.safety.max_payload_g == 500.0
        assert s.safety.supply_voltage == 12.0

    def test_workspace_bounds(self):
        s = Settings()
        assert s.workspace.x_min < s.workspace.x_max
        assert s.workspace.y_min < s.workspace.y_max
        assert s.workspace.z_min < s.workspace.z_max

    def test_approval_policy_on_by_default(self):
        s = Settings()
        assert s.approval.l2_require_approval is True
        assert s.approval.file_write_require_approval is True
        assert s.approval.code_execution_require_approval is True

    def test_timeouts_positive(self):
        s = Settings()
        assert s.timeout_action_s > 0
        assert s.timeout_code_exec_s > 0
        assert s.max_react_iterations > 0
