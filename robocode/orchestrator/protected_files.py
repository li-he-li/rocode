"""受保护文件注册表 — Phase 2 代码演化 agent 不能静默修改这些文件喵~

规则: apply_patch 在修改这些文件前必须取得操作者显式审批。
"""

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

PROTECTED_FILES: list[str] = [
    # 安全策略 — 工作空间限制、硬件约束、关节限位
    "robocode/config/settings.py",
    "robocode/orchestrator/safety.py",
    # 后端适配器 — 硬件分发路径
    "robocode/backends/base.py",
    "robocode/backends/sdk_backend.py",
    # 审批门控 — L2 强制执行、会话自动审批
    "robocode/orchestrator/approval.py",
    "robocode/orchestrator/tool_guard.py",
    "robocode/orchestrator/protected_files.py",
    # 急停 — 本地直发命令，绕过 LLM
    "robocode/cli/slash.py",  # /estop 处理
    "robocode/cli/app.py",  # _trigger_estop, esc 监听
    # Agent 核心 — 工具执行循环、系统 prompt、风险门控集成
    "robocode/agent/core.py",
    "robocode/agent/context.py",
    # 经验系统 — prompt 注入、经验生成
    "robocode/agent/experience_manager.py",
    "robocode/agent/experience_reader.py",
    "robocode/agent/experience_filesystem.py",
    "robocode/agent/physics_collector.py",
    "robocode/agent/annotation.py",
    # 工具注册 — 注册、风险级别、schema
    "robocode/tools/registry.py",
    # 硬件操作工具 — 直接控制机器人
    "robocode/tools/motion_tools.py",
    "robocode/tools/gripper_tools.py",
    "robocode/tools/script_tools.py",
    # 代码沙箱 — 禁止模式、隔离
    "robocode/tools/codegen_tools.py",
    "robocode/tools/exec_tools.py",
    # 审计 DB — schema、聚合查询
    "robocode/services/analytics/db.py",
]

# 解析后的绝对路径集合，用于快速匹配
PROTECTED_PATHS: set[str] = {str((_PROJECT_ROOT / p).resolve()) for p in PROTECTED_FILES}


def is_protected(file_path: str | Path) -> bool:
    """检查文件路径是否匹配受保护列表中的文件喵~"""
    resolved = str(Path(file_path).resolve())
    return resolved in PROTECTED_PATHS


def list_protected() -> list[str]:
    """列出所有受保护文件路径（相对于项目根目录）喵~"""
    return list(PROTECTED_FILES)
