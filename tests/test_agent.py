"""Agent runtime tests — provider interface, ReAct loop, intent classification."""

from robocode.llm.base import StreamEvent, ToolUse
from robocode.llm.fake_provider import FakeProvider
from robocode.agent.core import AgentLoop


class TestStreamEvent:
    def test_text_delta(self):
        e = StreamEvent(kind="text_delta", payload={"delta": "hello"})
        assert e.kind == "text_delta"
        assert e.payload["delta"] == "hello"

    def test_tool_use(self):
        tu = ToolUse(id="1", name="get_status", input={})
        assert tu.name == "get_status"


class TestFakeProvider:
    async def test_returns_configured_responses(self):
        fp = FakeProvider(
            responses=[
                [
                    StreamEvent(kind="text_delta", payload={"delta": "hello"}),
                    StreamEvent(kind="end_turn", payload={}),
                ]
            ]
        )
        events = [e async for e in fp.stream("sys", [{"role": "user"}], [])]
        assert len(events) == 2
        assert events[0].payload["delta"] == "hello"

    async def test_records_inputs(self):
        fp = FakeProvider(responses=[[StreamEvent(kind="end_turn", payload={})]])
        tools = [{"name": "t1"}]
        async for _ in fp.stream("system prompt", [{"role": "user", "content": "hi"}], tools):
            pass
        assert fp.last_system == "system prompt"
        assert fp.last_messages[0]["content"] == "hi"
        assert fp.last_tools == tools


