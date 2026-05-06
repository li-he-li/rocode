"""Tool authoring — wrapper template generation, metadata, registration gate.

Phase 2 core: agent discovers missing capability → generates SDK/ROS2-backed wrapper →
fake backend validation → registration as permanent callable tool.
"""

import json
from pathlib import Path

from robocode.utils.models import ToolResult
from robocode.tools.registry import ToolEntry, ToolRegistry

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_REGISTRY: ToolRegistry | None = None


SDK_WRAPPER_TEMPLATE = '''"""Auto-generated tool: {name} — {description}"""
from robocode.backends.base import RobotBackend
from robocode.orchestrator.safety import SafetyPolicy
from robocode.utils.models import ToolResult


def {name}({params_signature}):
    {params_doc}
{safety_block}
    # Backend call
{backend_calls}
    return ToolResult(
        success=True,
        message="{success_message}",
        metrics={{}},
    ).model_dump(mode="json")
'''

ROS2_WRAPPER_TEMPLATE = '''"""Auto-generated ROS2 tool: {name} — {description}"""
from robocode.backends.base import RobotBackend
from robocode.utils.models import ToolResult


def {name}({params_signature}):
    """ROS2-backed tool. Requires ROS2 node to be running."""
    # ROS2 action/service calls
{ros2_calls}
    return ToolResult(
        success=True,
        message="{success_message}",
        metrics={{"backend": "ros2"}},
    ).model_dump(mode="json")
'''


def generate_wrapper_template(
    *,
    name: str,
    description: str,
    sdk_methods: list[str] | None = None,
    ros2_actions: list[str] | None = None,
    risk_level: str = "L1",
    params: dict[str, str] | None = None,
    backend: str = "sdk",
    **kwargs,
) -> dict:
    """Generate a wrapper function template for SDK or ROS2 backend."""
    if not name or not name.isidentifier():
        return ToolResult(
            success=False,
            message=f"无效的工具名: {name}（必须是合法的 Python 标识符）",
        ).model_dump(mode="json")

    if backend == "ros2" and ros2_actions:
        params_dict = params or {}
        if params_dict:
            params_sig = "*, " + ", ".join(f"{k}=None" for k in sorted(params_dict.keys()))
        else:
            params_sig = "**kwargs"
        ros2_calls_lines = []
        for action in ros2_actions or []:
            ros2_calls_lines.append(f"    # TODO: call ROS2 action/service: {action}")
            ros2_calls_lines.append(f"    # result = ros2_node.call_action({action!r})")
        ros2_calls = "\n".join(ros2_calls_lines) if ros2_calls_lines else "    pass"
        code = ROS2_WRAPPER_TEMPLATE.format(
            name=name,
            description=description,
            params_signature=params_sig,
            ros2_calls=ros2_calls,
            success_message=description,
        )
    else:
        params_dict = params or {}
        if params_dict:
            params_sig = "*, " + ", ".join(f"{k}=None" for k in sorted(params_dict.keys()))
            params_doc = f'"""Params: {json.dumps(params_dict)}"""'
        else:
            params_sig = "**kwargs"
            params_doc = '"""No required params."""'

        sdk_methods = sdk_methods or []
        backend_calls_lines = []
        for method in sdk_methods:
            method_name = method.split("(")[0].strip()
            backend_calls_lines.append(f"    backend.{method_name}(...)  # {method}")
        if not backend_calls_lines:
            backend_calls_lines.append("    pass  # TODO: implement SDK calls")

        if risk_level == "L2":
            safety_block = "    # TODO: add safety checks (workspace, joint limits, payload)\n"
        elif risk_level == "L1":
            safety_block = "    # L1: logged action\n"
        else:
            safety_block = ""

        code = SDK_WRAPPER_TEMPLATE.format(
            name=name,
            description=description,
            params_signature=params_sig,
            params_doc=params_doc,
            safety_block=safety_block,
            backend_calls="\n".join(backend_calls_lines),
            success_message=description,
        )

    return ToolResult(
        success=True,
        message=f"Wrapper 模板已生成: {name}",
        metrics={
            "name": name,
            "backend": backend,
            "risk_level": risk_level,
            "sdk_methods": sdk_methods or [],
            "ros2_actions": ros2_actions or [],
        },
        artifacts={"code": code},
    ).model_dump(mode="json")


REQUIRED_METADATA_FIELDS = [
    "name",
    "description",
    "risk_level",
    "timeout_s",
    "backend",
    "parameters",
]
VALID_RISK_LEVELS = {"L0", "L1", "L2"}
VALID_BACKENDS = {"sdk", "ros2", "fake"}


