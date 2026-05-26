"""Fake VLM 感知 — sandbox/离线模式下的模拟感知喵~"""

from robocode.perception.vlm_perception import VlmPerception, CaptureResult


class FakeVlmPerception(VlmPerception):
    """不调相机、不调 API 的模拟 VLM 感知，用于测试和离线开发喵~"""

    def __init__(self, api_key: str = "", **kwargs):
        kwargs["sandbox"] = True
        super().__init__(api_key=api_key or "fake-key", **kwargs)
        self._counter = 0

    def capture(self) -> CaptureResult:
        """返回假图 + 单位内参喵~"""
        return self._fake_capture()

    def observe(self, image_path: str, prompt: str) -> dict:
        """返回预设的模拟观察结果喵~"""
        self._counter += 1
        return self._fake_observe(prompt)

    def locate(self, image_path: str, target: str, depth_image=None, intr_matrix=None) -> dict:
        """返回预设的模拟定位结果喵~"""
        self._counter += 1
        return self._fake_locate(target)
