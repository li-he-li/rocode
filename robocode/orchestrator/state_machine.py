"""编排器状态机 + 任务计划 — 控制 Agent 执行流程的有限状态机喵~"""

from enum import Enum
from dataclasses import dataclass, field


class OrchestratorState(str, Enum):
    """编排器状态枚举 — 从空闲到成功/失败的完整生命周期喵~"""

    IDLE = "idle"  # 空闲中
    PLANNING = "planning"  # 正在规划步骤
    VALIDATING = "validating"  # 验证计划合法性
    AWAITING_APPROVAL = "awaiting_approval"  # 等待操作者审批
    EXECUTING = "executing"  # 正在执行工具
    RECOVERING = "recovering"  # 失败后尝试恢复
    FAILED = "failed"  # 任务失败
    SUCCESS = "success"  # 任务成功


@dataclass
class TaskStep:
    """单个任务步骤 — 记录工具调用及其状态喵~"""

    name: str
    description: str
    risk_level: str
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    state: str = "pending"  # pending → running → success/failed
    result: dict | None = None  # 工具返回结果
    retry_count: int = 0  # 当前重试次数
    max_retries: int = 1  # 最大允许重试次数
    last_error: str = ""  # 最近一次错误信息


@dataclass
class TaskPlan:
    """任务计划 — 包含步骤列表 + 当前进度喵~"""

    steps: list[TaskStep] = field(default_factory=list)
    current_step: int = 0
    state: OrchestratorState = OrchestratorState.IDLE

    def add_step(self, step: TaskStep):
        """追加步骤到计划末尾喵~"""
        self.steps.append(step)

    def next_step(self) -> TaskStep | None:
        """取出下一步，推进 current_step 游标喵~"""
        if self.current_step < len(self.steps):
            step = self.steps[self.current_step]
            self.current_step += 1
            return step
        return None

    def has_pending(self) -> bool:
        """是否还有待执行的步骤喵~"""
        return any(s.state == "pending" for s in self.steps)


class Orchestrator:
    """编排器 — 管理任务计划的状态转换喵~"""

    def __init__(self):
        self.state = OrchestratorState.IDLE
        self.current_plan: TaskPlan | None = None

    def start_planning(self):
        """开始规划阶段，创建空计划喵~"""
        self.state = OrchestratorState.PLANNING
        self.current_plan = TaskPlan()

    def validate(self) -> bool:
        """验证计划合法性 → 有步骤进审批，否则失败喵~"""
        if self.state != OrchestratorState.PLANNING:
            raise RuntimeError(f"validate 只能在 PLANNING 状态调用，当前: {self.state}")
        self.state = OrchestratorState.VALIDATING
        if self.current_plan and self.current_plan.steps:
            self.state = OrchestratorState.AWAITING_APPROVAL
            return True
        self.state = OrchestratorState.FAILED
        return False

    def approve(self):
        """审批通过 → 进入执行阶段喵~"""
        if self.state != OrchestratorState.AWAITING_APPROVAL:
            raise RuntimeError(f"approve 只能在 AWAITING_APPROVAL 状态调用，当前: {self.state}")
        self.state = OrchestratorState.EXECUTING

    def reject(self):
        """审批拒绝 → 清空计划，回到空闲喵~"""
        if self.state != OrchestratorState.AWAITING_APPROVAL:
            raise RuntimeError(f"reject 只能在 AWAITING_APPROVAL 状态调用，当前: {self.state}")
        self.state = OrchestratorState.IDLE
        self.current_plan = None

    def step_success(self, step: TaskStep, result: dict):
        """标记步骤成功，记录结果喵~"""
        step.state = "success"
        step.result = result

    def step_failed(self, step: TaskStep, error: Exception):
        """步骤失败处理 — 自动重试或标记失败喵~"""
        step.retry_count += 1
        step.last_error = str(error)
        if step.retry_count > step.max_retries:
            step.state = "failed"
            self.state = OrchestratorState.FAILED
        else:
            step.state = "pending"  # 重置为待执行
            self.state = OrchestratorState.RECOVERING  # 进入恢复模式

    def recover(self):
        """从恢复状态回到执行状态喵~"""
        if self.state != OrchestratorState.RECOVERING:
            raise RuntimeError(f"recover 只能在 RECOVERING 状态调用，当前: {self.state}")
        self.state = OrchestratorState.EXECUTING

    def finish(self, success: bool):
        """任务结束，设置最终状态喵~"""
        if success:
            self.state = OrchestratorState.SUCCESS
        else:
            self.state = OrchestratorState.FAILED
