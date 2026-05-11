"""Approval gate — L2 / file-write / script-execution require operator confirm."""

from dataclasses import dataclass
from enum import Enum
from robocode.services.analytics.logger import get_logger

logger = get_logger("approval")


class ApprovalAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    APPROVE_ONCE = "approve_once"


@dataclass
class ApprovalRequest:
    tool_name: str
    risk_level: str
    params: dict
    summary: str
    details: dict | None = None

    def format_prompt(self) -> str:
        lines = [
            f"[approval needed] {self.risk_level} 动作待确认",
            "",
            f"  工具: {self.tool_name}",
        ]
        for key, val in self.params.items():
            lines.append(f"  {key}: {val}")
        if self.summary:
            lines.append(f"  摘要: {self.summary}")
        if self.details:
            for key, val in self.details.items():
                lines.append(f"  {key}: {val}")
        lines.append("")
        lines.append("  [Y] 批准本次   [N] 拒绝   [A] 本工具此后免审批   [S] 全部免审批")
        return "\n".join(lines)


class ApprovalGate:
    def __init__(self):
        self._session_approved: set[str] = set()
        self._all_approved: bool = False

    def request(
        self, tool_name: str, risk_level: str, params: dict, summary: str = ""
    ) -> ApprovalRequest:
        return ApprovalRequest(
            tool_name=tool_name,
            risk_level=risk_level,
            params=params,
            summary=summary,
        )

    def is_auto_approved(self, tool_name: str, risk_level: str) -> bool:
        if risk_level == "L0":
            return True
        if self._all_approved:
            return True
        return tool_name in self._session_approved

    def mark_session_approved(self, tool_name: str):
        self._session_approved.add(tool_name)

    def approve_all(self):
        self._all_approved = True

    def should_prompt(self, risk_level: str) -> bool:
        return risk_level == "L2"
