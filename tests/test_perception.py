"""感知系统测试 — FakeVlmPerception、深度反投影、HookRegistry、AgentLoop hook 注入喵~"""

from pathlib import Path
import numpy as np
import pytest


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def fake_perception():
    """创建 FakeVlmPerception 实例喵~"""
    from robocode.perception import FakeVlmPerception

    return FakeVlmPerception(api_key="test-key")


@pytest.fixture
def fake_capture(fake_perception):
    """捕获一帧假图喵~"""
    return fake_perception.capture()


@pytest.fixture
def hook_registry():
    """从经验文件加载 HookRegistry 喵~"""
    from robocode.perception.hooks import HookRegistry

    return HookRegistry()


# ── FakeVlmPerception 端到端测试 ────────────────────────────────────────


class TestFakeVlmPerception:
    """Fake 模式全链路测试喵~"""

    def test_capture_returns_success(self, fake_perception):
        """capture 返回 success=True，包含必要字段喵~"""
        cap = fake_perception.capture()
        assert cap.success is True
        assert cap.color_path.endswith(".jpg")
        assert cap.depth_path.endswith(".npy")
        assert cap.intr_matrix.shape == (3, 3)
        assert cap.color_image is not None
        assert cap.depth_image is not None

    def test_observe_returns_structured_json(self, fake_perception, fake_capture):
        """observe 返回结构化 dict，包含所有预期字段喵~"""
        result = fake_perception.observe(fake_capture.color_path, "桌面上有什么？")
        assert result["success"] is True
        assert len(result["observation"]) > 0
        assert len(result["objects"]) == 2
        assert result["objects"][0]["name"] == "red block"
        assert result["objects"][1]["name"] == "blue cup"
        assert "spatial_relations" in result
        assert result["suggestions"] == "sufficient"

    def test_locate_returns_3d_coordinates(self, fake_perception, fake_capture):
        """locate 返回 found=True 和 position_3d 列表喵~"""
        result = fake_perception.locate(fake_capture.color_path, "红色方块")
        assert result["success"] is True
        assert result["found"] is True
        assert result["class_name"] == "红色方块"
        assert result["position_3d"] == [250.0, 0.0, 100.0]
        assert len(result["bbox"]) == 2

    def test_fake_observe_different_prompts(self, fake_perception, fake_capture):
        """不同 prompt 都返回有效结果喵~"""
        for prompt in ["列出物体", "检查障碍物", "验证抓取"]:
            result = fake_perception.observe(fake_capture.color_path, prompt)
            assert result["success"] is True
            assert "observation" in result

    def test_fake_locate_different_targets(self, fake_perception, fake_capture):
        """不同 target 都返回 found=True 喵~"""
        for target in ["螺丝刀", "杯子", "零件"]:
            result = fake_perception.locate(fake_capture.color_path, target)
            assert result["found"] is True
            assert result["class_name"] == target


# ── 深度反投影测试 ─────────────────────────────────────────────────────


class TestDeprojection:
    """深度→3D 坐标反投影数学正确性测试喵~"""

    def test_center_pixel_returns_straight_ahead(self):
        """中心像素 → 相机正前方 (0, 0, Z) 喵~"""
        from robocode.perception.vlm_perception import VlmPerception

        intr = np.array([[640, 0, 320], [0, 640, 240], [0, 0, 1]], dtype=np.float64)
        depth = np.ones((480, 640), dtype=np.uint16) * 1000  # 1m = 1000mm
        result = VlmPerception._deproject_2d_to_3d(320, 240, depth, intr)
        assert result is not None
        assert abs(result[0]) < 0.1  # x ≈ 0
        assert abs(result[1]) < 0.1  # y ≈ 0
        assert result[2] == 1000.0  # z = 1000mm

    def test_depth_hole_returns_none(self):
        """深度全 0 → None 喵~"""
        from robocode.perception.vlm_perception import VlmPerception

        intr = np.array([[640, 0, 320], [0, 640, 240], [0, 0, 1]], dtype=np.float64)
        depth_hole = np.zeros((480, 640), dtype=np.uint16)
        result = VlmPerception._deproject_2d_to_3d(320, 240, depth_hole, intr)
        assert result is None

    def test_out_of_bounds_returns_none(self):
        """越界像素 → None 喵~"""
        from robocode.perception.vlm_perception import VlmPerception

        intr = np.array([[640, 0, 320], [0, 640, 240], [0, 0, 1]], dtype=np.float64)
        depth = np.ones((480, 640), dtype=np.uint16) * 1000
        assert VlmPerception._deproject_2d_to_3d(999, 999, depth, intr) is None
        assert VlmPerception._deproject_2d_to_3d(-1, -1, depth, intr) is None

    def test_neighborhood_median_handles_edge_holes(self):
        """3x3 邻域中位数处理边缘深度空洞喵~"""
        from robocode.perception.vlm_perception import VlmPerception

        intr = np.array([[640, 0, 320], [0, 640, 240], [0, 0, 1]], dtype=np.float64)
        depth = np.ones((480, 640), dtype=np.uint16) * 1000
        # 中心像素深度为 0，但周围有值
        depth[240, 320] = 0
        result = VlmPerception._deproject_2d_to_3d(320, 240, depth, intr)
        assert result is not None
        assert result[2] == 1000.0  # 取到了邻域中位数 1000


# ── HookRegistry 测试 ───────────────────────────────────────────────────


