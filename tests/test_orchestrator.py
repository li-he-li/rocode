"""Orchestrator tests — state machine, safety, approval, task plans."""

import pytest
from robocode.orchestrator.state_machine import (
    Orchestrator,
    OrchestratorState,
    TaskPlan,
    TaskStep,
)
from robocode.orchestrator.safety import SafetyPolicy
from robocode.orchestrator.approval import ApprovalGate


class TestTaskStep:
    def test_defaults(self):
        step = TaskStep(name="test", description="a step", risk_level="L0")
        assert step.state == "pending"
        assert step.retry_count == 0
        assert step.max_retries == 1


class TestTaskPlan:
    def test_add_and_iterate(self):
        plan = TaskPlan()
        plan.add_step(TaskStep(name="s1", description="", risk_level="L0"))
        plan.add_step(TaskStep(name="s2", description="", risk_level="L1"))
        assert plan.next_step().name == "s1"
        assert plan.next_step().name == "s2"
        assert plan.next_step() is None

    def test_has_pending(self):
        plan = TaskPlan()
        plan.add_step(TaskStep(name="s1", description="", risk_level="L0"))
        assert plan.has_pending()
        step = plan.next_step()
        step.state = "success"
        assert not plan.has_pending()


class TestOrchestrator:
    def test_full_flow(self):
        orch = Orchestrator()
        assert orch.state == OrchestratorState.IDLE

        orch.start_planning()
        assert orch.state == OrchestratorState.PLANNING
        orch.current_plan.add_step(TaskStep(name="s1", description="", risk_level="L1"))
        assert orch.validate() is True
        assert orch.state == OrchestratorState.AWAITING_APPROVAL

        orch.approve()
        assert orch.state == OrchestratorState.EXECUTING

        step = orch.current_plan.next_step()
        orch.step_success(step, {"result": "ok"})
        assert step.state == "success"

        orch.finish(True)
        assert orch.state == OrchestratorState.SUCCESS

    def test_reject_returns_to_idle(self):
        orch = Orchestrator()
        orch.start_planning()
        orch.current_plan.add_step(TaskStep(name="s1", description="", risk_level="L0"))
        orch.validate()
        orch.reject()
        assert orch.state == OrchestratorState.IDLE
        assert orch.current_plan is None

    def test_empty_plan_fails_validation(self):
        orch = Orchestrator()
        orch.start_planning()
        assert orch.validate() is False
        assert orch.state == OrchestratorState.FAILED

    def test_step_retry(self):
        orch = Orchestrator()
        step = TaskStep(
            name="s1",
            description="",
            risk_level="L1",
            max_retries=1,
        )
        orch.step_failed(step, Exception("fail"))
        assert step.retry_count == 1
        assert step.state == "pending"

        orch.step_failed(step, Exception("fail again"))
        assert step.retry_count == 2
        assert step.state == "failed"


class TestSafetyPolicy:
    def test_l0_no_approval(self):
        sp = SafetyPolicy()
        assert sp.requires_approval("L0") is False

    def test_l2_requires_approval(self):
        sp = SafetyPolicy()
        assert sp.requires_approval("L2") is True

    def test_workspace_reject_outside_x(self):
        sp = SafetyPolicy()
        result = sp.check_workspace_bounds(600, 0, 200)
        assert result.passed is False
        assert "X=" in result.reason

    def test_workspace_accept_inside(self):
        sp = SafetyPolicy()
        result = sp.check_workspace_bounds(300, 0, 200)
        assert result.passed is True

    def test_speed_cap(self):
        sp = SafetyPolicy()
        result = sp.check_speed(0.9)  # > 0.6
        assert result.passed is False

    def test_speed_ok(self):
        sp = SafetyPolicy()
        result = sp.check_speed(0.3)
        assert result.passed is True


class TestApprovalGate:
    def test_l0_auto_approved(self):
        gate = ApprovalGate()
        assert gate.should_prompt("L0") is False

    def test_l2_needs_prompt(self):
        gate = ApprovalGate()
        assert gate.should_prompt("L2") is True

    def test_session_approve(self):
        gate = ApprovalGate()
        gate.mark_session_approved("move_robot_xyz")
        assert gate.is_auto_approved("move_robot_xyz", "L2") is True


class TestSafetyCheckOperation:
    def test_non_numeric_params_rejected(self):
        sp = SafetyPolicy()
        results = sp.check_operation("move", {"x": "abc", "y": 0, "z": 0})
        assert any(not r.passed and "数字" in r.reason for r in results)

    def test_non_numeric_speed_rejected(self):
        sp = SafetyPolicy()
        results = sp.check_operation("move", {"speed_ratio": "fast"})
        assert any(not r.passed for r in results)

    def test_empty_params_passes(self):
        sp = SafetyPolicy()
        results = sp.check_operation("get_status", {})
        assert len(results) == 1
        assert results[0].passed is True


class TestStateGuards:
    def test_approve_from_idle_raises(self):
        orch = Orchestrator()
        with pytest.raises(RuntimeError, match="AWAITING_APPROVAL"):
            orch.approve()

    def test_reject_from_idle_raises(self):
        orch = Orchestrator()
        with pytest.raises(RuntimeError, match="AWAITING_APPROVAL"):
            orch.reject()

    def test_validate_not_planning_raises(self):
        orch = Orchestrator()
        orch.start_planning()
        orch.current_plan.add_step(TaskStep(name="s1", description="", risk_level="L0"))
        orch.validate()
        with pytest.raises(RuntimeError, match="PLANNING"):
            orch.validate()

    def test_recover_to_executing(self):
        orch = Orchestrator()
        orch.state = OrchestratorState.RECOVERING
        orch.recover()
        assert orch.state == OrchestratorState.EXECUTING

    def test_recover_not_recovering_raises(self):
        orch = Orchestrator()
        with pytest.raises(RuntimeError, match="RECOVERING"):
            orch.recover()


class TestRetrySemantics:
    def test_max_retries_1_gives_1_retry(self):
        orch = Orchestrator()
        step = TaskStep(name="s1", description="", risk_level="L1", max_retries=1)
        orch.step_failed(step, Exception("fail"))
        assert step.retry_count == 1
        assert step.state == "pending"  # still retrying

    def test_max_retries_0_no_retry(self):
        orch = Orchestrator()
        step = TaskStep(name="s1", description="", risk_level="L1", max_retries=0)
        orch.step_failed(step, Exception("fail"))
        assert step.retry_count == 1
        assert step.state == "failed"

    def test_last_error_stored(self):
        step = TaskStep(name="s1", description="", risk_level="L1")
        orch = Orchestrator()
        orch.step_failed(step, ValueError("bad value"))
        assert "bad value" in step.last_error


class TestApprovalRequest:
    def test_format_prompt_output(self):
        gate = ApprovalGate()
        req = gate.request("test_tool", "L2", {"x": 100}, "移动到 X=100")
        prompt = req.format_prompt()
        assert "test_tool" in prompt
        assert "x" in prompt
        assert "[Y]" in prompt
