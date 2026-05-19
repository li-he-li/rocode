"""Fake LLM provider for deterministic test scenarios."""

from robocode.llm.base import LLMProvider, StreamEvent


class FakeProvider(LLMProvider):
    def __init__(self, responses: list[list[StreamEvent]] | None = None):
        self.responses = responses or []
        self._call_count = 0
        self.last_system: str | None = None
        self.last_messages: list[dict] | None = None
        self.last_tools: list[dict] | None = None

    async def stream(self, system: str, messages: list[dict], tools: list[dict]):
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