def generate_wrapper_metadata(
    *,
    name: str,
    description: str,
    risk_level: str = "L1",
    timeout_s: float = 30.0,
    backend: str = "sdk",
    parameters: dict | None = None,
    dry_run: bool = False,
    **kwargs,
) -> dict:
    """Generate wrapper metadata dict in Phase-1 tool registry format."""
    return {
        "name": name,
        "description": description,
        "risk_level": risk_level,
        "timeout_s": timeout_s,
        "backend": backend,
        "parameters": parameters or {"type": "object", "properties": {}},
        "dry_run": dry_run,
    }


def validate_wrapper_metadata(metadata: dict) -> dict:
    """Validate wrapper metadata against Phase-1 registry requirements."""
    errors = []
    warnings = []

    for field in REQUIRED_METADATA_FIELDS:
        if field not in metadata or not metadata[field]:
            errors.append(f"缺少必填字段: {field}")

    risk = metadata.get("risk_level", "")
    if risk and risk not in VALID_RISK_LEVELS:
        errors.append(f"无效的风险级别: {risk}（应为 L0/L1/L2）")

    backend = metadata.get("backend", "")
    if backend and backend not in VALID_BACKENDS:
        errors.append(f"无效的后端: {backend}（应为 sdk/ros2/fake）")

    name = metadata.get("name", "")
    if name and not str(name).isidentifier():
        errors.append(f"无效的工具名: {name}（必须是合法的 Python 标识符）")

    timeout = metadata.get("timeout_s", 0)
    if isinstance(timeout, (int, float)) and timeout <= 0:
        errors.append("timeout_s 必须 > 0")

    if not metadata.get("dry_run"):
        warnings.append("建议先通过 dry-run 验证后再注册（设置 dry_run=True）")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def register_wrapper(
    *,
    name: str,
    description: str,
    handler_import_path: str = "",
    risk_level: str = "L1",
    timeout_s: float = 30.0,
    backend: str = "sdk",
    parameters: dict | None = None,
    dry_run: bool = True,
    **kwargs,
) -> dict:
    """Register a wrapper as a permanent callable tool in the registry.

    Validates metadata, then creates and registers a ToolEntry.
    Set dry_run=True (default) to validate without registering.
    """
    if _REGISTRY is None:
        return ToolResult(
            success=False,
            message="Registry 未初始化，无法注册工具",
        ).model_dump(mode="json")

    meta = generate_wrapper_metadata(
        name=name,
        description=description,
        risk_level=risk_level,
        timeout_s=timeout_s,
        backend=backend,
        parameters=parameters,
        dry_run=dry_run,
    )

    validation = validate_wrapper_metadata(meta)
    if not validation["valid"]:
        return ToolResult(
            success=False,
            message=f"Wrapper 元数据验证失败: {'; '.join(validation['errors'])}",
            metrics={"errors": validation["errors"], "warnings": validation["warnings"]},
        ).model_dump(mode="json")

    if dry_run:
        return ToolResult(
            success=True,
            message=f"[dry-run] Wrapper 验证通过: {name} (risk={risk_level}, backend={backend})",
            metrics={"name": name, "risk_level": risk_level, "backend": backend, "dry_run": True},
        ).model_dump(mode="json")

    try:
        entry = ToolEntry(
            name=meta["name"],
            description=meta["description"],
            parameters=meta["parameters"],
            risk_level=meta["risk_level"],
            timeout_s=meta["timeout_s"],
            backend=meta["backend"],
        )
        _REGISTRY.register(entry)
    except ValueError as e:
        return ToolResult(
            success=False,
            message=f"注册失败（可能重名）: {e}",
        ).model_dump(mode="json")

    return ToolResult(
        success=True,
        message=f"Wrapper 已注册: {name} (risk={meta['risk_level']}, backend={meta['backend']})",
        metrics={
            "name": meta["name"],
            "risk_level": meta["risk_level"],
            "backend": meta["backend"],
            "dry_run": False,
        },
    ).model_dump(mode="json")


def make_wrapper_tools(registry: ToolRegistry | None = None) -> dict:
    global _REGISTRY
    if registry is not None:
        _REGISTRY = registry
    return {
        "generate_wrapper_template": generate_wrapper_template,
        "generate_wrapper_metadata": generate_wrapper_metadata,
        "register_wrapper": register_wrapper,
    }
