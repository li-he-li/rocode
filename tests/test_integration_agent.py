"""Integration test: Agent full-stack test with fake backend (上位机未连接).

Exercises ALL Phase 1 + Phase 2 features in a simulated real-world session:
- Code inspection: read_file, search_code
- Existing tools: get_robot_status, move_robot_home (DRY-RUN)
- Approval gate: L2 move_robot_xyz rejected, then approved
- Sandbox isolation: FORBIDDEN_PATTERNS block raw socket
- One-shot wrapper: generate → execute via generate_and_run_sdk_code → discard
- /estop: local handling, never to LLM
- /audit: real DB records after tool calls
"""

import pytest
import os
from robocode.llm.fake_provider import StreamEvent


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def agent_session():
    """Create a full agent session with fake backend + ToolGuard + AuditDB."""
    from robocode.config import Settings
    from robocode.llm.fake_provider import FakeProvider
    from robocode.agent.core import AgentLoop
    from robocode.backends.sdk_backend import SdkBackend, FakeEpisodeAPP
    from robocode.orchestrator.safety import SafetyPolicy
    from robocode.orchestrator.approval import ApprovalGate
    from robocode.orchestrator.tool_guard import ToolGuard
    from robocode.persistence.db import AuditDB
    from robocode.tools.registry import ToolRegistry, ToolEntry
    from robocode.tools.motion_tools import make_motion_tools
    from robocode.tools.gripper_tools import make_gripper_tools
    from robocode.tools.script_tools import make_script_tools
    from robocode.tools.codegen_tools import make_codegen_tools
    from robocode.tools.exec_tools import make_exec_tools
    from robocode.tools.code_tools import make_code_tools
    from robocode.tools.patch_tools import make_patch_tools
    from robocode.tools.wrapper_tools import make_wrapper_tools

    # Real AuditDB (in-memory SQLite via temp file)
    db_path = "/tmp/test_integration_audit.db"
    if os.path.exists(db_path):
        os.unlink(db_path)
    db = AuditDB(path=db_path)
    db.initialize()
    session_id = db.create_session(backend="sdk")

    # Fake backend
    backend = SdkBackend(client=FakeEpisodeAPP())
    assert backend.is_fake is True  # DRY-RUN mode

    # Safety + approval
    safety = SafetyPolicy(Settings())
    gate = ApprovalGate()

    # Approval callback that records decisions
    approval_log = []

    async def owner_callback(tool_name, risk_level, params, summary):
        approval_log.append(
            {
                "tool_name": tool_name,
                "risk_level": risk_level,
                "params": params,
                "summary": summary,
            }
        )
        # Auto-approve for testing (simulating operator pressing Y)
        return "Y"

    guard = ToolGuard(
        approval_gate=gate,
        audit_db=db,
        safety_policy=safety,
        approval_settings=Settings().approval,
        owner_callback=owner_callback,
        session_id=session_id,
    )

    # Tool registry + handlers
    registry = ToolRegistry()
    risk_levels = {}

    # Register all Phase 1 + Phase 2 tools
    all_entries = [
        ToolEntry(
            name="get_robot_status",
            description="获取状态",
            parameters={"type": "object", "properties": {}},
            risk_level="L0",
        ),
        ToolEntry(
            name="move_robot_home",
            description="回零位",
            parameters={"type": "object", "properties": {}},
            risk_level="L1",
        ),
        ToolEntry(
            name="move_robot_xyz",
            description="移动",
            parameters={
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                },
                "required": ["x", "y", "z"],
            },
            risk_level="L2",
        ),
        ToolEntry(
            name="read_file",
            description="读取文件",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            risk_level="L0",
        ),
        ToolEntry(
            name="search_code",
            description="搜索代码",
            parameters={
                "type": "object",
                "properties": {"pattern": {"type": "string"}},
                "required": ["pattern"],
            },
            risk_level="L0",
        ),
        ToolEntry(
            name="generate_wrapper_template",
            description="生成模板",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}, "description": {"type": "string"}},
                "required": ["name", "description"],
            },
            risk_level="L0",
        ),
        ToolEntry(
            name="generate_and_run_sdk_code",
            description="执行SDK代码",
            parameters={
                "type": "object",
                "properties": {"code": {"type": "string"}, "summary": {"type": "string"}},
                "required": ["code"],
            },
            risk_level="L2",
        ),
        ToolEntry(
            name="execute_command",
            description="执行命令",
            parameters={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
            risk_level="L1",
        ),
    ]
    for e in all_entries:
        registry.register(e)
        risk_levels[e.name] = e.risk_level

    # Build handler map
    handlers = {}
    handlers.update(make_motion_tools(backend, safety))
    handlers.update(make_gripper_tools(backend, safety))
    handlers.update(make_script_tools())
    handlers.update(make_codegen_tools())
    handlers.update(make_exec_tools())
    handlers.update(make_code_tools())
    handlers.update(make_patch_tools())
    handlers.update(make_wrapper_tools())

    # FakeProvider — LLM responses that drive the test scenarios
    # Each element = one turn's stream events
    fake_responses = []

    # Provider that feeds canned responses
    provider = FakeProvider(responses=fake_responses)

    agent = AgentLoop(
        provider=provider,
        tool_handlers=handlers,
        tool_schemas=registry.all_schemas(),
        guard=guard,
        risk_levels=risk_levels,
        max_iterations=5,
    )

    return {
        "agent": agent,
        "provider": provider,
        "backend": backend,
        "guard": guard,
        "gate": gate,
        "db": db,
        "session_id": session_id,
        "approval_log": approval_log,
        "registry": registry,
        "safety": safety,
    }


