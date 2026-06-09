"""审批门控 — L2/文件写/脚本执行需操作者确认喵~"""

from dataclasses import dataclass
from enum import Enum
from robocode.services.analytics.logger import get_logger

logger = get_logger("approval")


class ApprovalAction(str, Enum):
    """审批动作类型喵~"""

    APPROVE = "approve"  # 批准本次
    REJECT = "reject"  # 拒绝
    APPROVE_ONCE = "approve_once"  # 本次免审批


@dataclass
class ApprovalRequest:
    """审批请求 — 包含工具信息和参数喵~"""

    tool_name: str
    risk_level: str
    params: dict
    summary: str
    details: dict | None = None

    def format_prompt(self) -> str:
        """生成 CLI 审批提示面板喵~"""
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
    """审批门 — 管理会话级自动审批状态喵~

    规则：
    - L0: 始终自动放行
    - 全免审批模式: 所有工具自动放行
    - 工具级免审批: 特定工具在本会话内自动放行
    """

    def __init__(self):
        self._session_approved: set[str] = set()  # 本会话已免审批的工具名集合
        self._all_approved: bool = False  # 是否开启了全免审批模式

    def request(
        self, tool_name: str, risk_level: str, params: dict, summary: str = ""
    ) -> ApprovalRequest:
        """创建审批请求喵~"""
        return ApprovalRequest(
            tool_name=tool_name,
            risk_level=risk_level,
            params=params,
            summary=summary,
        )

    def is_auto_approved(self, tool_name: str, risk_level: str) -> bool:
        """判断工具是否可自动放行喵~"""
        if risk_level == "L0":
            return True
        if self._all_approved:
            return True
        return tool_name in self._session_approved

    def mark_session_approved(self, tool_name: str):
        """将某工具加入本会话免审批名单喵~"""
        self._session_approved.add(tool_name)

    def approve_all(self):
        """开启全免审批模式喵~"""
        self._all_approved = True

    def should_prompt(self, risk_level: str) -> bool:
        """是否需要弹出审批提示喵~"""
        return risk_level == "L2"
