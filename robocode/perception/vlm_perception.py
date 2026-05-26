"""VLM 感知核心 — 相机捕获 + VLM API 调用 + 深度→3D 坐标转换喵~"""

import os
import json
import subprocess
import re
import base64
from pathlib import Path
from dataclasses import dataclass
import numpy as np
from openai import OpenAI

from robocode.services.analytics.logger import get_logger

logger = get_logger("vlm_perception")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class CaptureResult:
    success: bool
    color_path: str = ""
    depth_path: str = ""
    intr_matrix: np.ndarray | None = None
    color_image: np.ndarray | None = None
    depth_image: np.ndarray | None = None
    error: str = ""

    def __post_init__(self):
        if self.success and self.color_path and os.path.exists(self.color_path):
            try:
                from PIL import Image

                self.color_image = np.array(Image.open(self.color_path))
                if os.path.exists(self.depth_path):
                    self.depth_image = np.load(self.depth_path)
            except Exception:
                pass


# ── VLM observe 用的 system prompt，让 VLM 返回结构化 JSON ──

OBSERVE_SYSTEM_PROMPT = """你是机械臂的视觉感知助手。根据图片和用户 prompt 做观察分析。
输出严格 JSON 格式（不要 markdown 代码块，只输出纯 JSON）:

{
  "observation": "自然语言描述你看到的场景和物体",
  "objects": [{"name": "物体名", "description": "外观描述", "position_hint": "大致位置如左前/中间/右后"}],
  "spatial_relations": "物体之间的空间关系",
  "suggestions": "如果信息不足以完成任务，给出进一步观察建议；否则写 'sufficient'"
}"""