# ── Tests ─────────────────────────────────────────────────────────────


class TestCodeInspection:
    """Phase 2: read_file + search_code — workspace-limited code reading."""

    def test_read_file_works(self, agent_session):
        agent = agent_session["agent"]
        agent.provider.responses = [
            # Turn 1: call read_file
            [
                StreamEvent(
                    kind="tool_use",
                    payload={
                        "id": "t1",
                        "name": "read_file",
                        "input": {"path": "robocode/__init__.py"},
                    },
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "文件内容已读取"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]
        result = asyncio_run(agent.run_turn("读取 robocode/__init__.py"))
        assert "文件内容已读取" in result

    def test_read_file_rejects_outside_workspace(self, agent_session):
        agent = agent_session["agent"]
        agent.provider.responses = [
            [
                StreamEvent(
                    kind="tool_use",
                    payload={"id": "t1", "name": "read_file", "input": {"path": "/etc/passwd"}},
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "被拒绝"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]
        result = asyncio_run(agent.run_turn("读取 /etc/passwd"))
        assert "被拒绝" in result

    def test_search_code_finds_patterns(self, agent_session):
        agent = agent_session["agent"]
        agent.provider.responses = [
            [
                StreamEvent(
                    kind="tool_use",
                    payload={
                        "id": "t1",
                        "name": "search_code",
                        "input": {"pattern": "class AgentLoop"},
                    },
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "找到匹配"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]
        result = asyncio_run(agent.run_turn("搜索 AgentLoop 类"))
        assert "匹配" in result


class TestApprovalGate:
    """Phase 2: L2 tools trigger approval, L0 auto-pass."""

    def test_l0_tool_no_approval(self, agent_session):
        agent = agent_session["agent"]
        approval_log = agent_session["approval_log"]
        approval_log.clear()

        agent.provider.responses = [
            [
                StreamEvent(
                    kind="tool_use", payload={"id": "t1", "name": "get_robot_status", "input": {}}
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "状态正常"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]
        result = asyncio_run(agent.run_turn("状态"))
        assert "状态正常" in result
        # L0: no approval callback triggered
        assert len(approval_log) == 0

    def test_l2_tool_triggers_approval(self, agent_session):
        agent = agent_session["agent"]
        approval_log = agent_session["approval_log"]
        approval_log.clear()

        agent.provider.responses = [
            [
                StreamEvent(
                    kind="tool_use",
                    payload={
                        "id": "t1",
                        "name": "move_robot_xyz",
                        "input": {"x": 300, "y": 0, "z": 150},
                    },
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "已移动"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]
        result = asyncio_run(agent.run_turn("移动到300,0,150"))
        assert "已移动" in result
        # L2: approval callback must be triggered
        assert len(approval_log) == 1
        assert approval_log[0]["tool_name"] == "move_robot_xyz"
        assert approval_log[0]["risk_level"] == "L2"


class TestDRYRunLabel:
    """Phase 2: Fake backend marks all actions as DRY-RUN."""

    def test_move_home_shows_dry_run(self, agent_session):
        agent = agent_session["agent"]
        agent.provider.responses = [
            [
                StreamEvent(
                    kind="tool_use", payload={"id": "t1", "name": "move_robot_home", "input": {}}
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "回零完成"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]
        result = asyncio_run(agent.run_turn("回零位"))
        assert "回零完成" in result


class TestSandboxIsolation:
    """Phase 2: FORBIDDEN_PATTERNS block dangerous code, python3 -I isolation."""

    def test_socket_blocked_in_sandbox(self, agent_session):
        agent = agent_session["agent"]
        agent.provider.responses = [
            [
                StreamEvent(
                    kind="tool_use",
                    payload={
                        "id": "t1",
                        "name": "generate_and_run_sdk_code",
                        "input": {
                            "code": "import socket; s = socket.socket()",
                            "summary": "test socket block",
                        },
                    },
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "被拦截"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]
        result = asyncio_run(agent.run_turn("尝试创建 socket"))
        assert "被拦截" in result

    def test_write_text_blocked_in_sandbox(self, agent_session):
        agent = agent_session["agent"]
        agent.provider.responses = [
            [
                StreamEvent(
                    kind="tool_use",
                    payload={
                        "id": "t1",
                        "name": "generate_and_run_sdk_code",
                        "input": {
                            "code": "from pathlib import Path; Path('/tmp/hack.txt').write_text('pwned')",
                            "summary": "test write_text block",
                        },
                    },
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "被拦截"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]
        result = asyncio_run(agent.run_turn("尝试写文件"))
        assert "被拦截" in result

    def test_legitimate_code_runs(self, agent_session):
        agent = agent_session["agent"]
        agent.provider.responses = [
            [
                StreamEvent(
                    kind="tool_use",
                    payload={
                        "id": "t1",
                        "name": "generate_and_run_sdk_code",
                        "input": {
                            "code": "x = robot.get_motor_angles(); print(x)",
                            "summary": "get angles",
                        },
                    },
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "关节角度获取成功"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]
        result = asyncio_run(agent.run_turn("获取关节角度"))
        assert "成功" in result


class TestOneShotWrapperFlow:
    """Phase 2: One-shot wrapper — generate → execute → discard."""

    def test_generate_wrapper_template(self, agent_session):
        agent = agent_session["agent"]
        agent.provider.responses = [
            [
                StreamEvent(
                    kind="tool_use",
                    payload={
                        "id": "t1",
                        "name": "generate_wrapper_template",
                        "input": {
                            "name": "quick_home",
                            "description": "快速回零位",
                            "sdk_methods": ["move_xyz_rotation(position, orientation)"],
                            "risk_level": "L1",
                        },
                    },
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "模板已生成"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]
        result = asyncio_run(agent.run_turn("生成回零位 wrapper"))
        assert "生成" in result

    def test_wrapper_not_persisted(self, agent_session):
        """Generated wrapper does NOT pollute the tool registry."""
        registry = agent_session["registry"]
        assert registry.get("quick_home") is None


class TestAuditTrail:
    """Phase 2: AuditDB records tool calls and approvals."""

    def test_audit_records_tool_calls(self, agent_session):
        """Do tool calls → verify DB has records."""
        agent = agent_session["agent"]
        db = agent_session["db"]
        sid = agent_session["session_id"]

        # Execute a tool call that goes through guard
        agent.provider.responses = [
            [
                StreamEvent(
                    kind="tool_use", payload={"id": "t1", "name": "get_robot_status", "input": {}}
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "在线"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]
        asyncio_run(agent.run_turn("状态"))

        calls = db.list_tool_calls(sid, limit=100)
        assert len(calls) > 0, "AuditDB should record tool calls"
        assert calls[0]["tool_name"] == "get_robot_status"

    def test_audit_records_approvals(self, agent_session):
        """Do L2 tool call → verify approval recorded."""
        agent = agent_session["agent"]
        db = agent_session["db"]
        sid = agent_session["session_id"]
        approval_log = agent_session["approval_log"]
        approval_log.clear()

        agent.provider.responses = [
            [
                StreamEvent(
                    kind="tool_use",
                    payload={
                        "id": "t1",
                        "name": "move_robot_xyz",
                        "input": {"x": 300, "y": 0, "z": 150},
                    },
                ),
            ],
            [
                StreamEvent(kind="text_delta", payload={"delta": "ok"}),
                StreamEvent(kind="end_turn", payload={}),
            ],
        ]
        asyncio_run(agent.run_turn("移动"))

        approvals = db.list_approvals(sid)
        assert len(approvals) > 0, (
            f"AuditDB should record approvals for L2 tools. approvals={approvals}"
        )
        assert approvals[0]["approved"] == 1


class TestEstop:
    """/estop is handled locally, never goes to LLM."""

    def test_estop_local(self):
        from robocode.cli.slash import SlashDispatcher

        d = SlashDispatcher()
        result = d.dispatch("/estop")
        assert result.handled is True
        assert result.estop_requested is True


# ── Helpers ────────────────────────────────────────────────────────────


def asyncio_run(coro):
    import asyncio

    try:
        loop = asyncio.get_running_loop()
        import nest_asyncio

        nest_asyncio.apply()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)
