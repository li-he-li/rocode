"""Agent ReAct loop — stream → collect tool_uses → execute → feed back."""

import json
import asyncio
import structlog

from robocode.llm.base import LLMProvider, StreamEvent
from robocode.agent.context import ContextMemory
from robocode.utils.models import ToolResult
from robocode.orchestrator.state_machine import Orchestrator, OrchestratorState

logger = structlog.get_logger()

SYSTEM_PROMPT = """你是一个专业的机器人控制助手，控制一台 Episode 6 轴机械臂。

## 运行环境
- 所有 6D 标定和 6D 抓取操作必须通过 conda `episode` 环境执行
- 工具内部已自动使用 `conda run -n episode`，你无需手动指定环境
- 如需通过 execute_command 运行 6D 相关脚本，命令前加 `conda run -n episode python3`
- Agent 本身运行在 .venv (Python 3.12)，不要混淆

## 意图判断
每轮对话首先判断用户意图：
- CHAT: 闲聊问候、事实询问、概念解释，纯文本回应，不调工具
- QUERY: 查询机器人状态、标定信息，调用 L0 只读工具
- ACTION: 执行机器人动作，调用 L1/L2 工具（需要审批）
- CODE: 现有工具无法满足时，编写 SDK 代码实现自定义动作

## 6D 标定（6d_calibration）
- 用途：标定相机→机械臂末端变换 T_camera2end，供 6D 抓取使用
- 前提：RealSense D435 已连接、SDK Server 运行中、棋盘格标定板就位
- 流程：示教(人工)→采集→计算→标定，共 4 步，需人工操作 GUI
- 工具调用路径：用 run_script 或 /6d_calibration 斜杠命令
- 执行时自动使用 conda episode 环境

## 6D 抓取（6d_grasp）
- 用途：自然语言指令驱动 VLM 检测 + GraspNet 规划 + IK 执行抓取
- 前提：conda episode 环境、SDK Server、RealSense、T_camera2end.yaml 标定文件
- 流程：VLM解析→采集检测→加载模型→GraspNet推理筛选→IK迭代执行放置
- 工具调用：直接调用 6d_grasp(instruction="自然语言指令")
- 观察位姿：抓取开始前机械臂自动移动到预设观察位姿
- 执行时自动使用 conda episode 环境

## 执行原则
- 不确定时主动提问澄清，不要猜测
- 抓取前先调用 get_robot_status 确认机器人状态
- 工具调用失败时，把具体错误信息汇报给用户，不要自行调试多轮
- 不要假装执行了动作，必须等待工具返回结果
- 保持自然对话感，不要过于机械"""


