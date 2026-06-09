"""轻量进程内指标采集器 — 计数器和延迟直方图喵~

内存中累积，按需刷新到 AuditDB。
"""

import time
import threading
from contextlib import contextmanager
from collections import defaultdict


class MetricsCollector:
    """进程内指标: 计数器 + 延迟直方图 + 语音指标喵~

    Usage:
        metrics = MetricsCollector()
        with metrics.timer("tool_execution", tool_name="move_xyz"):
            ...  # 计时块

        metrics.record("safety_rejection", reason="joint_limit")
        summary = metrics.session_summary()
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._latencies: dict[str, list[float]] = defaultdict(list)
        self._started_at = time.time()

        # 语音专属指标
        self._stt_latency_ms: list[float] = []
        self._stt_confidence: list[float] = []
        self._stt_failure_total = 0
        self._voice_op_total = 0
        self._voice_op_success = 0

    # ── 公共 API ──────────────────────────────────────────────────

    def record(self, metric: str, value: int = 1):
        """计数器 +1（或指定值）喵~"""
        with self._lock:
            self._counters[metric] += value

    def record_latency(self, metric: str, latency_ms: float):
        """记录一条延迟样本喵~"""
        with self._lock:
            self._latencies[metric].append(latency_ms)

    @contextmanager
    def timer(self, metric: str, **tags):
        """上下文管理器 — 自动计时代码块喵~

        with metrics.timer("tool_execution", tool_name="move_xyz"):
            do_work()
        """
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - t0) * 1000
            self.record_latency(metric, elapsed)
            self.record(f"{metric}_total")

    def get_counter(self, metric: str) -> int:
        with self._lock:
            return self._counters.get(metric, 0)

    def get_latencies(self, metric: str) -> list[float]:
        with self._lock:
            return list(self._latencies.get(metric, []))

    # ── 语音指标 ──────────────────────────────────────────────────

    def record_stt_result(self, latency_ms: float, confidence: float, success: bool):
        """记录语音转文字结果喵~"""
        with self._lock:
            self._voice_op_total += 1
            if success:
                self._voice_op_success += 1
                self._stt_latency_ms.append(latency_ms)
                self._stt_confidence.append(confidence)
            else:
                self._stt_failure_total += 1

    # ── 会话摘要 ──────────────────────────────────────────────────

    def session_summary(self) -> dict:
        """生成会话级指标摘要喵~"""
        with self._lock:
            lats = self._stt_latency_ms
            confs = self._stt_confidence
            voice = {
                "total": self._voice_op_total,
                "success": self._voice_op_success,
                "failure": self._stt_failure_total,
                "avg_latency_ms": round(sum(lats) / len(lats), 1) if lats else 0,
                "avg_confidence": round(sum(confs) / len(confs), 3) if confs else 0,
            }

            tool_lats = self._latencies.get("tool_execution", [])
            sorted_lats = sorted(tool_lats) if tool_lats else []
            p50 = sorted_lats[len(sorted_lats) // 2] if sorted_lats else 0
            p95_idx = int(len(sorted_lats) * 0.95) if sorted_lats else 0
            p95 = sorted_lats[min(p95_idx, len(sorted_lats) - 1)] if sorted_lats else 0

            return {
                "session_duration_s": round(time.time() - self._started_at, 1),
                "tool_executions": {
                    "total": self._counters.get("tool_execution_total", 0),
                    "p50_ms": round(p50, 1),
                    "p95_ms": round(p95, 1),
                    "avg_ms": round(sum(tool_lats) / len(tool_lats), 1) if tool_lats else 0,
                },
                "safety_rejections": self._counters.get("safety_rejection", 0),
                "llm_calls": self._counters.get("llm_call_total", 0),
                "voice_operations": voice,
            }
