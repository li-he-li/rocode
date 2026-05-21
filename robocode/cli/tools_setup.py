"""工具注册 + handler map 构建 —— 从 app.py 拆分出来，减少主文件臃肿喵~"""

from robocode.tools.registry import ToolEntry, SkillEntry, ToolRegistry
from robocode.tools.script_tools import SCRIPT_INVENTORY
from robocode.tools.motion_tools import make_motion_tools
from robocode.tools.gripper_tools import make_gripper_tools
from robocode.tools.script_tools import make_script_tools
from robocode.tools.codegen_tools import make_codegen_tools
from robocode.tools.exec_tools import make_exec_tools
from robocode.tools.code_tools import make_code_tools
from robocode.tools.patch_tools import make_patch_tools
from robocode.tools.wrapper_tools import make_wrapper_tools


def register_all_tools(app) -> None:
    """注册所有工具到 app.registry + skills 到 app.slash。设置 app._skills。"""
    registry: ToolRegistry = app.registry

    entries = [
        ToolEntry(
            name="get_robot_status",
            description="获取机械臂当前状态：关节角度、末端位姿、急停状态",
            parameters={"type": "object", "properties": {}},
            risk_level="L0",
        ),
        ToolEntry(
            name="move_robot_home",
            description="机械臂回到安全零位 [260, 0, 200]",
            parameters={"type": "object", "properties": {}},
            risk_level="L1",
        ),
        ToolEntry(
            name="move_robot_xyz",
            description="移动机械臂末端到指定笛卡尔坐标 (mm)",
            parameters={
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                    "speed_ratio": {"type": "number"},
                },
                "required": ["x", "y", "z"],
            },
            risk_level="L2",
        ),
        ToolEntry(
            name="move_path",
            description="沿连续路径运动：一次传入多个 [x,y,z] 路点，内部用直线插值依次执行，消除多步调用间的停顿。用于画圆、弧线等平滑轨迹",
            parameters={
                "type": "object",
                "properties": {
                    "waypoints": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "minItems": 1,
                        "maxItems": 200,
                    },
                    "speed_ratio": {"type": "number"},
                    "rotation": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["waypoints"],
            },
            risk_level="L2",
        ),
        ToolEntry(
            name="move_robot_joints",
            description="移动机械臂各关节到指定角度 (度)",
            parameters={
                "type": "object",
                "properties": {"angles": {"type": "array"}, "speed_ratio": {"type": "number"}},
                "required": ["angles"],
            },
            risk_level="L2",
        ),
        ToolEntry(
            name="emergency_stop",
            description="立即急停（仅 enable=true）。解除急停请用 release_emergency_stop",
            parameters={"type": "object", "properties": {}},
            risk_level="L0",
        ),
        ToolEntry(
            name="release_emergency_stop",
            description="解除急停，恢复机械臂运动能力",
            parameters={"type": "object", "properties": {}},
            risk_level="L2",
        ),
        ToolEntry(
            name="control_suction",
            description="吸盘夹爪开/关",
            parameters={
                "type": "object",
                "properties": {"action": {"type": "string", "enum": ["on", "off"]}},
                "required": ["action"],
            },
            risk_level="L2",
        ),
        ToolEntry(
            name="servo_gripper_control",
            description="舵机夹爪角度控制 (0-110)",
            parameters={
                "type": "object",
                "properties": {"angle": {"type": "integer"}},
                "required": ["angle"],
            },
            risk_level="L2",
        ),
        ToolEntry(
            name="check_calibration_status",
            description="读取标定文件状态",
            parameters={"type": "object", "properties": {"calib_type": {"type": "string"}}},
            risk_level="L0",
        ),
        ToolEntry(
            name="run_script",
            description="启动标定/检测等脚本（需操作者确认）",
            parameters={
                "type": "object",
                "properties": {"script_name": {"type": "string"}},
                "required": ["script_name"],
            },
            risk_level="L1",
        ),
        ToolEntry(
            name="generate_and_run_sdk_code",
            description="【逃生舱】生成并执行 SDK 代码实现自定义动作",
            parameters={
                "type": "object",
                "properties": {"code": {"type": "string"}, "summary": {"type": "string"}},
                "required": ["code"],
            },
            risk_level="L2",
        ),
        ToolEntry(
            name="list_skills",
            description="列出所有可用技能（标定/检测/抓取/应用脚本），包括名称、类别、是否需要人工操作",
            parameters={"type": "object", "properties": {}},
            risk_level="L0",
        ),
        ToolEntry(
            name="execute_command",
            description="【L2 需审批】在主机上执行单条命令（不支持管道|重定向|链式;）。危险命令硬拦截。复杂 shell 操作请用 generate_and_run_sdk_code。",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "timeout_s": {"type": "number", "description": "超时秒数，默认30"},
                },
                "required": ["command"],
            },
            risk_level="L2",
        ),
        ToolEntry(
            name="read_file",
            description="【代码检查】在允许的工作空间内读取文件内容。拒绝二进制文件和超过 1MB 的文件。替代 execute_command cat。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径，相对于项目根目录"}
                },
                "required": ["path"],
            },
            risk_level="L0",
        ),
        ToolEntry(
            name="search_code",
            description="【代码检查】在工作空间内搜索代码模式（正则表达式）。返回 文件:行号:内容。替代 execute_command grep。",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "搜索模式（正则表达式）"},
                    "path": {
                        "type": "string",
                        "description": "搜索路径，相对于项目根目录，默认 robocode/",
                    },
                },
                "required": ["pattern"],
            },
            risk_level="L0",
        ),
        ToolEntry(
            name="apply_patch",
            description="【代码编辑】在允许的工作空间内应用 unified diff 补丁。拒绝受保护文件（安全策略/后端/审批/急停）。修改前需操作者审批。",
            parameters={
                "type": "object",
                "properties": {
                    "patch_text": {"type": "string", "description": "unified diff 格式补丁"},
                    "target_file": {"type": "string", "description": "目标文件路径"},
                },
                "required": ["patch_text", "target_file"],
            },
            risk_level="L1",
        ),
        ToolEntry(
            name="generate_diff_summary",
            description="【代码检查】解析 unified diff 补丁，返回变更摘要（路径、修改块数、增删行数）。只读。",
            parameters={
                "type": "object",
                "properties": {
                    "patch_text": {"type": "string", "description": "unified diff 格式补丁"}
                },
                "required": ["patch_text"],
            },
            risk_level="L0",
        ),
        ToolEntry(
            name="run_checks",
            description="【代码检查】对指定 Python 文件运行语法检查和导入检查。报告错误，绝不安装依赖。",
            parameters={
                "type": "object",
                "properties": {"file_path": {"type": "string", "description": "要检查的文件路径"}},
                "required": ["file_path"],
            },
            risk_level="L0",
        ),
        ToolEntry(
            name="generate_wrapper_template",
            description="【工具创作】生成 SDK 或 ROS2 工具 wrapper 模板代码。需提供工具名、描述、SDK 方法列表或 ROS2 action。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "工具名（Python 标识符）"},
                    "description": {"type": "string"},
                    "sdk_methods": {"type": "array", "items": {"type": "string"}},
                    "ros2_actions": {"type": "array", "items": {"type": "string"}},
                    "risk_level": {"type": "string", "enum": ["L0", "L1", "L2"]},
                    "backend": {"type": "string", "enum": ["sdk", "ros2"]},
                },
                "required": ["name", "description"],
            },
            risk_level="L0",
        ),
        ToolEntry(
            name="generate_wrapper_metadata",
            description="【工具创作】生成 wrapper 元数据（name/description/schema/risk/timeout/backend/dry_run）。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "risk_level": {"type": "string"},
                    "timeout_s": {"type": "number"},
                    "backend": {"type": "string"},
                    "parameters": {"type": "object"},
                },
                "required": ["name", "description"],
            },
            risk_level="L0",
        ),
        ToolEntry(
            name="register_wrapper",
            description="【工具创作】注册 wrapper 为永久工具。dry_run=True 仅验证不注册（默认），dry_run=False 正式注册。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "risk_level": {"type": "string", "enum": ["L0", "L1", "L2"]},
                    "timeout_s": {"type": "number"},
                    "backend": {"type": "string", "enum": ["sdk", "ros2"]},
                    "parameters": {"type": "object"},
                    "dry_run": {"type": "boolean"},
                },
                "required": ["name", "description"],
            },
            risk_level="L1",
        ),
    ]
    for entry in entries:
        registry.register(entry)

    # Register skills from script inventory
    for script in SCRIPT_INVENTORY:
        try:
            registry.register(
                SkillEntry(
                    name=script["name"],
                    description=script["description"],
                    parameters={"type": "object", "properties": {}},
                    script_path=script["path"],
                    requires_human=script["requires_human"],
                    output_files=script["output_files"],
                    category=script.get("category", ""),
                    risk_level="L1" if script["requires_human"] else "L0",
                )
            )
        except ValueError:
            pass

    # Register skills from robocode/skills/ folder (auto-discovered)
    from robocode.cli.skill_loader import load_skills

    skills = load_skills()
    _SKILL_PARAMS = {
        "6d_grasp": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": '自然语言抓取指令，如"抓取桌上的海绵块"',
                }
            },
            "required": ["instruction"],
        },
    }
    for skill in skills.values():
        try:
            params = _SKILL_PARAMS.get(skill.name, {"type": "object", "properties": {}})
            registry.register(
                SkillEntry(
                    name=skill.name,
                    description=skill.description,
                    parameters=params,
                    script_path=skill.script,
                    requires_human=skill.requires_human,
                    output_files=skill.output_files,
                    category=skill.category,
                    risk_level=skill.risk_level,
                )
            )
        except ValueError:
            pass
        app.slash.register_skill(skill)

    app._skills = skills


def build_handler_map(app) -> dict:
    """构建工具名 → handler 函数映射。复用各 tools/ 模块的 make_* 工厂函数。"""
    handlers = {"list_skills": _make_list_skills_handler(app.registry)}

    handlers.update(make_motion_tools(app.backend, app.safety))
    handlers.update(make_gripper_tools(app.backend, app.safety))
    handlers.update(make_script_tools())
    handlers.update(make_codegen_tools(session_id=app._session_id))
    handlers.update(make_exec_tools())
    handlers.update(make_code_tools())
    handlers.update(make_patch_tools())
    handlers.update(make_wrapper_tools(registry=app.registry))

    return handlers


def _make_list_skills_handler(registry):
    def list_skills(**kwargs):
        skills = registry.list_skills()
        return {
            "success": True,
            "message": f"共 {len(skills)} 个技能可用",
            "metrics": {
                "count": len(skills),
                "skills": [
                    {
                        "name": s.name,
                        "category": s.category,
                        "description": s.description,
                        "requires_human": s.requires_human,
                        "script_path": s.script_path,
                    }
                    for s in skills
                ],
            },
        }

    return list_skills
