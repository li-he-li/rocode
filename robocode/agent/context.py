"""Session context memory — messages and safety state."""


class ContextMemory:
    def __init__(self, max_messages: int = 50):
        self.messages: list[dict] = []
        self.max_messages = max_messages
        self.safety_state: dict = {}

    def add_message(self, role: str, content):
        self.messages.append({"role": role, "content": content})

    def set_safety_state(self, **kwargs):
        self.safety_state.update(kwargs)

    def trim(self):
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]

    def to_llm_messages(self) -> list[dict]:
        return list(self.messages)
