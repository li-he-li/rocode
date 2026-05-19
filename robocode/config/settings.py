from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root (3 levels up: settings.py → config/ → robocode/ → project/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class ProviderConfig(BaseModel):
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-v4-flash"
    thinking_enabled: bool = False


class BackendEndpoints(BaseModel):
    sdk_host: str = "localhost"
    sdk_port: int = 12345


class WorkspaceLimits(BaseModel):
    x_min: float = 200.0
    x_max: float = 550.0
    y_min: float = -200.0
    y_max: float = 200.0
    z_min: float = 50.0
    z_max: float = 300.0
    max_speed_ratio: float = 0.6


class SafetyLimits(BaseModel):
    max_radius_mm: float = 510.0
    max_payload_g: float = 500.0
    supply_voltage: float = 12.0
    supply_current_a: float = 10.0


class ApprovalPolicy(BaseModel):
    l2_require_approval: bool = True
    file_write_require_approval: bool = True
    script_launch_require_approval: bool = True
    code_execution_require_approval: bool = True


class Settings(BaseSettings):
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
    timeout_action_s: float = 30.0
    timeout_code_exec_s: float = 60.0
    max_react_iterations: int = 20
