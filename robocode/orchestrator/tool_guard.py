"""ToolGuard — bridges ApprovalGate + AuditDB + SafetyPolicy + Settings.approval.* into tool execution."""

from dataclasses import dataclass
from typing import Awaitable, Callable

from robocode.services.analytics.logger import get_logger

logger = get_logger("tool_guard")


@dataclass
class GuardResult:
    allowed: bool
    reason: str = ""
    decision: str = ""  # "auto" | "approved" | "rejected" | "session_approved"


ApprovalCallback = Callable[[str, str, dict, str], Awaitable[str]]
# callback(tool_name, risk_level, params, summary) -> "Y" | "N" | "A"


class ToolGuard:
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
        self._owner_callback = owner_callback
        self._session_id = session_id
        self._metrics = metrics

    async def check(
        self, tool_name: str, risk_level: str, params: dict, summary: str = ""
    ) -> GuardResult:
        # L0 always auto-approved
        if risk_level == "L0":
            return GuardResult(allowed=True, reason="L0 auto-approved", decision="auto")

        # Check session auto-approval
        if self._gate.is_auto_approved(tool_name, risk_level):
            return GuardResult(
                allowed=True, reason="session auto-approved", decision="session_approved"
            )

        # L1: auto-approve unless policy says otherwise
        if risk_level == "L1":
            file_write_policy = (
                self._settings.file_write_require_approval if self._settings else False
            )
            script_policy = (
                self._settings.script_launch_require_approval if self._settings else False
            )
            if file_write_policy and self._would_write_files(tool_name, params):
                pass  # fall through to approval
            elif script_policy and tool_name == "run_script":
                pass  # fall through to approval
            elif (
                script_policy
                and tool_name == "execute_command"
                and self._would_write_files(tool_name, params)
            ):
                pass  # fall through to approval
            else:
                return GuardResult(allowed=True, reason="L1 auto-approved", decision="auto")

        # L2: require approval (default safe: require unless explicitly disabled)
        if risk_level == "L2":
            l2_disabled = not self._settings.l2_require_approval if self._settings else False
            if l2_disabled:
                return GuardResult(
                    allowed=True, reason="L2 approval disabled in settings", decision="auto"
                )

        # Code execution always requires approval
        if tool_name in ("generate_and_run_sdk_code",):
            code_policy = self._settings.code_execution_require_approval if self._settings else True
            if not code_policy:
                return GuardResult(
                    allowed=True, reason="code execution approval disabled", decision="auto"
                )

        # Need owner approval
        if self._owner_callback is None:
            return self._record_and_return(
                tool_name, risk_level, params, "rejected", "no approval callback configured"
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
        if tool_name in ("run_script", "apply_patch"):
            return True
        if tool_name == "execute_command":
            cmd = params.get("command", "")
            # Shell redirects
            if any(op in cmd for op in (">", ">>", "| tee ")):
                return True
            # File creation/modification commands
            _write_cmds = ("cp ", "mv ", "touch ", "mkdir ", "dd of=", "install ", "tee ")
            if any(cmd.startswith(c) or f" {c}" in cmd for c in _write_cmds):
                return True
            # Python code writing files
            if "python" in cmd and ("open(" in cmd or "write_text" in cmd or "write_bytes" in cmd):
                return True
        return False

    def set_session_id(self, session_id: str):
        self._session_id = session_id

    def _record_approval(self, tool_name: str, risk_level: str, approved: bool):
        if self._db and self._session_id:
            try:
                self._db.record_approval(self._session_id, tool_name, risk_level, approved)
            except Exception:
                logger.error("audit_approval_write_failed", exc_info=True)

    def _record_and_return(
        self, tool_name: str, risk_level: str, params: dict, decision: str, reason: str
    ) -> GuardResult:
        if self._metrics is not None:
            self._metrics.record("safety_rejection")
        logger.info("tool_rejected", tool_name=tool_name, reason=reason)
        self._record_approval(tool_name, risk_level, decision != "rejected")
        return GuardResult(allowed=False, reason=reason, decision=decision)

    def record_call(
        self, tool_name: str, risk_level: str, params: dict, result: dict, duration_ms: float = 0
    ):
        """Record tool call to audit DB after execution."""
        if self._db and self._session_id:
            try:
                self._db.record_tool_call(
                    self._session_id,
                    tool_name,
                    risk_level,
                    params if params else {},
                    result if result else {},
                    duration_ms=duration_ms,
                )
            except Exception:
                logger.error("audit_tool_call_write_failed", exc_info=True)
