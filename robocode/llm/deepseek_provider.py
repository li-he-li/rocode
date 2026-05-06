"""DeepSeek V4 Pro provider via OpenAI-compatible API."""

import json
import structlog
from openai import AsyncOpenAI
from robocode.config import Settings
from robocode.llm.base import LLMProvider, StreamEvent

logger = structlog.get_logger()


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
            "max_tokens": 2048,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        if tools:
            params["tools"] = tools
        api_stream = await self._client.chat.completions.create(**params)

        tool_use_buffer: dict[int, dict] = {}
        reasoning_parts: list[str] = []
        async for chunk in api_stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            if delta.content:
                yield StreamEvent(kind="text_delta", payload={"delta": delta.content})

            rc = getattr(delta, "reasoning_content", None)
            if rc is None and hasattr(delta, "model_extra") and delta.model_extra:
                rc = delta.model_extra.get("reasoning_content")
            if rc:
                reasoning_parts.append(rc)

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
                if reasoning_parts:
                    yield StreamEvent(
                        kind="reasoning",
                        payload={"reasoning_content": "".join(reasoning_parts)},
                    )
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
                end_payload = {}
                if reasoning_parts:
                    end_payload["reasoning_content"] = "".join(reasoning_parts)
                yield StreamEvent(kind="end_turn", payload=end_payload)
            elif reason is not None:
                logger.warning("unhandled_finish_reason", reason=reason)
                yield StreamEvent(
                    kind="error",
                    payload={"message": f"API finish_reason={reason}"},
                )