class TestAgentLoop:
    def mk_agent(self, responses=None):
        fp = FakeProvider(responses=responses)
        return AgentLoop(provider=fp, max_iterations=5)

    async def test_chat_turn_returns_text(self):
        agent = self.mk_agent(
            responses=[
                [
                    StreamEvent(kind="text_delta", payload={"delta": "你好！"}),
                    StreamEvent(kind="end_turn", payload={}),
                ]
            ]
        )
        result = await agent.run_turn("你好")
        assert "你好" in result

    async def test_tool_call_loop(self):
        async def fake_status(**kwargs):
            return {"success": True, "message": "机器人在线"}

        responses = [
            [
                StreamEvent(
                    kind="tool_use",
                    payload={"id": "tu1", "name": "get_robot_status", "input": {}},
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "状态正常"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]
        agent = AgentLoop(
            provider=FakeProvider(responses=responses),
            tool_handlers={"get_robot_status": fake_status},
            tool_schemas=[
                {
                    "type": "function",
                    "function": {
                        "name": "get_robot_status",
                        "description": "获取机器人状态",
                    },
                }
            ],
            max_iterations=5,
        )
        result = await agent.run_turn("状态？")
        assert "状态正常" in result

    async def test_iteration_limit(self):
        responses = [
            [
                StreamEvent(
                    kind="tool_use",
                    payload={"id": f"tu{i}", "name": "get_robot_status", "input": {}},
                ),
            ]
            for i in range(10)
        ]
        agent = self.mk_agent(responses=responses)
        result = await agent.run_turn("loop")
        assert "迭代" in result

    async def test_unknown_tool_returns_error(self):
        responses = [
            [
                StreamEvent(
                    kind="tool_use",
                    payload={"id": "tu1", "name": "nonexistent_tool", "input": {}},
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "工具不存在"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]
        agent = AgentLoop(
            provider=FakeProvider(responses=responses),
            max_iterations=5,
        )
        result = await agent.run_turn("test")
        assert "工具不存在" in result


class TestApprovalGuard:
    """0.1.4: L2 tools must trigger approval before execution."""

    def mk_approval_callback(self, decision="Y"):
        """Return an async callback that records calls and returns the given decision."""
        calls = []

        async def cb(tool_name, risk_level, params, summary):
            calls.append(
                {
                    "tool_name": tool_name,
                    "risk_level": risk_level,
                    "params": params,
                    "summary": summary,
                }
            )
            return decision

        return cb, calls

    async def test_l2_tool_triggers_approval(self):
        from robocode.orchestrator.tool_guard import ToolGuard
        from robocode.orchestrator.approval import ApprovalGate
        from robocode.llm.fake_provider import FakeProvider

        cb, calls = self.mk_approval_callback("Y")

        guard = ToolGuard(
            approval_gate=ApprovalGate(),
            audit_db=None,
            safety_policy=None,
            approval_settings=None,
            owner_callback=cb,
        )

        async def fake_move(**kwargs):
            return {"success": True, "message": "已移动"}

        responses = [
            [
                StreamEvent(
                    kind="tool_use",
                    payload={
                        "id": "tu1",
                        "name": "move_robot_xyz",
                        "input": {"x": 300, "y": 0, "z": 150},
                    },
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "移动完成"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]

        agent = AgentLoop(
            provider=FakeProvider(responses=responses),
            tool_handlers={"move_robot_xyz": fake_move},
            tool_schemas=[
                {"type": "function", "function": {"name": "move_robot_xyz", "description": "移动"}}
            ],
            max_iterations=5,
            guard=guard,
            risk_levels={"move_robot_xyz": "L2"},
        )

        result = await agent.run_turn("移动到目标")
        assert "移动完成" in result
        assert len(calls) == 1
        assert calls[0]["tool_name"] == "move_robot_xyz"
        assert calls[0]["risk_level"] == "L2"

    async def test_l2_tool_rejected_when_operator_declines(self):
        from robocode.orchestrator.tool_guard import ToolGuard
        from robocode.orchestrator.approval import ApprovalGate
        from robocode.llm.fake_provider import FakeProvider

        cb, calls = self.mk_approval_callback("N")

        guard = ToolGuard(
            approval_gate=ApprovalGate(),
            audit_db=None,
            safety_policy=None,
            approval_settings=None,
            owner_callback=cb,
        )

        async def fake_grasp(**kwargs):
            return {"success": True, "message": "已抓取"}

        responses = [
            [
                StreamEvent(
                    kind="tool_use",
                    payload={
                        "id": "tu1",
                        "name": "6d_grasp",
                        "input": {"instruction": "抓取海绵块"},
                    },
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "操作被拒"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]

        agent = AgentLoop(
            provider=FakeProvider(responses=responses),
            tool_handlers={"6d_grasp": fake_grasp},
            tool_schemas=[
                {"type": "function", "function": {"name": "6d_grasp", "description": "6D抓取"}}
            ],
            max_iterations=5,
            guard=guard,
            risk_levels={"6d_grasp": "L2"},
        )

        result = await agent.run_turn("抓取")
        assert "操作被拒" in result
        assert len(calls) == 1

    async def test_l0_tool_auto_approved_no_callback(self):
        from robocode.orchestrator.tool_guard import ToolGuard
        from robocode.orchestrator.approval import ApprovalGate
        from robocode.llm.fake_provider import FakeProvider

        cb, calls = self.mk_approval_callback("Y")

        guard = ToolGuard(
            approval_gate=ApprovalGate(),
            audit_db=None,
            safety_policy=None,
            approval_settings=None,
            owner_callback=cb,
        )

        async def fake_status(**kwargs):
            return {"success": True, "message": "在线"}

        responses = [
            [
                StreamEvent(
                    kind="tool_use", payload={"id": "tu1", "name": "get_robot_status", "input": {}}
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "机器人正常"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]

        agent = AgentLoop(
            provider=FakeProvider(responses=responses),
            tool_handlers={"get_robot_status": fake_status},
            tool_schemas=[
                {
                    "type": "function",
                    "function": {"name": "get_robot_status", "description": "状态"},
                }
            ],
            max_iterations=5,
            guard=guard,
            risk_levels={"get_robot_status": "L0"},
        )

        result = await agent.run_turn("状态")
        assert "正常" in result
        assert len(calls) == 0  # L0 auto-approved, no callback needed

    async def test_session_auto_approval(self):
        from robocode.orchestrator.tool_guard import ToolGuard
        from robocode.orchestrator.approval import ApprovalGate
        from robocode.llm.fake_provider import FakeProvider

        cb, calls = self.mk_approval_callback("A")  # session approve

        gate = ApprovalGate()
        guard = ToolGuard(
            approval_gate=gate,
            audit_db=None,
            safety_policy=None,
            approval_settings=None,
            owner_callback=cb,
        )

        async def fake_move(**kwargs):
            return {"success": True, "message": "已移动"}

        responses = [
            [
                StreamEvent(
                    kind="tool_use",
                    payload={
                        "id": "tu1",
                        "name": "move_robot_xyz",
                        "input": {"x": 300, "y": 0, "z": 150},
                    },
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "第一次移动完成"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]

        agent = AgentLoop(
            provider=FakeProvider(responses=responses),
            tool_handlers={"move_robot_xyz": fake_move},
            tool_schemas=[
                {"type": "function", "function": {"name": "move_robot_xyz", "description": "移动"}}
            ],
            max_iterations=5,
            guard=guard,
            risk_levels={"move_robot_xyz": "L2"},
        )

        result = await agent.run_turn("移动1")
        assert "第一次移动完成" in result
        assert len(calls) == 1
        assert gate.is_auto_approved("move_robot_xyz", "L2")

    async def test_backward_compatible_guard_none(self):
        """AgentLoop without guard works as before."""
        from robocode.llm.fake_provider import FakeProvider

        async def fake_status(**kwargs):
            return {"success": True, "message": "在线"}

        responses = [
            [
                StreamEvent(
                    kind="tool_use", payload={"id": "tu1", "name": "get_robot_status", "input": {}}
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "正常"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]

        agent = AgentLoop(
            provider=FakeProvider(responses=responses),
            tool_handlers={"get_robot_status": fake_status},
            tool_schemas=[{"type": "function", "function": {"name": "get_robot_status"}}],
            max_iterations=5,
            # guard is None by default
        )

        result = await agent.run_turn("状态")
        assert "正常" in result


class TestContextMemory:
    def test_store_and_retrieve(self):
        from robocode.agent.context import ContextMemory

        ctx = ContextMemory()
        ctx.add_message("user", "hello")
        ctx.add_message("assistant", "hi there")
        ctx.set_safety_state(estop_active=False, last_approval="approved")
        assert len(ctx.messages) == 2
        assert ctx.safety_state["estop_active"] is False

    def test_trim_preserves_safety(self):
        from robocode.agent.context import ContextMemory

        ctx = ContextMemory(max_tokens=5)
        ctx.add_message("user", "hello")
        ctx.set_safety_state(estop_active=True, last_approval="denied")
        ctx.add_message("user", "world")
        ctx.trim()
        assert ctx.safety_state["estop_active"] is True
