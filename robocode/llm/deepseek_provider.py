"""DeepSeek V4 Pro 提供者 — 通过 OpenAI 兼容 API 流式调用喵~"""

import json
import time
import httpx
from openai import AsyncOpenAI
from robocode.config import Settings
from robocode.llm.base import LLMProvider, StreamEvent
from robocode.services.analytics.logger import get_logger

logger = get_logger("llm")


class DeepSeekProvider(LLMProvider):
    """DeepSeek 模型的异步流式提供者喵~"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        http_client = httpx.AsyncClient(trust_env=False)  # 不读系统代理
        self._client = AsyncOpenAI(
            api_key=self.settings.provider.api_key or "<MISSING>",
            base_url=self.settings.provider.base_url,
            http_client=http_client,
        )

    async def stream(self, system: str, messages: list[dict], tools: list[dict]):
        """异步流式生成 — 解析 text_delta / tool_use / reasoning / metadata 事件喵~"""
        t0 = time.perf_counter()
        text_chars = 0
        params = {
            "model": self.settings.provider.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "stream": True,
            "max_tokens": 8192,  # thinking 开启需要更大 token 预算喵~
        }
        if not self.settings.provider.thinking_enabled:
            params["extra_body"] = {"thinking": {"type": "disabled"}}
        if tools:
            params["tools"] = tools
        api_stream = await self._client.chat.completions.create(**params)

        tool_use_buffer: dict[int, dict] = {}  # index → {id, name, arguments}
        reasoning_parts: list[str] = []
        finish_reason = ""

        async for chunk in api_stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            if delta.content:
                text_chars += len(delta.content)
                yield StreamEvent(kind="text_delta", payload={"delta": delta.content})

            # 提取推理内容（DeepSeek 特有）
            rc = getattr(delta, "reasoning_content", None)
            if rc is None and hasattr(delta, "model_extra") and delta.model_extra:
                rc = delta.model_extra.get("reasoning_content")
            if rc:
                reasoning_parts.append(rc)

            # 累积 tool_calls 片段
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index if tc.index is not None else 0
                    buf = tool_use_buffer.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        buf["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            buf["name"] = tc.function.name
                        if tc.function.arguments:
                            buf["arguments"] += tc.function.arguments

            reason = chunk.choices[0].finish_reason
            if reason:
                finish_reason = reason

            if reason == "tool_calls":
                # 工具调用 — 先发推理内容，再逐个发 tool_use 事件喵~
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
                        payload={"id": buf["id"], "name": buf["name"], "input": inp},
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

        # 流结束时发 metadata 事件喵~
        latency_ms = (time.perf_counter() - t0) * 1000
        yield StreamEvent(
            kind="metadata",
            payload={
                "model": self.settings.provider.model,
                "finish_reason": finish_reason,
                "latency_ms": round(latency_ms, 1),
                "completion_chars": text_chars,
                "completion_tokens_est": max(1, text_chars // 4),
            },
        )
