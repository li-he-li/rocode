"""Physics data collector — captures joint angles before/after L1/L2 tool execution."""

import time
from robocode.services.analytics.logger import get_logger

logger = get_logger("physics_collector")


class PhysicsCollector:
    """Captures joint angle snapshots before and after tool execution.

    Only calls get_motor_angles() — end_pose is derived via FK when needed,
    not stored redundantly.
    """

    def __init__(self, backend, db, session_id: str = "", metrics=None):
        self._backend = backend
        self._db = db
        self._session_id = session_id
        self._metrics = metrics

    # ── public API ────────────────────────────────────────────────────

    def capture_before(self, tool_name: str) -> dict:
        """Capture joint angles before tool execution.

        Returns a snapshot dict with joint_angles and tool_name.
        On SDK failure, logs error and returns snapshot with None angles.
        """
        snapshot = {"tool_name": tool_name, "joint_angles": None}
        try:
            angles = self._backend.get_motor_angles()
            if angles is not None and len(angles) == 6:
                snapshot["joint_angles"] = list(angles)
            else:
                snapshot["capture_error"] = "unexpected_data"
        except Exception as e:
            snapshot["capture_error"] = str(e)
            logger.warning("physics_capture_failed", tool_name=tool_name, error=str(e))

        if self._metrics is not None:
            self._metrics.record("physics_capture_total")

        return snapshot

    def capture_after(
        self,
        tool_name: str,
        before_snapshot: dict,
        tool_call_id: int | None = None,
        duration_ms: float = 0,
        speed_ratio: float = 1.0,
    ) -> dict:
        """Capture joint angles after tool execution and write physics data to DB.

        Returns the after-snapshot. Skips DB write if tool_call_id is None.
        """
        t0 = time.perf_counter()
        after_snapshot = self.capture_before(tool_name)

        if tool_call_id is not None and self._db and self._session_id:
            try:
                self._db.insert_physics_data(
                    tool_call_id=tool_call_id,
                    session_id=self._session_id,
                    tool_name=tool_name,
                    joint_angles_before=before_snapshot.get("joint_angles"),
                    joint_angles_after=after_snapshot.get("joint_angles"),
                    duration_ms=duration_ms,
                    speed_ratio=speed_ratio,
                )
                # Mark physics_captured on the tool_call row
                self._db.conn.execute(
                    "UPDATE tool_calls SET physics_captured=1 WHERE id=?",
                    (tool_call_id,),
                )
                self._db.conn.commit()
                summary = self.get_physics_summary(before_snapshot, after_snapshot)
                if summary:
                    logger.info(
                        "physics_captured",
                        tool_name=tool_name,
                        joint_delta=summary.get("joint_delta"),
                        duration_ms=summary.get("duration_ms"),
                    )
            except Exception:
                logger.exception("physics_db_write_failed", tool_name=tool_name)

        capture_latency = (time.perf_counter() - t0) * 1000
        if self._metrics is not None:
            self._metrics.record_latency("physics_capture", capture_latency)

        return after_snapshot

    def get_physics_summary(self, before: dict, after: dict) -> dict | None:
        """Compute joint delta and aggregate summary from before/after snapshots."""
        before_angles = before.get("joint_angles")
        after_angles = after.get("joint_angles")
        if before_angles is None or after_angles is None:
            return None
        if len(before_angles) != len(after_angles):
            return None

        joint_delta = [round(a - b, 2) for a, b in zip(after_angles, before_angles)]
        return {
            "joint_delta": joint_delta,
            "duration_ms": after.get("duration_ms", 0),
            "tool_name": before.get("tool_name", ""),
        }
