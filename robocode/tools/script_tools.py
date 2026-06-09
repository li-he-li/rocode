"""流程编排 — 脚本清单、标定/检测/抓取工具喵~"""

import json
import time
import subprocess
import yaml
from pathlib import Path
from robocode.utils.models import ToolResult

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CALIB_DIR = _PROJECT_ROOT / "src/student_ros/src/episode_apps/calibration_scripts"
ROOT_DIR = _PROJECT_ROOT / "src"
D6_DIR = ROOT_DIR / "6D/6D/6d"

# ── 脚本清单 ──────────────────────────────────────────────────────

SCRIPT_INVENTORY = [
    # ── 6D 标定脚本 ──
    {
        "name": "6d_calibration_teach",
        "path": str(D6_DIR / "0.teach_mode.py"),
        "category": "calibration",
        "requires_human": True,
        "output_files": [str(D6_DIR / "motors_degrees.npy")],
        "description": "6D标定 Step 0: 示教采集点（人工自由拖拽机械臂记录位姿）",
    },
    {
        "name": "6d_calibration_collect",
        "path": str(D6_DIR / "1.generate_points.py"),
        "category": "calibration",
        "requires_human": True,
        "output_files": [],
        "description": "6D标定 Step 1: 自动采集棋盘格图像并评估质量",
    },
    {
        "name": "6d_calibration_capture",
        "path": str(D6_DIR / "2.generate_images_and_T.py"),
        "category": "calibration",
        "requires_human": False,
        "output_files": [],
        "description": "6D标定 Step 2: 遍历角度拍摄棋盘格，计算 R_list/t_list",
    },
    {
        "name": "6d_calibration_compute",
        "path": str(D6_DIR / "3.calibrate.py"),
        "category": "calibration",
        "requires_human": False,
        "output_files": [str(ROOT_DIR / "6D/6D/graspnet-baseline/T_camera2end.yaml")],
        "description": "6D标定 Step 3: OpenCV calibrateHandEye 计算 T_camera2end",
    },
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
]


def make_script_tools() -> dict:
    """构建脚本/检测/抓取工具 handler 映射喵~"""

    def check_calibration_status(*, calib_type="hand_eye", **kwargs):
        """检查标定文件是否存在且包含有效变换矩阵喵~"""
        file_map = {
            "hand_eye": CALIB_DIR / "hand_eye_calibration.yaml",
            "perspective": CALIB_DIR / "camera_calibration.yaml",
            "storage_hand_eye": CALIB_DIR / "storage_hand_eye_calibration.yaml",
            "storage_perspective": CALIB_DIR / "storage_camera_calibration.yaml",
            "6d": ROOT_DIR / "6D/6D/graspnet-baseline/T_camera2end.yaml",
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
        has_t = False
        if calib_type == "6d":
            has_t = "T_camera2end" in data and data["T_camera2end"] is not None
        else:
            has_t = "T_matrix" in data and data["T_matrix"] is not None
        return ToolResult(
            success=has_t,
            message=f"{calib_type} 标定{'已' if has_t else '未'}完成",
            metrics={"calib_type": calib_type, "T_matrix_available": has_t, "path": str(path)},
        ).model_dump(mode="json")

    def run_script(*, script_name, args="", **kwargs):
        """启动标定/检测脚本 — 需人工的脚本仅返回启动指令，自动脚本在 conda episode 中执行喵~"""
        t0 = time.perf_counter()
        entry = next((s for s in SCRIPT_INVENTORY if s["name"] == script_name), None)
        if not entry:
            return ToolResult(
                success=False,
                message=f"未知脚本: {script_name}。可用: {[s['name'] for s in SCRIPT_INVENTORY]}",
            ).model_dump(mode="json")
        if entry["requires_human"]:
            # 需人工操作的脚本 — 只返回启动指令，不自动执行喵~
            return ToolResult(
                success=False,
                message=f"脚本 {script_name} 需要操作者在 GUI 上手动操作。启动: python {entry['path']}",
                metrics={"script": script_name, "requires_human": True, "path": entry["path"]},
            ).model_dump(mode="json")
        # 自动脚本 — 经由 conda episode 执行
        cmd = [
            "conda",
            "run",
            "-n",
            "episode",
            "--no-capture-output",
            "python3",
            str(Path(entry["path"]).resolve()),
        ]
        if args:
            cmd.append(args)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            duration_ms = (time.perf_counter() - t0) * 1000
            rv = ToolResult(
                success=proc.returncode == 0,
                message=proc.stdout.strip()[-500:]
                if proc.stdout.strip()
                else ("完成" if proc.returncode == 0 else f"退出码: {proc.returncode}"),
                metrics={
                    "script": script_name,
                    "returncode": proc.returncode,
                    "stdout": proc.stdout[-2000:],
                    "stderr": proc.stderr[-1000:],
                },
            )
            from robocode.utils.runtime_log import log_script

            log_script(script_name, cmd, proc.returncode, proc.stdout, proc.stderr, duration_ms)
            return rv.model_dump(mode="json")
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, message=f"脚本 {script_name} 超时 (120s)").model_dump(
                mode="json"
            )
        except Exception as e:
            return ToolResult(success=False, message=f"脚本执行异常: {e}").model_dump(mode="json")

    def grasp_6d(*, instruction, **kwargs):
        """6D 抓取 — VLM 检测 + GraspNet 规划 + IK 执行喵~"""
        t0 = time.perf_counter()
        script = ROOT_DIR / "6D/6D/graspnet-baseline/run_grasp.py"
        if not script.exists():
            return ToolResult(success=False, message=f"抓取脚本不存在: {script}").model_dump(
                mode="json"
            )
        try:
            cmd = [
                "conda",
                "run",
                "-n",
                "episode",
                "--no-capture-output",
                "python3",
                str(script.resolve()),
                instruction,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            duration_ms = (time.perf_counter() - t0) * 1000
            # 解析 run_grasp.py 的 JSON 输出（取 stdout 最后一行）
            try:
                result = (
                    json.loads(proc.stdout.strip().split("\n")[-1]) if proc.stdout.strip() else {}
                )
            except json.JSONDecodeError:
                result = {}
            success = result.get("status") == "ok"
            rv = ToolResult(
                success=success,
                message=result.get(
                    "message",
                    proc.stdout.strip()[-500:] or ("完成" if proc.returncode == 0 else "失败"),
                ),
                metrics={
                    "instruction": instruction,
                    "returncode": proc.returncode,
                    "class_name": result.get("class_name"),
                    "ik_attempts": result.get("ik_attempts"),
                    "total_candidates": result.get("total_candidates"),
                    "stderr": proc.stderr[-1000:],
                },
            )
            from robocode.utils.runtime_log import log_script

            log_script("6d_grasp", cmd, proc.returncode, proc.stdout, proc.stderr, duration_ms)
            return rv.model_dump(mode="json")
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, message="6D 抓取超时 (180s)").model_dump(mode="json")
        except Exception as e:
            return ToolResult(success=False, message=f"6D 抓取异常: {e}").model_dump(mode="json")

    return {
        "check_calibration_status": check_calibration_status,
        "run_script": run_script,
        "6d_grasp": grasp_6d,
    }
