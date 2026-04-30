"""Agent ReAct loop — stream → collect tool_uses → execute → feed back."""

import json
import asyncio
import structlog

from robocode.llm.base import LLMProvider, StreamEvent
from robocode.agent.context import ContextMemory
from robocode.utils.models import ToolResult

logger = structlog.get_logger()

SYSTEM_PROMPT = """你是一个专业的机器人控制助手，控制一台 Episode 6 轴机械臂。

## 意图判断
每轮对话首先判断用户意图：
- CHAT: 闲聊问候、事实询问、概念解释，纯文本回应，不调工具
- QUERY: 查询机器人状态、标定信息，调用 L0 只读工具
- ACTION: 执行机器人动作，调用 L1/L2 工具（需要审批）
- CODE: 现有工具无法满足时，编写 SDK 代码实现自定义动作

## 执行原则
- 不确定时主动提问澄清，不要猜测
- 抓取前先检测确认目标存在
- 动作失败时分析原因，尝试替代方案
- 不要假装执行了动作，必须等待工具返回结果
- 保持自然对话感，不要过于机械"""


class AgentLoop:
    def __init__(
        self,
        provider: LLMProvider,
        tool_handlers: dict | None = None,
        tool_schemas: list[dict] | None = None,
        max_iterations: int = 20,
    ):
        self.provider = provider
        self.tool_handlers = tool_handlers or {}
        self.tool_schemas = tool_schemas or []
        self.max_iterations = max_iterations
        self.context = ContextMemory()

    async def run_turn(self, user_input: str) -> str:
        self.context.add_message("user", user_input)
        last_text = ""

        for iteration in range(self.max_iterations):
            async for event in self.provider.stream(
                system=SYSTEM_PROMPT,
                messages=self.context.to_llm_messages(),
                tools=self.tool_schemas,
            ):
                if event.kind == "text_delta":
                    last_text = event.payload.get("delta", "")
                elif event.kind == "tool_use":
                    result = await self._execute_tool(event)
                    self.context.add_message(
                        "tool_result",
                        json.dumps(result, ensure_ascii=False),
                    )
                elif event.kind == "end_turn":
                    self.context.trim()
                    return last_text or "ok"
                elif event.kind == "error":
                    self.context.trim()
                    return f"API 错误: {event.payload.get('message', 'unknown')}"

        self.context.trim()
        return "已达最大迭代次数，任务未完成。"

    async def _execute_tool(self, event: StreamEvent) -> dict:
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

        try:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**tool_input)
            else:
                result = handler(**tool_input)
            if isinstance(result, ToolResult):
                return result.model_dump(mode="json")
            return result
        except Exception:
            logger.exception("tool_execution_failed", tool_name=tool_name, input=tool_input)
            return ToolResult(
                success=False,
                message=f"工具 {tool_name} 执行异常",
            ).model_dump(mode="json")