class TestHookRegistry:
    """Hook 规则加载和查询测试喵~"""

    def test_loads_hooks_from_file(self, hook_registry):
        """从 vlm-hooks.md 加载 5 条规则喵~"""
        assert hook_registry.hook_count == 5

    def test_pre_hooks_for_move_robot_xyz(self, hook_registry):
        """move_robot_xyz 有 1 条 pre-hook 喵~"""
        pre = hook_registry.get_pre_hooks("move_robot_xyz")
        assert len(pre) == 1
        assert pre[0].phase == "pre"
        assert pre[0].action == "observe"
        assert "目标位置" in pre[0].prompt_template

    def test_post_hooks_for_servo_gripper(self, hook_registry):
        """servo_gripper_control 有 1 条 post-hook 喵~"""
        post = hook_registry.get_post_hooks("servo_gripper_control")
        assert len(post) == 1
        assert post[0].phase == "post"
        assert "夹爪" in post[0].prompt_template

    def test_vlm_tools_excluded_from_hooks(self, hook_registry):
        """observe/locate 不触发 hooks（防循环）喵~"""
        assert len(hook_registry.get_pre_hooks("observe")) == 0
        assert len(hook_registry.get_post_hooks("observe")) == 0
        assert len(hook_registry.get_pre_hooks("locate")) == 0
        assert len(hook_registry.get_post_hooks("locate")) == 0

    def test_unknown_tool_returns_empty(self, hook_registry):
        """未注册的工具返回空列表喵~"""
        assert hook_registry.get_pre_hooks("nonexistent_tool") == []
        assert hook_registry.get_post_hooks("nonexistent_tool") == []

    def test_builtin_defaults_fallback(self):
        """经验文件不存在时使用内置默认规则喵~"""
        from robocode.perception.hooks import HookRegistry

        hr = HookRegistry(hooks_file=Path("/nonexistent/hooks.md"))
        assert hr.hook_count == 8  # 内置 8 条默认规则


# ── CaptureResult 测试 ─────────────────────────────────────────────────


class TestCaptureResult:
    """CaptureResult dataclass 测试喵~"""

    def test_success_false_skips_image_loading(self):
        """失败时不尝试加载图片喵~"""
        from robocode.perception.vlm_perception import CaptureResult

        cap = CaptureResult(success=False, error="test error")
        assert cap.color_image is None
        assert cap.depth_image is None

    def test_success_true_without_files(self):
        """无文件路径时图像为 None 不崩溃喵~"""
        from robocode.perception.vlm_perception import CaptureResult

        cap = CaptureResult(success=True)
        assert cap.color_image is None


# ── JSON 解析测试 ─────────────────────────────────────────────────────


class TestJsonParsing:
    """VLM 返回文本的 JSON 提取测试喵~"""

    def test_clean_json(self):
        """纯 JSON 正确解析喵~"""
        from robocode.perception.vlm_perception import VlmPerception

        result = VlmPerception._parse_json('{"found": true, "className": "test"}')
        assert result["found"] is True
        assert result["className"] == "test"

    def test_json_with_markdown_fence(self):
        """带 markdown 代码块的 JSON 正确解析喵~"""
        from robocode.perception.vlm_perception import VlmPerception

        result = VlmPerception._parse_json('```json\n{"found": true}\n```')
        assert result["found"] is True

    def test_json_with_prefix_text(self):
        """带前缀文本的 JSON 正确提取喵~"""
        from robocode.perception.vlm_perception import VlmPerception

        result = VlmPerception._parse_json('这是分析结果：{"found": true, "name": "test"}')
        assert result["found"] is True

    def test_invalid_json_returns_empty(self):
        """无效文本返回空 dict 喵~"""
        from robocode.perception.vlm_perception import VlmPerception

        result = VlmPerception._parse_json("这不是 JSON")
        assert result == {}


# ── Hook 规则解析测试 ──────────────────────────────────────────────────


class TestHookRuleParsing:
    """从经验文件文本解析 HookRule 测试喵~"""

    def test_parse_single_hook_rule(self):
        """解析单条钩子规则喵~"""
        from robocode.perception.hooks import HookRegistry

        content = '- [移动前观察|HOOK] @move_robot_xyz pre:observe "确认目标位置"'
        rules = HookRegistry._parse_hooks(content)
        assert len(rules) == 1
        assert rules[0].tool_name == "move_robot_xyz"
        assert rules[0].phase == "pre"
        assert rules[0].action == "observe"
        assert rules[0].prompt_template == "确认目标位置"

    def test_parse_multiple_rules(self):
        """解析多条规则喵~"""
        from robocode.perception.hooks import HookRegistry

        content = """
- [移动前|HOOK] @move_robot_xyz pre:observe "检查工作区"
- [抓取后|HOOK] @servo_gripper_control post:observe "确认抓取"
"""
        rules = HookRegistry._parse_hooks(content)
        assert len(rules) == 2


# ── FakeVlmPerception 多实例测试 ──────────────────────────────────────


class TestFakeVlmPerceptionIsolation:
    """FakeVlmPerception 实例独立性测试喵~"""

    def test_multiple_instances_independent(self):
        """多个实例各自创建不崩溃喵~"""
        from robocode.perception import FakeVlmPerception

        a = FakeVlmPerception()
        b = FakeVlmPerception()
        cap_a = a.capture()
        cap_b = b.capture()
        assert cap_a.success and cap_b.success  # 两个实例都正常工作
        assert isinstance(cap_a.color_path, str)
        assert isinstance(cap_b.color_path, str)
