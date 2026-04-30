"""LLM provider abstract interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamEvent:
    kind: str  # "text_delta" | "tool_use" | "end_turn"
    payload: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    @abstractmethod
    async def stream(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
    ) -> AsyncIterator[StreamEvent]: ...
