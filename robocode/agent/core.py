"""Agent ReAct loop — stream → collect tool_uses → execute → feed back."""

import json
import asyncio

from robocode.llm.base import LLMProvider, StreamEvent
from robocode.agent.context import ContextMemory
from robocode.utils.models import ToolResult
from robocode.orchestrator.state_machine import OrchestratorState
from robocode.services.analytics.logger import get_logger

logger = get_logger("agent")


def _summarize_params(params: dict, max_len: int = 80) -> str:
    """Summarize tool params, truncating long values like code blocks."""
    parts = []
    for k, v in params.items():
        if isinstance(v, str) and len(v) > max_len:
            v = v[:max_len] + "..."
        elif isinstance(v, (list, dict)):
            v = f"<{len(v)} items>"
        parts.append(f"{k}={v}")
    return ", ".join(parts)


SYSTEM_PROMPT = """你是一个专业的机器人控制助手，控制一台 Episode 6 轴机械臂。

## 运行环境
- 6D 标定/抓取通过 conda `episode` 环境执行，工具内部已自动处理

## 意图判断
每轮对话首先判断用户意图：
- CHAT: 闲聊问候、概念解释，纯文本回应，不调工具
- QUERY: 查询机器人状态、标定信息，调用 L0 只读工具
- ACTION: 执行机器人动作，调用 L1/L2 工具（需要审批）
- CODE: 现有工具无法满足时，编写 SDK 代码实现自定义动作

## 6D 标定与抓取
- 6D 标定（6d_calibration）：标定 T_camera2end，4 步示教→采集→计算→标定，需人工操作 GUI
- 6D 抓取（6d_grasp）：VLM 检测 + GraspNet 规划 + IK 执行，直接调用 6d_grasp(instruction="自然语言指令")

## VLM 视觉感知
- **observe(prompt)**: 拍摄桌面并用 VLM 分析，返回结构化观察结果和后续建议。首次用宽泛 prompt，根据 suggestions 决定是否跟进第二轮
- **locate(target)**: 定位物体返回 3D 坐标 (mm)，必须先 observe 确认物体在视野中再调用
- 移动前 observe 确认无障碍，抓取/放置后 observe 验证结果

## 执行原则（硬约束）
1. **先查后动**：任何移动/夹爪操作前，必须先调用 get_robot_status 确认状态。定位前必须先 observe
2. **一步一验**：每轮只做一个动作，等结果返回并验证后再决定下一步。不要连续发送多个 tool_call
3. **失败即停**：工具调用失败时汇报用户，不要自行多轮调试。连续操作无效果时停下来汇报当前状态
4. **不盲猜**：不确定时主动提问澄清。不要假装执行了动作，必须等待工具返回结果"""


# 重复调用检测白名单：这些工具允许连续多次调用喵~
_DUPLICATE_WHITELIST = {"observe", "get_robot_status", "read_file", "search_code", "list_skills"}

# 前置依赖映射：工具 → (前置工具, 缺失时的提醒文本) 喵~
_PREREQUISITES: dict[str, tuple[str, str]] = {
    "move_robot_xyz": ("get_robot_status", "请先调用 get_robot_status 确认机器人状态"),
    "move_robot_joints": ("get_robot_status", "请先调用 get_robot_status 确认当前关节角度"),
    "move_robot_home": ("get_robot_status", "请先调用 get_robot_status 确认机器人状态"),
    "move_path": ("get_robot_status", "请先调用 get_robot_status 确认机器人状态"),
    "locate": ("observe", "请先调用 observe 确认物体在视野中"),
    "control_suction": ("get_robot_status", "请先调用 get_robot_status 确认机器人状态"),
    "servo_gripper_control": ("get_robot_status", "请先调用 get_robot_status 确认机器人状态"),
}


