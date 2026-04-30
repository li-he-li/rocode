"""Process orchestration — script inventory, detection, grasp tools."""

import yaml
from pathlib import Path
from robocode.backends.base import RobotBackend
from robocode.orchestrator.safety import SafetyPolicy
from robocode.utils.models import ToolResult

CALIB_DIR = Path("src/student_ros/src/episode_apps/calibration_scripts")
ROOT_DIR = Path("src")

# ── Script Inventory (9.1-9.2) ──────────────────────────────────────

SCRIPT_INVENTORY = [
    # Calibration scripts
    {
        "name": "perspective_calibration",
        "path": str(CALIB_DIR / "2.calibrate_perspective_camera_qt.py"),
        "category": "calibration",
        "requires_human": True,
        "output_files": [str(CALIB_DIR / "camera_calibration.yaml")],
        "description": "透视变换标定：点击棋盘 4 角点建立像素→物理mm映射",
    },
    {
        "name": "hand_eye_calibration",
        "path": str(CALIB_DIR / "4.calibrate_hand_eye_qt_ros2.py"),
        "category": "calibration",
        "requires_human": True,
        "output_files": [str(CALIB_DIR / "hand_eye_calibration.yaml")],
        "description": "手眼标定：示教 4 点计算 T 矩阵（相机→机器人基座）",
    },
    {
        "name": "storage_perspective_calibration",
        "path": str(CALIB_DIR / "7.calibrate_storage_camera.py"),
        "category": "calibration",
        "requires_human": True,
        "output_files": [str(CALIB_DIR / "storage_camera_calibration.yaml")],
        "description": "存放区透视标定",
    },
    {
        "name": "storage_hand_eye_calibration",
        "path": str(CALIB_DIR / "9.calibrate_storage_hand_eye.py"),
        "category": "calibration",
        "requires_human": True,
        "output_files": [str(CALIB_DIR / "storage_hand_eye_calibration.yaml")],
        "description": "存放区手眼标定",
    },
    # Detection scripts
    {
        "name": "dino_detect",
        "path": str(ROOT_DIR / "3D/5.dino_detect.py"),
        "category": "detection",
        "requires_human": False,
        "output_files": [],
        "description": "GroundingDINO 开放词汇物体检测（需 --output_json）",
    },
    {
        "name": "dino_grasp",
        "path": str(ROOT_DIR / "3D/6.dino_grasp.py"),
        "category": "detection",
        "requires_human": True,
        "output_files": [],
        "description": "GroundingDINO 检测 + SDK 抓取闭环",
    },
    {
        "name": "board_state_detection",
        "path": str(CALIB_DIR / "3.live_cropped_feed.py"),
        "category": "detection",
        "requires_human": True,
        "output_files": [],
        "description": "YOLO 棋子检测 + 棋盘状态识别",
    },
    # Application scripts
    {
        "name": "gomoku_demo_raw",
        "path": str(ROOT_DIR / "student_ros/src/episode_apps/12.chess_demo_raw.py"),
        "category": "application",
        "requires_human": True,
        "output_files": [],
        "description": "五子棋 Demo（SDK 控制）",
    },
    {
        "name": "gomoku_demo_ros2",
        "path": str(ROOT_DIR / "student_ros/src/episode_apps/13.chess_demo_ros2.py"),
        "category": "application",
        "requires_human": True,
        "output_files": [],
        "description": "五子棋 Demo（ROS2 控制）",
    },
    {
        "name": "gomoku_demo_moveit",
        "path": str(ROOT_DIR / "student_ros/src/episode_apps/14.chess_demo_ros2_moveit.py"),
        "category": "application",
        "requires_human": True,
        "output_files": [],
        "description": "五子棋 Demo（MoveIt 控制）",
    },
    # 6D grasp pipeline
    {
        "name": "agent_grasp_6d",
        "path": str(ROOT_DIR / "6D/6D/graspnet-baseline/agent_grasp.py"),
        "category": "grasp",
        "requires_human": False,
        "output_files": [],
        "description": "6D 抓取 Agent：VLM 解析→GraspNet 候选→IK 迭代",
    },
    {
        "name": "vlm_handler_6d",
        "path": str(ROOT_DIR / "6D/6D/graspnet-baseline/3.demo_VLM_handler.py"),
        "category": "grasp",
        "requires_human": False,
        "output_files": [],
        "description": "GraspNet 执行器：监听交换文件执行抓取",
    },
]

# ── Tool Implementations ────────────────────────────────────────────


