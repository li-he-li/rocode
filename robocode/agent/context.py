"""Session context memory — messages follow OpenAI tool-calling spec:
user/assistant/tool roles, assistant may have tool_calls, tool requires tool_call_id."""

import json


class ContextMemory:
    def __init__(self, max_messages: int = 50):
        self.messages: list[dict] = []
        self.max_messages = max_messages
        self.safety_state: dict = {}

    def to_json(self) -> str:
        """Serialize context to JSON for checkpoint persistence."""
        return json.dumps(
            {
                "messages": self.messages,
                "max_messages": self.max_messages,
                "safety_state": self.safety_state,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, data: str) -> "ContextMemory":
        """Restore context from serialized JSON."""
        obj = json.loads(data)
        ctx = cls(max_messages=obj.get("max_messages", 50))
        ctx.messages = obj.get("messages", [])
        ctx.safety_state = obj.get("safety_state", {})
        return ctx

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
        """Legacy helper for tests — prefer add_user_message/add_assistant_message/add_tool_result."""
        self.messages.append({"role": role, "content": content})

    def set_safety_state(self, **kwargs):
        self.safety_state.update(kwargs)

    def trim(self):
        if len(self.messages) <= self.max_messages:
            return
        self.messages = self.messages[-self.max_messages :]
        # Remove orphaned tool messages at start (no preceding assistant tool_calls)
        while self.messages and self.messages[0].get("role") == "tool":
            self.messages.pop(0)

    def scrub_orphaned_tools(self):
        """Remove tool messages that lack a preceding assistant tool_calls."""
        cleaned = []
        has_pending_tool_calls = False
        for msg in self.messages:
            role = msg.get("role", "")
            if role == "assistant" and msg.get("tool_calls"):
                has_pending_tool_calls = True
                cleaned.append(msg)
            elif role == "tool" and not has_pending_tool_calls:
                continue  # orphaned, skip
            elif role == "tool":
                cleaned.append(msg)
            else:
                has_pending_tool_calls = False
                cleaned.append(msg)
        self.messages = cleaned

    def to_llm_messages(self) -> list[dict]:
        self.scrub_orphaned_tools()
        return list(self.messages)
