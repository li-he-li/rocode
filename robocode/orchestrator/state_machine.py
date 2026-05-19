"""Orchestrator state machine and task plans."""

from enum import Enum
from dataclasses import dataclass, field


class OrchestratorState(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    VALIDATING = "validating"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    RECOVERING = "recovering"
    FAILED = "failed"
    SUCCESS = "success"


@dataclass
class TaskStep:
    name: str
    description: str
    risk_level: str
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    state: str = "pending"
    result: dict | None = None
    retry_count: int = 0
    max_retries: int = 1
    last_error: str = ""


@dataclass
class TaskPlan:
    steps: list[TaskStep] = field(default_factory=list)
    current_step: int = 0
    state: OrchestratorState = OrchestratorState.IDLE

    def add_step(self, step: TaskStep):
        self.steps.append(step)

    def next_step(self) -> TaskStep | None:
        if self.current_step < len(self.steps):
            step = self.steps[self.current_step]
            self.current_step += 1
            return step
        return None

    def has_pending(self) -> bool:
        return any(s.state == "pending" for s in self.steps)


class Orchestrator:
    def __init__(self):
        self.state = OrchestratorState.IDLE
        self.current_plan: TaskPlan | None = None

    def start_planning(self):
        self.state = OrchestratorState.PLANNING
        self.current_plan = TaskPlan()

    def validate(self) -> bool:
        if self.state != OrchestratorState.PLANNING:
            raise RuntimeError(f"validate 只能在 PLANNING 状态调用，当前: {self.state}")
        self.state = OrchestratorState.VALIDATING
        if self.current_plan and self.current_plan.steps:
            self.state = OrchestratorState.AWAITING_APPROVAL
            return True
        self.state = OrchestratorState.FAILED
        return False

    def approve(self):
        if self.state != OrchestratorState.AWAITING_APPROVAL:
            raise RuntimeError(f"approve 只能在 AWAITING_APPROVAL 状态调用，当前: {self.state}")
        self.state = OrchestratorState.EXECUTING

    def reject(self):
        if self.state != OrchestratorState.AWAITING_APPROVAL:
            raise RuntimeError(f"reject 只能在 AWAITING_APPROVAL 状态调用，当前: {self.state}")
        self.state = OrchestratorState.IDLE
        self.current_plan = None

    def step_success(self, step: TaskStep, result: dict):
        step.state = "success"
        step.result = result

    def step_failed(self, step: TaskStep, error: Exception):
        step.retry_count += 1
        step.last_error = str(error)
        if step.retry_count > step.max_retries:
            step.state = "failed"
            self.state = OrchestratorState.FAILED
        else:
            step.state = "pending"
            self.state = OrchestratorState.RECOVERING

    def recover(self):
        if self.state != OrchestratorState.RECOVERING:
            raise RuntimeError(f"recover 只能在 RECOVERING 状态调用，当前: {self.state}")
        self.state = OrchestratorState.EXECUTING

    def finish(self, success: bool):
        if success:
            self.state = OrchestratorState.SUCCESS
        else:
            self.state = OrchestratorState.FAILED