def _detect_objects_impl(*, query, confidence_threshold=0.3, **kwargs) -> dict:
    """Detect objects using GroundingDINO (stub without model)."""
    # In production, this would subprocess 5.dino_detect.py --output_json
    # For now, returns guidance that model needs to be available
    dino_path = ROOT_DIR / "3D/5.dino_detect.py"
    if not dino_path.exists():
        return ToolResult(
            success=False,
            message=f"检测脚本不存在: {dino_path}",
        ).model_dump(mode="json")
    return ToolResult(
        success=False,
        message=f"检测模型需在真机环境中加载。执行: python {dino_path} --output_json --query '{query}'",
        metrics={"query": query, "threshold": confidence_threshold},
    ).model_dump(mode="json")


def _simple_grasp_impl(*, object_description, approach_height_mm=50, **kwargs) -> dict:
    """Simple 3D grasp pipeline via GroundingDINO detection + SDK execution."""
    return ToolResult(
        success=False,
        message=f"simple_grasp({object_description}) 需真机 GroundingDINO 模型。"
        f"流程: detect({object_description}) → transform → approach({approach_height_mm}mm) → pick → grip → lift",
        metrics={
            "object": object_description,
            "approach_height_mm": approach_height_mm,
            "pipeline": "3d_simple",
        },
    ).model_dump(mode="json")


def _plan_grasp_impl(*, object_description, **kwargs) -> dict:
    """6D grasp pipeline via VLM + GraspNet multi-candidate pose generation."""
    agent_path = ROOT_DIR / "6D/6D/graspnet-baseline/agent_grasp.py"
    return ToolResult(
        success=False,
        message=f"plan_grasp({object_description}) 需真机 GraspNet 模型。"
        f"流程: VLM parse → GraspNet generate → collision filter → IK iterate → execute\n"
        f"参考: python {agent_path} '{object_description}'",
        metrics={
            "object": object_description,
            "pipeline": "6d_plan",
        },
    ).model_dump(mode="json")


def make_script_tools(backend: RobotBackend, safety: SafetyPolicy) -> dict:
    def check_calibration_status(*, calib_type="hand_eye", **kwargs):
        file_map = {
            "hand_eye": CALIB_DIR / "hand_eye_calibration.yaml",
            "perspective": CALIB_DIR / "camera_calibration.yaml",
            "storage_hand_eye": CALIB_DIR / "storage_hand_eye_calibration.yaml",
            "storage_perspective": CALIB_DIR / "storage_camera_calibration.yaml",
        }
        path = file_map.get(calib_type)
        if not path or not path.exists():
            return ToolResult(
                success=False,
                message=f"标定文件未找到: {calib_type}",
                metrics={"path": str(path) if path else "unknown"},
            ).model_dump(mode="json")
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            return ToolResult(success=False, message=f"无法读取标定文件: {path}").model_dump(
                mode="json"
            )
        has_t = "T_matrix" in data and data["T_matrix"] is not None
        return ToolResult(
            success=has_t,
            message=f"{calib_type} 标定{'已' if has_t else '未'}完成",
            metrics={"calib_type": calib_type, "T_matrix_available": has_t, "path": str(path)},
        ).model_dump(mode="json")

    def detect_objects(*, query, confidence_threshold=0.3, **kwargs):
        return _detect_objects_impl(query=query, confidence_threshold=confidence_threshold)

    def simple_grasp(*, object_description, approach_height_mm=50, **kwargs):
        return _simple_grasp_impl(
            object_description=object_description, approach_height_mm=approach_height_mm
        )

    def plan_grasp(*, object_description, **kwargs):
        return _plan_grasp_impl(object_description=object_description)

    def run_script(*, script_name, **kwargs):
        entry = next((s for s in SCRIPT_INVENTORY if s["name"] == script_name), None)
        if not entry:
            return ToolResult(
                success=False,
                message=f"未知脚本: {script_name}。可用: {[s['name'] for s in SCRIPT_INVENTORY]}",
            ).model_dump(mode="json")
        if entry["requires_human"]:
            return ToolResult(
                success=False,
                message=f"脚本 {script_name} 需要操作者在 GUI 上手动操作。启动: python {entry['path']}",
                metrics={"script": script_name, "requires_human": True, "path": entry["path"]},
            ).model_dump(mode="json")
        return ToolResult(
            success=False,
            message=f"脚本 {script_name} 执行需操作者确认后启动 subprocess: python {entry['path']}",
            metrics={"script": script_name, "path": entry["path"]},
        ).model_dump(mode="json")

    return {
        "check_calibration_status": check_calibration_status,
        "detect_objects": detect_objects,
        "simple_grasp": simple_grasp,
        "plan_grasp": plan_grasp,
        "run_script": run_script,
    }
