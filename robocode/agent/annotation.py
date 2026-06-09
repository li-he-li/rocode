"""标注系统 — 每会话一个自由文本反馈，应用于所有待标注的工具调用喵~"""

from dataclasses import dataclass, field
from robocode.services.analytics.logger import get_logger

logger = get_logger("annotation")

# 工具名 → 类别映射，用于分类统计
TOOL_CATEGORIES = {
    "move_robot_xyz": "motion",
    "move_robot_joints": "motion",
    "move_robot_home": "motion",
    "move_path": "motion",
    "control_suction": "gripper",
    "servo_gripper_control": "gripper",
    "6d_grasp": "grasp",
    "generate_and_run_sdk_code": "code",
    "execute_command": "code",
    "run_script": "script",
}


@dataclass
class AnnotationResult:
    """标注结果 — 单个工具调用的标注记录喵~"""

    tool_call_id: int  # 工具调用 ID
    tool_name: str  # 工具名
    category: str  # 类别（motion/gripper/grasp/code/script）
    choices: dict = field(default_factory=dict)  # 多维选择
    is_failure: bool = False  # 是否标为失败
    free_text: str = ""  # 自由文本反馈

    def to_dict(self) -> dict:
        return {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "category": self.category,
            "choices": self.choices,
            "is_failure": self.is_failure,
            "free_text": self.free_text,
        }


class AnnotationCollector:
    """收集待标注的工具调用并持久化到 DB 喵~"""

    def __init__(self, db, session_id: str = ""):
        self._db = db
        self._session_id = session_id
        self._pending: dict[int, dict] = {}  # tool_call_id → {tool_name, params}

    def register_tool_call(self, tool_call_id: int, tool_name: str, params: dict):
        """注册一个工具调用为待标注状态喵~"""
        if tool_call_id and tool_call_id > 0:
            self._pending[tool_call_id] = {
                "tool_name": tool_name,
                "params": params,
            }

    def get_pending(self) -> list[dict]:
        """获取所有待标注的工具调用列表喵~"""
        return [{"tool_call_id": tid, **info} for tid, info in self._pending.items()]

    def count_unannotated(self) -> int:
        """未标注数量喵~"""
        return len(self._pending)

    def get_category(self, tool_name: str) -> str:
        """获取工具类别喵~"""
        return TOOL_CATEGORIES.get(tool_name, "general")

    def collect(
        self,
        tool_call_id: int,
        category: str,
        choices: dict,
        is_failure: bool,
        free_text: str = "",
    ) -> "AnnotationResult | None":
        """收集标注并写入 DB，完成后从 pending 移除喵~"""
        if tool_call_id not in self._pending:
            return None

        result = AnnotationResult(
            tool_call_id=tool_call_id,
            tool_name=self._pending[tool_call_id]["tool_name"],
            category=category,
            choices=choices,
            is_failure=is_failure,
            free_text=free_text,
        )

        if self._db and self._session_id:
            try:
                self._db.insert_annotation(
                    tool_call_id=tool_call_id,
                    session_id=self._session_id,
                    category=category,
                    choices=choices,
                    is_failure=is_failure,
                    free_text=free_text,
                )
            except Exception:
                logger.exception("annotation_db_write_failed")

        self._pending.pop(tool_call_id, None)
        return result

    def skip(self, tool_call_id: int):
        """跳过某个待标注项喵~"""
        self._pending.pop(tool_call_id, None)
