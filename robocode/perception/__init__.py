"""VLM 感知模块 — 相机 + VLM API + 深度→3D 坐标喵~"""

from robocode.perception.vlm_perception import VlmPerception
from robocode.perception.fake_perception import FakeVlmPerception

__all__ = ["VlmPerception", "FakeVlmPerception"]