class AgentLoop:
    SYSTEM_PROMPT = SYSTEM_PROMPT

    def __init__(
        self,
        provider: LLMProvider,
        tool_handlers: dict | None = None,
        tool_schemas: list[dict] | None = None,
        max_iterations: int = 20,
        guard=None,
        risk_levels: dict[str, str] | None = None,
        db=None,
        session_id: str = "",
        metrics=None,
        physics_collector=None,
        annotation_collector=None,
        experience_reader=None,
        hook_registry=None,
    ):
        self.provider = provider
        self.tool_handlers = tool_handlers or {}
        self.tool_schemas = tool_schemas or []
        self.max_iterations = max_iterations
        self.context = ContextMemory(max_tokens=15000)
        self.guard = guard
        self.risk_levels = risk_levels or {}
        self._state = OrchestratorState.IDLE
        self._db = db
        self._session_id = session_id
        self._metrics = metrics
        self._physics_collector = physics_collector
        self._annotation_collector = annotation_collector
        self._experience_reader = experience_reader
        self._hook_registry = hook_registry
        self._turn_number = 0
        self._prev_call_id: int | None = None
        self._current_task_instruction: str | None = None
        self._system_prompt = self._build_system_prompt()

        # ── 程序层硬约束状态 ──
        self._turn_tool_history: list[str] = []  # 当前 turn 已调用工具列表
        self._last_call_key: tuple | None = None  # (tool_name, param_hash)
        self._last_call_count: int = 0  # 连续相同次数

    async def execute_tool(self, event: StreamEvent) -> dict:
        return await self._execute_tool(event)

    async def run_turn(self, user_input: str) -> str:
        self._state = OrchestratorState.PLANNING
        self.context.add_user_message(user_input)
        self._current_task_instruction = user_input
        self._turn_number = 0
        self._prev_call_id = None
        self._turn_tool_history = []
        self._last_call_key = None
        self._last_call_count = 0
        last_text = ""

        for iteration in range(self.max_iterations):
            tool_uses: list[StreamEvent] = []
            reasoning_content = ""

            async for event in self.provider.stream(
                system=self._system_prompt,
                messages=self.context.to_llm_messages(),
                tools=self.tool_schemas,
            ):
                if event.kind == "text_delta":
                    last_text += event.payload.get("delta", "")
                elif event.kind == "reasoning":
                    reasoning_content = event.payload.get("reasoning_content", "")
                elif event.kind == "tool_use":
                    tool_uses.append(event)
                elif event.kind == "end_turn":
                    reasoning_content = event.payload.get("reasoning_content", "")
                    if last_text.strip():
                        self.context.add_assistant_message(
                            last_text, reasoning_content=reasoning_content
                        )
                    self.context.trim()
                    self._state = OrchestratorState.SUCCESS
                    self._save_checkpoint()
                    return last_text or "ok"
                elif event.kind == "metadata":
                    logger.info(
                        "llm_metadata",
                        model=event.payload.get("model"),
                        latency_ms=event.payload.get("latency_ms"),
                        completion_chars=event.payload.get("completion_chars", 0),
                    )
                    if self._metrics is not None:
                        self._metrics.record("llm_call_total")
                        self._metrics.record_latency("llm_call", event.payload.get("latency_ms", 0))
                elif event.kind == "error":
                    self.context.trim()
                    self._state = OrchestratorState.FAILED
                    self._save_checkpoint()
                    return f"API 错误: {event.payload.get('message', 'unknown')}"

            # 每轮只执行第一个工具，强制"一步一验证"喵~
            # 剩余的 tool_use 被丢弃，下一轮 LLM 看到结果后自然会决定下一步
            if tool_uses:
                self._state = OrchestratorState.EXECUTING
                first = tool_uses[0]
                assistant_tool_calls = [
                    {
                        "id": first.payload.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": first.payload.get("name", ""),
                            "arguments": json.dumps(
                                first.payload.get("input", {}), ensure_ascii=False
                            ),
                        },
                    }
                ]
                self.context.add_assistant_message(
                    tool_calls=assistant_tool_calls, reasoning_content=reasoning_content
                )

                result = await self._execute_tool(first)
                self.context.add_tool_result(
                    tool_call_id=first.payload.get("id", ""),
                    tool_name=first.payload.get("name", ""),
                    result=json.dumps(result, ensure_ascii=False),
                )

        self.context.trim()
        self._state = OrchestratorState.FAILED
        self._save_checkpoint()
        return "已达最大迭代次数，任务未完成。"

    _HARDWARE_SPEC_CACHE: str | None = None

    @classmethod
    def _load_hardware_spec(cls) -> str:
        """加载 episode1-spec.md，类级别缓存喵~"""
        if cls._HARDWARE_SPEC_CACHE is not None:
            return cls._HARDWARE_SPEC_CACHE
        from pathlib import Path

        spec_path = (
            Path(__file__).resolve().parent.parent / "experience" / "hardware" / "episode1-spec.md"
        )
        try:
            raw = spec_path.read_text(encoding="utf-8")
            if raw.startswith("---"):
                end = raw.find("---", 3)
                if end != -1:
                    raw = raw[end + 3 :].strip()
            cls._HARDWARE_SPEC_CACHE = raw
        except Exception:
            logger.warning("hardware_spec_load_failed", path=str(spec_path))
            cls._HARDWARE_SPEC_CACHE = ""
        return cls._HARDWARE_SPEC_CACHE

    def _build_system_prompt(self) -> str:
        """构建 system prompt：核心 prompt + 硬件手册 + 经验目录喵~"""
        prompt = SYSTEM_PROMPT
        spec = self._load_hardware_spec()
        if spec:
            prompt += "\n\n## 硬件手册（强制已知——回答任何关节/位姿/方向问题前必须对照）\n\n" + spec
        if self._experience_reader is not None:
            summary = self._experience_reader.get_index_summary()
            if summary:
                prompt += "\n\n" + summary
        return prompt

    def get_conversation_transcript(self) -> list[dict]:
        """Build structured transcript for the Reflector LLM.

        Each entry has role-specific fields:
          - user: content (max 500 chars)
          - tool_call: tool name, params (max 200 chars)
          - tool_result: success flag, message (max 300 chars, NO placeholders)
        """
        transcript: list[dict] = []
        for msg in self.context.messages:
            role = msg.get("role", "")
            if role == "user":
                content = msg.get("content", "")
                if content.strip():
                    transcript.append({"role": "user", "content": content[:500]})
            elif role == "assistant":
                text = msg.get("content") or ""
                tool_calls = msg.get("tool_calls") or []
                if text.strip():
                    transcript.append({"role": "assistant", "content": text[:300]})
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    args_str = fn.get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    params_str = _summarize_params(args, max_len=200)
                    transcript.append(
                        {
                            "role": "tool_call",
                            "tool": fn.get("name", "?"),
                            "params": params_str,
                        }
                    )
            elif role == "tool":
                result_str = msg.get("content", "{}")
                try:
                    result = json.loads(result_str) if isinstance(result_str, str) else result_str
                    success = result.get("success", True)
                    message = str(result.get("message", "")) if isinstance(result, dict) else ""
                except (json.JSONDecodeError, TypeError):
                    success = True
                    message = ""
                transcript.append(
                    {
                        "role": "tool_result",
                        "success": success,
                        "message": message[:300],
                    }
                )
        return transcript

    def inject_failure_annotation(self, tool_name: str, failures: list[str]):
        """Inject failure annotation into current conversation context."""
        failure_summary = "；".join(failures)
        self.context.add_user_message(
            f"[系统反馈] 上一操作 {tool_name} 标注为失败：{failure_summary}。"
            f"请在后续操作中注意避免此问题。"
        )

    def _save_checkpoint(self):
        if self._db and self._session_id:
            try:
                self._db.save_checkpoint(
                    self._session_id,
                    self._state.value,
                    {"context_json": self.context.to_json()},
                    step_index=len([m for m in self.context.messages if m.get("role") == "tool"]),
                )
            except Exception:
                logger.exception("checkpoint_save_failed")

    def _get_tool_tips(self, tool_name: str) -> list[str]:
        if self._experience_reader is None:
            return []
        return self._experience_reader.get_tool_tips(tool_name)

    # ── 程序层硬约束：重复调用检测 ───────────────────────────────

    @staticmethod
    def _param_key(tool_name: str, tool_input: dict) -> str:
        """提取工具参数的可哈希键，用于重复检测喵~"""
        if tool_name == "move_robot_joints":
            return json.dumps(tool_input.get("angles", []))
        elif tool_name == "move_robot_xyz":
            return json.dumps([tool_input.get(k) for k in ("x", "y", "z")])
        elif tool_name == "execute_command":
            return tool_input.get("command", "")
        elif tool_name == "read_file":
            return tool_input.get("path", "")
        elif tool_name == "locate":
            return tool_input.get("target", "")
        elif tool_name == "control_suction":
            return tool_input.get("action", "")
        elif tool_name == "servo_gripper_control":
            return str(tool_input.get("angle", ""))
        else:
            return json.dumps(tool_input, sort_keys=True)

    def _check_duplicate_call(self, tool_name: str, tool_input: dict) -> dict | None:
        """检测连续重复调用，返回 {"block": bool, "msg": str} 或 None 喵~

        第 1 次：放行 (None)
        第 2 次：放行 + 追加警告
        第 3+ 次：拦截返回错误
        白名单工具不检测。
        """
        if tool_name in _DUPLICATE_WHITELIST:
            return None

        key = self._param_key(tool_name, tool_input)
        if self._last_call_key == (tool_name, key):
            self._last_call_count += 1
        else:
            self._last_call_key = (tool_name, key)
            self._last_call_count = 1

        if self._last_call_count >= 3:
            return {
                "block": True,
                "msg": f"重复调用拦截: {tool_name} 已连续执行 {self._last_call_count} 次，请确认任务是否完成或调整策略",
            }
        elif self._last_call_count == 2:
            return {
                "block": False,
                "msg": f"[系统提醒] {tool_name} 连续调用，上一步结果是否符合预期？确认后再继续",
            }
        return None

    # ── 程序层硬约束：前置依赖检查 ───────────────────────────────

    def _check_prerequisite(self, tool_name: str) -> str | None:
        """检查前置工具是否已在当前 turn 调用过喵~

        返回缺失时的提醒文本，已调用则返回 None。
        """
        prereq = _PREREQUISITES.get(tool_name)
        if prereq is None:
            return None
        prereq_tool, reminder = prereq
        if prereq_tool not in self._turn_tool_history:
            return f"[前置提醒] {reminder}"
        return None

    # ── Hook 执行 ────────────────────────────────────────────────

    async def _execute_hook(self, hook, tool_input: dict) -> dict:
        """执行单个 hook: 调用 observe/locate handler，返回结果 dict 喵~"""
        handler = self.tool_handlers.get(hook.action)
        if handler is None:
            return {"success": False, "message": f"Hook action 未注册: {hook.action}"}
        try:
            kwargs = (
                {"prompt": hook.prompt_template}
                if hook.action == "observe"
                else {"target": hook.prompt_template}
            )
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**kwargs)
            else:
                result = await asyncio.to_thread(handler, **kwargs)
            return result if isinstance(result, dict) else result.model_dump(mode="json")
        except Exception as e:
            logger.warning("hook_execution_failed", hook_action=hook.action, error=str(e))
            return {"success": False, "message": f"Hook 执行失败: {e}"}

    # ── 工具执行核心 ─────────────────────────────────────────────

    async def _execute_tool(self, event: StreamEvent) -> dict:
        import time as _time

        payload = event.payload
        tool_name = payload.get("name", "")
        tool_input = payload.get("input", {})

        handler = self.tool_handlers.get(tool_name)
        if handler is None:
            logger.warning("unknown_tool_requested", tool_name=tool_name)
            return ToolResult(
                success=False,
                message=f"未知工具: {tool_name}",
            ).model_dump(mode="json")

        # ── 程序层硬约束 1: 重复调用检测 ──
        dup_check = self._check_duplicate_call(tool_name, tool_input)
        if dup_check and dup_check.get("block"):
            return ToolResult(
                success=False,
                message=dup_check["msg"],
                metrics={"duplicate_blocked": True, "call_count": self._last_call_count},
            ).model_dump(mode="json")

        # ── 程序层硬约束 2: 前置依赖检查 ──
        prereq_msg = self._check_prerequisite(tool_name)

        # Guard check before execution
        risk_level = self.risk_levels.get(tool_name, "L0")
        if self.guard is not None:
            gr = await self.guard.check(
                tool_name=tool_name,
                risk_level=risk_level,
                params=tool_input,
                summary=tool_input.get("summary", tool_input.get("instruction", "")),
            )
            if not gr.allowed:
                return ToolResult(
                    success=False,
                    message=f"操作被拒绝: {gr.reason}",
                    metrics={"decision": gr.decision},
                ).model_dump(mode="json")

        # ── Pre-hooks: 执行前自动观察，结果折叠进工具返回消息喵~ ──
        pre_hook_results: list[str] = []
        if self._hook_registry is not None:
            for hook in self._hook_registry.get_pre_hooks(tool_name):
                if hook.auto:
                    hook_result = await self._execute_hook(hook, tool_input)
                    obs = hook_result.get("observation", "") or json.dumps(
                        hook_result, ensure_ascii=False
                    )
                    pre_hook_results.append(f"[{hook.action}预检] {obs[:200]}")

        # Physics capture before (L1/L2 only)
        before_snapshot = None
        tool_call_id = None
        duration_ms = 0.0
        if risk_level in ("L1", "L2") and self._physics_collector is not None:
            before_snapshot = self._physics_collector.capture_before(tool_name)

        t0 = _time.perf_counter()
        try:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**tool_input)
            else:
                result = await asyncio.to_thread(handler, **tool_input)
            rv = result.model_dump(mode="json") if isinstance(result, ToolResult) else result
            duration_ms = (_time.perf_counter() - t0) * 1000

            # ── 注入约束信息到结果消息 ──
            msg = (rv.get("message", "") or "") if isinstance(rv, dict) else ""
            extras: list[str] = []

            # 重复调用警告
            if dup_check and not dup_check.get("block"):
                extras.append(dup_check["msg"])

            # 前置依赖提醒
            if prereq_msg:
                extras.append(prereq_msg)

            # 预检结果折叠进工具返回（不在上下文中单独出现，避免污染对话）喵~
            if pre_hook_results:
                extras.extend(pre_hook_results)

            # 经验提醒（瘦身版：最多1条，≤80字，纯文本前缀）喵~
            tips = self._get_tool_tips(tool_name)
            if tips:
                tip = tips[0]
                if len(tip) > 80:
                    tip = tip[:77] + "..."
                extras.append(f"[经验] {tip}")

            if extras:
                sep = "\n" if msg else ""
                if isinstance(rv, dict):
                    rv["message"] = msg + sep + "\n".join(extras)
                else:
                    rv = {"message": "\n".join(extras)}

            if self._metrics is not None:
                self._metrics.record_latency("tool_execution", duration_ms)
                self._metrics.record("tool_execution_total")

            logger.info("tool_execution_completed", tool_name=tool_name, duration_ms=duration_ms)

            # ── Post-hooks: 执行后自动验证，结果折叠进工具返回消息喵~ ──
            if self._hook_registry is not None:
                for hook in self._hook_registry.get_post_hooks(tool_name):
                    if hook.auto:
                        hook_result = await self._execute_hook(hook, tool_input)
                        obs = hook_result.get("observation", "") or json.dumps(
                            hook_result, ensure_ascii=False
                        )
                        post_extra = f"[{hook.action}验证] {obs[:200]}"
                        if isinstance(rv, dict):
                            cur = rv.get("message", "") or ""
                            rv["message"] = cur + "\n" + post_extra
                        else:
                            rv = {"message": post_extra}

            # Record to audit DB (with call flow context)
            if self.guard is not None:
                tool_call_id = self.guard.record_call(
                    tool_name,
                    risk_level,
                    tool_input,
                    rv,
                    duration_ms,
                    task_instruction=self._current_task_instruction,
                    turn_number=self._turn_number,
                    prev_call_id=self._prev_call_id,
                )
            return rv
        except Exception:
            duration_ms = (_time.perf_counter() - t0) * 1000
            logger.exception("tool_execution_failed", tool_name=tool_name, input=tool_input)
            error_result = ToolResult(
                success=False,
                message=f"工具 {tool_name} 执行异常",
            ).model_dump(mode="json")
            if self.guard is not None:
                tool_call_id = self.guard.record_call(
                    tool_name,
                    risk_level,
                    tool_input,
                    error_result,
                    duration_ms,
                    task_instruction=self._current_task_instruction,
                    turn_number=self._turn_number,
                    prev_call_id=self._prev_call_id,
                )
            return error_result
        finally:
            # Track tool call history for prerequisite checking
            self._turn_tool_history.append(tool_name)
            # Physics capture after (L1/L2 only)
            if before_snapshot is not None and self._physics_collector is not None:
                speed_ratio = tool_input.get("speed_ratio", 1.0)
                self._physics_collector.capture_after(
                    tool_name,
                    before_snapshot,
                    tool_call_id=tool_call_id,
                    duration_ms=duration_ms,
                    speed_ratio=speed_ratio,
                )
            # Register with annotation collector (L1/L2 only)
            if (
                tool_call_id
                and risk_level in ("L1", "L2")
                and self._annotation_collector is not None
            ):
                self._annotation_collector.register_tool_call(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    params=tool_input,
                )
            # Advance call flow tracking
            self._prev_call_id = tool_call_id
            self._turn_number += 1
