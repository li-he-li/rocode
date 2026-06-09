"""应用配置 — Pydantic Settings，.env + 环境变量自动加载喵~"""

from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（3 层: settings.py → config/ → robocode/ → project/）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class ProviderConfig(BaseModel):
    """LLM 提供者配置喵~"""

    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-v4-flash"
    thinking_enabled: bool = True  # 开启模型推理链，先想再动喵~


class BackendEndpoints(BaseModel):
    """后端连接配置喵~"""

    sdk_host: str = "localhost"
    sdk_port: int = 12345


class WorkspaceLimits(BaseModel):
    """机械臂工作空间限制 (mm) 喵~"""

    x_min: float = 200.0
    x_max: float = 550.0
    y_min: float = -200.0
    y_max: float = 200.0
    z_min: float = 50.0
    z_max: float = 300.0
    max_speed_ratio: float = 0.6


class SafetyLimits(BaseModel):
    """安全限值喵~"""

    max_radius_mm: float = 510.0  # 最大工作半径
    max_payload_g: float = 500.0  # 最大负载 (g)
    supply_voltage: float = 12.0  # 电源电压
    supply_current_a: float = 10.0  # 电源电流


class ApprovalPolicy(BaseModel):
    """审批策略配置喵~"""

    l2_require_approval: bool = True  # L2 操作需审批
    file_write_require_approval: bool = True  # 文件写入需审批
    script_launch_require_approval: bool = True  # 脚本启动需审批
    code_execution_require_approval: bool = True  # 代码执行需审批


class Settings(BaseSettings):
    """应用总设置 — 从 ROBOCODE_ 前缀环境变量 + .env 文件加载喵~"""

    model_config = SettingsConfigDict(
        env_prefix="ROBOCODE_",
        env_nested_delimiter="__",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: ProviderConfig = ProviderConfig()
    backend: BackendEndpoints = BackendEndpoints()
    workspace: WorkspaceLimits = WorkspaceLimits()
    safety: SafetyLimits = SafetyLimits()
    approval: ApprovalPolicy = ApprovalPolicy()

    active_backend: str = "sdk"
    timeout_action_s: float = 30.0  # 动作超时 (s)
    timeout_code_exec_s: float = 60.0  # 代码执行超时 (s)
    max_react_iterations: int = 20  # Agent 最大迭代次数
