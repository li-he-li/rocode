"""Fake LLM 提供者 — 用于测试场景的确定性响应喵~"""

from robocode.llm.base import LLMProvider, StreamEvent


class FakeProvider(LLMProvider):
    """假 LLM 提供者 — 返回预设的 StreamEvent 序列，用于单元测试喵~"""

    def __init__(self, responses: list[list[StreamEvent]] | None = None):
        self.responses = responses or []
        self._call_count = 0
        self.last_system: str | None = None
        self.last_messages: list[dict] | None = None
        self.last_tools: list[dict] | None = None

    async def stream(self, system: str, messages: list[dict], tools: list[dict]):
        """按预设顺序返回响应，超过则返回默认 fake 响应喵~"""
        self.last_system = system
        self.last_messages = list(messages)
        self.last_tools = list(tools)

        if self._call_count < len(self.responses):
            response = self.responses[self._call_count]
            self._call_count += 1
            for event in response:
                yield event
            return

        yield StreamEvent(kind="text_delta", payload={"delta": "fake response"})
        yield StreamEvent(kind="end_turn", payload={})