class AgentLoop:
    SYSTEM_PROMPT = SYSTEM_PROMPT

    def __init__(
        self,
        provider: LLMProvider,
        tool_handlers: dict | None = None,
        tool_schemas: list[dict] | None = None,
        max_iterations: int = 20,
        guard=None,
        risk_levels: dict[str, str] | None = None,
        orchestrator: Orchestrator | None = None,
        db=None,
        session_id: str = "",
    ):
        self.provider = provider
        self.tool_handlers = tool_handlers or {}
        self.tool_schemas = tool_schemas or []
        self.max_iterations = max_iterations
        self.context = ContextMemory()
        self.guard = guard
        self.risk_levels = risk_levels or {}
        self.orchestrator = orchestrator or Orchestrator()
        self._db = db
        self._session_id = session_id

    async def execute_tool(self, event: StreamEvent) -> dict:
        return await self._execute_tool(event)

    async def run_turn(self, user_input: str) -> str:
        self.orchestrator.state = OrchestratorState.PLANNING
        self.context.add_user_message(user_input)
        last_text = ""

        for iteration in range(self.max_iterations):
            # Collect tool_uses so we can build the assistant message
            tool_uses: list[StreamEvent] = []
            reasoning_content = ""

            async for event in self.provider.stream(
                system=SYSTEM_PROMPT,
                messages=self.context.to_llm_messages(),
                tools=self.tool_schemas,
            ):
                if event.kind == "text_delta":
                    last_text += event.payload.get("delta", "")
                elif event.kind == "reasoning":
                    reasoning_content = event.payload.get("reasoning_content", "")
                elif event.kind == "tool_use":
                    tool_uses.append(event)
                elif event.kind == "end_turn":
                    reasoning_content = event.payload.get("reasoning_content", "")
                    if last_text.strip():
                        self.context.add_assistant_message(
                            last_text, reasoning_content=reasoning_content
                        )
                    self.context.trim()
                    self.orchestrator.state = OrchestratorState.SUCCESS
                    self._save_checkpoint()
                    return last_text or "ok"
                elif event.kind == "error":
                    self.context.trim()
                    self.orchestrator.state = OrchestratorState.FAILED
                    self._save_checkpoint()
                    return f"API 错误: {event.payload.get('message', 'unknown')}"

            # After stream ends with tool_calls, record assistant message + execute tools
            if tool_uses:
                self.orchestrator.state = OrchestratorState.EXECUTING
                assistant_tool_calls = [
                    {
                        "id": tu.payload.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tu.payload.get("name", ""),
                            "arguments": json.dumps(
                                tu.payload.get("input", {}), ensure_ascii=False
                            ),
                        },
                    }
                    for tu in tool_uses
                ]
                self.context.add_assistant_message(
                    tool_calls=assistant_tool_calls, reasoning_content=reasoning_content
                )

                for tu in tool_uses:
                    result = await self._execute_tool(tu)
                    self.context.add_tool_result(
                        tool_call_id=tu.payload.get("id", ""),
                        tool_name=tu.payload.get("name", ""),
                        result=json.dumps(result, ensure_ascii=False),
                    )

        self.context.trim()
        self.orchestrator.state = OrchestratorState.FAILED
        self._save_checkpoint()
        return "已达最大迭代次数，任务未完成。"

    def _save_checkpoint(self):
        if self._db and self._session_id:
            try:
                self._db.save_checkpoint(
                    self._session_id,
                    self.orchestrator.state.value,
                    {},
                    step_index=len([m for m in self.context.messages if m.get("role") == "tool"]),
                )
            except Exception:
                pass

    async def _execute_tool(self, event: StreamEvent) -> dict:
        import time as _time

        payload = event.payload
        tool_name = payload.get("name", "")
        tool_input = payload.get("input", {})

        handler = self.tool_handlers.get(tool_name)
        if handler is None:
            logger.warning("unknown_tool_requested", tool_name=tool_name)
            return ToolResult(
                success=False,
                message=f"未知工具: {tool_name}",
            ).model_dump(mode="json")

        # Guard check before execution (backward compatible: guard=None skips)
        risk_level = self.risk_levels.get(tool_name, "L0")
        if self.guard is not None:
            gr = await self.guard.check(
                tool_name=tool_name,
                risk_level=risk_level,
                params=tool_input,
                summary=tool_input.get("summary", tool_input.get("instruction", "")),
            )
            if not gr.allowed:
                return ToolResult(
                    success=False,
                    message=f"操作被拒绝: {gr.reason}",
                    metrics={"decision": gr.decision},
                ).model_dump(mode="json")

        t0 = _time.perf_counter()
        try:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**tool_input)
            else:
                result = await asyncio.to_thread(handler, **tool_input)
            rv = result.model_dump(mode="json") if isinstance(result, ToolResult) else result
            duration_ms = (_time.perf_counter() - t0) * 1000
            # Runtime log
            from robocode.utils.runtime_log import log_tool_call

            log_tool_call(tool_name, risk_level, tool_input, rv, duration_ms, self._session_id)
            # Record to audit DB
            if self.guard is not None:
                self.guard.record_call(tool_name, risk_level, tool_input, rv)
            return rv
        except Exception:
            duration_ms = (_time.perf_counter() - t0) * 1000
            logger.exception("tool_execution_failed", tool_name=tool_name, input=tool_input)
            error_result = ToolResult(
                success=False,
                message=f"工具 {tool_name} 执行异常",
            ).model_dump(mode="json")
            from robocode.utils.runtime_log import log_tool_call

            log_tool_call(
                tool_name, risk_level, tool_input, error_result, duration_ms, self._session_id
            )
            if self.guard is not None:
                self.guard.record_call(tool_name, risk_level, tool_input, error_result)
            return error_result
