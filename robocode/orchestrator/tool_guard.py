"""ToolGuard — 桥接审批门 + 审计DB + 安全策略 + 审批设置到工具执行层喵~"""

from dataclasses import dataclass
from typing import Awaitable, Callable

from robocode.services.analytics.logger import get_logger

logger = get_logger("tool_guard")


@dataclass
class GuardResult:
    """门控结果喵~"""

    allowed: bool  # 是否允许执行
    reason: str = ""  # 放行/拒绝原因
    decision: str = ""  # 决策类型: "auto" | "approved" | "rejected" | "session_approved"


ApprovalCallback = Callable[[str, str, dict, str], Awaitable[str]]
# callback(tool_name, risk_level, params, summary) -> "Y" | "N" | "A"


class ToolGuard:
    """工具门控 — 执行前根据风险级别+策略+操作者意愿判断是否放行喵~

    决策链: L0→自动放行 → 会话免审批→放行 → L1→策略检查 → L2→审批
    """

    def __init__(
        self,
        approval_gate,
        audit_db,
        safety_policy,
        approval_settings,
        owner_callback: ApprovalCallback | None = None,
        session_id: str = "",
        metrics=None,
    ):
        self._gate = approval_gate
        self._db = audit_db
        self._safety = safety_policy
        self._settings = approval_settings
        self._owner_callback = owner_callback  # CLI 弹窗回调
        self._session_id = session_id
        self._metrics = metrics

    async def check(
        self, tool_name: str, risk_level: str, params: dict, summary: str = ""
    ) -> GuardResult:
        """执行前门控检查喵~"""
        # L0 始终自动放行
        if risk_level == "L0":
            return GuardResult(allowed=True, reason="L0 auto-approved", decision="auto")

        # 会话免审批？直接放行
        if self._gate.is_auto_approved(tool_name, risk_level):
            return GuardResult(
                allowed=True, reason="session auto-approved", decision="session_approved"
            )

        # L1: 默认放行，除非策略显式要求审批
        if risk_level == "L1":
            file_write_policy = (
                self._settings.file_write_require_approval if self._settings else False
            )
            script_policy = (
                self._settings.script_launch_require_approval if self._settings else False
            )
            if file_write_policy and self._would_write_files(tool_name, params):
                pass  # 需要审批，落入下方审批流程
            elif script_policy and tool_name == "run_script":
                pass
            elif (
                script_policy
                and tool_name == "execute_command"
                and self._would_write_files(tool_name, params)
            ):
                pass
            else:
                return GuardResult(allowed=True, reason="L1 auto-approved", decision="auto")

        # L2: 默认需要审批（安全默认：除非显式关闭）
        if risk_level == "L2":
            l2_disabled = not self._settings.l2_require_approval if self._settings else False
            if l2_disabled:
                return GuardResult(
                    allowed=True, reason="L2 approval disabled in settings", decision="auto"
                )

        # 代码执行始终需要审批
        if tool_name in ("generate_and_run_sdk_code",):
            code_policy = self._settings.code_execution_require_approval if self._settings else True
            if not code_policy:
                return GuardResult(
                    allowed=True, reason="code execution approval disabled", decision="auto"
                )

        # 需要操作者审批
        if self._owner_callback is None:
            return self._record_rejection(
                tool_name, risk_level, params, "no approval callback configured"
            )

        decision = await self._owner_callback(tool_name, risk_level, params, summary)
        if decision == "Y":
            self._record_approval(tool_name, risk_level, True)
            return GuardResult(allowed=True, reason="operator approved", decision="approved")
        elif decision == "A":
            self._gate.mark_session_approved(tool_name)
            self._record_approval(tool_name, risk_level, True)
            return GuardResult(allowed=True, reason="session approved", decision="session_approved")
        elif decision == "S":
            self._gate.approve_all()
            self._record_approval(tool_name, risk_level, True)
            return GuardResult(
                allowed=True, reason="all session approved", decision="session_all_approved"
            )
        else:
            self._record_approval(tool_name, risk_level, False)
            return GuardResult(allowed=False, reason="operator rejected", decision="rejected")

    @staticmethod
    def _would_write_files(tool_name: str, params: dict) -> bool:
        """检测工具调用是否会写入文件喵~（用于判断 L1 是否需要升级为审批）"""
        if tool_name in ("run_script", "apply_patch"):
            return True
        if tool_name == "execute_command":
            cmd = params.get("command", "")
            # Shell 重定向
            if any(op in cmd for op in (">", ">>", "| tee ")):
                return True
            # 文件创建/修改命令
            _write_cmds = ("cp ", "mv ", "touch ", "mkdir ", "dd of=", "install ", "tee ")
            if any(cmd.startswith(c) or f" {c}" in cmd for c in _write_cmds):
                return True
            # Python 代码中文件写入操作
            if "python" in cmd and ("open(" in cmd or "write_text" in cmd or "write_bytes" in cmd):
                return True
        return False

    def set_session_id(self, session_id: str):
        """更新会话 ID（会话恢复时使用）喵~"""
        self._session_id = session_id

    def _record_approval(self, tool_name: str, risk_level: str, approved: bool):
        """审批记录写入审计 DB 喵~"""
        if self._db and self._session_id:
            try:
                self._db.record_approval(self._session_id, tool_name, risk_level, approved)
            except Exception:
                logger.error("audit_approval_write_failed", exc_info=True)

    def _record_rejection(
        self, tool_name: str, risk_level: str, params: dict, reason: str
    ) -> GuardResult:
        """记录拒绝并返回 GuardResult 喵~"""
        if self._metrics is not None:
            self._metrics.record("safety_rejection")
        logger.info("tool_rejected", tool_name=tool_name, reason=reason)
        self._record_approval(tool_name, risk_level, approved=False)
        return GuardResult(allowed=False, reason=reason, decision="rejected")

    def record_call(
        self,
        tool_name: str,
        risk_level: str,
        params: dict,
        result: dict,
        duration_ms: float = 0,
        task_instruction: str | None = None,
        turn_number: int | None = None,
        prev_call_id: int | None = None,
    ) -> int | None:
        """工具执行后记录到审计 DB，返回 lastrowid 喵~"""
        if self._db and self._session_id:
            try:
                return self._db.record_tool_call(
                    self._session_id,
                    tool_name,
                    risk_level,
                    params if params else {},
                    result if result else {},
                    duration_ms=duration_ms,
                    task_instruction=task_instruction,
                    turn_number=turn_number,
                    prev_call_id=prev_call_id,
                )
            except Exception:
                logger.error("audit_tool_call_write_failed", exc_info=True)
        return None
