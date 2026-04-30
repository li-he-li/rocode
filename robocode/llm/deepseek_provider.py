"""DeepSeek V4 Pro provider via OpenAI-compatible API."""

import json
import structlog
from openai import AsyncOpenAI
from robocode.config import Settings
from robocode.llm.base import LLMProvider, StreamEvent

logger = structlog.get_logger()


def tool_schema_from_registry(registry: dict) -> list[dict]:
    """Convert tool registry entries to OpenAI function-calling schema."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": meta.get("description", ""),
                "parameters": meta.get(
                    "parameters",
                    {"type": "object", "properties": {}},
                ),
            },
        }
        for name, meta in registry.items()
    ]


class DeepSeekProvider(LLMProvider):
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self._client = AsyncOpenAI(
            api_key=self.settings.provider.api_key or "<MISSING>",
            base_url=self.settings.provider.base_url,
        )

    async def stream(self, system: str, messages: list[dict], tools: list[dict]):
        params = {
            "model": self.settings.provider.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "stream": True,
        }
        if tools:
            params["tools"] = tools
        api_stream = await self._client.chat.completions.create(**params)

        tool_use_buffer: dict[int, dict] = {}
        async for chunk in api_stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            if delta.content:
                yield StreamEvent(kind="text_delta", payload={"delta": delta.content})

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index if tc.index is not None else 0
                    buf = tool_use_buffer.setdefault(
                        idx,
                        {"id": "", "name": "", "arguments": ""},
                    )
                    if tc.id:
                        buf["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            buf["name"] = tc.function.name
                        if tc.function.arguments:
                            buf["arguments"] += tc.function.arguments

            reason = chunk.choices[0].finish_reason
            if reason == "tool_calls":
                for _idx, buf in tool_use_buffer.items():
                    try:
                        inp = json.loads(buf["arguments"]) if buf["arguments"] else {}
                    except json.JSONDecodeError:
                        inp = {}
                    yield StreamEvent(
                        kind="tool_use",
                        payload={
                            "id": buf["id"],
                            "name": buf["name"],
                            "input": inp,
                        },
                    )
            elif reason == "stop":
                yield StreamEvent(kind="end_turn", payload={})
            elif reason is not None:
                logger.warning("unhandled_finish_reason", reason=reason)
                yield StreamEvent(
                    kind="error",
                    payload={"message": f"API finish_reason={reason}"},
                )
