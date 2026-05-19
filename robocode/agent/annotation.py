"""Annotation system — human feedback on tool execution quality."""

from dataclasses import dataclass, field
from robocode.services.analytics.logger import get_logger

logger = get_logger("annotation")

# ── Tool → category mapping ──────────────────────────────────────────

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

# ── Annotation dimensions per category ────────────────────────────────

ANNOTATION_SCHEMA = {
    "motion": {
        "motion_quality": ["平稳", "轻微振动", "严重振动", "异常噪音"],
        "position_accuracy": ["准确", "轻微偏差", "明显偏差"],
    },
    "gripper": {
        "grasp_result": ["成功", "未抓取", "抓空", "物体掉落"],
        "gripper_force": ["合适", "过大", "过小"],
    },
    "grasp": {
        "grasp_result": ["成功", "失败", "未命中", "碰撞"],
        "overall": ["成功", "失败"],
    },
    "code": {
        "correctness": ["正确", "有偏差", "错误"],
        "side_effects": ["无异常", "有异常", "有副作用"],
    },
    "script": {
        "execution_result": ["成功", "部分成功", "失败"],
        "anomaly": ["无", "有异常"],
    },
    "general": {
        "result": ["成功", "失败"],
    },
}

# ── Failure detection rules ───────────────────────────────────────────

_FAILURE_INDICATORS = {
    "motion": ["严重振动", "异常噪音", "明显偏差"],
    "gripper": ["未抓取", "抓空", "物体掉落", "过小"],
    "grasp": ["失败", "未命中", "碰撞"],
    "code": ["错误", "有副作用"],
    "script": ["失败", "有异常"],
}


class FailureRules:
    """Detects failure based on annotation choices."""

    @staticmethod
    def is_failure(category: str, choices: dict) -> bool:
        indicators = _FAILURE_INDICATORS.get(category, [])
        return any(choices.get(dim, "") in indicators for dim, value in choices.items())


FAILURE_RULES = FailureRules()

# ── Annotation result ─────────────────────────────────────────────────


@dataclass
class AnnotationResult:
    tool_call_id: int
    tool_name: str
    category: str
    choices: dict = field(default_factory=dict)
    is_failure: bool = False
    free_text: str = ""

    def to_dict(self) -> dict:
        return {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "category": self.category,
            "choices": self.choices,
            "is_failure": self.is_failure,
            "free_text": self.free_text,
        }


# ── Annotation collector ──────────────────────────────────────────────


class AnnotationCollector:
    """Collects pending annotations and persists them to DB."""

    def __init__(self, db, session_id: str = ""):
        self._db = db
        self._session_id = session_id
        self._pending: dict[int, dict] = {}  # tool_call_id → {tool_name, params}

    def register_tool_call(self, tool_call_id: int, tool_name: str, params: dict):
        if tool_call_id and tool_call_id > 0:
            self._pending[tool_call_id] = {
                "tool_name": tool_name,
                "params": params,
            }

    def get_pending(self) -> list[dict]:
        return [{"tool_call_id": tid, **info} for tid, info in self._pending.items()]

    def count_unannotated(self) -> int:
        return len(self._pending)

    def get_category(self, tool_name: str) -> str:
        return TOOL_CATEGORIES.get(tool_name, "general")

    def collect(
        self,
        tool_call_id: int,
        category: str,
        choices: dict,
        is_failure: bool,
        free_text: str = "",
    ) -> AnnotationResult | None:
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

        logger.info(
            "annotation_completed",
            tool_count=1,
            annotated_count=1 if result else 0,
            failure_count=1 if is_failure else 0,
        )
        return result

    def skip(self, tool_call_id: int):
        self._pending.pop(tool_call_id, None)