class VlmPerception:
    """相机 + VLM API + 深度→3D，供 Agent 工具调用喵~"""

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen3-vl-plus",
        camera_bridge_script: str | None = None,
        image_dir: str = "/tmp/vlm_perception",
        sandbox: bool = False,
    ):
        self._api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        self._api_base = api_base
        self._model = model
        self._image_dir = image_dir
        self._sandbox = sandbox

        if camera_bridge_script:
            self._bridge_script = camera_bridge_script
        else:
            self._bridge_script = str(Path(__file__).parent / "camera_bridge.py")

        self._client: OpenAI | None = None
        if self._api_key:
            self._client = OpenAI(api_key=self._api_key, base_url=self._api_base)

    # ── 相机捕获 ──────────────────────────────────────────────────

    def capture(self) -> CaptureResult:
        """通过 camera_bridge.py 子进程捕获一帧喵~"""
        if self._sandbox:
            return self._fake_capture()

        os.makedirs(self._image_dir, exist_ok=True)

        try:
            result = subprocess.run(
                [
                    "conda",
                    "run",
                    "-n",
                    "episode",
                    "python3",
                    self._bridge_script,
                    "capture",
                    "--output-dir",
                    self._image_dir,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                logger.error("camera_bridge_failed", stderr=result.stderr)
                return CaptureResult(success=False, error=f"相机桥接失败: {result.stderr[:200]}")

            # 取 stdout 最后一行 JSON（跳过可能的 conda 警告行）喵~
            stdout_lines = result.stdout.strip().split("\n")
            data = None
            for line in reversed(stdout_lines):
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
            if data is None:
                return CaptureResult(success=False, error="相机桥接返回无效 JSON")
            if not data.get("success"):
                return CaptureResult(success=False, error=data.get("error", "未知错误"))

            intr = np.array(data["intr_matrix"], dtype=np.float64)
            return CaptureResult(
                success=True,
                color_path=data["color_path"],
                depth_path=data["depth_path"],
                intr_matrix=intr,
            )
        except subprocess.TimeoutExpired:
            return CaptureResult(success=False, error="相机桥接超时 (15s)")
        except Exception as e:
            logger.exception("capture_error")
            return CaptureResult(success=False, error=str(e))

    def _fake_capture(self) -> CaptureResult:
        """Sandbox 模式：返回 480x640 黑图 + 单位内参喵~"""
        os.makedirs(self._image_dir, exist_ok=True)
        from PIL import Image

        fake_color = Image.new("RGB", (640, 480), color=(0, 0, 0))
        fake_depth = np.ones((480, 640), dtype=np.uint16) * 1000  # 1m depth
        color_path = os.path.join(self._image_dir, "fake_color.jpg")
        depth_path = os.path.join(self._image_dir, "fake_depth.npy")
        fake_color.save(color_path)
        np.save(depth_path, fake_depth)
        intr = np.array([[640, 0, 320], [0, 640, 240], [0, 0, 1]], dtype=np.float64)
        return CaptureResult(
            success=True,
            color_path=color_path,
            depth_path=depth_path,
            intr_matrix=intr,
        )

    # ── VLM API 调用 ──────────────────────────────────────────────

    def observe(self, image_path: str, prompt: str) -> dict:
        """发送图片 + prompt 到 VLM，返回结构化观察结果喵~"""
        if self._sandbox:
            return self._fake_observe(prompt)

        if self._client is None:
            return {
                "success": False,
                "error": "VLM 客户端未初始化（缺少 API Key）",
                "observation": "",
                "objects": [],
                "suggestions": "",
            }

        try:
            full_prompt = f"{OBSERVE_SYSTEM_PROMPT}\n\n用户 prompt: {prompt}"
            raw = self._call_vlm(image_path, full_prompt)
            parsed = self._parse_json(raw)
            return {
                "success": True,
                "observation": parsed.get("observation", raw[:500]),
                "objects": parsed.get("objects", []),
                "spatial_relations": parsed.get("spatial_relations", ""),
                "suggestions": parsed.get("suggestions", "sufficient"),
                "raw_response": raw,
            }
        except Exception as e:
            logger.exception("observe_error")
            return {
                "success": False,
                "error": str(e),
                "observation": "",
                "objects": [],
                "suggestions": "",
            }

    def locate(
        self,
        image_path: str,
        target: str,
        depth_image: np.ndarray | None = None,
        intr_matrix: np.ndarray | None = None,
    ) -> dict:
        """定位特定物体：VLM 检测 bbox → 深度反投影 → 3D 坐标喵~"""
        if self._sandbox:
            return self._fake_locate(target)

        if self._client is None:
            return {"success": False, "error": "VLM 客户端未初始化", "found": False}

        try:
            locate_prompt = (
                f'在图片中找出 "{target}"，输出严格 JSON（不要 markdown 代码块）:\n'
                f'{{"found": true/false, "className": "类别名", '
                f'"xyxy": [[左上x, 左上y], [右下x, 右下y]], "confidence": 0.0~1.0}}\n'
                f"如果找不到，found 为 false，className 为空字符串。"
            )
            raw = self._call_vlm(image_path, locate_prompt)
            parsed = self._parse_json(raw)

            if not parsed.get("found") or "xyxy" not in parsed:
                return {
                    "success": True,
                    "found": False,
                    "class_name": "",
                    "position_3d": None,
                    "bbox": None,
                    "confidence": parsed.get("confidence", 0),
                    "raw_response": raw,
                }

            xyxy = parsed["xyxy"]
            if isinstance(xyxy[0], (list, tuple)):
                x1, y1, x2, y2 = int(xyxy[0][0]), int(xyxy[0][1]), int(xyxy[1][0]), int(xyxy[1][1])
            else:
                x1, y1, x2, y2 = [int(c) for c in xyxy[:4]]

            # 深度→3D 反投影
            position_3d = None
            if depth_image is not None and intr_matrix is not None:
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                position_3d = self._deproject_2d_to_3d(cx, cy, depth_image, intr_matrix)

            return {
                "success": True,
                "found": True,
                "class_name": parsed.get("className", target),
                "position_3d": position_3d,  # [x, y, z] mm in camera frame, or None
                "bbox": [[x1, y1], [x2, y2]],
                "confidence": parsed.get("confidence", 0.8),
                "raw_response": raw,
            }
        except Exception as e:
            logger.exception("locate_error")
            return {"success": False, "error": str(e), "found": False}

    # ── VLM API 底层调用 ──────────────────────────────────────────

    def _call_vlm(self, image_path: str, prompt: str) -> str:
        """发送图片 + prompt 到 VLM API，返回原始文本喵~"""
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                    ],
                }
            ],
            temperature=0.1,
            max_tokens=1024,
        )
        text = resp.choices[0].message.content.strip()
        # 去掉可能的 think 标签
        text = re.sub(r"<think.*?</think\s*>", "", text, flags=re.DOTALL)
        return text.strip()

    # ── 深度→3D 反投影 ────────────────────────────────────────────

    @staticmethod
    def _deproject_2d_to_3d(
        px: int,
        py: int,
        depth_image: np.ndarray,
        intr_matrix: np.ndarray,
        neighborhood: int = 3,
    ) -> list[float] | None:
        """像素坐标 + 深度图 + 内参 → 相机坐标系 3D 坐标 (mm) 喵~"""
        h, w = depth_image.shape
        if not (0 <= px < w and 0 <= py < h):
            return None

        # 邻域中位数处理深度空洞
        half = neighborhood // 2
        y1 = max(0, py - half)
        y2 = min(h, py + half + 1)
        x1 = max(0, px - half)
        x2 = min(w, px + half + 1)
        patch = depth_image[y1:y2, x1:x2]
        depth_mm = float(np.median(patch[patch > 0])) if np.any(patch > 0) else 0.0

        if depth_mm <= 0:
            return None

        depth_m = depth_mm / 1000.0
        fx, fy = intr_matrix[0, 0], intr_matrix[1, 1]
        cx, cy = intr_matrix[0, 2], intr_matrix[1, 2]

        x = (px - cx) * depth_m / fx
        y = (py - cy) * depth_m / fy
        z = depth_m

        return [round(x * 1000, 1), round(y * 1000, 1), round(z * 1000, 1)]

    # ── JSON 解析 ─────────────────────────────────────────────────

    @staticmethod
    def _parse_json(text: str) -> dict:
        """从 VLM 返回文本中提取 JSON 喵~"""
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```", "", text)
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    # ── Fake 模式返回 ─────────────────────────────────────────────

    def _fake_observe(self, prompt: str) -> dict:
        return {
            "success": True,
            "observation": f"[sandbox] 模拟观察结果（prompt: {prompt[:50]}...）: 桌面上有一个红色方块和一个蓝色杯子",
            "objects": [
                {"name": "red block", "description": "红色方块", "position_hint": "左前"},
                {"name": "blue cup", "description": "蓝色杯子", "position_hint": "右后"},
            ],
            "spatial_relations": "红色方块在蓝色杯子左边，间距约100mm",
            "suggestions": "sufficient",
            "raw_response": "",
        }

    def _fake_locate(self, target: str) -> dict:
        return {
            "success": True,
            "found": True,
            "class_name": target,
            "position_3d": [250.0, 0.0, 100.0],
            "bbox": [[300, 400], [500, 600]],
            "confidence": 0.9,
            "raw_response": "",
        }
