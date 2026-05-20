"""Session context memory — messages follow OpenAI tool-calling spec:
user/assistant/tool roles, assistant may have tool_calls, tool requires tool_call_id.
"""

import json


# Correction keywords — user messages containing these are preserved during trim
_CORRECTION_KW = ("不对", "改成", "应该是", "纠正", "别", "不要", "换", "这才对")


def _is_correction(msg: dict) -> bool:
    content = msg.get("content", "")
    return any(kw in content for kw in _CORRECTION_KW)


class ContextMemory:
    def __init__(self, max_tokens: int = 15000):
        self.messages: list[dict] = []
        self.max_tokens = max_tokens
        self.safety_state: dict = {}

    # ── serialization ─────────────────────────────────────────────────

    def to_json(self) -> str:
        return json.dumps(
            {
                "messages": self.messages,
                "max_tokens": self.max_tokens,
                "safety_state": self.safety_state,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, data: str) -> "ContextMemory":
        obj = json.loads(data)
        # Backward compat: old checkpoints stored max_messages
        max_tok = obj.get("max_tokens", 15000)
        if "max_messages" in obj and "max_tokens" not in obj:
            max_tok = obj["max_messages"] * 300  # rough: 300 tokens/msg avg
        ctx = cls(max_tokens=max_tok)
        ctx.messages = obj.get("messages", [])
        ctx.safety_state = obj.get("safety_state", {})
        return ctx

    # ── adders ────────────────────────────────────────────────────────

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(
        self, content: str = "", tool_calls: list[dict] | None = None, reasoning_content: str = ""
    ):
        msg = {"role": "assistant", "content": content or None}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if reasoning_content:
            msg["reasoning_content"] = reasoning_content
        self.messages.append(msg)

    def add_tool_result(self, tool_call_id: str, tool_name: str, result: str):
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result,
            }
        )

    def add_message(self, role: str, content: str):
        """Legacy helper for tests."""
        self.messages.append({"role": role, "content": content})

    def set_safety_state(self, **kwargs):
        self.safety_state.update(kwargs)

    # ── token estimation ──────────────────────────────────────────────

    @staticmethod
    def _estimate_tokens(msg: dict) -> int:
        """Rough token count: chars // 2 for mixed Chinese/English text."""
        chars = 0
        for key in ("content", "reasoning_content"):
            v = msg.get(key)
            if isinstance(v, str):
                chars += len(v)
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                fn = tc.get("function", {})
                chars += len(fn.get("name", ""))
                args = fn.get("arguments", "")
                chars += (
                    len(args)
                    if isinstance(args, str)
                    else len(json.dumps(args, ensure_ascii=False))
                )
        return max(1, chars // 2)

    def _total_tokens(self) -> int:
        return sum(self._estimate_tokens(m) for m in self.messages)

    # ── priority scoring for trim ─────────────────────────────────────

    @staticmethod
    def _msg_priority(msg: dict) -> int:
        """Higher = more valuable, drop lower first."""
        role = msg.get("role", "")
        if role == "user" and _is_correction(msg):
            return 5  # user correction — never drop
        if role == "user":
            return 4  # user instruction
        if role == "assistant" and msg.get("tool_calls"):
            return 3  # tool call decision
        if role == "assistant":
            return 2  # assistant text
        if role == "tool":
            return 1  # tool result — drop first
        return 0

    # ── trim ──────────────────────────────────────────────────────────

    def trim(self):
        """Drop low-priority messages until under max_tokens.

        Priority (lowest dropped first): tool results > assistant text >
        assistant tool_calls (with results) > user messages.
        User corrections (priority 5) are never dropped.
        """
        if self._total_tokens() <= self.max_tokens:
            return

        # Score each message
        scored = [(self._msg_priority(m), i) for i, m in enumerate(self.messages)]

        # Build removal queue: lowest priority, earliest first
        removable = [(pri, i) for pri, i in scored if pri < 5]
        removable.sort(key=lambda x: (x[0], x[1]))

        # Find assistant→tool_result links so we can cascade drops
        tool_to_assistant: dict[int, int] = {}  # tool_result_idx → assistant_idx
        prev_assistant = -1
        for i, m in enumerate(self.messages):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                prev_assistant = i
            elif m.get("role") == "tool" and prev_assistant >= 0:
                tool_to_assistant[i] = prev_assistant

        removed = set()
        for pri, idx in removable:
            if idx in removed:
                continue
            removed.add(idx)

            # Cascade: if we drop an assistant with tool_calls, drop its tool results
            msg = self.messages[idx]
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for ti, ai in tool_to_assistant.items():
                    if ai == idx:
                        removed.add(ti)

        self.messages = [m for i, m in enumerate(self.messages) if i not in removed]
        self.scrub_orphaned_tools()

        # Still over? Drop from head (oldest first) except corrections
        if self._total_tokens() > self.max_tokens:
            kept = []
            budget = self.max_tokens
            for m in reversed(self.messages):
                if _is_correction(m):
                    kept.insert(0, m)
                    budget -= self._estimate_tokens(m)
                    continue
                cost = self._estimate_tokens(m)
                if budget >= cost:
                    kept.insert(0, m)
                    budget -= cost
            self.messages = kept
            self.scrub_orphaned_tools()

    # ── scrub orphaned tools ──────────────────────────────────────────

    def scrub_orphaned_tools(self):
        """Remove orphaned tool messages AND assistant tool_calls without results."""
        cleaned = []
        has_pending_tool_calls = False
        for msg in self.messages:
            role = msg.get("role", "")
            if role == "assistant" and msg.get("tool_calls"):
                has_pending_tool_calls = True
                cleaned.append(msg)
            elif role == "tool" and not has_pending_tool_calls:
                continue
            elif role == "tool":
                cleaned.append(msg)
            else:
                has_pending_tool_calls = False
                cleaned.append(msg)

        result_ids = {m.get("tool_call_id") for m in cleaned if m.get("role") == "tool"}
        final = []
        for msg in cleaned:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                call_ids = {tc.get("id") for tc in msg["tool_calls"]}
                if not call_ids.issubset(result_ids):
                    continue
            final.append(msg)
        self.messages = final

    def to_llm_messages(self) -> list[dict]:
        self.scrub_orphaned_tools()
        return list(self.messages)
