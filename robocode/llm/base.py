"""LLM 提供者抽象接口 — 流式事件类型定义喵~"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class ToolUse:
    """LLM 返回的工具调用喵~"""

    id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamEvent:
    """流式事件 — 统一的事件类型喵~

    kind 可以是: text_delta, tool_use, end_turn, metadata, reasoning, error
    """

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """LLM 提供者抽象基类 — 所有 LLM 实现必须实现 stream 方法喵~"""

    @abstractmethod
    async def stream(
        self,
        system: str,  # 系统 prompt
        messages: list[dict],  # 对话历史
        tools: list[dict],  # 工具 schema 列表
    ) -> AsyncIterator[StreamEvent]:
        """异步流式生成，逐事件 yield 喵~"""
        ...
